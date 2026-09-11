"""The quarterly aangifte, scenario by scenario.

Each test states one rule about how a document lands in the rubrieken. Read together
they are the specification of what this application believes about Dutch BTW.
"""

from __future__ import annotations

import datetime as dt

import pytest

from boekhouding.models import Settings
from boekhouding.services import expenses as exp
from boekhouding.services import invoices as svc
from boekhouding.services import vat_return as btw
from boekhouding.vat import PurchaseVat, Rubriek, SalesVat

Q1 = (2023, 1)


def _invoice(session, client, bedrag: str, behandeling=SalesVat.HOOG_21, datum=None, finaal=True):
    invoice = svc.create_draft(
        session, client, datum=datum or dt.date(2023, 2, 2), prestatie_omschrijving="februari"
    )
    svc.add_line(
        session, invoice, aantal="1", code="X", omschrijving="werk",
        stuksprijs=bedrag, btw_behandeling=behandeling,
    )
    if finaal:
        svc.finalise(session, invoice)
    return invoice


class TestSalesRubrieken:
    def test_high_rate_lands_in_1a_with_its_vat(self, session, acme):
        _invoice(session, acme, "1638,00")
        aangifte = btw.compute(session, *Q1)
        assert aangifte.regel(Rubriek.R1A).omzet_cents == 163800
        assert aangifte.regel(Rubriek.R1A).btw_cents == 34398
        assert aangifte.verschuldigd_cents == 34398
        assert aangifte.saldo_cents == 34398

    def test_low_rate_lands_in_1b(self, session, acme):
        _invoice(session, acme, "1000,00", SalesVat.LAAG_9)
        aangifte = btw.compute(session, *Q1)
        assert aangifte.regel(Rubriek.R1B).omzet_cents == 100000
        assert aangifte.regel(Rubriek.R1B).btw_cents == 9000
        assert aangifte.regel(Rubriek.R1A).omzet_cents == 0

    @pytest.mark.parametrize(
        "behandeling", [SalesVat.NUL, SalesVat.VRIJGESTELD, SalesVat.VERLEGD_BINNENLAND]
    )
    def test_zero_exempt_and_domestic_reverse_charge_land_in_1e(self, session, acme, behandeling):
        _invoice(session, acme, "1000,00", behandeling)
        aangifte = btw.compute(session, *Q1)
        assert aangifte.regel(Rubriek.R1E).omzet_cents == 100000
        assert aangifte.regel(Rubriek.R1E).btw_cents == 0
        assert aangifte.verschuldigd_cents == 0

    def test_eu_services_land_in_3b(self, session, duitse_klant):
        _invoice(session, duitse_klant, "2000,00", SalesVat.EU_DIENSTEN)
        aangifte = btw.compute(session, *Q1)
        assert aangifte.regel(Rubriek.R3B).omzet_cents == 200000
        assert aangifte.regel(Rubriek.R3B).btw_cents == 0

    def test_export_outside_the_eu_lands_in_3a(self, session, acme):
        _invoice(session, acme, "500,00", SalesVat.EXPORT_BUITEN_EU)
        aangifte = btw.compute(session, *Q1)
        assert aangifte.regel(Rubriek.R3A).omzet_cents == 50000

    def test_private_use_lands_in_1d(self, session, acme):
        _invoice(session, acme, "100,00", SalesVat.PRIVEGEBRUIK)
        aangifte = btw.compute(session, *Q1)
        assert aangifte.regel(Rubriek.R1D).omzet_cents == 10000
        assert aangifte.regel(Rubriek.R1D).btw_cents == 2100

    def test_a_draft_invoice_owes_no_vat(self, session, acme):
        _invoice(session, acme, "1638,00", finaal=False)
        aangifte = btw.compute(session, *Q1)
        assert aangifte.regel(Rubriek.R1A).omzet_cents == 0
        assert aangifte.saldo_cents == 0

    def test_a_credit_note_reduces_the_rubriek(self, session, acme):
        origineel = _invoice(session, acme, "1000,00")
        credit = svc.create_credit_note(session, origineel, datum=dt.date(2023, 2, 20))
        svc.finalise(session, credit)
        aangifte = btw.compute(session, *Q1)
        assert aangifte.regel(Rubriek.R1A).omzet_cents == 0
        assert aangifte.regel(Rubriek.R1A).btw_cents == 0
        assert aangifte.saldo_cents == 0

    def test_a_credit_note_lands_in_the_quarter_it_is_issued(self, session, acme):
        origineel = _invoice(session, acme, "1000,00", datum=dt.date(2023, 2, 2))
        credit = svc.create_credit_note(session, origineel, datum=dt.date(2023, 4, 5))
        svc.finalise(session, credit)
        assert btw.compute(session, 2023, 1).regel(Rubriek.R1A).btw_cents == 21000
        assert btw.compute(session, 2023, 2).regel(Rubriek.R1A).btw_cents == -21000


