"""The data model.

Rules that hold everywhere in this file:

  * Money is an integer number of eurocents, named ``*_cents``.
  * Quantities are integer thousandths, named ``*_milli``.
  * Nothing is ever hard-deleted. Records carry ``deleted_at``; the Belastingdienst
    requires seven years of history and a deleted invoice is still part of that history.
  * Finalised invoices are immutable. The guard lives in services/invoices.py, and the
    ``status`` column is what it checks.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from boekhouding import money
from boekhouding.vat import PurchaseVat, SalesVat


class Base(DeclarativeBase):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


# --------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------


class Settings(Base, TimestampMixin):
    """Single-row table holding everything that appears on an invoice."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Leeg bij een nieuwe installatie. Deze gegevens komen op elke factuur, dus ze
    # moeten van de gebruiker zelf komen: een standaardwaarde hier zou betekenen dat
    # iemand ongemerkt met andermans IBAN of btw-nummer factureert.
    bedrijfsnaam: Mapped[str] = mapped_column(String, default="")
    adres: Mapped[str] = mapped_column(String, default="")
    postcode: Mapped[str] = mapped_column(String, default="")
    plaats: Mapped[str] = mapped_column(String, default="")
    land: Mapped[str] = mapped_column(String, default="Nederland")
    telefoon: Mapped[str] = mapped_column(String, default="")
    email: Mapped[str] = mapped_column(String, default="")
    btw_nummer: Mapped[str] = mapped_column(String, default="")
    iban: Mapped[str] = mapped_column(String, default="")
    kvk_nummer: Mapped[str] = mapped_column(String, default="")

    factuur_prefix: Mapped[str] = mapped_column(String, default="F")
    factuur_cijfers: Mapped[int] = mapped_column(Integer, default=5)
    offerte_prefix: Mapped[str] = mapped_column(String, default="O")
    offerte_cijfers: Mapped[int] = mapped_column(Integer, default=5)
    #: Restart the invoice counter every calendar year, or keep counting across years.
    nummering_per_jaar: Mapped[bool] = mapped_column(Boolean, default=False)

    betaaltermijn_dagen: Mapped[int] = mapped_column(Integer, default=14)
    factuur_voettekst: Mapped[str] = mapped_column(
        Text,
        default=(
            "Gelieve deze factuur binnen {betaaltermijn} dagen onder vermelding "
            "van het factuurnummer te betalen."
        ),
    )
    factuur_voettekst_en: Mapped[str] = mapped_column(
        Text,
        default=(
            "Please pay this invoice within {betaaltermijn} days, quoting the "
            "invoice number."
        ),
    )
    logo_pad: Mapped[str | None] = mapped_column(String, default=None)
    accentkleur: Mapped[str] = mapped_column(String, default="#000000")
    toon_betaal_qr: Mapped[bool] = mapped_column(Boolean, default=False)

    #: Kleineondernemersregeling. When active, sales are exempt and voorbelasting is
    #: not deductible from the start date onwards.
    kor_actief: Mapped[bool] = mapped_column(Boolean, default=False)
    kor_startdatum: Mapped[dt.date | None] = mapped_column(Date, default=None)

    #: Date from which this system is authoritative; before it, opening balances apply.
    startdatum: Mapped[dt.date] = mapped_column(Date, default=lambda: dt.date(2023, 1, 1))
    #: Percentage of profit to set aside for income tax, shown on the dashboard.
    reservering_permille: Mapped[int] = mapped_column(Integer, default=350)

    @staticmethod
    def get_or_create(session: Session) -> Settings:
        settings = session.scalar(select(Settings).limit(1))
        if settings is None:
            settings = Settings()
            session.add(settings)
            session.flush()
        return settings

    @property
    def adresregels(self) -> list[str]:
        return [
            self.bedrijfsnaam,
            self.adres,
            f"{self.postcode} {self.plaats}",
            self.telefoon,
            self.email,
        ]

    #: Zonder deze velden mag er geen factuur de deur uit; ze zijn wettelijk verplicht.
    VERPLICHTE_VELDEN = {
        "bedrijfsnaam": "bedrijfsnaam",
        "adres": "adres",
        "plaats": "plaats",
        "btw_nummer": "btw-nummer",
        "kvk_nummer": "KvK-nummer",
        "iban": "IBAN",
    }

    @property
    def ontbrekende_velden(self) -> list[str]:
        return [
            omschrijving
            for veld, omschrijving in self.VERPLICHTE_VELDEN.items()
            if not (getattr(self, veld) or "").strip()
        ]

    @property
    def is_ingericht(self) -> bool:
        """False bij een verse installatie die nog ingevuld moet worden."""
        return not self.ontbrekende_velden


