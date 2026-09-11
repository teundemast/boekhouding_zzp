from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from app import db, money
from app.services import vat_return as svc
from app.vat import Rubriek

router = APIRouter(prefix="/btw", tags=["btw"])


def _templates():
    from app.web.main import templates

    return templates


@router.get("", response_class=HTMLResponse)
def aangifte(request: Request, jaar: str = "", kwartaal: str = "", fout: str = ""):
    vandaag = dt.date.today()
    huidig_jaar, huidig_kwartaal = svc.quarter_of(vandaag)
    # Default to the quarter just ended, which is the one being filed.
    if not jaar or not kwartaal:
        k, j = huidig_kwartaal - 1, huidig_jaar
        if k == 0:
            k, j = 4, j - 1
        jaar, kwartaal = str(j), str(k)

    jaar_i, kwartaal_i = int(jaar), int(kwartaal)
    with db.session_scope() as session:
        aangifte = svc.compute(session, jaar_i, kwartaal_i)
        correctie = svc.corrections(session, jaar_i, kwartaal_i)
        historie = svc.history(session, jaar_i, kwartaal_i, aantal=4)
        return _templates().TemplateResponse(
            request,
            "btw.html",
            {
                "titel": f"Btw-aangifte {kwartaal_i}e kwartaal {jaar_i}",
                "aangifte": aangifte,
                "correctie": correctie,
                "historie": historie,
                "Rubriek": Rubriek,
                "jaar": jaar_i,
                "kwartaal": kwartaal_i,
                "fout": fout,
                "volgorde": [
                    Rubriek.R1A, Rubriek.R1B, Rubriek.R1C, Rubriek.R1D, Rubriek.R1E,
                    Rubriek.R2A,
                    Rubriek.R3A, Rubriek.R3B, Rubriek.R3C,
                    Rubriek.R4A, Rubriek.R4B,
                ],
            },
        )


@router.get("/detail/{rubriek}", response_class=HTMLResponse)
def detail(request: Request, rubriek: str, jaar: int, kwartaal: int):
    with db.session_scope() as session:
        aangifte = svc.compute(session, jaar, kwartaal)
        regel = aangifte.rubrieken[Rubriek(rubriek)]
        return _templates().TemplateResponse(
            request,
            "btw_detail.html",
            {
                "titel": f"Rubriek {rubriek} - {kwartaal}e kwartaal {jaar}",
                "regel": regel,
                "aangifte": aangifte,
            },
        )


@router.post("/indienen")
def indienen(jaar: int = Form(...), kwartaal: int = Form(...), notities: str = Form("")):
    with db.session_scope() as session:
        try:
            svc.mark_filed(session, jaar, kwartaal, notities=notities)
        except ValueError as exc:
            return RedirectResponse(
                f"/btw?jaar={jaar}&kwartaal={kwartaal}&fout={exc}", status_code=303
            )
    return RedirectResponse(f"/btw?jaar={jaar}&kwartaal={kwartaal}", status_code=303)


@router.get("/icp", response_class=HTMLResponse)
def icp(request: Request, jaar: int, kwartaal: int):
    with db.session_scope() as session:
        aangifte = svc.compute(session, jaar, kwartaal)
        return _templates().TemplateResponse(
            request,
            "icp.html",
            {
                "titel": f"ICP-opgaaf {kwartaal}e kwartaal {jaar}",
                "aangifte": aangifte,
            },
        )


@router.get("/export.csv", response_class=PlainTextResponse)
def export_csv(jaar: int, kwartaal: int):
    """The underlying detail, for the archive and for anyone who asks."""
    import csv
    import io

    with db.session_scope() as session:
        aangifte = svc.compute(session, jaar, kwartaal)
        buffer = io.StringIO()
        schrijver = csv.writer(buffer, delimiter=";")
        schrijver.writerow(
            ["rubriek", "omschrijving", "soort", "nummer", "datum", "toelichting",
             "omzet", "btw"]
        )
        for rubriek, regel in aangifte.rubrieken.items():
            for post in regel.posten:
                schrijver.writerow(
                    [
                        rubriek.value,
                        regel.label,
                        post["soort"],
                        post["nummer"] or "",
                        post["datum"].strftime("%d-%m-%Y"),
                        post["omschrijving"],
                        money.format_euro(post["omzet_cents"], symbol=False),
                        money.format_euro(post["btw_cents"], symbol=False),
                    ]
                )
        return PlainTextResponse(
            buffer.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="btw-{jaar}-Q{kwartaal}.csv"'
                )
            },
        )