class TestPurchaseRubrieken:
    def test_domestic_vat_is_deductible_in_5b_only(self, session):
        exp.create(
            session, datum=dt.date(2023, 1, 15), leverancier="Coolblue",
            omschrijving="monitor", bedrag_excl="200,00",
            btw_behandeling=PurchaseVat.BINNENLAND_21,
        )
        aangifte = btw.compute(session, *Q1)
        assert aangifte.voorbelasting_cents == 4200
        assert aangifte.verschuldigd_cents == 0
        assert aangifte.saldo_cents == -4200

    def test_domestic_reverse_charge_is_owed_in_2a_and_deducted_in_5b(self, session):
        exp.create(
            session, datum=dt.date(2023, 1, 15), leverancier="Onderaannemer",
            omschrijving="detachering", bedrag_excl="1000,00",
            btw_behandeling=PurchaseVat.VERLEGD_BINNENLAND,
        )
        aangifte = btw.compute(session, *Q1)
        assert aangifte.regel(Rubriek.R2A).omzet_cents == 100000
        assert aangifte.regel(Rubriek.R2A).btw_cents == 21000
        assert aangifte.voorbelasting_cents == 21000
        assert aangifte.saldo_cents == 0, "reverse charge must net to zero"

    def test_eu_acquisition_is_owed_in_4b_and_deducted_in_5b(self, session):
        exp.create(
            session, datum=dt.date(2023, 2, 1), leverancier="Hetzner",
            omschrijving="servers", bedrag_excl="300,00",
            btw_behandeling=PurchaseVat.EU_VERWERVING,
        )
        aangifte = btw.compute(session, *Q1)
        assert aangifte.regel(Rubriek.R4B).omzet_cents == 30000
        assert aangifte.regel(Rubriek.R4B).btw_cents == 6300
        assert aangifte.voorbelasting_cents == 6300
        assert aangifte.saldo_cents == 0

    def test_import_from_outside_the_eu_is_owed_in_4a(self, session):
        exp.create(
            session, datum=dt.date(2023, 2, 1), leverancier="US vendor",
            omschrijving="apparatuur", bedrag_excl="1000,00",
            btw_behandeling=PurchaseVat.IMPORT_BUITEN_EU,
        )
        aangifte = btw.compute(session, *Q1)
        assert aangifte.regel(Rubriek.R4A).btw_cents == 21000
        assert aangifte.saldo_cents == 0

    def test_a_purchase_without_vat_adds_nothing(self, session):
        exp.create(
            session, datum=dt.date(2023, 1, 5), leverancier="Verzekeraar",
            omschrijving="AOV", bedrag_excl="250,00",
            btw_behandeling=PurchaseVat.GEEN_BTW,
        )
        aangifte = btw.compute(session, *Q1)
        assert aangifte.voorbelasting_cents == 0

    def test_private_use_reduces_the_deductible_vat(self, session):
        expense = exp.create(
            session, datum=dt.date(2023, 1, 10), leverancier="KPN",
            omschrijving="telefoon", bedrag_excl="100,00",
            btw_behandeling=PurchaseVat.BINNENLAND_21, zakelijk_permille=700,
        )
        assert expense.btw_cents == 2100
        assert expense.aftrekbare_btw_cents == 1470
        aangifte = btw.compute(session, *Q1)
        assert aangifte.voorbelasting_cents == 1470

    def test_private_use_also_reduces_reverse_charge_deduction(self, session):
        exp.create(
            session, datum=dt.date(2023, 1, 10), leverancier="EU leverancier",
            omschrijving="dienst", bedrag_excl="1000,00",
            btw_behandeling=PurchaseVat.EU_VERWERVING, zakelijk_permille=500,
        )
        aangifte = btw.compute(session, *Q1)
        assert aangifte.regel(Rubriek.R4B).btw_cents == 21000, "the full amount is owed"
        assert aangifte.voorbelasting_cents == 10500, "only the business half is deductible"
        assert aangifte.saldo_cents == 10500


class TestPeriods:
    def test_documents_are_assigned_by_invoice_date(self, session, acme):
        _invoice(session, acme, "1000,00", datum=dt.date(2023, 3, 31))
        _invoice(session, acme, "2000,00", datum=dt.date(2023, 4, 1))
        q1 = btw.compute(session, 2023, 1)
        q2 = btw.compute(session, 2023, 2)
        assert q1.regel(Rubriek.R1A).omzet_cents == 100000
        assert q2.regel(Rubriek.R1A).omzet_cents == 200000

    @pytest.mark.parametrize(
        ("kwartaal", "van", "tot"),
        [
            (1, dt.date(2023, 1, 1), dt.date(2023, 3, 31)),
            (2, dt.date(2023, 4, 1), dt.date(2023, 6, 30)),
            (3, dt.date(2023, 7, 1), dt.date(2023, 9, 30)),
            (4, dt.date(2023, 10, 1), dt.date(2023, 12, 31)),
        ],
    )
    def test_quarter_boundaries(self, kwartaal, van, tot):
        assert btw.quarter_range(2023, kwartaal) == (van, tot)

    def test_an_invalid_quarter_is_refused(self):
        with pytest.raises(ValueError):
            btw.quarter_range(2023, 5)