# --------------------------------------------------------------------------------------
# Numbering
# --------------------------------------------------------------------------------------


class NumberSequence(Base):
    """Gap-free counters.

    A row per (kind, year). The counter is incremented inside the same transaction that
    creates the numbered document, with the unique constraint on the document number as
    the last line of defence, so a crash can never produce a gap or a duplicate.
    """

    __tablename__ = "number_sequence"
    __table_args__ = (UniqueConstraint("soort", "jaar", name="uq_sequence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    soort: Mapped[str] = mapped_column(String)  # 'factuur' | 'offerte'
    jaar: Mapped[int] = mapped_column(Integer)
    laatste: Mapped[int] = mapped_column(Integer, default=0)


# --------------------------------------------------------------------------------------
# Clients and projects
# --------------------------------------------------------------------------------------


class Client(Base, TimestampMixin):
    __tablename__ = "client"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    naam: Mapped[str] = mapped_column(String)
    klantnummer: Mapped[str] = mapped_column(String, default="")
    contactpersoon: Mapped[str] = mapped_column(String, default="")
    email: Mapped[str] = mapped_column(String, default="")
    adres: Mapped[str] = mapped_column(String, default="")
    postcode: Mapped[str] = mapped_column(String, default="")
    plaats: Mapped[str] = mapped_column(String, default="")
    landcode: Mapped[str] = mapped_column(String, default="NL")
    land: Mapped[str] = mapped_column(String, default="Nederland")
    btw_nummer: Mapped[str] = mapped_column(String, default="")
    betaaltermijn_dagen: Mapped[int | None] = mapped_column(Integer, default=None)
    standaard_btw: Mapped[str] = mapped_column(String, default=SalesVat.HOOG_21.value)
    taal: Mapped[str] = mapped_column(String, default="nl")
    valuta: Mapped[str] = mapped_column(String, default="EUR")
    uurtarief_cents: Mapped[int | None] = mapped_column(Integer, default=None)
    notities: Mapped[str] = mapped_column(Text, default="")

    projecten: Mapped[list[Project]] = relationship(back_populates="client")
    facturen: Mapped[list[Invoice]] = relationship(back_populates="client")

    @property
    def adresregels(self) -> list[str]:
        regels = [self.naam]
        if self.contactpersoon:
            regels.append(self.contactpersoon)
        if self.adres:
            regels.append(self.adres)
        if self.postcode or self.plaats:
            regels.append(f"{self.postcode} {self.plaats}".strip())
        if self.land:
            regels.append(self.land)
        return regels


class Project(Base, TimestampMixin):
    """A stream of work for a client. The code ends up in the invoice's Code column."""

    __tablename__ = "project"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("client.id"))
    code: Mapped[str] = mapped_column(String)
    omschrijving: Mapped[str] = mapped_column(Text, default="")
    uurtarief_cents: Mapped[int] = mapped_column(Integer, default=0)
    btw_behandeling: Mapped[str] = mapped_column(String, default=SalesVat.HOOG_21.value)
    actief: Mapped[bool] = mapped_column(Boolean, default=True)

    client: Mapped[Client] = relationship(back_populates="projecten")


class TimeEntry(Base, TimestampMixin):
    __tablename__ = "time_entry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    datum: Mapped[dt.date] = mapped_column(Date)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("project.id"), default=None)
    uren_milli: Mapped[int] = mapped_column(Integer, default=0)
    omschrijving: Mapped[str] = mapped_column(Text, default="")
    declarabel: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Set once the hours have been billed; prevents billing them twice.
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoice.id"), default=None)

    project: Mapped[Project | None] = relationship()

    @property
    def uren(self) -> Decimal:
        return money.milli_to_decimal(self.uren_milli)


# --------------------------------------------------------------------------------------
# Invoices
# --------------------------------------------------------------------------------------


class InvoiceStatus(str):
    CONCEPT = "concept"
    DEFINITIEF = "definitief"
    VERZONDEN = "verzonden"
    BETAALD = "betaald"
    ONINBAAR = "oninbaar"


FINAL_STATUSES = {
    InvoiceStatus.DEFINITIEF,
    InvoiceStatus.VERZONDEN,
    InvoiceStatus.BETAALD,
    InvoiceStatus.ONINBAAR,
}


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoice"
    __table_args__ = (UniqueConstraint("nummer", name="uq_invoice_nummer"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nummer: Mapped[str | None] = mapped_column(String, default=None)
    client_id: Mapped[int] = mapped_column(ForeignKey("client.id"))
    datum: Mapped[dt.date] = mapped_column(Date, default=dt.date.today)
    vervaldatum: Mapped[dt.date | None] = mapped_column(Date, default=None)
    betaaltermijn_dagen: Mapped[int] = mapped_column(Integer, default=14)
    uw_kenmerk: Mapped[str] = mapped_column(String, default="")
    #: Period the work was delivered in; legally required alongside the invoice date.
    prestatie_omschrijving: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default=InvoiceStatus.CONCEPT)
    taal: Mapped[str] = mapped_column(String, default="nl")
    valuta: Mapped[str] = mapped_column(String, default="EUR")
    #: Rate to EUR at invoice date, in millionths (1.0 -> 1_000_000). Always 1 for EUR.
    wisselkoers_micro: Mapped[int] = mapped_column(Integer, default=1_000_000)
    notities: Mapped[str] = mapped_column(Text, default="")

    #: A credit note references the invoice it corrects.
    crediteert_id: Mapped[int | None] = mapped_column(ForeignKey("invoice.id"), default=None)
    is_creditfactuur: Mapped[bool] = mapped_column(Boolean, default=False)

    definitief_op: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None)
    pdf_pad: Mapped[str | None] = mapped_column(String, default=None)
    betaald_cents: Mapped[int] = mapped_column(Integer, default=0)
    betaald_op: Mapped[dt.date | None] = mapped_column(Date, default=None)
    #: Quarter in which the BTW on an uncollectible invoice was reclaimed.
    oninbaar_geclaimd_kwartaal: Mapped[str | None] = mapped_column(String, default=None)

    client: Mapped[Client] = relationship(back_populates="facturen")
    regels: Mapped[list[InvoiceLine]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="InvoiceLine.volgorde",
    )
    crediteert: Mapped[Invoice | None] = relationship(remote_side=[id])

    @property
    def is_final(self) -> bool:
        return self.status in FINAL_STATUSES

    @property
    def openstaand_cents(self) -> int:
        return self.totaal_incl_cents - self.betaald_cents

    @property
    def subtotaal_cents(self) -> int:
        return sum(regel.totaal_cents for regel in self.regels)

    @property
    def btw_per_tarief(self) -> dict[str, tuple[int, int, int]]:
        """{treatment: (rate_permille, grondslag_cents, btw_cents)}.

        BTW is calculated over the summed base per treatment rather than per line: that
        is what makes the totals block on the invoice reconcile exactly.
        """
        grondslagen: dict[str, int] = {}
        for regel in self.regels:
            grondslagen[regel.btw_behandeling] = (
                grondslagen.get(regel.btw_behandeling, 0) + regel.totaal_cents
            )
        from boekhouding.vat import sales_spec

        resultaat = {}
        for behandeling, grondslag in grondslagen.items():
            tarief = sales_spec(behandeling).rate_permille
            resultaat[behandeling] = (tarief, grondslag, money.vat_cents(grondslag, tarief))
        return resultaat

    @property
    def btw_totaal_cents(self) -> int:
        return sum(btw for _, _, btw in self.btw_per_tarief.values())

    @property
    def totaal_incl_cents(self) -> int:
        return self.subtotaal_cents + self.btw_totaal_cents

    @property
    def is_overdue(self) -> bool:
        if self.status == InvoiceStatus.BETAALD or self.vervaldatum is None:
            return False
        return self.vervaldatum < dt.date.today() and self.openstaand_cents > 0


class InvoiceLine(Base):
    __tablename__ = "invoice_line"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoice.id"))
    volgorde: Mapped[int] = mapped_column(Integer, default=0)
    aantal_milli: Mapped[int] = mapped_column(Integer, default=1000)
    code: Mapped[str] = mapped_column(String, default="")
    omschrijving: Mapped[str] = mapped_column(Text, default="")
    stuksprijs_cents: Mapped[int] = mapped_column(Integer, default=0)
    btw_behandeling: Mapped[str] = mapped_column(String, default=SalesVat.HOOG_21.value)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("project.id"), default=None)

    invoice: Mapped[Invoice] = relationship(back_populates="regels")

    @property
    def totaal_cents(self) -> int:
        return money.line_total_cents(self.aantal_milli, self.stuksprijs_cents)


