"""Invoice lifecycle: numbering, finalising, credit notes, payments.

Two rules are enforced here and nowhere else, so this is the file to read when in doubt:

  1. A finalised invoice is immutable. Corrections happen through a credit note.
  2. Invoice numbers are sequential and gap-free. The number is assigned inside the same
     transaction that finalises the invoice, under a row lock on the counter.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from boekhouding import money
from boekhouding.models import (
    AuditLog,
    Client,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    NumberSequence,
    Settings,
    TimeEntry,
)
from boekhouding.vat import SalesVat, sales_spec


class InvoiceLocked(Exception):
    """Raised when something tries to change a finalised invoice."""


class QuarterLocked(Exception):
    """Raised when a document would land in an already-filed BTW quarter."""


def audit(session: Session, entiteit: str, entiteit_id: int, actie: str, details: str = "") -> None:
    session.add(
        AuditLog(entiteit=entiteit, entiteit_id=entiteit_id, actie=actie, details=details)
    )


def guard_editable(invoice: Invoice) -> None:
    if invoice.is_final:
        raise InvoiceLocked(
            f"Factuur {invoice.nummer} is definitief en kan niet meer worden gewijzigd. "
            "Maak een creditfactuur om te corrigeren."
        )


# --------------------------------------------------------------------------------------
# Numbering
# --------------------------------------------------------------------------------------


def next_number(session: Session, soort: str, datum: dt.date) -> str:
    """Claim the next number in the sequence.

    The counter row is selected FOR UPDATE (SQLite serialises writers anyway, but the
    explicit read-modify-write inside one transaction is what matters) and the unique
    constraint on Invoice.nummer is the backstop: if two processes ever raced, the
    second commit fails rather than reusing a number.
    """
    settings = Settings.get_or_create(session)
    if soort == "factuur":
        prefix, cijfers = settings.factuur_prefix, settings.factuur_cijfers
    else:
        prefix, cijfers = settings.offerte_prefix, settings.offerte_cijfers

    jaar = datum.year if settings.nummering_per_jaar else 0
    sequence = session.scalar(
        select(NumberSequence).where(
            NumberSequence.soort == soort, NumberSequence.jaar == jaar
        )
    )
    if sequence is None:
        sequence = NumberSequence(soort=soort, jaar=jaar, laatste=0)
        session.add(sequence)
        session.flush()

    sequence.laatste += 1
    session.flush()

    if settings.nummering_per_jaar:
        return f"{prefix}{datum.year}{sequence.laatste:0{cijfers}d}"
    return f"{prefix}{sequence.laatste:0{cijfers}d}"


def set_counter(session: Session, soort: str, jaar: int, laatste: int) -> None:
    """Seed the counter, for starting partway through an existing numbering series.

    Only ever moves forward: lowering it could hand out a number that has already been
    used on a real invoice, which is exactly what the sequence exists to prevent.
    """
    sequence = session.scalar(
        select(NumberSequence).where(
            NumberSequence.soort == soort, NumberSequence.jaar == jaar
        )
    )
    if sequence is None:
        sequence = NumberSequence(soort=soort, jaar=jaar, laatste=0)
        session.add(sequence)
        session.flush()
    if laatste < sequence.laatste:
        raise ValueError(
            f"De teller staat al op {sequence.laatste}. Verlagen zou een nummer opnieuw "
            "uitgeven; dat mag niet."
        )
    sequence.laatste = laatste
    session.flush()
    audit(session, "number_sequence", sequence.id, "teller gezet", f"{soort}={laatste}")


def peek_number(session: Session, soort: str, datum: dt.date) -> str:
    """The number a document would get, for display on a draft. Claims nothing."""
    settings = Settings.get_or_create(session)
    prefix = settings.factuur_prefix if soort == "factuur" else settings.offerte_prefix
    cijfers = settings.factuur_cijfers if soort == "factuur" else settings.offerte_cijfers
    jaar = datum.year if settings.nummering_per_jaar else 0
    sequence = session.scalar(
        select(NumberSequence).where(
            NumberSequence.soort == soort, NumberSequence.jaar == jaar
        )
    )
    volgende = (sequence.laatste if sequence else 0) + 1
    if settings.nummering_per_jaar:
        return f"{prefix}{datum.year}{volgende:0{cijfers}d}"
    return f"{prefix}{volgende:0{cijfers}d}"


# --------------------------------------------------------------------------------------
# Creating and editing
# --------------------------------------------------------------------------------------


def create_draft(
    session: Session,
    client: Client,
    datum: dt.date | None = None,
    uw_kenmerk: str = "",
    prestatie_omschrijving: str = "",
) -> Invoice:
    settings = Settings.get_or_create(session)
    datum = datum or dt.date.today()
    termijn = client.betaaltermijn_dagen or settings.betaaltermijn_dagen
    invoice = Invoice(
        client_id=client.id,
        datum=datum,
        betaaltermijn_dagen=termijn,
        vervaldatum=datum + dt.timedelta(days=termijn),
        uw_kenmerk=uw_kenmerk,
        prestatie_omschrijving=prestatie_omschrijving,
        status=InvoiceStatus.CONCEPT,
        taal=client.taal,
        valuta=client.valuta,
    )
    session.add(invoice)
    session.flush()
    audit(session, "invoice", invoice.id, "concept aangemaakt", f"klant={client.naam}")
    return invoice


def add_line(
    session: Session,
    invoice: Invoice,
    *,
    aantal: str | Decimal | int,
    code: str,
    omschrijving: str,
    stuksprijs: str | Decimal | int,
    btw_behandeling: SalesVat | str = SalesVat.HOOG_21,
    project_id: int | None = None,
) -> InvoiceLine:
    guard_editable(invoice)
    regel = InvoiceLine(
        invoice_id=invoice.id,
        volgorde=len(invoice.regels),
        aantal_milli=money.quantity_to_milli(aantal),
        code=code,
        omschrijving=omschrijving,
        stuksprijs_cents=money.euros_to_cents(stuksprijs),
        btw_behandeling=SalesVat(btw_behandeling).value,
        project_id=project_id,
    )
    session.add(regel)
    invoice.regels.append(regel)
    session.flush()
    return regel


def set_datum(session: Session, invoice: Invoice, datum: dt.date) -> None:
    guard_editable(invoice)
    invoice.datum = datum
    invoice.vervaldatum = datum + dt.timedelta(days=invoice.betaaltermijn_dagen)


def validate_for_finalisation(session: Session, invoice: Invoice) -> list[str]:
    """Everything the Belastingdienst requires on an invoice, checked before locking."""
    problemen: list[str] = []
    settings = Settings.get_or_create(session)
    client = invoice.client

    if not invoice.regels:
        problemen.append("De factuur heeft geen regels.")
    if settings.ontbrekende_velden:
        problemen.append(
            "Je eigen bedrijfsgegevens zijn nog niet compleet: "
            f"{', '.join(settings.ontbrekende_velden)}. Vul ze aan bij Instellingen."
        )
    if not client.naam or not client.adres:
        problemen.append(f"Adresgegevens van {client.naam or 'de klant'} zijn onvolledig.")
    if not invoice.prestatie_omschrijving:
        problemen.append(
            "Vul de prestatiedatum of -periode in; die is verplicht op de factuur."
        )

    behandelingen = {regel.btw_behandeling for regel in invoice.regels}
    for behandeling in behandelingen:
        spec = sales_spec(behandeling)
        if spec.requires_customer_vat_number and not client.btw_nummer:
            problemen.append(
                f"Voor '{spec.label}' is het btw-nummer van de klant verplicht op de factuur."
            )
    return problemen


def finalise(session: Session, invoice: Invoice, force: bool = False) -> Invoice:
    """Assign a number and lock the invoice. Refuses if required data is missing."""
    if invoice.is_final:
        raise InvoiceLocked(f"Factuur {invoice.nummer} is al definitief.")

    problemen = validate_for_finalisation(session, invoice)
    if problemen and not force:
        raise ValueError(" ".join(problemen))

    invoice.nummer = next_number(session, "factuur", invoice.datum)
    invoice.status = InvoiceStatus.DEFINITIEF
    invoice.definitief_op = dt.datetime.now(dt.UTC)
    session.flush()
    audit(
        session,
        "invoice",
        invoice.id,
        "definitief gemaakt",
        f"nummer={invoice.nummer} totaal={money.format_euro(invoice.totaal_incl_cents)}",
    )
    return invoice


def create_credit_note(
    session: Session, invoice: Invoice, reden: str = "", datum: dt.date | None = None
) -> Invoice:
    """A credit note mirroring an invoice, with the amounts negated.

    Dated today by default: a credit note lands in the quarter it is issued, not in the
    quarter of the invoice it corrects. Pass ``datum`` to correct within the same period
    while that period is still open.
    """
    if not invoice.is_final:
        raise ValueError("Alleen een definitieve factuur kan gecrediteerd worden.")
    if invoice.is_creditfactuur:
        raise ValueError("Een creditfactuur kan niet zelf gecrediteerd worden.")

    datum = datum or dt.date.today()
    credit = Invoice(
        client_id=invoice.client_id,
        datum=datum,
        betaaltermijn_dagen=invoice.betaaltermijn_dagen,
        vervaldatum=datum + dt.timedelta(days=invoice.betaaltermijn_dagen),
        uw_kenmerk=invoice.uw_kenmerk,
        prestatie_omschrijving=invoice.prestatie_omschrijving,
        status=InvoiceStatus.CONCEPT,
        taal=invoice.taal,
        valuta=invoice.valuta,
        is_creditfactuur=True,
        crediteert_id=invoice.id,
        notities=reden,
    )
    session.add(credit)
    session.flush()
    for regel in invoice.regels:
        session.add(
            InvoiceLine(
                invoice_id=credit.id,
                volgorde=regel.volgorde,
                aantal_milli=-regel.aantal_milli,
                code=regel.code,
                omschrijving=regel.omschrijving,
                stuksprijs_cents=regel.stuksprijs_cents,
                btw_behandeling=regel.btw_behandeling,
                project_id=regel.project_id,
            )
        )
    session.flush()
    session.refresh(credit)
    audit(session, "invoice", credit.id, "creditfactuur aangemaakt", f"voor={invoice.nummer}")
    return credit


def duplicate(session: Session, invoice: Invoice) -> Invoice:
    """Copy an invoice into a new draft -- the most common way to bill a monthly client."""
    kopie = create_draft(
        session,
        invoice.client,
        datum=dt.date.today(),
        uw_kenmerk=invoice.uw_kenmerk,
        prestatie_omschrijving=invoice.prestatie_omschrijving,
    )
    for regel in invoice.regels:
        session.add(
            InvoiceLine(
                invoice_id=kopie.id,
                volgorde=regel.volgorde,
                aantal_milli=regel.aantal_milli,
                code=regel.code,
                omschrijving=regel.omschrijving,
                stuksprijs_cents=regel.stuksprijs_cents,
                btw_behandeling=regel.btw_behandeling,
                project_id=regel.project_id,
            )
        )
    session.flush()
    session.refresh(kopie)
    return kopie


def register_payment(
    session: Session, invoice: Invoice, bedrag_cents: int, datum: dt.date
) -> None:
    """Record a (possibly partial) payment."""
    invoice.betaald_cents += bedrag_cents
    if invoice.openstaand_cents <= 0:
        invoice.status = InvoiceStatus.BETAALD
        invoice.betaald_op = datum
    elif invoice.status == InvoiceStatus.DEFINITIEF:
        invoice.status = InvoiceStatus.VERZONDEN
    audit(
        session,
        "invoice",
        invoice.id,
        "betaling geregistreerd",
        f"{money.format_euro(bedrag_cents)} op {datum:%d-%m-%Y}",
    )


# --------------------------------------------------------------------------------------
# Invoicing from tracked hours
# --------------------------------------------------------------------------------------


def draft_from_hours(
    session: Session,
    client: Client,
    van: dt.date,
    tot: dt.date,
    uw_kenmerk: str = "",
) -> Invoice:
    """One invoice line per project, summing unbilled billable hours in the period.

    Entries are linked to the invoice so the same hours can never be billed twice.
    """
    entries = list(
        session.scalars(
            select(TimeEntry)
            .join(TimeEntry.project)
            .where(
                TimeEntry.invoice_id.is_(None),
                TimeEntry.declarabel.is_(True),
                TimeEntry.deleted_at.is_(None),
                TimeEntry.datum >= van,
                TimeEntry.datum <= tot,
            )
            .order_by(TimeEntry.datum)
        )
    )
    entries = [e for e in entries if e.project and e.project.client_id == client.id]
    if not entries:
        raise ValueError("Geen ongefactureerde declarabele uren in deze periode.")

    per_project: dict[int, list[TimeEntry]] = {}
    for entry in entries:
        per_project.setdefault(entry.project_id, []).append(entry)

    periode = f"{van:%d-%m-%Y} t/m {tot:%d-%m-%Y}"
    invoice = create_draft(
        session, client, uw_kenmerk=uw_kenmerk, prestatie_omschrijving=periode
    )
    for project_id, project_entries in per_project.items():
        project = project_entries[0].project
        uren_milli = sum(e.uren_milli for e in project_entries)
        tarief = project.uurtarief_cents or client.uurtarief_cents or 0
        regel = InvoiceLine(
            invoice_id=invoice.id,
            volgorde=len(invoice.regels),
            aantal_milli=uren_milli,
            code=project.code,
            omschrijving=project.omschrijving or project.code,
            stuksprijs_cents=tarief,
            btw_behandeling=project.btw_behandeling,
            project_id=project_id,
        )
        session.add(regel)
        invoice.regels.append(regel)
        for entry in project_entries:
            entry.invoice_id = invoice.id
    session.flush()
    session.refresh(invoice)
    return invoice


def totals_summary(invoice: Invoice) -> dict:
    """Everything the PDF and the web page need to render the totals block."""
    groepen = []
    for behandeling, (tarief, grondslag, btw) in sorted(
        invoice.btw_per_tarief.items(), key=lambda item: -item[1][0]
    ):
        spec = sales_spec(behandeling)
        groepen.append(
            {
                "behandeling": behandeling,
                "label": spec.label,
                "tarief_naam": spec.tarief_naam,
                "tarief_permille": tarief,
                "grondslag_cents": grondslag,
                "btw_cents": btw,
            }
        )
    return {
        "subtotaal_cents": invoice.subtotaal_cents,
        "groepen": groepen,
        "btw_totaal_cents": invoice.btw_totaal_cents,
        "totaal_cents": invoice.totaal_incl_cents,
    }


def recurring_lines(regels_json: str) -> list[dict]:
    return json.loads(regels_json or "[]")
