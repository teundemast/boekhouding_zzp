"""Starting the counter partway through an existing numbering series.

I have been invoicing since 2023 and am well past F00006, so the first invoice this
system issues must continue that series rather than restart it.
"""

from __future__ import annotations

import datetime as dt

import pytest

from boekhouding.services import invoices as svc


def _factuur(session, klant, datum=dt.date(2026, 8, 10)):
    invoice = svc.create_draft(session, klant, datum=datum, prestatie_omschrijving="augustus")
    svc.add_line(session, invoice, aantal="1", code="A", omschrijving="werk",
                 stuksprijs="100,00")
    return invoice


def test_the_series_continues_from_the_seeded_number(session, acme):
    svc.set_counter(session, "factuur", 0, 6)
    assert svc.peek_number(session, "factuur", dt.date(2026, 8, 10)) == "F00007"

    invoice = _factuur(session, acme)
    svc.finalise(session, invoice)
    assert invoice.nummer == "F00007"


def test_the_counter_can_never_go_backwards(session, acme):
    invoice = _factuur(session, acme)
    svc.finalise(session, invoice)
    assert invoice.nummer == "F00001"

    with pytest.raises(ValueError, match="Verlagen"):
        svc.set_counter(session, "factuur", 0, 0)


def test_seeding_twice_upwards_is_allowed(session, acme):
    svc.set_counter(session, "factuur", 0, 6)
    svc.set_counter(session, "factuur", 0, 20)
    invoice = _factuur(session, acme)
    svc.finalise(session, invoice)
    assert invoice.nummer == "F00021"
