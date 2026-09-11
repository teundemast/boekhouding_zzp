from __future__ import annotations

import datetime as dt

import pytest

from app import db
from app.models import Client, ExpenseCategory, Project, Settings


def vul_bedrijfsgegevens(s) -> Settings:
    """Give the test administration its own business details.

    A fresh install ships with these empty on purpose, so that a copy handed to someone
    else can never invoice with the previous owner's IBAN. Every test that finalises an
    invoice therefore has to fill them in first, exactly like a real first run.
    """
    instellingen = Settings.get_or_create(s)
    instellingen.bedrijfsnaam = "Voorbeeld Data Science"
    instellingen.adres = "Teststraat 1"
    instellingen.postcode = "1234 AB"
    instellingen.plaats = "Leiden"
    instellingen.telefoon = "0600000000"
    instellingen.email = "test@example.nl"
    instellingen.btw_nummer = "NL000000000B00"
    instellingen.iban = "NL00 TEST 0000 0000 00"
    instellingen.kvk_nummer = "00000000"
    s.flush()
    return instellingen


@pytest.fixture()
def session(tmp_path, monkeypatch):
    db.configure_for_tests(tmp_path / "data")
    with db.session_scope() as s:
        vul_bedrijfsgegevens(s)
        yield s


@pytest.fixture()
def settings(session) -> Settings:
    return Settings.get_or_create(session)


@pytest.fixture()
def acme(session) -> Client:
    client = Client(
        naam="Acme Analytics B.V.",
        klantnummer="ACME",
        adres="Voorbeeldkade 12",
        postcode="1011 AB",
        plaats="Amsterdam",
        land="Nederland",
        landcode="NL",
        btw_nummer="NL812345678B01",
    )
    session.add(client)
    session.flush()
    return client


@pytest.fixture()
def duitse_klant(session) -> Client:
    client = Client(
        naam="Datenwerk GmbH",
        adres="Hauptstrasse 1",
        postcode="10115",
        plaats="Berlin",
        land="Duitsland",
        landcode="DE",
        btw_nummer="DE123456789",
        taal="en",
    )
    session.add(client)
    session.flush()
    return client


@pytest.fixture()
def project_adsd(session, acme) -> Project:
    project = Project(
        client_id=acme.id,
        code="ADSD",
        omschrijving="Algemene Data Science Diensten",
        uurtarief_cents=1800,
    )
    session.add(project)
    session.flush()
    return project


@pytest.fixture()
def categorie_software(session) -> ExpenseCategory:
    categorie = ExpenseCategory(code="SOFT", naam="Software-abonnementen")
    session.add(categorie)
    session.flush()
    return categorie


@pytest.fixture()
def vandaag() -> dt.date:
    return dt.date(2023, 2, 2)