class RecurringInvoice(Base, TimestampMixin):
    """Template that prepares a draft invoice on a monthly cadence. Never sends."""

    __tablename__ = "recurring_invoice"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("client.id"))
    omschrijving: Mapped[str] = mapped_column(String, default="")
    interval_maanden: Mapped[int] = mapped_column(Integer, default=1)
    volgende_datum: Mapped[dt.date] = mapped_column(Date)
    actief: Mapped[bool] = mapped_column(Boolean, default=True)
    #: JSON list of line dicts, kept simple deliberately.
    regels_json: Mapped[str] = mapped_column(Text, default="[]")

    client: Mapped[Client] = relationship()


# --------------------------------------------------------------------------------------
# Expenses and assets
# --------------------------------------------------------------------------------------


class ExpenseCategory(Base, TimestampMixin):
    __tablename__ = "expense_category"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String)
    naam: Mapped[str] = mapped_column(String)
    #: Deductible share of the cost for the income tax, in tenths of a percent.
    aftrekbaar_permille: Mapped[int] = mapped_column(Integer, default=1000)
    toelichting: Mapped[str] = mapped_column(Text, default="")


class Expense(Base, TimestampMixin):
    __tablename__ = "expense"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    datum: Mapped[dt.date] = mapped_column(Date)
    leverancier: Mapped[str] = mapped_column(String, default="")
    omschrijving: Mapped[str] = mapped_column(Text, default="")
    factuurnummer: Mapped[str] = mapped_column(String, default="")
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("expense_category.id"), default=None
    )
    bedrag_excl_cents: Mapped[int] = mapped_column(Integer, default=0)
    btw_behandeling: Mapped[str] = mapped_column(String, default=PurchaseVat.BINNENLAND_21.value)
    #: BTW as stated on the supplier's invoice. For reverse-charge and EU acquisitions
    #: this is self-assessed rather than charged, and is computed from the rate.
    btw_cents: Mapped[int] = mapped_column(Integer, default=0)
    #: Business share, in tenths of a percent. A phone used 70% for business is 700.
    zakelijk_permille: Mapped[int] = mapped_column(Integer, default=1000)
    betaald: Mapped[bool] = mapped_column(Boolean, default=True)
    document_pad: Mapped[str | None] = mapped_column(String, default=None)

    category: Mapped[ExpenseCategory | None] = relationship()

    @property
    def totaal_incl_cents(self) -> int:
        return self.bedrag_excl_cents + self.btw_cents

    @property
    def aftrekbare_btw_cents(self) -> int:
        """Voorbelasting, reduced by the private-use share."""
        from boekhouding.vat import purchase_spec

        if not purchase_spec(self.btw_behandeling).deductible:
            return 0
        return money.round_half_up(
            Decimal(self.btw_cents) * Decimal(self.zakelijk_permille) / 1000
        )

    @property
    def zakelijke_kosten_cents(self) -> int:
        """The part of the cost that is a business expense, before category limits."""
        return money.round_half_up(
            Decimal(self.bedrag_excl_cents) * Decimal(self.zakelijk_permille) / 1000
        )


