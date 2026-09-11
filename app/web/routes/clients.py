from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app import db
from app.models import Client, Project

router = APIRouter(prefix="/klanten", tags=["klanten"])


def _templates():
    from app.web.main import templates

    return templates


@router.get("", response_class=HTMLResponse)
def lijst(request: Request):
    with db.session_scope() as session:
        klanten = list(
            session.scalars(
                select(Client).where(Client.deleted_at.is_(None)).order_by(Client.naam)
            )
        )
        return _templates().TemplateResponse(
            request, "klanten.html", {"titel": "Klanten", "klanten": klanten}
        )


@router.get("/nieuw", response_class=HTMLResponse)
def nieuw(request: Request):
    return _templates().TemplateResponse(
        request, "klant_form.html", {"titel": "Nieuwe klant", "klant": None}
    )


@router.get("/{klant_id}", response_class=HTMLResponse)
def bewerken(request: Request, klant_id: int):
    with db.session_scope() as session:
        klant = session.get(Client, klant_id)
        projecten = list(
            session.scalars(
                select(Project).where(
                    Project.client_id == klant_id, Project.deleted_at.is_(None)
                )
            )
        )
        return _templates().TemplateResponse(
            request,
            "klant_form.html",
            {"titel": klant.naam, "klant": klant, "projecten": projecten},
        )


@router.post("/opslaan")
def opslaan(
    klant_id: str = Form(""),
    naam: str = Form(...),
    klantnummer: str = Form(""),
    contactpersoon: str = Form(""),
    email: str = Form(""),
    adres: str = Form(""),
    postcode: str = Form(""),
    plaats: str = Form(""),
    land: str = Form("Nederland"),
    landcode: str = Form("NL"),
    btw_nummer: str = Form(""),
    betaaltermijn_dagen: str = Form(""),
    standaard_btw: str = Form("hoog_21"),
    taal: str = Form("nl"),
    uurtarief: str = Form(""),
    notities: str = Form(""),
):
    from app import money

    with db.session_scope() as session:
        klant = session.get(Client, int(klant_id)) if klant_id else Client()
        klant.naam = naam
        klant.klantnummer = klantnummer
        klant.contactpersoon = contactpersoon
        klant.email = email
        klant.adres = adres
        klant.postcode = postcode
        klant.plaats = plaats
        klant.land = land
        klant.landcode = landcode.upper()
        klant.btw_nummer = btw_nummer
        klant.betaaltermijn_dagen = int(betaaltermijn_dagen) if betaaltermijn_dagen else None
        klant.standaard_btw = standaard_btw
        klant.taal = taal
        klant.uurtarief_cents = money.euros_to_cents(uurtarief) if uurtarief else None
        klant.notities = notities
        if not klant.id:
            session.add(klant)
        session.flush()
        return RedirectResponse(f"/klanten/{klant.id}", status_code=303)


@router.post("/{klant_id}/verwijderen")
def verwijderen(klant_id: int):
    """Soft delete only: a client referenced by an invoice stays in the books forever."""
    with db.session_scope() as session:
        klant = session.get(Client, klant_id)
        klant.deleted_at = dt.datetime.now(dt.timezone.utc)
    return RedirectResponse("/klanten", status_code=303)


@router.post("/{klant_id}/project")
def project_opslaan(
    klant_id: int,
    project_id: str = Form(""),
    code: str = Form(...),
    omschrijving: str = Form(""),
    uurtarief: str = Form("0"),
    btw_behandeling: str = Form("hoog_21"),
):
    from app import money

    with db.session_scope() as session:
        project = session.get(Project, int(project_id)) if project_id else Project(
            client_id=klant_id
        )
        project.code = code
        project.omschrijving = omschrijving
        project.uurtarief_cents = money.euros_to_cents(uurtarief or "0")
        project.btw_behandeling = btw_behandeling
        if not project.id:
            session.add(project)
    return RedirectResponse(f"/klanten/{klant_id}", status_code=303)
