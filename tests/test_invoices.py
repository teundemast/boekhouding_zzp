from __future__ import annotations

import datetime as dt

import pytest

from app import money
from app.models import Invoice, InvoiceStatus, Settings, TimeEntry
from app.services import invoices as svc
from app.vat import SalesVat


def _f00006(session, acme) -> Invoice:
    """The reference invoice: three project lines whose totals were checked by hand."""
    invoice = svc.create_draft(
        session, acme, datum=dt.date(2023, 2, 2), uw_kenmerk="FEB",
        prestatie_omschrijving="februari 2023",
    )
    svc.add_line(
        session, invoice, aantal="41", code="ADSD",
        omschrijving="Algemene Data Science Diensten", stuksprijs="18,00",
    )
    svc.add_line(
        session, invoice, aantal="23", code="ACME",
        omschrijving="Data Science Diensten voor Project Statistiek", stuksprijs="20,00",
    )
    svc.add_line(
        session, invoice, aantal="22", code="NOVA",
        omschrijving=(
            "Data science diensten verricht voor Nova, exploratie en transformatie van data."
        ),
        stuksprijs="20,00",
    )
    return invoice


class TestTotals:
    def test_reproduces_the_reference_invoice_exactly(self, session, acme):
        invoice = _f00006(session, acme)
        assert [r.totaal_cents for r in invoice.regels] == [73800, 46000, 44000]
        assert invoice.subtotaal_cents == 163800
        assert invoice.btw_totaal_cents == 34398
        assert invoice.totaal_incl_cents == 198198
        assert money.format_euro(invoice.totaal_incl_cents) == "€ 1.981,98"

    def test_vat_is_grouped_per_rate_not_per_line(self, session, acme):
        invoice = _f00006(session, acme)
        groepen = invoice.btw_per_tarief
        assert set(groepen) == {SalesVat.HOOG_21.value}
        tarief, grondslag, btw = groepen[SalesVat.HOOG_21.value]
        assert (tarief, grondslag, btw) == (210, 163800, 34398)

    def test_mixed_rates_are_totalled_separately(self, session, acme):
        invoice = svc.create_draft(session, acme, prestatie_omschrijving="test")
        svc.add_line(session, invoice, aantal="1", code="A", omschrijving="hoog",
                     stuksprijs="100,00", btw_behandeling=SalesVat.HOOG_21)
        svc.add_line(session, invoice, aantal="1", code="B", omschrijving="laag",
                     stuksprijs="100,00", btw_behandeling=SalesVat.LAAG_9)
        svc.add_line(session, invoice, aantal="1", code="C", omschrijving="vrij",
                     stuksprijs="100,00", btw_behandeling=SalesVat.VRIJGESTELD)
        assert invoice.subtotaal_cents == 30000
        assert invoice.btw_totaal_cents == 2100 + 900
        assert invoice.totaal_incl_cents == 33000


class TestNumbering:
    def test_numbers_are_sequential_and_zero_padded(self, session, acme):
        nummers = []
        for _ in range(3):
            invoice = _f00006(session, acme)
            svc.finalise(session, invoice)
            nummers.append(invoice.nummer)
        assert nummers == ["F00001", "F00002", "F00003"]

    def test_a_deleted_draft_does_not_consume_a_number(self, session, acme):
        concept = _f00006(session, acme)
        concept.deleted_at = dt.datetime.now(dt.timezone.utc)
        session.flush()
        tweede = _f00006(session, acme)
        svc.finalise(session, tweede)
        assert tweede.nummer == "F00001"

    def test_numbers_never_repeat_even_across_interleaved_drafts(self, session, acme):
        a = _f00006(session, acme)
        b = _f00006(session, acme)
        svc.finalise(session, b)
        svc.finalise(session, a)
        assert {a.nummer, b.nummer} == {"F00001", "F00002"}
        assert a.nummer != b.nummer

    def test_duplicate_numbers_are_rejected_by_the_database(self, session, acme):
        from sqlalchemy.exc import IntegrityError

        a = _f00006(session, acme)
        svc.finalise(session, a)
        b = _f00006(session, acme)
        svc.finalise(session, b)
        b.nummer = a.nummer
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    def test_per_year_numbering_when_enabled(self, session, acme):
        Settings.get_or_create(session).nummering_per_jaar = True
        session.flush()
        invoice = _f00006(session, acme)
        svc.finalise(session, invoice)
        assert invoice.nummer == "F202300001"

    def test_peek_does_not_claim_a_number(self, session, acme):
        eerst = svc.peek_number(session, "factuur", dt.date(2023, 2, 2))
        opnieuw = svc.peek_number(session, "factuur", dt.date(2023, 2, 2))
        assert eerst == opnieuw == "F00001"
        invoice = _f00006(session, acme)
        svc.finalise(session, invoice)
        assert invoice.nummer == "F00001"


