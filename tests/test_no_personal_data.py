"""The code must stay free of personal data.

Business details, clients, and rates belong in the database, so that a copy of this
program starts empty and nobody can invoice with the previous owner's IBAN. This
repository is public, which makes that a promise to keep rather than a preference:
`tools/maak_zip.py` already refuses to package a BTW number, IBAN, e-mail address, or
phone number, and this test runs the same check on every commit.
"""

from __future__ import annotations

from tools import maak_zip


def test_no_personal_data_anywhere_in_the_code():
    problemen = maak_zip.controleer(maak_zip.bestanden())
    assert problemen == [], "\n".join(["Persoonsgegevens in de code:", *problemen])


def test_the_handover_zip_ships_the_licence():
    """Whoever you hand a copy to gets the licence that lets them use it."""
    assert "LICENSE" in maak_zip.LOSSE_BESTANDEN
    assert (maak_zip.WORTEL / "LICENSE").exists()
