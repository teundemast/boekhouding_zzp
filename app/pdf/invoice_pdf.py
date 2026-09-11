"""Invoice PDF, laid out to match the invoices I already send.

The layout follows F00006: my details top right, the client block top left, a centred
FACTUUR heading, a metadata block, the line table, the totals block, and the payment
sentence at the bottom.

A finalised invoice's PDF is written once and never regenerated -- the file that was
sent is the record.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from reportlab.lib.colors import HexColor, black
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas as pdfcanvas

from app import money
from app.models import Invoice, Settings
from app.services.invoices import totals_summary
from app.vat import sales_spec

PAGE_W, PAGE_H = A4
MARGIN = 56.0
FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"

LABELS = {
    "nl": {
        "titel": "FACTUUR",
        "credit_titel": "CREDITFACTUUR",
        "datum": "Datum:",
        "nummer": "Factuurnummer:",
        "klantnummer": "Klantnummer:",
        "kenmerk": "Uw kenmerk:",
        "periode": "Prestatieperiode:",
        "aantal": "Aantal",
        "code": "Code",
        "omschrijving": "Omschrijving",
        "totaal": "Totaal",
        "btw": "Btw",
        "subtotaal": "Totaal excl btw",
        "te_betalen": "Totaal te betalen",
        "crediteert": "Creditering van factuur",
    },
    "en": {
        "titel": "INVOICE",
        "credit_titel": "CREDIT NOTE",
        "datum": "Date:",
        "nummer": "Invoice number:",
        "klantnummer": "Customer number:",
        "kenmerk": "Your reference:",
        "periode": "Service period:",
        "aantal": "Quantity",
        "code": "Code",
        "omschrijving": "Description",
        "totaal": "Total",
        "btw": "VAT",
        "subtotaal": "Total excl. VAT",
        "te_betalen": "Total due",
        "crediteert": "Credit note for invoice",
    },
}

# Column x-positions, tuned so the description column has room for two lines of text.
COL_AANTAL = MARGIN
COL_CODE = MARGIN + 52
COL_OMSCHRIJVING = MARGIN + 118
COL_EURO = PAGE_W - MARGIN - 168
COL_BEDRAG_RIGHT = PAGE_W - MARGIN - 62
COL_BTW_RIGHT = PAGE_W - MARGIN
OMSCHRIJVING_BREEDTE = COL_EURO - COL_OMSCHRIJVING - 12


def _draw_right(c: pdfcanvas.Canvas, x: float, y: float, text: str) -> None:
    c.drawRightString(x, y, text)


def _percentage(permille: int) -> str:
    if permille % 10 == 0:
        return f"{permille // 10}%"
    return f"{permille / 10:.1f}".replace(".", ",") + "%"


def render(invoice: Invoice, settings: Settings, doelpad: Path) -> Path:
    labels = LABELS.get(invoice.taal, LABELS["nl"])
    accent = HexColor(settings.accentkleur) if settings.accentkleur else black

    doelpad.parent.mkdir(parents=True, exist_ok=True)
    c = pdfcanvas.Canvas(str(doelpad), pagesize=A4)
    c.setTitle(f"{labels['titel']} {invoice.nummer or 'concept'}")
    c.setAuthor(settings.bedrijfsnaam)

    # ---- Own details, top right ---------------------------------------------------
    y = PAGE_H - MARGIN - 10
    if settings.logo_pad and Path(settings.logo_pad).exists():
        try:
            c.drawImage(
                settings.logo_pad, MARGIN, y - 30, width=120, height=40,
                preserveAspectRatio=True, anchor="sw", mask="auto",
            )
        except Exception:
            pass  # a broken logo must never stop an invoice from being produced

    c.setFont(FONT_BOLD, 8)
    _draw_right(c, PAGE_W - MARGIN, y, settings.bedrijfsnaam)
    c.setFont(FONT, 8)
    for regel in [
        settings.adres,
        f"{settings.postcode} {settings.plaats}",
        settings.telefoon,
        settings.email,
    ]:
        y -= 11
        _draw_right(c, PAGE_W - MARGIN, y, regel)

    y -= 22
    for regel in [settings.btw_nummer, settings.iban, settings.kvk_nummer]:
        _draw_right(c, PAGE_W - MARGIN, y, regel)
        y -= 11

    # ---- Client block, top left ---------------------------------------------------
    y = PAGE_H - MARGIN - 10
    c.setFont(FONT, 9)
    for regel in invoice.client.adresregels:
        c.drawString(MARGIN, y, regel)
        y -= 12

    # ---- Heading ------------------------------------------------------------------
    titel = labels["credit_titel"] if invoice.is_creditfactuur else labels["titel"]
    c.setFont(FONT_BOLD, 20)
    c.setFillColor(accent)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 285, titel)
    c.setFillColor(black)

    # ---- Metadata -----------------------------------------------------------------
    y = PAGE_H - 355
    c.setFont(FONT, 9)
    meta = [
        (labels["datum"], f"{invoice.datum:%d-%m-%Y}"),
        (labels["nummer"], invoice.nummer or "CONCEPT"),
        (labels["klantnummer"], invoice.client.klantnummer or invoice.client.naam),
        (labels["kenmerk"], invoice.uw_kenmerk or ""),
    ]
    if invoice.prestatie_omschrijving:
        meta.append((labels["periode"], invoice.prestatie_omschrijving))
    if invoice.is_creditfactuur and invoice.crediteert is not None:
        meta.append((labels["crediteert"], invoice.crediteert.nummer or ""))

    for label, waarde in meta:
        c.drawString(MARGIN, y, label)
        c.drawString(MARGIN + 100, y, waarde)
        y -= 12

    # ---- Line table ---------------------------------------------------------------
    y = PAGE_H - 480
    c.setFont(FONT_BOLD, 9)
    c.drawString(COL_AANTAL, y, labels["aantal"])
    c.drawString(COL_CODE, y, labels["code"])
    c.drawString(COL_OMSCHRIJVING, y, labels["omschrijving"])
    _draw_right(c, COL_BEDRAG_RIGHT, y, labels["totaal"])
    _draw_right(c, COL_BTW_RIGHT, y, labels["btw"])

    y -= 6
    c.setLineWidth(0.7)
    c.line(MARGIN, y, PAGE_W - MARGIN, y)
    y -= 15

    c.setFont(FONT, 9)
    for regel in invoice.regels:
        stukken = simpleSplit(regel.omschrijving, FONT, 9, OMSCHRIJVING_BREEDTE)
        benodigd = max(len(stukken), 1) * 11 + 4
        if y - benodigd < MARGIN + 120:
            c.showPage()
            y = PAGE_H - MARGIN - 20
            c.setFont(FONT, 9)

        spec = sales_spec(regel.btw_behandeling)
        c.drawString(COL_AANTAL, y, money.format_quantity(regel.aantal_milli))
        c.drawString(COL_CODE, y, regel.code)
        for index, stuk in enumerate(stukken or [""]):
            c.drawString(COL_OMSCHRIJVING, y - index * 11, stuk)
        c.drawString(COL_EURO, y, "€")
        _draw_right(c, COL_BEDRAG_RIGHT, y, money.format_euro(regel.totaal_cents, symbol=False))
        _draw_right(c, COL_BTW_RIGHT, y, _percentage(spec.rate_permille))
        y -= benodigd

    # ---- Totals -------------------------------------------------------------------
    y -= 2
    c.line(MARGIN + 40, y, PAGE_W - MARGIN, y)
    y -= 15

    totalen = totals_summary(invoice)
    c.setFont(FONT, 9)
    _draw_right(c, COL_EURO - 8, y, labels["subtotaal"])
    c.drawString(COL_EURO, y, "€")
    _draw_right(c, COL_BEDRAG_RIGHT, y, money.format_euro(totalen["subtotaal_cents"], symbol=False))
    y -= 14

    for groep in totalen["groepen"]:
        if groep["tarief_permille"] == 0:
            omschrijving = f"{groep['label']} ({money.format_euro(groep['grondslag_cents'])})"
        else:
            naam = f" {groep['tarief_naam']}" if groep.get("tarief_naam") else ""
            omschrijving = (
                f"Btw{naam} {_percentage(groep['tarief_permille'])} "
                f"({money.format_euro(groep['grondslag_cents'])})"
            )
        _draw_right(c, COL_EURO - 8, y, omschrijving)
        c.drawString(COL_EURO, y, "€")
        _draw_right(c, COL_BEDRAG_RIGHT, y, money.format_euro(groep["btw_cents"], symbol=False))
        y -= 14

    y -= 2
    c.line(COL_EURO - 200, y + 8, PAGE_W - MARGIN, y + 8)
    c.setFont(FONT_BOLD, 9)
    _draw_right(c, COL_EURO - 8, y, labels["te_betalen"])
    c.drawString(COL_EURO, y, "€")
    _draw_right(c, COL_BEDRAG_RIGHT, y, money.format_euro(totalen["totaal_cents"], symbol=False))

    # ---- Legally required notes and footer ----------------------------------------
    y -= 40
    c.setFont(FONT, 8)
    behandelingen = {regel.btw_behandeling for regel in invoice.regels}
    for behandeling in behandelingen:
        spec = sales_spec(behandeling)
        if spec.invoice_note:
            tekst = spec.invoice_note
            if spec.requires_customer_vat_number and invoice.client.btw_nummer:
                tekst += f" - btw-nummer afnemer: {invoice.client.btw_nummer}"
            c.drawString(MARGIN, y, tekst)
            y -= 11

    if invoice.valuta != "EUR":
        koers = invoice.wisselkoers_micro / 1_000_000
        c.drawString(
            MARGIN,
            y,
            f"Bedragen in {invoice.valuta}; omrekenkoers op factuurdatum: 1 {invoice.valuta}"
            f" = {koers:.6f} EUR".replace(".", ","),
        )
        y -= 11

    voettekst = (
        settings.factuur_voettekst if invoice.taal == "nl" else settings.factuur_voettekst_en
    )
    c.setFont(FONT, 9)
    c.drawString(
        MARGIN,
        max(y - 20, MARGIN + 30),
        voettekst.format(betaaltermijn=invoice.betaaltermijn_dagen),
    )

    c.showPage()
    c.save()
    return doelpad


def pdf_path_for(invoice: Invoice, base: Path) -> Path:
    naam = invoice.nummer or f"concept-{invoice.id}"
    return base / f"{invoice.datum:%Y}" / f"{naam}.pdf"


def render_and_store(invoice: Invoice, settings: Settings, base: Path) -> Path:
    """Write the PDF for a finalised invoice, once. Existing files are never replaced."""
    doel = pdf_path_for(invoice, base)
    if invoice.is_final and doel.exists():
        return doel
    return render(invoice, settings, doel)


def render_preview(invoice: Invoice, settings: Settings, base: Path) -> Path:
    """A draft preview, always regenerated, kept apart from the stored records."""
    doel = base / "concept" / f"concept-{invoice.id}-{dt.datetime.now():%H%M%S}.pdf"
    return render(invoice, settings, doel)
