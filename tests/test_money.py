from __future__ import annotations

from decimal import Decimal

import pytest

from boekhouding import money


class TestRounding:
    def test_halves_round_away_from_zero_not_to_even(self):
        # Python's default would give 2 for both; commercial rounding gives 3 and 2.
        assert money.round_half_up(Decimal("2.5")) == 3
        assert money.round_half_up(Decimal("1.5")) == 2
        assert money.round_half_up(Decimal("0.5")) == 1

    def test_line_total_rounds_once(self):
        # 3 x 0.335 = 1.005 -> 1.01, not 1.00
        assert money.line_total_cents(money.quantity_to_milli("3"), 34) == 102

    def test_many_small_lines_sum_to_the_invoice_total_exactly(self):
        # Each line rounds independently; the invoice total is the sum of rounded lines.
        regels = [money.line_total_cents(money.quantity_to_milli("1.5"), 1667) for _ in range(7)]
        assert regels == [2501] * 7
        assert sum(regels) == 17507

    def test_vat_is_computed_over_the_summed_base(self):
        assert money.vat_cents(163800, 210) == 34398
        assert money.vat_cents(10000, 90) == 900
        assert money.vat_cents(0, 210) == 0

    def test_vat_on_a_negative_base_stays_negative(self):
        assert money.vat_cents(-163800, 210) == -34398


class TestParsing:
    @pytest.mark.parametrize(
        ("tekst", "cents"),
        [
            ("1.638,00", 163800),
            ("1638.00", 163800),
            ("1638", 163800),
            ("€ 1.981,98", 198198),
            ("0,01", 1),
            ("", 0),
        ],
    )
    def test_dutch_and_plain_notation(self, tekst, cents):
        assert money.euros_to_cents(tekst) == cents

    def test_quantities_keep_three_decimals(self):
        assert money.quantity_to_milli("41") == 41000
        assert money.quantity_to_milli("41,5") == 41500
        assert money.quantity_to_milli("0,25") == 250


class TestFormatting:
    @pytest.mark.parametrize(
        ("cents", "tekst"),
        [
            (163800, "€ 1.638,00"),
            (198198, "€ 1.981,98"),
            (34398, "€ 343,98"),
            (5, "€ 0,05"),
            (0, "€ 0,00"),
            (-34398, "€ -343,98"),
            (123456789, "€ 1.234.567,89"),
        ],
    )
    def test_dutch_money_formatting(self, cents, tekst):
        assert money.format_euro(cents) == tekst

    @pytest.mark.parametrize(
        ("milli", "tekst"),
        [(41000, "41"), (41500, "41,5"), (250, "0,25"), (1000, "1")],
    )
    def test_quantities_drop_trailing_zeros(self, milli, tekst):
        assert money.format_quantity(milli) == tekst
