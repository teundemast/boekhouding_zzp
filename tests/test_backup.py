"""A backup is only worth anything if the restore has been tried."""

from __future__ import annotations

import datetime as dt
import sqlite3
import zipfile

import pytest

from boekhouding import backup as backup_tool
from boekhouding import db
from boekhouding.models import Client
from boekhouding.services import invoices as svc
from tests.conftest import vul_bedrijfsgegevens


@pytest.fixture()
def gevulde_administratie(tmp_path):
    db.configure_for_tests(tmp_path / "data")
    with db.session_scope() as session:
        vul_bedrijfsgegevens(session)
        klant = Client(naam="Acme Analytics B.V.", adres="Voorbeeldkade 12", plaats="Amsterdam")
        session.add(klant)
        session.flush()
        invoice = svc.create_draft(
            session, klant, datum=dt.date(2023, 2, 2), prestatie_omschrijving="februari"
        )
        svc.add_line(session, invoice, aantal="41", code="ADSD",
                     omschrijving="Data science", stuksprijs="18,00")
        svc.finalise(session, invoice)
    (db.DOCUMENTS_DIR / "2023").mkdir(parents=True, exist_ok=True)
    (db.DOCUMENTS_DIR / "2023" / "bon.pdf").write_bytes(b"%PDF-1.4 nep bonnetje")
    return tmp_path


def test_the_backup_contains_the_database_and_the_attachments(gevulde_administratie):
    archief_pad = backup_tool.backup()
    assert archief_pad.exists()

    with zipfile.ZipFile(archief_pad) as archief:
        namen = archief.namelist()
    assert "boekhouding.sqlite3" in namen
    assert any(naam.endswith("bon.pdf") for naam in namen)


def test_restoring_produces_a_working_database(gevulde_administratie, tmp_path):
    archief_pad = backup_tool.backup()
    doel = tmp_path / "hersteld"
    backup_tool.restore(archief_pad, doel)

    verbinding = sqlite3.connect(doel / "boekhouding.sqlite3")
    nummers = [rij[0] for rij in verbinding.execute("SELECT nummer FROM invoice")]
    verbinding.close()
    assert nummers == ["F00001"]
    assert (doel / "documenten" / "2023" / "bon.pdf").exists()


def test_restoring_refuses_to_overwrite_an_existing_administration(
    gevulde_administratie, tmp_path
):
    archief_pad = backup_tool.backup()
    doel = tmp_path / "bezet"
    doel.mkdir()
    (doel / "iets.txt").write_text("bestaande administratie")

    with pytest.raises(SystemExit, match="niet leeg"):
        backup_tool.restore(archief_pad, doel)


def test_the_csv_export_is_readable_without_this_application(gevulde_administratie):
    export = backup_tool.export_csv()
    factuur_csv = (export / "invoice.csv").read_text(encoding="utf-8")
    assert "nummer" in factuur_csv.splitlines()[0]
    assert "F00001" in factuur_csv
    assert (export / "invoice_line.csv").exists()
    assert (export / "client.csv").exists()
