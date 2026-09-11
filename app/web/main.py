"""FastAPI application: server-rendered pages, no JavaScript framework.

Everything is a form post followed by a redirect, which keeps the browser's back button
honest and means the application works with JavaScript disabled.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app import db, money
from app.models import Expense, Invoice, InvoiceStatus, Settings, TimeEntry
from app.services import expenses as expense_svc
from app.services import income_tax
from app.services import vat_return as btw_svc
from app.taxyears import is_estimate, tax_year

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

templates.env.filters["euro"] = money.format_euro
templates.env.filters["euro_kaal"] = lambda c: money.format_euro(c, symbol=False)
templates.env.filters["aantal"] = money.format_quantity
templates.env.filters["datum"] = lambda d: d.strftime("%d-%m-%Y") if d else ""
templates.env.filters["permille"] = lambda p: (
    f"{p // 10}%" if p % 10 == 0 else f"{p / 10:.1f}".replace(".", ",") + "%"
)


def create_app() -> FastAPI:
    db.init_db()
    with db.session_scope() as session:
        expense_svc.ensure_categories(session)

    application = FastAPI(title="Boekhouding", docs_url=None, redoc_url=None)
    application.mount(
        "/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static"
    )

    from app.web.routes import clients, expenses, invoices, timesheet, settings as settings_routes
    from app.web.routes import vat

    application.include_router(clients.router)
    application.include_router(invoices.router)
    application.include_router(expenses.router)
    application.include_router(vat.router)
    application.include_router(timesheet.router)
    application.include_router(settings_routes.router)

    @application.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        vandaag = dt.date.today()
        jaar, kwartaal = btw_svc.quarter_of(vandaag)
        with db.session_scope() as session:
            instellingen = Settings.get_or_create(session)

            # Verse installatie: stuur direct naar Instellingen. Zonder eigen
            # bedrijfsgegevens is elke factuur die hier uit komt ongeldig.
            if not instellingen.is_ingericht:
                return RedirectResponse("/instellingen?eerste_start=1", status_code=303)

            aangifte = btw_svc.compute(session, jaar, kwartaal)

            openstaand = list(
                session.scalars(
                    select(Invoice)
                    .where(
                        Invoice.deleted_at.is_(None),
                        Invoice.status.in_(
                            [
                                InvoiceStatus.DEFINITIEF,
                                InvoiceStatus.VERZONDEN,
                            ]
                        ),
                    )
                    .order_by(Invoice.vervaldatum)
                )
            )
            openstaand = [f for f in openstaand if f.openstaand_cents > 0]
            te_laat = [f for f in openstaand if f.is_overdue]

            jaar_start = dt.date(jaar, 1, 1)
            omzet_jaar = sum(
                f.subtotaal_cents
                for f in session.scalars(
                    select(Invoice).where(
                        Invoice.datum >= jaar_start,
                        Invoice.datum <= vandaag,
                        Invoice.deleted_at.is_(None),
                        Invoice.status.in_(btw_svc.FINAL_STATUSES),
                    )
                )
            )
            kosten_jaar = sum(
                e.zakelijke_kosten_cents
                for e in session.scalars(
                    select(Expense).where(
                        Expense.datum >= jaar_start,
                        Expense.datum <= vandaag,
                        Expense.deleted_at.is_(None),
                    )
                )
            )
            uren_jaar = sum(
                t.uren_milli
                for t in session.scalars(
                    select(TimeEntry).where(
                        TimeEntry.datum >= jaar_start,
                        TimeEntry.datum <= vandaag,
                        TimeEntry.deleted_at.is_(None),
                    )
                )
            )

            winst = omzet_jaar - kosten_jaar
            parameters = tax_year(jaar)

            # The reservation is based on the *expected annual* profit, because both the
            # brackets and the heffingskortingen are annual. Reserving on year-to-date
            # profit alone would understate the burden early in the year.
            dagen_verstreken = (vandaag - jaar_start).days + 1
            verwachte_winst = income_tax.annualise(winst, dagen_verstreken)
            urencriterium_gehaald = uren_jaar >= parameters.urencriterium * 1000
            schatting = income_tax.estimate(
                verwachte_winst, jaar, urencriterium_gehaald=urencriterium_gehaald
            )
            # Set aside the share of the expected annual bill that this year's profit has
            # already earned, so the number grows with the work rather than jumping.
            reservering = (
                money.round_half_up(
                    Decimal(schatting.totaal_cents) * Decimal(winst) / Decimal(verwachte_winst)
                )
                if verwachte_winst > 0
                else 0
            )
            maandomzet = _maandomzet(session, jaar)

            return templates.TemplateResponse(
                request,
                "dashboard.html",
                {
                    "titel": "Overzicht",
                    "vandaag": vandaag,
                    "jaar": jaar,
                    "kwartaal": kwartaal,
                    "aangifte": aangifte,
                    "openstaand": openstaand,
                    "openstaand_totaal": sum(f.openstaand_cents for f in openstaand),
                    "te_laat": te_laat,
                    "omzet_jaar": omzet_jaar,
                    "kosten_jaar": kosten_jaar,
                    "winst_jaar": winst,
                    "reservering_cents": reservering,
                    "schatting": schatting,
                    "verwachte_winst_cents": verwachte_winst,
                    "cijfers_onzeker": is_estimate(jaar),
                    "uren_jaar_milli": uren_jaar,
                    "urencriterium": parameters.urencriterium,
                    "urencriterium_gehaald": urencriterium_gehaald,
                    "maandomzet": maandomzet,
                },
            )

    return application


def _maandomzet(session, jaar: int) -> list[tuple[str, int]]:
    maanden = [
        "jan", "feb", "mrt", "apr", "mei", "jun",
        "jul", "aug", "sep", "okt", "nov", "dec",
    ]
    totalen = [0] * 12
    for invoice in session.scalars(
        select(Invoice).where(
            Invoice.datum >= dt.date(jaar, 1, 1),
            Invoice.datum <= dt.date(jaar, 12, 31),
            Invoice.deleted_at.is_(None),
            Invoice.status.in_(btw_svc.FINAL_STATUSES),
        )
    ):
        totalen[invoice.datum.month - 1] += invoice.subtotaal_cents
    return list(zip(maanden, totalen))


app = create_app()