class TestRoundingAcrossAQuarter:
    def test_the_quarter_total_equals_the_sum_of_the_invoices(self, session, acme):
        bedragen = ["33,33", "16,67", "0,01", "999,99", "1,50"]
        for index, bedrag in enumerate(bedragen):
            _invoice(session, acme, bedrag, datum=dt.date(2023, 1, index + 1))

        from sqlalchemy import select

        from boekhouding.models import Invoice

        facturen = session.scalars(select(Invoice)).all()
        aangifte = btw.compute(session, *Q1)
        assert aangifte.regel(Rubriek.R1A).omzet_cents == sum(f.subtotaal_cents for f in facturen)
        assert aangifte.regel(Rubriek.R1A).btw_cents == sum(f.btw_totaal_cents for f in facturen)


class TestIcp:
    def test_eu_sales_are_listed_per_vat_number(self, session, duitse_klant):
        _invoice(session, duitse_klant, "1000,00", SalesVat.EU_DIENSTEN)
        _invoice(session, duitse_klant, "500,00", SalesVat.EU_DIENSTEN)
        aangifte = btw.compute(session, *Q1)
        assert len(aangifte.icp) == 1
        regel = aangifte.icp[0]
        assert regel["btw_nummer"] == "DE123456789"
        assert regel["bedrag_cents"] == 150000

    def test_domestic_sales_never_appear_on_the_icp(self, session, acme):
        _invoice(session, acme, "1000,00")
        assert btw.compute(session, *Q1).icp == []


class TestKor:
    def test_kor_exempts_sales_and_blocks_deduction(self, session, acme):
        settings = Settings.get_or_create(session)
        settings.kor_actief = True
        settings.kor_startdatum = dt.date(2023, 1, 1)
        session.flush()

        _invoice(session, acme, "1000,00")
        exp.create(
            session, datum=dt.date(2023, 1, 5), leverancier="Coolblue",
            omschrijving="monitor", bedrag_excl="200,00",
        )
        aangifte = btw.compute(session, *Q1)
        assert aangifte.kor_actief
        assert aangifte.regel(Rubriek.R1E).omzet_cents == 100000
        assert aangifte.regel(Rubriek.R1A).btw_cents == 0
        assert aangifte.voorbelasting_cents == 0
        assert aangifte.saldo_cents == 0


class TestFilingAndCorrections:
    def test_filing_records_the_figures_as_submitted(self, session, acme):
        _invoice(session, acme, "1000,00")
        filing = btw.mark_filed(session, 2023, 1)
        assert filing.saldo_cents == 21000

    def test_filing_the_same_quarter_twice_is_refused(self, session, acme):
        _invoice(session, acme, "1000,00")
        btw.mark_filed(session, 2023, 1)
        with pytest.raises(ValueError, match="al gemarkeerd"):
            btw.mark_filed(session, 2023, 1)

    def test_a_late_document_surfaces_as_a_correction(self, session, acme):
        _invoice(session, acme, "1000,00")
        btw.mark_filed(session, 2023, 1)

        _invoice(session, acme, "500,00", datum=dt.date(2023, 3, 20))
        correctie = btw.corrections(session, 2023, 1)

        assert correctie is not None
        assert correctie["saldo_verschil_cents"] == 10500
        verschil = next(v for v in correctie["verschillen"] if v["rubriek"] == "1a")
        assert verschil["omzet_verschil_cents"] == 50000
        assert verschil["btw_verschil_cents"] == 10500

    def test_a_small_correction_may_go_in_the_next_return(self, session, acme):
        _invoice(session, acme, "1000,00")
        btw.mark_filed(session, 2023, 1)
        _invoice(session, acme, "100,00", datum=dt.date(2023, 3, 20))
        correctie = btw.corrections(session, 2023, 1)
        assert not correctie["suppletie_nodig"]
        assert "eerstvolgende aangifte" in correctie["advies"]

    def test_a_large_correction_needs_a_suppletie(self, session, acme):
        _invoice(session, acme, "1000,00")
        btw.mark_filed(session, 2023, 1)
        _invoice(session, acme, "20000,00", datum=dt.date(2023, 3, 20))
        correctie = btw.corrections(session, 2023, 1)
        assert correctie["suppletie_nodig"]
        assert "suppletie" in correctie["advies"]

    def test_an_unfiled_quarter_has_no_corrections(self, session, acme):
        _invoice(session, acme, "1000,00")
        assert btw.corrections(session, 2023, 1) is None

    def test_a_filed_quarter_is_locked(self, session, acme):
        _invoice(session, acme, "1000,00")
        assert not btw.is_locked(session, dt.date(2023, 2, 2))
        btw.mark_filed(session, 2023, 1)
        assert btw.is_locked(session, dt.date(2023, 2, 2))
        assert not btw.is_locked(session, dt.date(2023, 5, 2))