class Asset(Base, TimestampMixin):
    """Capitalised investment, depreciated straight-line."""

    __tablename__ = "asset"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    omschrijving: Mapped[str] = mapped_column(String)
    aanschafdatum: Mapped[dt.date] = mapped_column(Date)
    aanschafwaarde_cents: Mapped[int] = mapped_column(Integer, default=0)
    restwaarde_cents: Mapped[int] = mapped_column(Integer, default=0)
    afschrijftermijn_jaren: Mapped[int] = mapped_column(Integer, default=5)
    zakelijk_permille: Mapped[int] = mapped_column(Integer, default=1000)
    expense_id: Mapped[int | None] = mapped_column(ForeignKey("expense.id"), default=None)
    verkocht_op: Mapped[dt.date | None] = mapped_column(Date, default=None)
    verkoopprijs_cents: Mapped[int | None] = mapped_column(Integer, default=None)


# --------------------------------------------------------------------------------------
# Bank and filings
# --------------------------------------------------------------------------------------


class BankTransaction(Base, TimestampMixin):
    __tablename__ = "bank_transaction"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_bank_fingerprint"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    datum: Mapped[dt.date] = mapped_column(Date)
    bedrag_cents: Mapped[int] = mapped_column(Integer)  # negative is money out
    tegenrekening: Mapped[str] = mapped_column(String, default="")
    tegenpartij: Mapped[str] = mapped_column(String, default="")
    omschrijving: Mapped[Text] = mapped_column(Text, default="")
    #: Stable hash of the source row, so re-importing a statement cannot duplicate it.
    fingerprint: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="open")  # open|gekoppeld|genegeerd
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoice.id"), default=None)
    expense_id: Mapped[int | None] = mapped_column(ForeignKey("expense.id"), default=None)
    soort: Mapped[str | None] = mapped_column(String, default=None)  # prive|belasting|...


