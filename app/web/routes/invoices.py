from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import select

from app import db, money
from app.models import Client, Invoice, InvoiceLine, InvoiceStatus, Settings
from app.pdf import invoice_pdf
from app.services import invoices as svc
from app.services import vat_return as btw_svc
from app.vat import SALES_SPECS, SalesVat

router = APIRouter(prefix="/facturen", tags=["facturen"])


def _templates():
    from app.web.main import templates

    return templates


def _btw_opties():
    return [(t.value, spec.label) for t, spec in SALES_SPECS.items()]


@router.get("", response_class=HTMLResponse)
def lijst(request: Request, status: str = "", jaar: str = ""):
    with db.session_scope() as session:
        query = select(Invoice).where(Invoice.deleted_at.is_(None))
        if status:
            query = query.where(Invoice.status == status)
        if jaar:
            query = query.where(
                Invoice.datum >= dt.date(int(jaar), 1, 1),
                Invoice.datum <= dt.date(int(jaar), 12, 31),
            )
        facturen = list(session.scalars(query.order_by(Invoice.datum.desc(), Invoice.id.desc())))
        return _templates().TemplateResponse(
            request,
            "facturen.html",
            {
                "titel": "Facturen",
                "facturen": facturen,
                "status": status,
                "jaar": jaar,
                "openstaand_totaal": sum(
                    f.openstaand_cents for f in facturen if f.openstaand_cents > 0
                ),
            },
        )


@router.get("/nieuw", response_class=HTMLResponse)
def nieuw(request: Request):
    with db.session_scope() as session:
        klanten = list(
            session.scalars(
                select(Client).where(Client.deleted_at.is_(None)).order_by(Client.naam)
            )
        )
        return _templates().TemplateResponse(
            request,
            "factuur_nieuw.html",
            {"titel": "Nieuwe factuur", "klanten": klanten, "vandaag": dt.date.today()},
        )


@router.post("/nieuw")
def aanmaken(
    client_id: int = Form(...),
    datum: str = Form(...),
    uw_kenmerk: str = Form(""),
    prestatie_omschrijving: str = Form(""),
):
    with db.session_scope() as session:
        klant = session.get(Client, client_id)
        invoice = svc.create_draft(
            session,
            klant,
            datum=dt.date.fromisoformat(datum),
            uw_kenmerk=uw_kenmerk,
            prestatie_omschrijving=prestatie_omschrijving,
        )
        return RedirectResponse(f"/facturen/{invoice.id}", status_code=303)


@router.get("/{factuur_id}", response_class=HTMLResponse)
def tonen(request: Request, factuur_id: int, fout: str = ""):
    with db.session_scope() as session:
        invoice = session.get(Invoice, factuur_id)
        if invoice is None:
            raise HTTPException(404, "Factuur niet gevonden")
        problemen = (
            svc.validate_for_finalisation(session, invoice) if not invoice.is_final else []
        )
        return _templates().TemplateResponse(
            request,
            "factuur.html",
            {
                "titel": f"Factuur {invoice.nummer or 'concept'}",
                "factuur": invoice,
                "totalen": svc.totals_summary(invoice),
                "btw_opties": _btw_opties(),
                "problemen": problemen,
                "volgend_nummer": svc.peek_number(session, "factuur", invoice.datum),
                "kwartaal_vergrendeld": btw_svc.is_locked(session, invoice.datum),
                "fout": fout,
            },
        )


@router.post("/{factuur_id}/kop")
def kop_opslaan(
    factuur_id: int,
    datum: str = Form(...),
    uw_kenmerk: str = Form(""),
    prestatie_omschrijving: str = Form(""),
    betaaltermijn_dagen: int = Form(14),
    taal: str = Form("nl"),
    notities: str = Form(""),
):
    with db.session_scope() as session:
        invoice = session.get(Invoice, factuur_id)
        try:
            svc.guard_editable(invoice)
        except svc.InvoiceLocked as exc:
            return RedirectResponse(f"/facturen/{factuur_id}?fout={exc}", status_code=303)
        invoice.betaaltermijn_dagen = betaaltermijn_dagen
        svc.set_datum(session, invoice, dt.date.fromisoformat(datum))
        invoice.uw_kenmerk = uw_kenmerk
        invoice.prestatie_omschrijving = prestatie_omschrijving
        invoice.taal = taal
        invoice.notities = notities
    return RedirectResponse(f"/facturen/{factuur_id}", status_code=303)


@router.post("/{factuur_id}/regel")
def regel_toevoegen(
    factuur_id: int,
    aantal: str = Form("1"),
    code: str = Form(""),
    omschrijving: str = Form(""),
    stuksprijs: str = Form("0"),
    btw_behandeling: str = Form("hoog_21"),
):
    with db.session_scope() as session:
        invoice = session.get(Invoice, factuur_id)
        try:
            svc.add_line(
                session,
                invoice,
                aantal=aantal,
                code=code,
                omschrijving=omschrijving,
                stuksprijs=stuksprijs,
                btw_behandeling=btw_behandeling,
            )
        except svc.InvoiceLocked as exc:
            return RedirectResponse(f"/facturen/{factuur_id}?fout={exc}", status_code=303)
    return RedirectResponse(f"/facturen/{factuur_id}", status_code=303)


