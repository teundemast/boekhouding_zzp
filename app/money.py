"""Money and quantity arithmetic.

Every amount in this application is an integer number of eurocents. Quantities are
integer thousandths of a unit, so 41.5 hours is 41_500. Nothing here uses floats:
rounding must be predictable and reproducible, because these numbers end up on a
tax return.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENTS = Decimal("0.01")
QUANTITY_SCALE = 1000


def round_half_up(value: Decimal | int) -> int:
    """Round a Decimal to a whole number, halves away from zero.

    This is ordinary commercial rounding, which is what the Belastingdienst and every
    Dutch invoice expect -- not Python's default banker's rounding.

    Floats are rejected rather than converted. A float here means some caller divided
    with ``/`` instead of building a Decimal, and that is precisely the mistake this
    application must never make with money.
    """
    if isinstance(value, float):
        raise TypeError(
            "round_half_up kreeg een float; gebruik Decimal voor bedragen. "
            "Waarschijnlijk staat er een '/' waar Decimal(...) hoort."
        )
    if isinstance(value, int):
        return value
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def euros_to_cents(value: str | Decimal | int) -> int:
    """Parse a euro amount into cents. Accepts Dutch or plain notation."""
    if isinstance(value, str):
        value = parse_dutch_decimal(value)
    return round_half_up(Decimal(value) * 100)


def cents_to_decimal(cents: int) -> Decimal:
    return (Decimal(cents) / 100).quantize(CENTS)


def parse_dutch_decimal(text: str) -> Decimal:
    """Parse '1.638,00' or '1638.00' or '1638' into a Decimal.

    A comma always means the decimal separator; dots are thousands separators unless
    there is no comma, in which case a single dot is treated as the decimal separator.
    """
    cleaned = text.strip().replace("€", "").replace(" ", "").replace(" ", "")
    if not cleaned:
        return Decimal(0)
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    return Decimal(cleaned)


def quantity_to_milli(value: str | Decimal | int) -> int:
    if isinstance(value, str):
        value = parse_dutch_decimal(value)
    return round_half_up(Decimal(value) * QUANTITY_SCALE)


def milli_to_decimal(milli: int) -> Decimal:
    return (Decimal(milli) / QUANTITY_SCALE).quantize(Decimal("0.001"))


def line_total_cents(quantity_milli: int, unit_price_cents: int) -> int:
    """Line total, rounded to whole cents once."""
    return round_half_up(Decimal(quantity_milli) * Decimal(unit_price_cents) / QUANTITY_SCALE)


def vat_cents(base_cents: int, rate_permille: int) -> int:
    """VAT over a base amount. `rate_permille` is tenths of a percent: 21% is 210.

    Applied to the summed base per rate, not per line, which is how the totals block on
    a Dutch invoice reconciles.
    """
    return round_half_up(Decimal(base_cents) * Decimal(rate_permille) / 1000)


def format_euro(cents: int, symbol: bool = True) -> str:
    """Dutch money formatting: 163800 -> '€ 1.638,00'."""
    negative = cents < 0
    whole, fraction = divmod(abs(cents), 100)
    groups = f"{whole:,}".replace(",", ".")
    body = f"{groups},{fraction:02d}"
    if negative:
        body = "-" + body
    return f"€ {body}" if symbol else body


def format_quantity(milli: int) -> str:
    """Drop trailing zeros: 41000 -> '41', 41500 -> '41,5'."""
    text = f"{milli // QUANTITY_SCALE},{milli % QUANTITY_SCALE:03d}".rstrip("0").rstrip(",")
    return text or "0"
