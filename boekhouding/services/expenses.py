"""Recording costs and purchase invoices.

The BTW on a purchase comes from one of two places, and confusing them is the usual way
to file a wrong return:

  * The supplier charged it, and the amount on their invoice is authoritative. We store
    what they wrote, because that is what we are reclaiming.
  * Nobody charged it (reverse charge, EU acquisition, import). We compute it from the
    rate, declare it as owed, and reclaim the same amount.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from boekhouding import money
from boekhouding.db import DOCUMENTS_DIR
from boekhouding.models import Asset, Expense, ExpenseCategory, InboxDocument
from boekhouding.services.invoices import audit
from boekhouding.taxyears import tax_year
from boekhouding.vat import PurchaseVat, purchase_spec

#: Categories with the deduction rules that actually differ for an eenmanszaak.
STANDAARD_CATEGORIEEN = [
    ("KANT", "Kantoorkosten", 1000, ""),
    ("SOFT", "Software en abonnementen", 1000, ""),
    ("HARD", "Kleine hardware", 1000, "Boven de investeringsgrens: activeren en afschrijven."),
    ("TELE", "Telefoon en internet", 1000, "Corrigeer het privegebruik per post."),
    ("WERK", "Werkruimte thuis", 1000, "Alleen aftrekbaar bij een zelfstandige werkruimte."),
    ("VAKL", "Vakliteratuur", 1000, ""),
    ("OPLE", "Opleidingen en cursussen", 1000, ""),
    ("VERZ", "Verzekeringen", 1000, ""),
    ("ADMI", "Administratie en advies", 1000, ""),
    ("REIS", "Reiskosten", 1000, ""),
    ("AUTO", "Autokosten (zakelijke kilometers)", 1000, ""),
    ("REPR", "Representatie en relatiegeschenken", 800, "Beperkt aftrekbaar voor de IB."),
    ("ETEN", "Zakelijke etentjes", 800, "Beperkt aftrekbaar voor de IB."),
    ("MARK", "Marketing en website", 1000, ""),
    ("BANK", "Bankkosten", 1000, ""),
    ("CONT", "Contributies en abonnementen", 1000, ""),
    ("OVER", "Overige kosten", 1000, ""),
]


def ensure_categories(session: Session) -> None:
    bestaand = {c.code for c in session.scalars(select(ExpenseCategory))}
    for code, naam, permille, toelichting in STANDAARD_CATEGORIEEN:
        if code not in bestaand:
            session.add(
                ExpenseCategory(
                    code=code, naam=naam, aftrekbaar_permille=permille, toelichting=toelichting
                )
            )
    session.flush()


def computed_vat_cents(bedrag_excl_cents: int, behandeling: PurchaseVat | str) -> int:
    """BTW implied by the rate. Used for reverse-charge, EU and import purchases."""
    spec = purchase_spec(behandeling)
    return money.vat_cents(bedrag_excl_cents, spec.rate_permille)


def create(
    session: Session,
    *,
    datum: dt.date,
    leverancier: str,
    omschrijving: str,
    bedrag_excl: str | Decimal | int,
    btw_behandeling: PurchaseVat | str = PurchaseVat.BINNENLAND_21,
    btw: str | Decimal | int | None = None,
    category_id: int | None = None,
    factuurnummer: str = "",
    zakelijk_permille: int = 1000,
    document_pad: str | None = None,
) -> Expense:
    bedrag_excl_cents = money.euros_to_cents(bedrag_excl)
    spec = purchase_spec(btw_behandeling)

    if spec.owed_rubriek is not None:
        # Self-assessed: there is no supplier figure to trust.
        btw_cents = computed_vat_cents(bedrag_excl_cents, btw_behandeling)
    elif btw is not None:
        btw_cents = money.euros_to_cents(btw)
    else:
        btw_cents = money.vat_cents(bedrag_excl_cents, spec.rate_permille)

    expense = Expense(
        datum=datum,
        leverancier=leverancier,
        omschrijving=omschrijving,
        factuurnummer=factuurnummer,
        category_id=category_id,
        bedrag_excl_cents=bedrag_excl_cents,
        btw_behandeling=PurchaseVat(btw_behandeling).value,
        btw_cents=btw_cents,
        zakelijk_permille=zakelijk_permille,
        document_pad=document_pad,
    )
    session.add(expense)
    session.flush()
    audit(
        session,
        "expense",
        expense.id,
        "kostenpost aangemaakt",
        f"{leverancier} {money.format_euro(expense.totaal_incl_cents)}",
    )
    return expense


def should_capitalise(bedrag_excl_cents: int, jaar: int) -> bool:
    """Purchases at or above the investment threshold are assets, not costs."""
    return bedrag_excl_cents >= tax_year(jaar).investeringsgrens_cents


def capitalise(
    session: Session,
    expense: Expense,
    afschrijftermijn_jaren: int = 5,
    restwaarde: str | Decimal | int = 0,
) -> Asset:
    asset = Asset(
        omschrijving=f"{expense.leverancier} - {expense.omschrijving}",
        aanschafdatum=expense.datum,
        aanschafwaarde_cents=expense.bedrag_excl_cents,
        restwaarde_cents=money.euros_to_cents(restwaarde),
        afschrijftermijn_jaren=afschrijftermijn_jaren,
        zakelijk_permille=expense.zakelijk_permille,
        expense_id=expense.id,
    )
    session.add(asset)
    session.flush()
    audit(session, "asset", asset.id, "geactiveerd", f"uit kostenpost {expense.id}")
    return asset


def depreciation_for_year(asset: Asset, jaar: int) -> int:
    """Straight-line, pro rata in the year of purchase, in whole months."""
    af_te_schrijven = asset.aanschafwaarde_cents - asset.restwaarde_cents
    if af_te_schrijven <= 0 or asset.afschrijftermijn_jaren <= 0:
        return 0

    per_maand = Decimal(af_te_schrijven) / (asset.afschrijftermijn_jaren * 12)
    start = asset.aanschafdatum
    eind_maand = start.year * 12 + start.month + asset.afschrijftermijn_jaren * 12 - 1

    maanden = 0
    for maand in range(1, 13):
        absolute = jaar * 12 + maand
        if absolute < start.year * 12 + start.month:
            continue
        if absolute > eind_maand:
            continue
        if asset.verkocht_op and absolute > asset.verkocht_op.year * 12 + asset.verkocht_op.month:
            continue
        maanden += 1

    bedrag = money.round_half_up(per_maand * maanden)
    return money.round_half_up(Decimal(bedrag) * asset.zakelijk_permille / 1000)


def book_value(asset: Asset, per: dt.date) -> int:
    afgeschreven = sum(
        depreciation_for_year(asset, jaar)
        for jaar in range(asset.aanschafdatum.year, per.year + 1)
    )
    return max(asset.aanschafwaarde_cents - afgeschreven, asset.restwaarde_cents)


def kia_check(session: Session, jaar: int) -> dict:
    """Whether the year's investments reach the kleinschaligheidsinvesteringsaftrek."""
    assets = session.scalars(
        select(Asset).where(
            Asset.aanschafdatum >= dt.date(jaar, 1, 1),
            Asset.aanschafdatum <= dt.date(jaar, 12, 31),
            Asset.deleted_at.is_(None),
        )
    ).all()
    totaal = sum(a.aanschafwaarde_cents for a in assets)
    ondergrens = tax_year(jaar).kia_ondergrens_cents
    return {
        "jaar": jaar,
        "totaal_cents": totaal,
        "ondergrens_cents": ondergrens,
        "komt_in_aanmerking": totaal >= ondergrens,
        "aantal": len(assets),
    }


# --------------------------------------------------------------------------------------
# Document inbox
# --------------------------------------------------------------------------------------


def scan_inbox(session: Session, inbox: Path) -> list[InboxDocument]:
    """Register new files dropped in the inbox folder. Idempotent."""
    inbox.mkdir(parents=True, exist_ok=True)
    bekend = {d.pad for d in session.scalars(select(InboxDocument))}
    nieuw = []
    for pad in sorted(inbox.iterdir()):
        if not pad.is_file() or str(pad) in bekend:
            continue
        document = InboxDocument(bestandsnaam=pad.name, pad=str(pad))
        session.add(document)
        nieuw.append(document)
    session.flush()
    return nieuw


def store_document(bestandsnaam: str, inhoud: bytes, datum: dt.date) -> str:
    """Store an attachment immutably, under year/month, without overwriting."""
    doel_map = DOCUMENTS_DIR / f"{datum:%Y}" / f"{datum:%m}"
    doel_map.mkdir(parents=True, exist_ok=True)
    doel = doel_map / bestandsnaam
    teller = 1
    while doel.exists():
        doel = doel_map / f"{doel.stem}-{teller}{doel.suffix}"
        teller += 1
    doel.write_bytes(inhoud)
    return str(doel)
