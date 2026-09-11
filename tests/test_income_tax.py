"""The income tax estimate, checked against the Belastingdienst's own tables.

The bracket and heffingskorting figures used here are the official 2026 tables:
box 1 35,75% / 37,56% / 49,50%, algemene heffingskorting max EUR 3.115 tapering 6,398%
from EUR 29.736, arbeidskorting in four phases to a maximum of EUR 5.685.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from boekhouding.services import income_tax as ib
from boekhouding.taxyears import tax_year

JAAR = 2026


class TestBrackets:
    def test_income_inside_the_first_bracket(self):
        parameters = tax_year(JAAR)
        # EUR 10.000 entirely in the 35,75% bracket
        assert ib._bracket_tax(1_000_000, parameters.box1_brackets) == 357_500

    def test_income_spanning_two_brackets_is_taxed_per_slice(self):
        parameters = tax_year(JAAR)
        # EUR 50.000: 38.883 @ 35,75% + 11.117 @ 37,56%
        verwacht = round(3_888_300 * 0.3575) + round((5_000_000 - 3_888_300) * 0.3756)
        assert ib._bracket_tax(5_000_000, parameters.box1_brackets) == pytest.approx(
            verwacht, abs=2
        )

    def test_exactly_at_a_bracket_boundary(self):
        parameters = tax_year(JAAR)
        assert ib._bracket_tax(3_888_300, parameters.box1_brackets) == 1_390_067

    def test_top_bracket_applies_only_above_the_boundary(self):
        parameters = tax_year(JAAR)
        onder = ib._bracket_tax(7_842_600, parameters.box1_brackets)
        boven = ib._bracket_tax(7_942_600, parameters.box1_brackets)
        assert boven - onder == round(1_000_00 * 0.495)

    def test_zero_and_negative_profit_owe_nothing(self):
        parameters = tax_year(JAAR)
        assert ib._bracket_tax(0, parameters.box1_brackets) == 0
        assert ib._bracket_tax(-500_000, parameters.box1_brackets) == 0


class TestHeffingskortingen:
    def test_algemene_heffingskorting_is_the_maximum_below_the_taper(self):
        parameters = tax_year(JAAR)
        assert ib._credit(2_000_000, parameters.algemene_heffingskorting) == 311_500
        assert ib._credit(2_973_600, parameters.algemene_heffingskorting) == 311_500

    def test_algemene_heffingskorting_tapers_above_the_threshold(self):
        parameters = tax_year(JAAR)
        # EUR 40.000: 3.115 - 6,398% x (40.000 - 29.736) = 3.115 - 656,70
        assert ib._credit(4_000_000, parameters.algemene_heffingskorting) == 245_831

    def test_algemene_heffingskorting_reaches_zero_at_the_top_bracket(self):
        parameters = tax_year(JAAR)
        assert ib._credit(7_842_600, parameters.algemene_heffingskorting) == 0
        assert ib._credit(9_000_000, parameters.algemene_heffingskorting) == 0

    def test_arbeidskorting_builds_up_then_peaks(self):
        parameters = tax_year(JAAR)
        # The build-up formula gives 5.685,07 at the top of the third phase, seven cents
        # above the published maximum of 5.685. estimate() clamps it; the raw table does
        # not, and this test pins that difference so it stays deliberate.
        assert ib._credit(4_559_200, parameters.arbeidskorting) == 568_507
        assert parameters.arbeidskorting_max_cents == 568_500
        assert ib.estimate(6_000_000, JAAR).arbeidskorting_cents <= 568_500

    def test_arbeidskorting_in_the_third_phase(self):
        parameters = tax_year(JAAR)
        # EUR 35.000: 5.300 + 1,950% x (35.000 - 25.845) = 5.300 + 178,52
        assert ib._credit(3_500_000, parameters.arbeidskorting) == 547_852

    def test_arbeidskorting_tapers_to_zero(self):
        parameters = tax_year(JAAR)
        assert ib._credit(13_292_000, parameters.arbeidskorting) == 0
        assert ib._credit(15_000_000, parameters.arbeidskorting) == 0


class TestFullEstimate:
    def test_a_typical_year(self):
        """EUR 40.000 profit, urencriterium met, not a starter."""
        schatting = ib.estimate(4_000_000, JAAR)

        assert schatting.ondernemersaftrek_cents == 120_000  # zelfstandigenaftrek
        # MKB-winstvrijstelling: 12,7% van 38.800
        assert schatting.mkb_vrijstelling_cents == 492_760
        assert schatting.belastbare_winst_cents == 3_387_240

        # Box 1 over 33.872,40, entirely in the first bracket: x 35,75%
        assert schatting.box1_belasting_cents == 1_210_938
        assert schatting.algemene_heffingskorting_cents > 0
        assert schatting.arbeidskorting_cents > 0
        assert schatting.zvw_cents == 164_281  # 4,85% van 33.872,40

        # The whole point: the burden is far below a flat 35%.
        assert schatting.effectief_tarief_pct < Decimal("25")
        assert schatting.totaal_cents == (
            schatting.inkomstenbelasting_cents + schatting.zvw_cents
        )

    def test_missing_the_urencriterium_costs_the_zelfstandigenaftrek(self):
        met = ib.estimate(4_000_000, JAAR, urencriterium_gehaald=True)
        zonder = ib.estimate(4_000_000, JAAR, urencriterium_gehaald=False)
        assert zonder.ondernemersaftrek_cents == 0
        assert zonder.totaal_cents > met.totaal_cents
        assert any("urencriterium" in w for w in zonder.waarschuwingen)

    def test_the_startersaftrek_lowers_the_bill(self):
        gewoon = ib.estimate(4_000_000, JAAR)
        starter = ib.estimate(4_000_000, JAAR, starter=True)
        assert starter.totaal_cents < gewoon.totaal_cents

    def test_a_low_profit_is_almost_entirely_offset_by_the_heffingskortingen(self):
        # EUR 15.000 profit -> belastbare winst 12.047,40 -> box 1 4.306,94, against
        # 3.115 algemene heffingskorting + 1.021,55 arbeidskorting. Barely any tax left,
        # but the Zvw contribution is still owed in full.
        schatting = ib.estimate(1_500_000, JAAR)
        assert schatting.inkomstenbelasting_cents == 17_040
        assert schatting.zvw_cents > schatting.inkomstenbelasting_cents

    def test_a_very_low_profit_owes_no_income_tax_at_all(self):
        schatting = ib.estimate(800_000, JAAR)
        assert schatting.inkomstenbelasting_cents == 0, "heffingskortingen exceed the tax"
        assert schatting.zvw_cents > 0
        assert schatting.totaal_cents == schatting.zvw_cents

    def test_heffingskortingen_never_produce_a_refund(self):
        schatting = ib.estimate(500_000, JAAR)
        assert schatting.inkomstenbelasting_cents >= 0

    def test_zero_profit_owes_nothing(self):
        schatting = ib.estimate(0, JAAR)
        assert schatting.totaal_cents == 0

    def test_a_loss_is_treated_as_zero_profit(self):
        schatting = ib.estimate(-1_000_000, JAAR)
        assert schatting.totaal_cents == 0

    def test_zvw_is_capped_at_the_maximum_grondslag(self):
        parameters = tax_year(JAAR)
        schatting = ib.estimate(20_000_000, JAAR)
        maximum = round(parameters.zvw_max_grondslag_cents * float(parameters.zvw_pct) / 100)
        assert schatting.zvw_cents == pytest.approx(maximum, abs=2)

    def test_a_high_profit_warns_about_the_tariefsaanpassing(self):
        schatting = ib.estimate(12_000_000, JAAR)
        assert any("tariefsaanpassing" in w for w in schatting.waarschuwingen)

    def test_the_effective_rate_rises_with_profit(self):
        tarieven = [
            ib.estimate(winst, JAAR).effectief_tarief_pct
            for winst in (2_000_000, 4_000_000, 8_000_000, 15_000_000)
        ]
        assert tarieven == sorted(tarieven), "progressive, so never decreasing"

    def test_every_step_is_shown_so_the_number_can_be_checked(self):
        schatting = ib.estimate(4_000_000, JAAR)
        labels = [regel.label for regel in schatting.regels]
        assert "Winst uit onderneming" in labels
        assert "MKB-winstvrijstelling" in labels
        assert "Heffingskortingen" in labels
        assert "Bijdrage Zorgverzekeringswet" in labels
        assert labels[-1] == "Totaal over het hele jaar"

    def test_the_lines_add_up_to_the_total(self):
        """What the table shows must reconcile, at every profit level."""
        for winst in (50_000, 60_000, 150_000, 1_500_000, 4_000_000, 12_000_000):
            schatting = ib.estimate(winst, JAAR)
            regels = {r.label: r.bedrag_cents for r in schatting.regels}
            berekend = (
                regels["Inkomstenbelasting box 1"]
                + regels["Heffingskortingen"]  # already negative
                )
            assert berekend == regels["Inkomstenbelasting"], f"bij winst {winst}"
            assert (
                regels["Inkomstenbelasting"] + regels["Bijdrage Zorgverzekeringswet"]
                == regels["Totaal over het hele jaar"]
            ), f"bij winst {winst}"


class TestHeffingskortingenAreNeverShownLargerThanTheTax:
    def test_at_a_low_profit_only_the_used_part_is_shown(self):
        """A EUR 646 profit must not display a EUR 3.115 deduction."""
        schatting = ib.estimate(64_602, JAAR)
        korting = next(r for r in schatting.regels if r.label == "Heffingskortingen")
        box1 = next(r for r in schatting.regels if r.label == "Inkomstenbelasting box 1")

        assert abs(korting.bedrag_cents) <= box1.bedrag_cents
        assert schatting.inkomstenbelasting_cents == 0
        assert "niet uitbetaald" in korting.toelichting
        # The full entitlement is still visible, just as explanation rather than a line.
        assert "3.115,00" in korting.toelichting

    def test_at_a_normal_profit_the_full_credit_is_used(self):
        schatting = ib.estimate(4_000_000, JAAR)
        korting = next(r for r in schatting.regels if r.label == "Heffingskortingen")
        assert abs(korting.bedrag_cents) == (
            schatting.algemene_heffingskorting_cents + schatting.arbeidskorting_cents
        )
        assert "niet uitbetaald" not in korting.toelichting

    def test_missing_the_urencriterium_shows_an_explicit_zero_line(self):
        schatting = ib.estimate(4_000_000, JAAR, urencriterium_gehaald=False)
        regel = next(r for r in schatting.regels if r.label == "Zelfstandigenaftrek")
        assert regel.bedrag_cents == 0
        assert "vervalt" in regel.toelichting


class TestAnnualising:
    def test_year_to_date_profit_is_extrapolated_to_a_full_year(self):
        # EUR 10.000 after a quarter implies about EUR 40.000 for the year.
        assert ib.annualise(1_000_000, 91) == pytest.approx(4_010_989, abs=100)

    def test_no_days_elapsed_gives_zero_rather_than_dividing_by_zero(self):
        assert ib.annualise(1_000_000, 0) == 0

    def test_a_full_year_is_left_alone(self):
        assert ib.annualise(4_000_000, 365) == 4_000_000


class TestUnverifiedYears:
    def test_a_year_without_tables_is_flagged(self):
        schatting = ib.estimate(4_000_000, 2023)
        assert any("taxyears.py" in w for w in schatting.waarschuwingen)

    def test_2026_is_verified_against_the_belastingdienst(self):
        assert tax_year(2026).verified is True
