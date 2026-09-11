from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from boekhouding import db, money
from boekhouding.models import Client, Project, TimeEntry
from boekhouding.taxyears import tax_year

router = APIRouter(prefix="/uren", tags=["uren"])


def _templates():
    from boekhouding.web.main import templates

    return templates


@router.get("", response_class=HTMLResponse)
def lijst(request: Request, jaar: str = "", fout: str = ""):
    jaar_i = int(jaar) if jaar else dt.date.today().year
    with db.session_scope() as session:
        entries = list(
            session.scalars(
                select(TimeEntry)
                .where(
                    TimeEntry.deleted_at.is_(None),
                    TimeEntry.datum >= dt.date(jaar_i, 1, 1),
                    TimeEntry.datum <= dt.date(jaar_i, 12, 31),
                )
                .order_by(TimeEntry.datum.desc(), TimeEntry.id.desc())
            )
        )
        projecten = list(
            session.scalars(
                select(Project).where(
                    Project.deleted_at.is_(None), Project.actief.is_(True)
                )
            )
        )
        klanten = list(
            session.scalars(
                select(Client).where(Client.deleted_at.is_(None)).order_by(Client.naam)
            )
        )

        totaal_milli = sum(e.uren_milli for e in entries)
        declarabel_milli = sum(e.uren_milli for e in entries if e.declarabel)
        ongefactureerd_milli = sum(
            e.uren_milli for e in entries if e.declarabel and e.invoice_id is None
        )

        per_maand: dict[int, int] = {}
        for entry in entries:
            per_maand[entry.datum.month] = per_maand.get(entry.datum.month, 0) + entry.uren_milli

        per_project: dict[str, dict] = {}
        for entry in entries:
            sleutel = entry.project.code if entry.project else "(geen project)"
            regel = per_project.setdefault(sleutel, {"uren_milli": 0, "omzet_cents": 0})
            regel["uren_milli"] += entry.uren_milli
            if entry.project and entry.declarabel:
                regel["omzet_cents"] += money.line_total_cents(
                    entry.uren_milli, entry.project.uurtarief_cents
                )

        return _templates().TemplateResponse(
            request,
            "uren.html",
            {
                "titel": f"Urenregistratie {jaar_i}",
                "entries": entries,
                "projecten": projecten,
                "klanten": klanten,
                "jaar": jaar_i,
                "vandaag": dt.date.today(),
                "totaal_milli": totaal_milli,
                "declarabel_milli": declarabel_milli,
                "ongefactureerd_milli": ongefactureerd_milli,
                "urencriterium": tax_year(jaar_i).urencriterium,
                "per_maand": per_maand,
                "per_project": per_project,
                "fout": fout,
            },
        )


@router.post("/nieuw")
def toevoegen(
    datum: str = Form(...),
    project_id: str = Form(""),
    uren: str = Form("0"),
    omschrijving: str = Form(""),
    declarabel: str = Form(""),
):
    with db.session_scope() as session:
        session.add(
            TimeEntry(
                datum=dt.date.fromisoformat(datum),
                project_id=int(project_id) if project_id else None,
                uren_milli=money.quantity_to_milli(uren),
                omschrijving=omschrijving,
                declarabel=bool(declarabel),
            )
        )
    return RedirectResponse(f"/uren?jaar={dt.date.fromisoformat(datum).year}", status_code=303)


@router.post("/{entry_id}/verwijderen")
def verwijderen(entry_id: int):
    with db.session_scope() as session:
        entry = session.get(TimeEntry, entry_id)
        if entry.invoice_id is not None:
            return RedirectResponse(
                "/uren?fout=Deze uren zijn al gefactureerd en kunnen niet verwijderd worden.",
                status_code=303,
            )
        entry.deleted_at = dt.datetime.now(dt.UTC)
    return RedirectResponse("/uren", status_code=303)