class TestImmutability:
    def test_a_finalised_invoice_cannot_gain_a_line(self, session, acme):
        invoice = _f00006(session, acme)
        svc.finalise(session, invoice)
        with pytest.raises(svc.InvoiceLocked):
            svc.add_line(session, invoice, aantal="1", code="X",
                         omschrijving="stiekem", stuksprijs="1000,00")

    def test_a_finalised_invoice_cannot_be_redated(self, session, acme):
        invoice = _f00006(session, acme)
        svc.finalise(session, invoice)
        with pytest.raises(svc.InvoiceLocked):
            svc.set_datum(session, invoice, dt.date(2023, 3, 1))

    def test_finalising_twice_is_refused(self, session, acme):
        invoice = _f00006(session, acme)
        svc.finalise(session, invoice)
        with pytest.raises(svc.InvoiceLocked):
            svc.finalise(session, invoice)

    def test_a_draft_is_freely_editable(self, session, acme):
        invoice = _f00006(session, acme)
        svc.set_datum(session, invoice, dt.date(2023, 3, 1))
        svc.add_line(session, invoice, aantal="1", code="X", omschrijving="extra",
                     stuksprijs="10,00")
        assert len(invoice.regels) == 4


class TestValidation:
    def test_refuses_an_invoice_without_lines(self, session, acme):
        invoice = svc.create_draft(session, acme, prestatie_omschrijving="leeg")
        with pytest.raises(ValueError, match="geen regels"):
            svc.finalise(session, invoice)

    def test_refuses_a_reverse_charge_invoice_without_the_client_vat_number(
        self, session, duitse_klant
    ):
        duitse_klant.btw_nummer = ""
        invoice = svc.create_draft(session, duitse_klant, prestatie_omschrijving="maart")
        svc.add_line(session, invoice, aantal="10", code="EU", omschrijving="advies",
                     stuksprijs="100,00", btw_behandeling=SalesVat.EU_DIENSTEN)
        with pytest.raises(ValueError, match="btw-nummer van de klant"):
            svc.finalise(session, invoice)

    def test_requires_a_performance_period(self, session, acme):
        invoice = svc.create_draft(session, acme)
        svc.add_line(session, invoice, aantal="1", code="A", omschrijving="werk",
                     stuksprijs="100,00")
        with pytest.raises(ValueError, match="prestatiedatum"):
            svc.finalise(session, invoice)


