"""Whole-euro rounding for the aangifte itself.

The Belastingdienst: "In de btw-aangifte rondt u de btw-bedragen af op hele euro's.
Dit mag u in uw voordeel doen." So amounts owed round down and voorbelasting rounds up,
and the form's own totals must be the sum of the *rounded* lines -- otherwise 5a minus
5b does not equal the saldo on the form.

The exact cent figures stay available underneath, because that is what the audit trail
and the drill-down need.
"""

from __future__ import annotations

import datetime as dt

import pytest

from boekhouding.services import expenses as exp
from boekhouding.services import invoices as svc
from boekhouding.services import vat_return as btw
from boekhouding.vat import PurchaseVat, Rubriek, SalesVat

Q1 = (2023, 1)


def _invoice(session, client, bedrag: str, behandeling=SalesVat.HOOG_21, datum=None):
    invoice = svc.create_draft(
        session, client, datum=datum or dt.date(2023, 2, 2), prestatie_omschrijving="feb"
    )
    svc.add_line(session, invoice, aantal="1", code="X", omschrijving="werk",
                 stuksprijs=bedrag, btw_behandeling=behandeling)
    svc.finalise(session, invoice)
    return invoice


class TestRoundingHelpers:
    @pytest.mark.parametrize(
        ("cents", "verwacht"),
        [(0, 0), (99, 0), (100, 100), (199, 100), (34_398, 34_300), (-150, -200)],
    )
    def test_amounts_owed_round_down(self, cents, verwacht):
        assert btw.floor_euro(cents) == verwacht

    @pytest.mark.parametrize(
        ("cents", "verwacht"),
        [(0, 0), (1, 100), (99, 100), (100, 100), (101, 200), (4_200, 4_200)],
    )
    def test_voorbelasting_rounds_up(self, cents, verwacht):
        assert btw.ceil_euro(cents) == verwacht

    def test_rounding_is_always_in_my_favour(self):
        # Owed: never more than the exact amount. Deductible: never less.
        for cents in range(0, 1000, 7):
            assert btw.floor_euro(cents) <= cents
            assert btw.ceil_euro(cents) >= cents


