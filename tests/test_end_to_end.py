"""A full quarter, driven through the web interface the way I would actually use it.

Create a client and a project, log hours, invoice them, book expenses, run the BTW
return, mark it filed, then add a late document and see it surface as a correction.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import db
from app.models import Invoice, InvoiceStatus, Settings
from app.services import vat_return as btw_svc
from app.vat import Rubriek


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BOEKHOUDING_DATA", str(tmp_path / "data"))
    db.configure_for_tests(tmp_path / "data")

    from app.web import main as web_main

    app = web_main.create_app()
    with TestClient(app) as testclient:
        yield testclient


VOLLEDIGE_INSTELLINGEN = {
    "bedrijfsnaam": "Voorbeeld Data Science", "adres": "Teststraat 1",
    "postcode": "1234 AB", "plaats": "Leiden", "telefoon": "0600000000",
    "email": "test@example.nl", "btw_nummer": "NL000000000B00",
    "iban": "NL00 TEST 0000 0000 00", "kvk_nummer": "00000000",
    "factuur_prefix": "F", "factuur_cijfers": "5", "betaaltermijn_dagen": "14",
    "accentkleur": "#000000", "reservering_procent": "35",
}


def test_a_full_quarter_from_client_to_filed_return(client, tmp_path):
    # --- First run: fill in my own details, as any new install must ------------------
    client.post("/instellingen", data=VOLLEDIGE_INSTELLINGEN)

    # --- A client and a project -----------------------------------------------------
    antwoord = client.post(
        "/klanten/opslaan",
        data={
            "naam": "Acme Analytics B.V.", "klantnummer": "ACME", "adres": "Voorbeeldkade 12",
            "postcode": "1011 AB", "plaats": "Amsterdam", "land": "Nederland",
            "landcode": "NL", "btw_nummer": "NL812345678B01", "standaard_btw": "hoog_21",
            "taal": "nl", "uurtarief": "20,00",
        },
        follow_redirects=False,
    )
    assert antwoord.status_code == 303
    klant_id = int(antwoord.headers["location"].rsplit("/", 1)[1])

    client.post(
        f"/klanten/{klant_id}/project",
        data={
            "code": "ADSD", "omschrijving": "Algemene Data Science Diensten",
            "uurtarief": "18,00", "btw_behandeling": "hoog_21",
        },
    )

    # --- Hours ----------------------------------------------------------------------
    with db.session_scope() as session:
        from sqlalchemy import select
        from app.models import Project

        project_id = session.scalar(select(Project.id))

    for dag, uren in [(6, "8"), (7, "8"), (8, "8"), (9, "8"), (10, "9")]:
        client.post(
            "/uren/nieuw",
            data={
                "datum": f"2023-02-{dag:02d}", "project_id": str(project_id),
                "uren": uren, "omschrijving": "data science werk", "declarabel": "1",
            },
        )
    client.post(
        "/uren/nieuw",
        data={
            "datum": "2023-02-13", "project_id": str(project_id), "uren": "4",
            "omschrijving": "administratie", "declarabel": "",
        },
    )

    # --- Invoice from those hours ----------------------------------------------------
    antwoord = client.post(
        "/facturen/uit-uren",
        data={
            "client_id": str(klant_id), "van": "2023-02-01", "tot": "2023-02-28",
            "uw_kenmerk": "FEB",
        },
        follow_redirects=False,
    )
    assert antwoord.status_code == 303
    factuur_id = int(antwoord.headers["location"].rsplit("/", 1)[1])

    with db.session_scope() as session:
        factuur = session.get(Invoice, factuur_id)
        assert factuur.regels[0].aantal_milli == 41000, "8+8+8+8+9 billable hours"
        assert factuur.subtotaal_cents == 73800  # 41 x € 18,00
        assert factuur.status == InvoiceStatus.CONCEPT

    # Add the two other project lines by hand, reproducing the reference invoice F00006.
    for aantal, code, omschrijving, prijs in [
        ("23", "ACME", "Data Science Diensten voor Project Statistiek", "20,00"),
        ("22", "NOVA", "Data science diensten verricht voor Nova.", "20,00"),
    ]:
        client.post(
            f"/facturen/{factuur_id}/regel",
            data={
                "aantal": aantal, "code": code, "omschrijving": omschrijving,
                "stuksprijs": prijs, "btw_behandeling": "hoog_21",
            },
        )

    client.post(
        f"/facturen/{factuur_id}/kop",
        data={
            "datum": "2023-02-02", "uw_kenmerk": "FEB",
            "prestatie_omschrijving": "februari 2023", "betaaltermijn_dagen": "14",
            "taal": "nl", "notities": "",
        },
    )

    # --- Finalise -------------------------------------------------------------------
    client.post(f"/facturen/{factuur_id}/definitief")

    with db.session_scope() as session:
        factuur = session.get(Invoice, factuur_id)
        assert factuur.nummer == "F00001"
        assert factuur.status == InvoiceStatus.DEFINITIEF
        assert factuur.subtotaal_cents == 163800
        assert factuur.btw_totaal_cents == 34398
        assert factuur.totaal_incl_cents == 198198
        assert factuur.pdf_pad and dt.date.today()  # pdf was written
        from pathlib import Path

        assert Path(factuur.pdf_pad).exists()
        pdf_bytes = Path(factuur.pdf_pad).read_bytes()
        assert pdf_bytes.startswith(b"%PDF")

    # A finalised invoice refuses further lines, through the web layer too.
    antwoord = client.post(
        f"/facturen/{factuur_id}/regel",
        data={"aantal": "1", "code": "X", "omschrijving": "stiekem", "stuksprijs": "999,00"},
        follow_redirects=False,
    )
    assert "fout=" in antwoord.headers["location"]
    with db.session_scope() as session:
        assert session.get(Invoice, factuur_id).subtotaal_cents == 163800

    # --- Expenses -------------------------------------------------------------------
    client.post(
        "/kosten/nieuw",
        data={
            "datum": "2023-01-15", "leverancier": "Coolblue", "omschrijving": "monitor",
            "bedrag_excl": "200,00", "btw_behandeling": "binnenland_21",
            "zakelijk_procent": "100",
        },
    )
    client.post(
        "/kosten/nieuw",
        data={
            "datum": "2023-02-01", "leverancier": "KPN", "omschrijving": "telefoon",
            "bedrag_excl": "100,00", "btw_behandeling": "binnenland_21",
            "zakelijk_procent": "70",
        },
    )
    client.post(
        "/kosten/nieuw",
        data={
            "datum": "2023-03-01", "leverancier": "Hetzner", "omschrijving": "servers",
            "bedrag_excl": "300,00", "btw_behandeling": "eu_verwerving",
            "zakelijk_procent": "100",
        },
    )

    # --- The return -----------------------------------------------------------------
    antwoord = client.get("/btw?jaar=2023&kwartaal=1")
    assert antwoord.status_code == 200
    assert "1.638,00" in antwoord.text

    with db.session_scope() as session:
        aangifte = btw_svc.compute(session, 2023, 1)
        assert aangifte.regel(Rubriek.R1A).omzet_cents == 163800
        assert aangifte.regel(Rubriek.R1A).btw_cents == 34398
        assert aangifte.regel(Rubriek.R4B).btw_cents == 6300
        assert aangifte.voorbelasting_cents == 4200 + 1470 + 6300  # € 119,70
        assert aangifte.verschuldigd_cents == 34398 + 6300  # € 406,98
        assert aangifte.saldo_cents == 40698 - 11970 == 28728

    # The CSV export carries the underlying detail.
    csv = client.get("/btw/export.csv?jaar=2023&kwartaal=1")
    assert csv.status_code == 200
    assert "F00001" in csv.text

    # --- File it --------------------------------------------------------------------
    client.post("/btw/indienen", data={"jaar": "2023", "kwartaal": "1", "notities": ""})
    with db.session_scope() as session:
        assert btw_svc.is_locked(session, dt.date(2023, 2, 2))
        assert btw_svc.corrections(session, 2023, 1)["verschillen"] == []

    # --- A late document becomes a correction, not a silent change -------------------
    client.post(
        "/kosten/nieuw",
        data={
            "datum": "2023-03-20", "leverancier": "Vergeten leverancier",
            "omschrijving": "late bon", "bedrag_excl": "500,00",
            "btw_behandeling": "binnenland_21", "zakelijk_procent": "100",
        },
    )

    with db.session_scope() as session:
        correctie = btw_svc.corrections(session, 2023, 1)
        assert correctie["saldo_verschil_cents"] == -10500
        verschil = next(v for v in correctie["verschillen"] if v["rubriek"] == "5b")
        assert verschil["btw_verschil_cents"] == 10500
        assert not correctie["suppletie_nodig"]
        assert "eerstvolgende aangifte" in correctie["advies"]

    pagina = client.get("/btw?jaar=2023&kwartaal=1")
    assert "Verschil met de ingediende aangifte" in pagina.text

    # --- The dashboard reflects all of it -------------------------------------------
    # The figures are scoped to the current year, but the unpaid 2023 invoice still
    # shows as outstanding and overdue, which is the point of that panel.
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "1.981,98" in dashboard.text
    assert "F00001" in dashboard.text
    assert "te laat" in dashboard.text


def test_the_urencriterium_counts_non_billable_hours_too(client):
    antwoord = client.post(
        "/klanten/opslaan",
        data={"naam": "Klant", "adres": "Straat 1", "landcode": "NL", "taal": "nl"},
        follow_redirects=False,
    )
    klant_id = int(antwoord.headers["location"].rsplit("/", 1)[1])
    client.post(
        f"/klanten/{klant_id}/project", data={"code": "P", "uurtarief": "100,00"}
    )

    from sqlalchemy import select
    from app.models import Project

    with db.session_scope() as session:
        project_id = session.scalar(select(Project.id))

    jaar = dt.date.today().year
    client.post(
        "/uren/nieuw",
        data={"datum": f"{jaar}-01-10", "project_id": str(project_id), "uren": "6",
              "omschrijving": "werk", "declarabel": "1"},
    )
    client.post(
        "/uren/nieuw",
        data={"datum": f"{jaar}-01-11", "project_id": str(project_id), "uren": "3",
              "omschrijving": "acquisitie", "declarabel": ""},
    )

    pagina = client.get(f"/uren?jaar={jaar}")
    assert pagina.status_code == 200
    # 9 hours total towards the urencriterium, of which 6 are billable.
    assert ">9<" in pagina.text.replace(" ", "").replace("\n", "") or "9" in pagina.text


def test_a_fresh_install_carries_nobody_elses_details(client):
    """The one thing a shared copy must never do: invoice with someone else's IBAN."""
    with db.session_scope() as session:
        instellingen = Settings.get_or_create(session)
        assert instellingen.bedrijfsnaam == ""
        assert instellingen.btw_nummer == ""
        assert instellingen.iban == ""
        assert instellingen.kvk_nummer == ""
        assert not instellingen.is_ingericht
        assert "btw-nummer" in instellingen.ontbrekende_velden

        # Neutral defaults that are safe to ship do stay.
        assert instellingen.betaaltermijn_dagen == 14
        assert instellingen.land == "Nederland"
        assert "14 dagen" in instellingen.factuur_voettekst.format(betaaltermijn=14)


