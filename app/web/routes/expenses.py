from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import select

from app import db
from app.models import Expense, ExpenseCategory, InboxDocument
from app.services import expenses as svc
from app.vat import PURCHASE_SPECS

router = APIRouter(prefix="/kosten", tags=["kosten"])


def _templates():
    from app.web.main import templates

    return templates


def _context(session):
    return {
        "categorieen": list(
            session.scalars(
                select(ExpenseCategory)
                .where(ExpenseCategory.deleted_at.is_(None))
                .order_by(ExpenseCategory.naam)
            )
        ),
        "btw_opties": [(t.value, spec.label) for t, spec in PURCHASE_SPECS.items()],
    }


@router.get("", response_class=HTMLResponse)
def lijst(request: Request, jaar: str = "", kwartaal: str = ""):
    with db.session_scope() as session:
        query = select(Expense).where(Expense.deleted_at.is_(None))
        if jaar:
            from app.services.vat_return import quarter_range

            if kwartaal:
                van, tot = quarter_range(int(jaar), int(kwartaal))
            else:
                van, tot = dt.date(int(jaar), 1, 1), dt.date(int(jaar), 12, 31)
            query = query.where(Expense.datum >= van, Expense.datum <= tot)

        kosten = list(session.scalars(query.order_by(Expense.datum.desc(), Expense.id.desc())))
        inbox = list(
            session.scalars(
                select(InboxDocument).where(
                    InboxDocument.verwerkt.is_(False), InboxDocument.deleted_at.is_(None)
                )
            )
        )
        return _templates().TemplateResponse(
            request,
            "kosten.html",
            {
                "titel": "Kosten",
                "kosten": kosten,
                "inbox": inbox,
                "jaar": jaar,
                "kwartaal": kwartaal,
                "totaal_excl": sum(k.bedrag_excl_cents for k in kosten),
                "totaal_btw": sum(k.aftrekbare_btw_cents for k in kosten),
                "vandaag": dt.date.today(),
                **_context(session),
            },
        )


@router.post("/nieuw")
async def aanmaken(
    datum: str = Form(...),
    leverancier: str = Form(...),
    omschrijving: str = Form(""),
    factuurnummer: str = Form(""),
    bedrag_excl: str = Form("0"),
    btw_behandeling: str = Form("binnenland_21"),
    btw: str = Form(""),
    category_id: str = Form(""),
    zakelijk_procent: str = Form("100"),
    document: UploadFile | None = File(None),
    inbox_id: str = Form(""),
):
    from app.money import parse_dutch_decimal

    datum_obj = dt.date.fromisoformat(datum)
    document_pad = None
    if document is not None and document.filename:
        inhoud = await document.read()
        document_pad = svc.store_document(document.filename, inhoud, datum_obj)

    with db.session_scope() as session:
        if inbox_id and not document_pad:
            inbox_doc = session.get(InboxDocument, int(inbox_id))
            if inbox_doc:
                document_pad = inbox_doc.pad

        expense = svc.create(
            session,
            datum=datum_obj,
            leverancier=leverancier,
            omschrijving=omschrijving,
            factuurnummer=factuurnummer,
            bedrag_excl=bedrag_excl,
            btw_behandeling=btw_behandeling,
            btw=btw or None,
            category_id=int(category_id) if category_id else None,
            zakelijk_permille=int(parse_dutch_decimal(zakelijk_procent or "100") * 10),
            document_pad=document_pad,
        )

        if inbox_id:
            inbox_doc = session.get(InboxDocument, int(inbox_id))
            if inbox_doc:
                inbox_doc.verwerkt = True
                inbox_doc.expense_id = expense.id

        if svc.should_capitalise(expense.bedrag_excl_cents, datum_obj.year):
            return RedirectResponse(f"/kosten/{expense.id}/activeren", status_code=303)
    return RedirectResponse("/kosten", status_code=303)


@router.get("/{kosten_id}/activeren", response_class=HTMLResponse)
def activeren_form(request: Request, kosten_id: int):
    with db.session_scope() as session:
        expense = session.get(Expense, kosten_id)
        from app.taxyears import tax_year

        return _templates().TemplateResponse(
            request,
            "kosten_activeren.html",
            {
                "titel": "Investering activeren",
                "kosten": expense,
                "grens_cents": tax_year(expense.datum.year).investeringsgrens_cents,
            },
        )


@router.post("/{kosten_id}/activeren")
def activeren(
    kosten_id: int,
    termijn: int = Form(5),
    restwaarde: str = Form("0"),
    activeren: str = Form("ja"),
):
    with db.session_scope() as session:
        expense = session.get(Expense, kosten_id)
        if activeren == "ja":
            svc.capitalise(session, expense, afschrijftermijn_jaren=termijn, restwaarde=restwaarde)
    return RedirectResponse("/kosten", status_code=303)


@router.post("/{kosten_id}/verwijderen")
def verwijderen(kosten_id: int):
    with db.session_scope() as session:
        expense = session.get(Expense, kosten_id)
        expense.deleted_at = dt.datetime.now(dt.timezone.utc)
    return RedirectResponse("/kosten", status_code=303)


@router.get("/{kosten_id}/bijlage")
def bijlage(kosten_id: int):
    with db.session_scope() as session:
        expense = session.get(Expense, kosten_id)
        if not expense.document_pad:
            return RedirectResponse("/kosten", status_code=303)
        return FileResponse(expense.document_pad)


@router.post("/inbox/scannen")
def inbox_scannen():
    with db.session_scope() as session:
        svc.scan_inbox(session, db.INBOX_DIR)
    return RedirectResponse("/kosten", status_code=303)


@router.get("/inbox/{document_id}")
def inbox_bekijken(document_id: int):
    with db.session_scope() as session:
        document = session.get(InboxDocument, document_id)
        return FileResponse(document.pad)