class TestTheFiguresOnTheForm:
    def test_a_rubriek_reports_whole_euros(self, session, acme):
        _invoice(session, acme, "1638,00")  # btw 343,98
        aangifte = btw.compute(session, *Q1)
        regel = aangifte.regel(Rubriek.R1A)

        assert regel.btw_cents == 34_398, "exact figure stays available"
        assert regel.btw_aangifte_cents == 34_300, "343,98 -> 343 on the form"
        assert regel.omzet_aangifte_cents == 163_800

    def test_voorbelasting_rounds_up_on_the_form(self, session):
        exp.create(
            session, datum=dt.date(2023, 1, 5), leverancier="Coolblue",
            omschrijving="kabel", bedrag_excl="10,05",
        )
        aangifte = btw.compute(session, *Q1)
        assert aangifte.voorbelasting_cents == 211  # 2,11 exact
        assert aangifte.voorbelasting_aangifte_cents == 300, "2,11 -> 3 in my favour"

    def test_5a_is_the_sum_of_the_rounded_lines(self, session, acme):
        _invoice(session, acme, "1638,00")  # 1a btw 343,98 -> 343
        exp.create(
            session, datum=dt.date(2023, 1, 5), leverancier="EU",
            omschrijving="dienst", bedrag_excl="333,00",
            btw_behandeling=PurchaseVat.EU_VERWERVING,  # 4b btw 69,93 -> 69
        )
        aangifte = btw.compute(session, *Q1)

        assert aangifte.regel(Rubriek.R4B).btw_cents == 6_993
        assert aangifte.regel(Rubriek.R4B).btw_aangifte_cents == 6_900
        assert aangifte.verschuldigd_aangifte_cents == 34_300 + 6_900
        # The form must add up on its own terms, not on the exact figures.
        assert aangifte.verschuldigd_aangifte_cents != aangifte.verschuldigd_cents

    def test_the_saldo_on_the_form_is_5a_minus_5b_in_whole_euros(self, session, acme):
        _invoice(session, acme, "1638,00")
        exp.create(
            session, datum=dt.date(2023, 1, 5), leverancier="Coolblue",
            omschrijving="monitor", bedrag_excl="200,05",
        )
        aangifte = btw.compute(session, *Q1)
        assert aangifte.saldo_aangifte_cents == (
            aangifte.verschuldigd_aangifte_cents - aangifte.voorbelasting_aangifte_cents
        )
        assert aangifte.saldo_aangifte_cents % 100 == 0, "whole euros"

    def test_the_rounding_difference_is_never_against_me(self, session, acme):
        _invoice(session, acme, "1638,00")
        exp.create(
            session, datum=dt.date(2023, 1, 5), leverancier="Coolblue",
            omschrijving="monitor", bedrag_excl="200,05",
        )
        aangifte = btw.compute(session, *Q1)
        assert aangifte.afrondingsverschil_cents <= 0, "I never pay more than the exact"
        assert abs(aangifte.afrondingsverschil_cents) < 5_000, "and only by a few euros"

    def test_an_empty_quarter_rounds_to_nothing(self, session):
        aangifte = btw.compute(session, *Q1)
        assert aangifte.saldo_aangifte_cents == 0
        assert aangifte.verschuldigd_aangifte_cents == 0

    def test_a_credit_heavy_quarter_still_rounds_in_my_favour(self, session, acme):
        origineel = _invoice(session, acme, "1000,00", datum=dt.date(2023, 1, 10))
        credit = svc.create_credit_note(session, origineel, datum=dt.date(2023, 2, 10))
        svc.add_line(session, credit, aantal="1", code="Y", omschrijving="extra credit",
                     stuksprijs="-50,55")
        svc.finalise(session, credit)

        aangifte = btw.compute(session, *Q1)
        assert aangifte.regel(Rubriek.R1A).btw_cents < 0
        assert aangifte.regel(Rubriek.R1A).btw_aangifte_cents <= (
            aangifte.regel(Rubriek.R1A).btw_cents
        ), "a negative owed amount also rounds away from what I pay"


class TestFilingRecordsBothViews:
    def test_the_filing_stores_the_exact_and_the_submitted_figures(self, session, acme):
        import json

        _invoice(session, acme, "1638,00")
        filing = btw.mark_filed(session, 2023, 1)
        opgeslagen = json.loads(filing.rubrieken_json)

        assert opgeslagen["exact"]["1a"]["btw"] == 34_398
        assert opgeslagen["aangifte"]["1a"]["btw"] == 34_300
        assert "saldo" in opgeslagen["aangifte"]

    def test_corrections_still_compare_exact_figures(self, session, acme):
        _invoice(session, acme, "1638,00")
        btw.mark_filed(session, 2023, 1)
        _invoice(session, acme, "100,00", datum=dt.date(2023, 3, 1))

        correctie = btw.corrections(session, 2023, 1)
        verschil = next(v for v in correctie["verschillen"] if v["rubriek"] == "1a")
        assert verschil["btw_verschil_cents"] == 2_100, "exact, not rounded"


class TestVrijgesteldWarning:
    def test_exempt_turnover_is_flagged_because_the_rules_are_ambiguous(self, session, acme):
        _invoice(session, acme, "1000,00", SalesVat.VRIJGESTELD)
        aangifte = btw.compute(session, *Q1)
        assert any("vrijgestelde omzet" in punt.lower() for punt in aangifte.aandachtspunten)

    def test_ordinary_turnover_raises_no_such_flag(self, session, acme):
        _invoice(session, acme, "1000,00")
        aangifte = btw.compute(session, *Q1)
        assert not any("vrijgestelde omzet" in p.lower() for p in aangifte.aandachtspunten)
