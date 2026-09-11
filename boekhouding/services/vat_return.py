"""The quarterly aangifte omzetbelasting.

This is the part that has to be right, so it is written to be read: every rubriek is
computed from the individual documents that make it up, and every figure keeps the list
of those documents alongside it for drill-down.

Method: factuurstelsel. The invoice date determines the period, not the payment date.
Only finalised invoices count -- a draft has not been issued and owes no BTW.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from boekhouding import money
from boekhouding.models import (
    BankTransaction,
    Expense,
    InboxDocument,
    Invoice,
    InvoiceStatus,
    Settings,
    VatFiling,
)
from boekhouding.vat import RUBRIEK_LABELS, Rubriek, purchase_spec, sales_spec

FINAL_STATUSES = (
    InvoiceStatus.DEFINITIEF,
    InvoiceStatus.VERZONDEN,
    InvoiceStatus.BETAALD,
    InvoiceStatus.ONINBAAR,
)


def quarter_range(jaar: int, kwartaal: int) -> tuple[dt.date, dt.date]:
    if kwartaal not in (1, 2, 3, 4):
        raise ValueError("Kwartaal moet 1, 2, 3 of 4 zijn.")
    start_maand = (kwartaal - 1) * 3 + 1
    start = dt.date(jaar, start_maand, 1)
    if kwartaal == 4:
        eind = dt.date(jaar, 12, 31)
    else:
        eind = dt.date(jaar, start_maand + 3, 1) - dt.timedelta(days=1)
    return start, eind


def quarter_of(datum: dt.date) -> tuple[int, int]:
    return datum.year, (datum.month - 1) // 3 + 1


def floor_euro(cents: int) -> int:
    """Round down to whole euros, in cents. Used for amounts I owe.

    The aangifte is filled in whole euros and the Belastingdienst allows rounding in
    your own favour ("in de btw-aangifte rondt u de btw-bedragen af op hele euro's.
    Dit mag u in uw voordeel doen."). For amounts owed, that means downwards -- and for
    a negative amount (a quarter with more credit notes than invoices) downwards is
    still in your favour, so a plain floor is correct in both directions.
    """
    return (cents // 100) * 100


def ceil_euro(cents: int) -> int:
    """Round up to whole euros, in cents. Used for voorbelasting, which I reclaim."""
    return -((-cents // 100) * 100)


@dataclass
class RubriekRegel:
    rubriek: Rubriek
    omzet_cents: int = 0
    btw_cents: int = 0
    posten: list[dict] = field(default_factory=list)
    #: True for rubriek 5b, the only line that is money coming back to me.
    is_voorbelasting: bool = False

    @property
    def label(self) -> str:
        return RUBRIEK_LABELS[self.rubriek]

    @property
    def omzet_aangifte_cents(self) -> int:
        """Turnover as it goes on the form: whole euros, rounded down."""
        return floor_euro(self.omzet_cents)

    @property
    def btw_aangifte_cents(self) -> int:
        """VAT as it goes on the form: whole euros, rounded in my favour."""
        return ceil_euro(self.btw_cents) if self.is_voorbelasting else floor_euro(self.btw_cents)


@dataclass
class VatReturn:
    jaar: int
    kwartaal: int
    van: dt.date
    tot: dt.date
    rubrieken: dict[Rubriek, RubriekRegel]
    verschuldigd_cents: int
    voorbelasting_cents: int
    saldo_cents: int
    kor_actief: bool
    icp: list[dict]
    aandachtspunten: list[str]
    checklist: list[dict]

    @property
    def te_betalen(self) -> bool:
        return self.saldo_cents >= 0

    def regel(self, rubriek: Rubriek) -> RubriekRegel:
        return self.rubrieken[rubriek]

    # -- The figures as they go on the form ------------------------------------------
    # Everything above is exact to the cent, which is what the audit trail needs. What
    # actually gets typed into the portal is whole euros, and 5a and the saldo must be
    # the sum of the *rounded* lines, otherwise the form does not add up.

    @property
    def verschuldigd_aangifte_cents(self) -> int:
        return sum(
            self.rubrieken[r].btw_aangifte_cents
            for r in (
                Rubriek.R1A, Rubriek.R1B, Rubriek.R1C, Rubriek.R1D, Rubriek.R1E,
                Rubriek.R2A, Rubriek.R3A, Rubriek.R3B, Rubriek.R3C,
                Rubriek.R4A, Rubriek.R4B,
            )
        )

    @property
    def voorbelasting_aangifte_cents(self) -> int:
        return self.rubrieken[Rubriek.R5B].btw_aangifte_cents

    @property
    def saldo_aangifte_cents(self) -> int:
        return self.verschuldigd_aangifte_cents - self.voorbelasting_aangifte_cents

    @property
    def afrondingsverschil_cents(self) -> int:
        """Difference between the exact saldo and the one on the form.

        Always in my favour, and only ever a few euros. Worth showing so the number is
        explainable rather than mysterious.
        """
        return self.saldo_aangifte_cents - self.saldo_cents

    def as_dict(self) -> dict:
        """Exact figures, for detecting later differences down to the cent."""
        return {
            r.value: {"omzet": regel.omzet_cents, "btw": regel.btw_cents}
            for r, regel in self.rubrieken.items()
        }

    def as_aangifte_dict(self) -> dict:
        """The whole-euro figures as typed into the portal."""
        return {
            r.value: {
                "omzet": regel.omzet_aangifte_cents,
                "btw": regel.btw_aangifte_cents,
            }
            for r, regel in self.rubrieken.items()
        } | {
            "5a": {"omzet": 0, "btw": self.verschuldigd_aangifte_cents},
            "saldo": {"omzet": 0, "btw": self.saldo_aangifte_cents},
        }


def _empty_rubrieken() -> dict[Rubriek, RubriekRegel]:
    return {
        rubriek: RubriekRegel(rubriek=rubriek, is_voorbelasting=rubriek is Rubriek.R5B)
        for rubriek in Rubriek
    }


def _kor_active_in(settings: Settings, van: dt.date, tot: dt.date) -> bool:
    if not settings.kor_actief:
        return False
    if settings.kor_startdatum is None:
        return True
    return settings.kor_startdatum <= tot


def expense_owed_vat_cents(expense: Expense) -> int:
    """Self-assessed BTW on a reverse-charge, EU or import purchase.

    Computed from the rate rather than read from the stored amount: the supplier did not
    charge it, so there is no invoiced figure to trust.
    """
    spec = purchase_spec(expense.btw_behandeling)
    if spec.owed_rubriek is None:
        return 0
    return money.vat_cents(expense.bedrag_excl_cents, spec.rate_permille)


def compute(session: Session, jaar: int, kwartaal: int) -> VatReturn:
    van, tot = quarter_range(jaar, kwartaal)
    settings = Settings.get_or_create(session)
    kor = _kor_active_in(settings, van, tot)
    rubrieken = _empty_rubrieken()

    # ---- Sales -------------------------------------------------------------------
    invoices = list(
        session.scalars(
            select(Invoice)
            .where(
                Invoice.datum >= van,
                Invoice.datum <= tot,
                Invoice.deleted_at.is_(None),
                Invoice.status.in_(FINAL_STATUSES),
            )
            .order_by(Invoice.datum, Invoice.nummer)
        )
    )

    icp_totalen: dict[tuple[str, str], dict] = {}

    for invoice in invoices:
        for behandeling, (_tarief, grondslag, btw) in invoice.btw_per_tarief.items():
            spec = sales_spec(behandeling)
            doel = Rubriek.R1E if kor else spec.rubriek
            regel = rubrieken[doel]
            regel.omzet_cents += grondslag
            if not kor:
                regel.btw_cents += btw
            regel.posten.append(
                {
                    "soort": "factuur",
                    "id": invoice.id,
                    "nummer": invoice.nummer,
                    "datum": invoice.datum,
                    "omschrijving": invoice.client.naam,
                    "behandeling": spec.label,
                    "omzet_cents": grondslag,
                    "btw_cents": 0 if kor else btw,
                }
            )

            if spec.icp and not kor:
                sleutel = (invoice.client.btw_nummer or "ONBEKEND", spec.code)
                entry = icp_totalen.setdefault(
                    sleutel,
                    {
                        "btw_nummer": invoice.client.btw_nummer,
                        "klant": invoice.client.naam,
                        "landcode": invoice.client.landcode,
                        "soort": "diensten" if "dienst" in spec.code else "goederen",
                        "bedrag_cents": 0,
                        "facturen": [],
                    },
                )
                entry["bedrag_cents"] += grondslag
                entry["facturen"].append(invoice.nummer)

    # ---- Purchases ---------------------------------------------------------------
    expenses = list(
        session.scalars(
            select(Expense)
            .where(
                Expense.datum >= van,
                Expense.datum <= tot,
                Expense.deleted_at.is_(None),
            )
            .order_by(Expense.datum)
        )
    )

    voorbelasting = 0
    voorbelasting_posten: list[dict] = []

    for expense in expenses:
        spec = purchase_spec(expense.btw_behandeling)

        # Self-assessed BTW: owed in 2a/4a/4b, and deductible again in 5b.
        if spec.owed_rubriek is not None:
            owed = expense_owed_vat_cents(expense)
            regel = rubrieken[spec.owed_rubriek]
            regel.omzet_cents += expense.bedrag_excl_cents
            regel.btw_cents += owed
            regel.posten.append(
                {
                    "soort": "kosten",
                    "id": expense.id,
                    "nummer": expense.factuurnummer,
                    "datum": expense.datum,
                    "omschrijving": f"{expense.leverancier} - {expense.omschrijving}",
                    "behandeling": spec.label,
                    "omzet_cents": expense.bedrag_excl_cents,
                    "btw_cents": owed,
                }
            )
            aftrekbaar = 0 if kor else money.round_half_up(
                Decimal(owed) * Decimal(expense.zakelijk_permille) / 1000
            )
        else:
            aftrekbaar = 0 if kor else expense.aftrekbare_btw_cents

        if aftrekbaar:
            voorbelasting += aftrekbaar
            voorbelasting_posten.append(
                {
                    "soort": "kosten",
                    "id": expense.id,
                    "nummer": expense.factuurnummer,
                    "datum": expense.datum,
                    "omschrijving": f"{expense.leverancier} - {expense.omschrijving}",
                    "behandeling": spec.label,
                    "omzet_cents": expense.bedrag_excl_cents,
                    "btw_cents": aftrekbaar,
                }
            )

    rubrieken[Rubriek.R5B].btw_cents = voorbelasting
    rubrieken[Rubriek.R5B].posten = voorbelasting_posten

    verschuldigd = sum(
        rubrieken[r].btw_cents
        for r in (
            Rubriek.R1A,
            Rubriek.R1B,
            Rubriek.R1C,
            Rubriek.R1D,
            Rubriek.R1E,
            Rubriek.R2A,
            Rubriek.R3A,
            Rubriek.R3B,
            Rubriek.R3C,
            Rubriek.R4A,
            Rubriek.R4B,
        )
    )
    rubrieken[Rubriek.R5A].btw_cents = verschuldigd
    saldo = verschuldigd - voorbelasting

    return VatReturn(
        jaar=jaar,
        kwartaal=kwartaal,
        van=van,
        tot=tot,
        rubrieken=rubrieken,
        verschuldigd_cents=verschuldigd,
        voorbelasting_cents=voorbelasting,
        saldo_cents=saldo,
        kor_actief=kor,
        icp=sorted(icp_totalen.values(), key=lambda e: e["klant"]),
        aandachtspunten=_aandachtspunten(session, jaar, kwartaal, van, tot),
        checklist=_checklist(session, van, tot),
    )


# --------------------------------------------------------------------------------------
# Warnings and pre-filing checks
# --------------------------------------------------------------------------------------


def oninbare_vorderingen(session: Session, peildatum: dt.date) -> list[dict]:
    """Invoices unpaid a year after the due date: the BTW on them can be reclaimed."""
    grens = peildatum - dt.timedelta(days=365)
    kandidaten = list(
        session.scalars(
            select(Invoice).where(
                Invoice.deleted_at.is_(None),
                Invoice.status.in_(FINAL_STATUSES),
                Invoice.vervaldatum.is_not(None),
                Invoice.vervaldatum <= grens,
                Invoice.oninbaar_geclaimd_kwartaal.is_(None),
            )
        )
    )
    resultaat = []
    for invoice in kandidaten:
        if invoice.openstaand_cents <= 0:
            continue
        onbetaald_deel = invoice.openstaand_cents
        terug_te_vragen = money.round_half_up(
            Decimal(invoice.btw_totaal_cents)
            * Decimal(onbetaald_deel)
            / Decimal(max(invoice.totaal_incl_cents, 1))
        )
        resultaat.append(
            {
                "invoice_id": invoice.id,
                "nummer": invoice.nummer,
                "klant": invoice.client.naam,
                "vervaldatum": invoice.vervaldatum,
                "openstaand_cents": onbetaald_deel,
                "btw_terug_cents": terug_te_vragen,
            }
        )
    return resultaat


def _aandachtspunten(
    session: Session, jaar: int, kwartaal: int, van: dt.date, tot: dt.date
) -> list[str]:
    punten: list[str] = []

    filing = session.scalar(
        select(VatFiling).where(VatFiling.jaar == jaar, VatFiling.kwartaal == kwartaal)
    )
    if filing is not None:
        punten.append(
            f"Dit kwartaal is ingediend op {filing.ingediend_op:%d-%m-%Y}. "
            "Wijzigingen sindsdien tellen als correctie."
        )

    vrijgesteld = rubriek_bevat_vrijgesteld(session, van, tot)
    if vrijgesteld:
        punten.append(
            f"Er staat vrijgestelde omzet ({money.format_euro(vrijgesteld)}) in dit "
            "kwartaal, geboekt in rubriek 1e. Waar vrijgestelde prestaties precies horen "
            "is niet eenduidig; controleer of je niet eigenlijk 0% of btw verlegd bedoelt."
        )

    for post in oninbare_vorderingen(session, tot):
        punten.append(
            f"Factuur {post['nummer']} ({post['klant']}) staat langer dan een jaar open; "
            f"je kunt {money.format_euro(post['btw_terug_cents'])} btw terugvragen."
        )

    settings = Settings.get_or_create(session)
    if not settings.kor_actief:
        omzet = _jaaromzet_cents(session, jaar)
        from boekhouding.taxyears import tax_year

        grens = tax_year(jaar).kor_omzetgrens_cents
        if omzet < grens and omzet > 0:
            pass  # below the ceiling is normal; only warn when close while in the KOR
    else:
        omzet = _jaaromzet_cents(session, jaar)
        from boekhouding.taxyears import tax_year

        grens = tax_year(jaar).kor_omzetgrens_cents
        if omzet > grens:
            punten.append(
                f"Je omzet dit jaar ({money.format_euro(omzet)}) is boven de KOR-grens "
                f"van {money.format_euro(grens)}. De KOR vervalt."
            )
        elif omzet > grens * 0.9:
            punten.append(
                f"Je omzet dit jaar ({money.format_euro(omzet)}) nadert de KOR-grens "
                f"van {money.format_euro(grens)}."
            )
    return punten


def rubriek_bevat_vrijgesteld(session: Session, van: dt.date, tot: dt.date) -> int:
    """Turnover booked as vrijgesteld in the period, if any."""
    from boekhouding.vat import SalesVat

    totaal = 0
    for invoice in session.scalars(
        select(Invoice).where(
            Invoice.datum >= van,
            Invoice.datum <= tot,
            Invoice.deleted_at.is_(None),
            Invoice.status.in_(FINAL_STATUSES),
        )
    ):
        for regel in invoice.regels:
            if regel.btw_behandeling == SalesVat.VRIJGESTELD.value:
                totaal += regel.totaal_cents
    return totaal


def _jaaromzet_cents(session: Session, jaar: int) -> int:
    invoices = session.scalars(
        select(Invoice).where(
            Invoice.datum >= dt.date(jaar, 1, 1),
            Invoice.datum <= dt.date(jaar, 12, 31),
            Invoice.deleted_at.is_(None),
            Invoice.status.in_(FINAL_STATUSES),
        )
    )
    return sum(invoice.subtotaal_cents for invoice in invoices)


def _checklist(session: Session, van: dt.date, tot: dt.date) -> list[dict]:
    """Things worth fixing before filing. Each item is a count plus a description."""
    items = []

    concepten = session.scalars(
        select(Invoice).where(
            Invoice.datum >= van,
            Invoice.datum <= tot,
            Invoice.deleted_at.is_(None),
            Invoice.status == InvoiceStatus.CONCEPT,
        )
    ).all()
    items.append(
        {
            "ok": not concepten,
            "tekst": f"{len(concepten)} conceptfactuur(en) met een datum in dit kwartaal",
            "detail": (
                "Een concept telt niet mee in de aangifte. "
                "Maak ze definitief of verwijder ze."
            ),
        }
    )

    onverwerkt = session.scalars(
        select(InboxDocument).where(
            InboxDocument.verwerkt.is_(False), InboxDocument.deleted_at.is_(None)
        )
    ).all()
    items.append(
        {
            "ok": not onverwerkt,
            "tekst": f"{len(onverwerkt)} document(en) in de inbox nog niet geboekt",
            "detail": "Bonnetjes die nog niet verwerkt zijn tellen niet mee als voorbelasting.",
        }
    )

    ongekoppeld = session.scalars(
        select(BankTransaction).where(
            BankTransaction.datum >= van,
            BankTransaction.datum <= tot,
            BankTransaction.status == "open",
            BankTransaction.deleted_at.is_(None),
        )
    ).all()
    items.append(
        {
            "ok": not ongekoppeld,
            "tekst": f"{len(ongekoppeld)} banktransactie(s) in dit kwartaal nog niet verwerkt",
            "detail": "Een onverwerkte afschrijving kan een kostenpost zijn die je mist.",
        }
    )

    zonder_bewijs = session.scalars(
        select(Expense).where(
            Expense.datum >= van,
            Expense.datum <= tot,
            Expense.deleted_at.is_(None),
            Expense.document_pad.is_(None),
        )
    ).all()
    items.append(
        {
            "ok": not zonder_bewijs,
            "tekst": f"{len(zonder_bewijs)} kostenpost(en) zonder bijlage",
            "detail": "Zonder factuur of bon is de voorbelasting bij een controle niet aftrekbaar.",
        }
    )
    return items


# --------------------------------------------------------------------------------------
# Filing and corrections
# --------------------------------------------------------------------------------------


def is_locked(session: Session, datum: dt.date) -> bool:
    jaar, kwartaal = quarter_of(datum)
    return (
        session.scalar(
            select(VatFiling).where(VatFiling.jaar == jaar, VatFiling.kwartaal == kwartaal)
        )
        is not None
    )


def mark_filed(session: Session, jaar: int, kwartaal: int, notities: str = "") -> VatFiling:
    bestaand = session.scalar(
        select(VatFiling).where(VatFiling.jaar == jaar, VatFiling.kwartaal == kwartaal)
    )
    if bestaand is not None:
        raise ValueError(f"Kwartaal {kwartaal} van {jaar} is al gemarkeerd als ingediend.")

    aangifte = compute(session, jaar, kwartaal)
    filing = VatFiling(
        jaar=jaar,
        kwartaal=kwartaal,
        ingediend_op=dt.date.today(),
        # Exact figures drive the correction comparison; the whole-euro figures record
        # what was actually typed into the portal.
        rubrieken_json=json.dumps(
            {"exact": aangifte.as_dict(), "aangifte": aangifte.as_aangifte_dict()}
        ),
        saldo_cents=aangifte.saldo_cents,
        notities=notities,
    )
    session.add(filing)
    session.flush()
    return filing


def corrections(session: Session, jaar: int, kwartaal: int) -> dict | None:
    """Difference between what was filed and what the books say now.

    A late document dated inside a filed quarter shows up here rather than silently
    changing a figure that has already gone to the Belastingdienst.
    """
    filing = session.scalar(
        select(VatFiling).where(VatFiling.jaar == jaar, VatFiling.kwartaal == kwartaal)
    )
    if filing is None:
        return None

    opgeslagen = json.loads(filing.rubrieken_json)
    # Filings made before the whole-euro rounding was added store the exact figures at
    # the top level; newer ones nest them under "exact".
    ingediend = opgeslagen.get("exact", opgeslagen)
    huidig = compute(session, jaar, kwartaal)
    verschillen = []
    for rubriek in Rubriek:
        oud = ingediend.get(rubriek.value, {"omzet": 0, "btw": 0})
        nieuw = huidig.rubrieken[rubriek]
        d_omzet = nieuw.omzet_cents - oud["omzet"]
        d_btw = nieuw.btw_cents - oud["btw"]
        if d_omzet or d_btw:
            verschillen.append(
                {
                    "rubriek": rubriek.value,
                    "label": RUBRIEK_LABELS[rubriek],
                    "omzet_verschil_cents": d_omzet,
                    "btw_verschil_cents": d_btw,
                }
            )

    saldo_verschil = huidig.saldo_cents - filing.saldo_cents
    from boekhouding.taxyears import tax_year

    grens = tax_year(jaar).suppletie_grens_cents
    return {
        "filing": filing,
        "verschillen": verschillen,
        "saldo_verschil_cents": saldo_verschil,
        "suppletie_nodig": abs(saldo_verschil) > grens,
        "grens_cents": grens,
        "advies": (
            f"Het verschil van {money.format_euro(abs(saldo_verschil))} is groter dan "
            f"{money.format_euro(grens)}: dien een suppletie in."
            if abs(saldo_verschil) > grens
            else f"Het verschil van {money.format_euro(abs(saldo_verschil))} blijft onder "
            f"{money.format_euro(grens)} en mag je in de eerstvolgende aangifte verwerken."
        )
        if saldo_verschil
        else "Geen verschil met de ingediende aangifte.",
    }


def history(session: Session, jaar: int, kwartaal: int, aantal: int = 4) -> list[VatReturn]:
    """The previous quarters, so an obviously wrong figure stands out."""
    resultaat = []
    j, k = jaar, kwartaal
    for _ in range(aantal):
        k -= 1
        if k == 0:
            k = 4
            j -= 1
        resultaat.append(compute(session, j, k))
    return resultaat