@router.post("/{factuur_id}/regel/{regel_id}/verwijderen")
def regel_verwijderen(factuur_id: int, regel_id: int):
    with db.session_scope() as session:
        invoice = session.get(Invoice, factuur_id)
        try:
            svc.guard_editable(invoice)
        except svc.InvoiceLocked as exc:
            return RedirectResponse(f"/facturen/{factuur_id}?fout={exc}", status_code=303)
        regel = session.get(InvoiceLine, regel_id)
        if regel and regel.invoice_id == factuur_id:
            session.delete(regel)
    return RedirectResponse(f"/facturen/{factuur_id}", status_code=303)


@router.post("/{factuur_id}/definitief")
def definitief_maken(factuur_id: int):
    with db.session_scope() as session:
        invoice = session.get(Invoice, factuur_id)
        try:
            svc.finalise(session, invoice)
        except (ValueError, svc.InvoiceLocked) as exc:
            return RedirectResponse(f"/facturen/{factuur_id}?fout={exc}", status_code=303)
        settings = Settings.get_or_create(session)
        pad = invoice_pdf.render_and_store(invoice, settings, db.INVOICE_PDF_DIR)
        invoice.pdf_pad = str(pad)
    return RedirectResponse(f"/facturen/{factuur_id}", status_code=303)


@router.get("/{factuur_id}/pdf")
def pdf(factuur_id: int):
    with db.session_scope() as session:
        invoice = session.get(Invoice, factuur_id)
        settings = Settings.get_or_create(session)
        if invoice.is_final and invoice.pdf_pad:
            pad = invoice.pdf_pad
        elif invoice.is_final:
            pad = str(invoice_pdf.render_and_store(invoice, settings, db.INVOICE_PDF_DIR))
            invoice.pdf_pad = pad
        else:
            pad = str(invoice_pdf.render_preview(invoice, settings, db.INVOICE_PDF_DIR))
        bestandsnaam = f"{invoice.nummer or f'concept-{invoice.id}'}.pdf"
        return FileResponse(pad, media_type="application/pdf", filename=bestandsnaam)


@router.post("/{factuur_id}/dupliceren")
def dupliceren(factuur_id: int):
    with db.session_scope() as session:
        invoice = session.get(Invoice, factuur_id)
        kopie = svc.duplicate(session, invoice)
        return RedirectResponse(f"/facturen/{kopie.id}", status_code=303)


@router.post("/{factuur_id}/crediteren")
def crediteren(factuur_id: int, reden: str = Form("")):
    with db.session_scope() as session:
        invoice = session.get(Invoice, factuur_id)
        try:
            credit = svc.create_credit_note(session, invoice, reden=reden)
        except ValueError as exc:
            return RedirectResponse(f"/facturen/{factuur_id}?fout={exc}", status_code=303)
        return RedirectResponse(f"/facturen/{credit.id}", status_code=303)


@router.post("/{factuur_id}/betaling")
def betaling(factuur_id: int, bedrag: str = Form(...), datum: str = Form(...)):
    with db.session_scope() as session:
        invoice = session.get(Invoice, factuur_id)
        svc.register_payment(
            session, invoice, money.euros_to_cents(bedrag), dt.date.fromisoformat(datum)
        )
    return RedirectResponse(f"/facturen/{factuur_id}", status_code=303)


@router.post("/{factuur_id}/verwijderen")
def verwijderen(factuur_id: int):
    """Only a draft can be removed, and even then it is a soft delete."""
    with db.session_scope() as session:
        invoice = session.get(Invoice, factuur_id)
        if invoice.is_final:
            return RedirectResponse(
                f"/facturen/{factuur_id}?fout=Een definitieve factuur kan niet verwijderd "
                "worden; maak een creditfactuur.",
                status_code=303,
            )
        invoice.deleted_at = dt.datetime.now(dt.timezone.utc)
        svc.audit(session, "invoice", invoice.id, "concept verwijderd")
    return RedirectResponse("/facturen", status_code=303)


@router.post("/uit-uren")
def uit_uren(
    client_id: int = Form(...),
    van: str = Form(...),
    tot: str = Form(...),
    uw_kenmerk: str = Form(""),
):
    with db.session_scope() as session:
        klant = session.get(Client, client_id)
        try:
            invoice = svc.draft_from_hours(
                session,
                klant,
                dt.date.fromisoformat(van),
                dt.date.fromisoformat(tot),
                uw_kenmerk=uw_kenmerk,
            )
        except ValueError as exc:
            return RedirectResponse(f"/uren?fout={exc}", status_code=303)
        return RedirectResponse(f"/facturen/{invoice.id}", status_code=303)