class TestCreditNotes:
    def test_a_credit_note_mirrors_and_negates(self, session, acme):
        origineel = _f00006(session, acme)
        svc.finalise(session, origineel)
        credit = svc.create_credit_note(session, origineel, reden="verkeerd tarief")

        assert credit.is_creditfactuur
        assert credit.crediteert_id == origineel.id
        assert credit.subtotaal_cents == -origineel.subtotaal_cents
        assert credit.btw_totaal_cents == -origineel.btw_totaal_cents
        assert credit.totaal_incl_cents == -198198

    def test_a_draft_cannot_be_credited(self, session, acme):
        concept = _f00006(session, acme)
        with pytest.raises(ValueError, match="definitieve factuur"):
            svc.create_credit_note(session, concept)

    def test_a_credit_note_gets_its_own_number(self, session, acme):
        origineel = _f00006(session, acme)
        svc.finalise(session, origineel)
        credit = svc.create_credit_note(session, origineel)
        svc.finalise(session, credit)
        assert (origineel.nummer, credit.nummer) == ("F00001", "F00002")


class TestPayments:
    def test_partial_payment_leaves_the_invoice_open(self, session, acme):
        invoice = _f00006(session, acme)
        svc.finalise(session, invoice)
        svc.register_payment(session, invoice, 100000, dt.date(2023, 2, 20))
        assert invoice.openstaand_cents == 98198
        assert invoice.status != InvoiceStatus.BETAALD

    def test_payments_summing_to_the_total_close_the_invoice(self, session, acme):
        invoice = _f00006(session, acme)
        svc.finalise(session, invoice)
        svc.register_payment(session, invoice, 100000, dt.date(2023, 2, 20))
        svc.register_payment(session, invoice, 98198, dt.date(2023, 2, 25))
        assert invoice.openstaand_cents == 0
        assert invoice.status == InvoiceStatus.BETAALD
        assert invoice.betaald_op == dt.date(2023, 2, 25)


class TestDuplication:
    def test_duplicating_copies_the_lines_into_a_new_draft(self, session, acme):
        origineel = _f00006(session, acme)
        svc.finalise(session, origineel)
        kopie = svc.duplicate(session, origineel)
        assert kopie.status == InvoiceStatus.CONCEPT
        assert kopie.nummer is None
        assert kopie.subtotaal_cents == origineel.subtotaal_cents
        assert [r.code for r in kopie.regels] == ["ADSD", "ACME", "NOVA"]


class TestInvoicingFromHours:
    def test_unbilled_hours_become_one_line_per_project(self, session, acme, project_adsd):
        for dag, uren in [(1, "8"), (2, "8"), (3, "4,5")]:
            session.add(
                TimeEntry(
                    datum=dt.date(2023, 2, dag),
                    project_id=project_adsd.id,
                    uren_milli=money.quantity_to_milli(uren),
                    omschrijving="werk",
                )
            )
        session.flush()

        invoice = svc.draft_from_hours(session, acme, dt.date(2023, 2, 1), dt.date(2023, 2, 28))
        assert len(invoice.regels) == 1
        regel = invoice.regels[0]
        assert regel.code == "ADSD"
        assert regel.aantal_milli == 20500
        assert regel.totaal_cents == 36900  # 20,5 uur x € 18,00

    def test_the_same_hours_cannot_be_billed_twice(self, session, acme, project_adsd):
        session.add(
            TimeEntry(
                datum=dt.date(2023, 2, 1), project_id=project_adsd.id,
                uren_milli=8000, omschrijving="werk",
            )
        )
        session.flush()
        svc.draft_from_hours(session, acme, dt.date(2023, 2, 1), dt.date(2023, 2, 28))
        with pytest.raises(ValueError, match="Geen ongefactureerde"):
            svc.draft_from_hours(session, acme, dt.date(2023, 2, 1), dt.date(2023, 2, 28))

    def test_non_billable_hours_are_not_invoiced(self, session, acme, project_adsd):
        session.add(
            TimeEntry(
                datum=dt.date(2023, 2, 1), project_id=project_adsd.id,
                uren_milli=8000, omschrijving="administratie", declarabel=False,
            )
        )
        session.flush()
        with pytest.raises(ValueError, match="Geen ongefactureerde"):
            svc.draft_from_hours(session, acme, dt.date(2023, 2, 1), dt.date(2023, 2, 28))
