from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from boekhouding import db
from boekhouding.models import Settings
from boekhouding.taxyears import TAX_YEARS, is_estimate

router = APIRouter(prefix="/instellingen", tags=["instellingen"])


def _templates():
    from boekhouding.web.main import templates

    return templates


@router.get("", response_class=HTMLResponse)
def tonen(request: Request, fout: str = "", eerste_start: str = ""):
    from boekhouding.services.invoices import peek_number

    with db.session_scope() as session:
        instellingen = Settings.get_or_create(session)
        jaar = dt.date.today().year
        return _templates().TemplateResponse(
            request,
            "instellingen.html",
            {
                "titel": "Instellingen" if not eerste_start else "Welkom - even instellen",
                "instellingen": instellingen,
                "eerste_start": bool(eerste_start),
                "ontbrekend": instellingen.ontbrekende_velden,
                "fout": fout,
                "volgend_nummer": peek_number(session, "factuur", dt.date.today()),
                "belastingjaren": sorted(TAX_YEARS.values(), key=lambda t: -t.year),
                "huidig_jaar_is_schatting": is_estimate(jaar),
                "data_map": str(db.DATA_DIR),
            },
        )


@router.post("")
def opslaan(
    bedrijfsnaam: str = Form(...),
    adres: str = Form(""),
    postcode: str = Form(""),
    plaats: str = Form(""),
    telefoon: str = Form(""),
    email: str = Form(""),
    btw_nummer: str = Form(""),
    iban: str = Form(""),
    kvk_nummer: str = Form(""),
    factuur_prefix: str = Form("F"),
    factuur_cijfers: int = Form(5),
    nummering_per_jaar: str = Form(""),
    betaaltermijn_dagen: int = Form(14),
    factuur_voettekst: str = Form(""),
    accentkleur: str = Form("#000000"),
    kor_actief: str = Form(""),
    kor_startdatum: str = Form(""),
    reservering_procent: int = Form(35),
    laatste_factuurnummer: str = Form(""),
):
    from boekhouding.services.invoices import set_counter

    with db.session_scope() as session:
        instellingen = Settings.get_or_create(session)
        if laatste_factuurnummer.strip():
            jaar = dt.date.today().year if instellingen.nummering_per_jaar else 0
            try:
                set_counter(session, "factuur", jaar, int(laatste_factuurnummer))
            except ValueError as exc:
                return RedirectResponse(f"/instellingen?fout={exc}", status_code=303)
        instellingen.bedrijfsnaam = bedrijfsnaam
        instellingen.adres = adres
        instellingen.postcode = postcode
        instellingen.plaats = plaats
        instellingen.telefoon = telefoon
        instellingen.email = email
        instellingen.btw_nummer = btw_nummer
        instellingen.iban = iban
        instellingen.kvk_nummer = kvk_nummer
        instellingen.factuur_prefix = factuur_prefix
        instellingen.factuur_cijfers = factuur_cijfers
        instellingen.nummering_per_jaar = bool(nummering_per_jaar)
        instellingen.betaaltermijn_dagen = betaaltermijn_dagen
        if factuur_voettekst:
            instellingen.factuur_voettekst = factuur_voettekst
        instellingen.accentkleur = accentkleur
        instellingen.kor_actief = bool(kor_actief)
        instellingen.kor_startdatum = (
            dt.date.fromisoformat(kor_startdatum) if kor_startdatum else None
        )
        instellingen.reservering_permille = reservering_procent * 10
    return RedirectResponse("/instellingen", status_code=303)