class VatFiling(Base, TimestampMixin):
    """A quarter that has been filed. Locks the period against silent changes."""

    __tablename__ = "vat_filing"
    __table_args__ = (UniqueConstraint("jaar", "kwartaal", name="uq_filing_period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jaar: Mapped[int] = mapped_column(Integer)
    kwartaal: Mapped[int] = mapped_column(Integer)
    ingediend_op: Mapped[dt.date] = mapped_column(Date, default=dt.date.today)
    #: The figures as filed, so a later change is visible as a difference.
    rubrieken_json: Mapped[str] = mapped_column(Text, default="{}")
    saldo_cents: Mapped[int] = mapped_column(Integer, default=0)
    notities: Mapped[str] = mapped_column(Text, default="")


class AuditLog(Base):
    """What changed, when, and from what to what."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tijdstip: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    entiteit: Mapped[str] = mapped_column(String)
    entiteit_id: Mapped[int] = mapped_column(Integer)
    actie: Mapped[str] = mapped_column(String)
    details: Mapped[str] = mapped_column(Text, default="")


class InboxDocument(Base, TimestampMixin):
    """A receipt dropped in the inbox folder, waiting to be booked."""

    __tablename__ = "inbox_document"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bestandsnaam: Mapped[str] = mapped_column(String)
    pad: Mapped[str] = mapped_column(String)
    ontvangen_op: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    verwerkt: Mapped[bool] = mapped_column(Boolean, default=False)
    expense_id: Mapped[int | None] = mapped_column(ForeignKey("expense.id"), default=None)