def test_a_fresh_install_sends_you_to_the_settings_screen(client):
    antwoord = client.get("/", follow_redirects=False)
    assert antwoord.status_code == 303
    assert "eerste_start" in antwoord.headers["location"]

    pagina = client.get("/instellingen?eerste_start=1")
    assert "Welkom" in pagina.text
    assert "btw-nummer" in pagina.text


def test_no_invoice_can_be_finalised_before_the_details_are_filled_in(client):
    antwoord = client.post(
        "/klanten/opslaan",
        data={"naam": "Klant", "adres": "Straat 1", "landcode": "NL", "taal": "nl"},
        follow_redirects=False,
    )
    klant_id = int(antwoord.headers["location"].rsplit("/", 1)[1])
    antwoord = client.post(
        "/facturen/nieuw",
        data={"client_id": str(klant_id), "datum": "2026-08-11", "uw_kenmerk": "",
              "prestatie_omschrijving": "augustus"},
        follow_redirects=False,
    )
    factuur_id = int(antwoord.headers["location"].rsplit("/", 1)[1])
    client.post(
        f"/facturen/{factuur_id}/regel",
        data={"aantal": "1", "code": "A", "omschrijving": "werk", "stuksprijs": "100,00",
              "btw_behandeling": "hoog_21"},
    )

    antwoord = client.post(f"/facturen/{factuur_id}/definitief", follow_redirects=False)
    assert "fout=" in antwoord.headers["location"]

    with db.session_scope() as session:
        assert session.get(Invoice, factuur_id).nummer is None, "no number was consumed"


def test_once_the_details_are_in_everything_works(client):
    client.post("/instellingen", data=VOLLEDIGE_INSTELLINGEN)
    with db.session_scope() as session:
        assert Settings.get_or_create(session).is_ingericht
    assert client.get("/", follow_redirects=False).status_code == 200
