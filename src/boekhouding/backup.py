"""One-command backup and export.

    boekhouding-backup            -> a single zip of everything
    boekhouding-backup --export   -> plain CSV of every table as well
    boekhouding-backup --restore <zip> <doelmap>

The zip contains the database and every attachment and generated PDF. The CSV export
exists so this application can never hold my administration hostage: those files are
readable with or without this code, in seven years' time.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import sqlite3
import sys
import zipfile
from pathlib import Path

from boekhouding import db


def backup(doelmap: Path | None = None) -> Path:
    db.ensure_directories()
    doelmap = doelmap or (db.DATA_DIR / "backups")
    doelmap.mkdir(parents=True, exist_ok=True)
    doel = doelmap / f"boekhouding-{dt.datetime.now():%Y%m%d-%H%M%S}.zip"

    # Copy the database through SQLite's own backup API so a running application, and
    # anything sitting in the WAL, is captured consistently.
    tijdelijk = doelmap / "_tijdelijk.sqlite3"
    bron = sqlite3.connect(db.DB_PATH)
    kopie = sqlite3.connect(tijdelijk)
    with kopie:
        bron.backup(kopie)
    kopie.close()
    bron.close()

    with zipfile.ZipFile(doel, "w", zipfile.ZIP_DEFLATED) as archief:
        archief.write(tijdelijk, "boekhouding.sqlite3")
        for map_naam, pad in [
            ("documenten", db.DOCUMENTS_DIR),
            ("facturen", db.INVOICE_PDF_DIR),
            ("inbox", db.INBOX_DIR),
        ]:
            if not pad.exists():
                continue
            for bestand in pad.rglob("*"):
                if bestand.is_file():
                    archief.write(bestand, f"{map_naam}/{bestand.relative_to(pad)}")
    tijdelijk.unlink()
    return doel


def export_csv(doelmap: Path | None = None) -> Path:
    """Every table as a semicolon-separated CSV, readable without this application."""
    doelmap = doelmap or (db.DATA_DIR / "export" / f"{dt.date.today():%Y-%m-%d}")
    doelmap.mkdir(parents=True, exist_ok=True)

    verbinding = sqlite3.connect(db.DB_PATH)
    verbinding.row_factory = sqlite3.Row
    tabellen = [
        rij[0]
        for rij in verbinding.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    for tabel in tabellen:
        rijen = verbinding.execute(f"SELECT * FROM {tabel}").fetchall()
        with (doelmap / f"{tabel}.csv").open("w", newline="", encoding="utf-8") as bestand:
            schrijver = csv.writer(bestand, delimiter=";")
            if rijen:
                schrijver.writerow(rijen[0].keys())
                schrijver.writerows([tuple(rij) for rij in rijen])
            else:
                kolommen = [
                    k[1] for k in verbinding.execute(f"PRAGMA table_info({tabel})")
                ]
                schrijver.writerow(kolommen)
    verbinding.close()
    return doelmap


def restore(archief_pad: Path, doelmap: Path) -> None:
    """Unpack a backup into a directory. Refuses to overwrite an existing one."""
    if doelmap.exists() and any(doelmap.iterdir()):
        raise SystemExit(
            f"{doelmap} bestaat al en is niet leeg. Kies een lege map, zodat een restore "
            "nooit een bestaande administratie overschrijft."
        )
    doelmap.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archief_pad) as archief:
        archief.extractall(doelmap)
    print(f"Teruggezet in {doelmap}")
    print(f"Start met:  set BOEKHOUDING_DATA={doelmap}  en dan  boekhouding")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Back-up en export van de boekhouding")
    parser.add_argument("--export", action="store_true", help="ook alles als CSV wegschrijven")
    parser.add_argument("--restore", nargs=2, metavar=("ZIP", "DOELMAP"))
    parser.add_argument("--naar", type=Path, default=None, help="map voor de back-up")
    argumenten = parser.parse_args(argv)

    if argumenten.restore:
        restore(Path(argumenten.restore[0]), Path(argumenten.restore[1]))
        return 0

    doel = backup(argumenten.naar)
    print(f"Back-up: {doel}  ({doel.stat().st_size / 1_000_000:.1f} MB)")

    if argumenten.export:
        export = export_csv()
        print(f"CSV-export: {export}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
