"""Maak een zip om aan iemand anders te geven.

    python -m tools.maak_zip

Levert een bestand op dat de ontvanger uitpakt en waarin hij Boekhouding.cmd
dubbelklikt. Bevat de code, niet de git-historie, niet de virtuele omgeving en
uiteraard geen administratie -- die staat sowieso buiten deze map.

Voor het inpakken wordt gecontroleerd dat er geen persoonsgegevens in de code staan.
Die controle is de reden dat dit script bestaat: een zip met andermans IBAN erin is
precies wat we niet willen versturen.
"""

from __future__ import annotations

import datetime as dt
import re
import sys
import zipfile
from pathlib import Path

WORTEL = Path(__file__).resolve().parent.parent

#: Alles wat mee moet in de zip.
MEE = ["app", "tools", "tests"]
LOSSE_BESTANDEN = [
    "Boekhouding.cmd", "start.ps1", "requirements.txt",
    "README.md", "PROMPT.md", "LICENSE",
]

#: Nooit meesturen.
OVERSLAAN = {".venv", ".git", "__pycache__", ".pytest_cache", "boekhouding-data"}

#: Patronen die op een echt persoon wijzen. Een treffer stopt het inpakken.
VERDACHT = [
    (r"NL\d{9}B\d{2}", "een btw-nummer"),
    (r"\bNL\d{2}\s?[A-Z]{4}\s?\d{4}\s?\d{4}\s?\d{2}\b", "een IBAN"),
    (r"[\w.+-]+@(?!example\.)[\w-]+\.[\w.]+", "een e-mailadres"),
    (r"\+31\s?6\s?\d{8}", "een telefoonnummer"),
]

#: Deze mogen wel: duidelijke voorbeeldwaarden uit tests en documentatie.
TOEGESTAAN = {
    "NL000000000B00", "NL00 TEST 0000 0000 00", "NL123456789B01", "NL812345678B01",
    "DE123456789", "noreply@anthropic.com", "test@example.nl",
}


def bestanden() -> list[Path]:
    gevonden: list[Path] = []
    for naam in MEE:
        for pad in (WORTEL / naam).rglob("*"):
            if pad.is_file() and not any(deel in OVERSLAAN for deel in pad.parts):
                gevonden.append(pad)
    for naam in LOSSE_BESTANDEN:
        pad = WORTEL / naam
        if pad.exists():
            gevonden.append(pad)
    return sorted(gevonden)


def controleer(paden: list[Path]) -> list[str]:
    problemen: list[str] = []
    for pad in paden:
        if pad.suffix not in {".py", ".md", ".html", ".css", ".cmd", ".ps1", ".txt"}:
            continue
        tekst = pad.read_text(encoding="utf-8", errors="ignore")
        for patroon, omschrijving in VERDACHT:
            for treffer in re.findall(patroon, tekst):
                if treffer in TOEGESTAAN:
                    continue
                problemen.append(
                    f"{pad.relative_to(WORTEL)}: {omschrijving} gevonden -> {treffer}"
                )
    return problemen


def main() -> int:
    paden = bestanden()
    problemen = controleer(paden)
    if problemen:
        print("Inpakken gestopt. Er staan nog persoonsgegevens in de code:\n")
        for probleem in problemen:
            print(f"  {probleem}")
        print("\nHaal deze eruit of voeg ze toe aan TOEGESTAAN als het voorbeelden zijn.")
        return 1

    doel = WORTEL.parent / f"boekhouding-{dt.date.today():%Y%m%d}.zip"
    with zipfile.ZipFile(doel, "w", zipfile.ZIP_DEFLATED) as archief:
        for pad in paden:
            archief.write(pad, f"boekhouding/{pad.relative_to(WORTEL).as_posix()}")

    print(f"Gecontroleerd: {len(paden)} bestanden, geen persoonsgegevens gevonden.")
    print(f"Zip: {doel}  ({doel.stat().st_size / 1024:.0f} kB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