class TestChecklistAndWarnings:
    def test_a_draft_in_the_period_is_flagged(self, session, acme):
        _invoice(session, acme, "1000,00", finaal=False)
        aangifte = btw.compute(session, *Q1)
        concepten = next(i for i in aangifte.checklist if "conceptfactuur" in i["tekst"])
        assert not concepten["ok"]

    def test_an_expense_without_an_attachment_is_flagged(self, session):
        exp.create(
            session, datum=dt.date(2023, 1, 5), leverancier="Coolblue",
            omschrijving="monitor", bedrag_excl="200,00",
        )
        aangifte = btw.compute(session, *Q1)
        bijlagen = next(i for i in aangifte.checklist if "zonder bijlage" in i["tekst"])
        assert not bijlagen["ok"]

    def test_a_clean_quarter_passes_every_check(self, session, acme):
        _invoice(session, acme, "1000,00")
        exp.create(
            session, datum=dt.date(2023, 1, 5), leverancier="Coolblue",
            omschrijving="monitor", bedrag_excl="200,00", document_pad="/ergens/bon.pdf",
        )
        aangifte = btw.compute(session, *Q1)
        assert all(item["ok"] for item in aangifte.checklist)

    def test_an_invoice_unpaid_for_a_year_becomes_reclaimable(self, session, acme):
        _invoice(session, acme, "1000,00", datum=dt.date(2023, 2, 2))
        oninbaar = btw.oninbare_vorderingen(session, dt.date(2024, 6, 30))
        assert len(oninbaar) == 1
        assert oninbaar[0]["btw_terug_cents"] == 21000

    def test_a_paid_invoice_is_never_reclaimable(self, session, acme):
        invoice = _invoice(session, acme, "1000,00", datum=dt.date(2023, 2, 2))
        svc.register_payment(session, invoice, invoice.totaal_incl_cents, dt.date(2023, 2, 20))
        assert btw.oninbare_vorderingen(session, dt.date(2024, 6, 30)) == []


class TestFullQuarter:
    def test_a_realistic_quarter_reconciles_in_every_rubriek(self, session, acme, duitse_klant):
        _invoice(session, acme, "1638,00", datum=dt.date(2023, 1, 2))
        _invoice(session, acme, "1638,00", datum=dt.date(2023, 2, 2))
        _invoice(session, acme, "2000,00", datum=dt.date(2023, 3, 2))
        _invoice(session, duitse_klant, "1500,00", SalesVat.EU_DIENSTEN, dt.date(2023, 3, 5))
        exp.create(
            session, datum=dt.date(2023, 1, 10), leverancier="Coolblue",
            omschrijving="laptopstandaard", bedrag_excl="100,00", document_pad="/x.pdf",
        )
        exp.create(
            session, datum=dt.date(2023, 2, 10), leverancier="Hetzner",
            omschrijving="servers", bedrag_excl="200,00",
            btw_behandeling=PurchaseVat.EU_VERWERVING, document_pad="/y.pdf",
        )

        aangifte = btw.compute(session, 2023, 1)

        assert aangifte.regel(Rubriek.R1A).omzet_cents == 527600
        assert aangifte.regel(Rubriek.R1A).btw_cents == 110796
        assert aangifte.regel(Rubriek.R3B).omzet_cents == 150000
        assert aangifte.regel(Rubriek.R4B).btw_cents == 4200

        # 5a is the sum of everything owed; 5b of everything deductible.
        assert aangifte.verschuldigd_cents == 110796 + 4200
        assert aangifte.voorbelasting_cents == 2100 + 4200
        assert aangifte.saldo_cents == 108696
        assert aangifte.rubrieken[Rubriek.R5A].btw_cents == aangifte.verschuldigd_cents

    def test_every_rubriek_can_be_drilled_down_to_documents(self, session, acme):
        _invoice(session, acme, "1000,00")
        aangifte = btw.compute(session, *Q1)
        posten = aangifte.regel(Rubriek.R1A).posten
        assert len(posten) == 1
        assert posten[0]["nummer"] == "F00001"
        assert posten[0]["omzet_cents"] == 100000
