"""The published repository must stay free of personal data.

Business details, clients, and rates belong in the database, so that a fresh install
starts empty and nobody can invoice with the previous owner's IBAN. Now that this
repository is public, that is a promise to keep rather than a preference, and a promise
nobody can keep by hand: the check runs over everything git tracks, which is exactly what
a visitor sees on GitHub.

This used to live in a script that packed a zip to hand to someone else. Git does that
part now; only the check was worth keeping.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

WORTEL = Path(__file__).resolve().parent.parent

#: Patronen die op een echt persoon wijzen. Een treffer is een bug.
VERDACHT = [
    (r"NL\d{9}B\d{2}", "een btw-nummer"),
    (r"\bNL\d{2}\s?[A-Z]{4}\s?\d{4}\s?\d{4}\s?\d{2}\b", "een IBAN"),
    (r"[\w.+-]+@(?!example\.)[\w-]+\.[\w.]+", "een e-mailadres"),
    (r"\+31\s?6\s?\d{8}", "een telefoonnummer"),
    (r"\b06[-\s]?\d{8}\b", "een telefoonnummer"),
]

#: Deze mogen wel: onmiskenbare voorbeeldwaarden uit tests en documentatie.
TOEGESTAAN = {
    "NL000000000B00",
    "NL00 TEST 0000 0000 00",
    "NL123456789B01",
    "NL812345678B01",
    "DE123456789",
    "test@example.nl",
    "0600000000",
}


def gepubliceerde_bestanden() -> list[Path]:
    """Everything git tracks, which is everything a visitor can read."""
    try:
        uitvoer = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=WORTEL,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as fout:
        pytest.skip(f"geen git-checkout, dus niets te controleren: {fout}")
    return [WORTEL / naam for naam in uitvoer.split("\0") if naam]


def test_no_personal_data_in_any_published_file():
    bestanden = gepubliceerde_bestanden()
    assert bestanden, "git ls-files gaf niets terug; dan controleert deze test niets"

    problemen: list[str] = []
    for pad in bestanden:
        try:
            tekst = pad.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binair, of net verwijderd maar nog getrackt
        for patroon, omschrijving in VERDACHT:
            for treffer in re.findall(patroon, tekst):
                if treffer in TOEGESTAAN:
                    continue
                problemen.append(f"{pad.relative_to(WORTEL)}: {omschrijving} -> {treffer}")

    assert problemen == [], "\n".join(
        [
            "Persoonsgegevens in de repository. Haal ze eruit, of zet ze in TOEGESTAAN",
            "als het echt een voorbeeldwaarde is:",
            *problemen,
        ]
    )
