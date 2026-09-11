"""Year-tagged tax parameters.

Every rate, threshold and allowance that the Belastingdienst changes lives here with the
year attached, never inline in the code. When a new year starts, add a block; nothing
else needs to change.

These figures drive *indicative* income tax calculations and warnings. They are not tax
advice, and the BTW figures in vat.py do not depend on them.

Amounts are integer eurocents. Percentages are Decimals in percent (35.75 means 35,75%),
because several of them have three significant decimals and would not survive being
squeezed into an integer permille.

Sources, all checked 10-08-2026 (see `verified`):
  - Box 1 brackets, algemene heffingskorting, arbeidskorting:
    belastingdienst.nl/wps/wcm/connect/nl/voorlopige-aanslag/content/
    voorlopige-aanslag-tarieven-en-heffingskortingen
  - Arbeidskorting table: .../heffingskortingen/arbeidskorting/tabel-arbeidskorting-2026
  - Algemene heffingskorting table: .../algemene_heffingskorting/
    tabel-algemene-heffingskorting-2026
  - Zvw percentages and maximum bijdrage-inkomen:
    belastingdienst.nl/.../zorgverzekeringswet/veranderingen-bijdrage-zvw/percentages-zvw
  - KIA: belastingdienst.nl/.../investeringsaftrek-2026/
    kleinschaligheidsinvesteringsaftrek-2026
  - Zelfstandigenaftrek, MKB-winstvrijstelling, urencriterium: kvk.nl/geldzaken/
    belastingtarieven-2026/
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal

#: (upper bound in cents or None for "and above", rate in percent)
Bracket = tuple[int | None, Decimal]

#: (upper bound in cents or None, base amount in cents, percentage, threshold in cents)
#: Credit = base + percentage% x (income - threshold). A negative percentage tapers.
CreditBracket = tuple[int | None, int, Decimal, int]


@dataclass(frozen=True)
class TaxYear:
    year: int

    # -- Ondernemersaftrek ------------------------------------------------------------
    #: Hours of business activity required for the zelfstandigenaftrek.
    urencriterium: int = 1225
    zelfstandigenaftrek_cents: int = 0
    #: On top of the zelfstandigenaftrek, at most three times in the first five years.
    startersaftrek_cents: int = 0
    #: MKB-winstvrijstelling, applied to profit *after* the ondernemersaftrek.
    mkb_winstvrijstelling_pct: Decimal = Decimal(0)

    # -- Box 1 ------------------------------------------------------------------------
    box1_brackets: tuple[Bracket, ...] = field(default_factory=tuple)
    algemene_heffingskorting: tuple[CreditBracket, ...] = field(default_factory=tuple)
    arbeidskorting: tuple[CreditBracket, ...] = field(default_factory=tuple)
    #: The published maximum. The build-up formula overshoots it by a few cents at the
    #: top of the third phase (5.300 + 1,950% x 19.747 = 5.685,07 against a stated
    #: maximum of 5.685), so the result is clamped to this.
    arbeidskorting_max_cents: int = 0

    # -- Zorgverzekeringswet ----------------------------------------------------------
    #: Rate self-employed people pay themselves over their bijdrage-inkomen.
    zvw_pct: Decimal = Decimal(0)
    zvw_max_grondslag_cents: int = 0

    # -- Btw and investments ----------------------------------------------------------
    kor_omzetgrens_cents: int = 2_000_000
    #: Minimum per bedrijfsmiddel to count as an investment rather than a cost.
    investeringsgrens_cents: int = 45_000
    #: Total yearly investment needed before any KIA applies.
    kia_ondergrens_cents: int = 0
    kia_bovengrens_cents: int = 0
    kia_pct: Decimal = Decimal(0)
    kia_max_cents: int = 0

    kilometervergoeding_cents: int = 23
    #: Correction below which a BTW error may go in the next return instead of a suppletie.
    suppletie_grens_cents: int = 100_000

    #: Set to True only after checking every figure above against the source.
    verified: bool = False


TAX_YEARS: dict[int, TaxYear] = {
    2026: TaxYear(
        year=2026,
        urencriterium=1225,
        zelfstandigenaftrek_cents=120_000,
        startersaftrek_cents=212_300,  # niet geverifieerd voor 2026
        mkb_winstvrijstelling_pct=Decimal("12.70"),
        box1_brackets=(
            (3_888_300, Decimal("35.75")),
            (7_842_600, Decimal("37.56")),
            (None, Decimal("49.50")),
        ),
        algemene_heffingskorting=(
            (2_973_600, 311_500, Decimal(0), 0),
            (7_842_600, 311_500, Decimal("-6.398"), 2_973_600),
            (None, 0, Decimal(0), 0),
        ),
        arbeidskorting=(
            (1_196_500, 0, Decimal("8.324"), 0),
            (2_584_500, 99_600, Decimal("31.009"), 1_196_500),
            (4_559_200, 530_000, Decimal("1.950"), 2_584_500),
            (13_292_000, 568_500, Decimal("-6.510"), 4_559_200),
            (None, 0, Decimal(0), 0),
        ),
        arbeidskorting_max_cents=568_500,
        zvw_pct=Decimal("4.85"),
        zvw_max_grondslag_cents=7_940_900,
        kor_omzetgrens_cents=2_000_000,
        investeringsgrens_cents=45_000,
        kia_ondergrens_cents=290_100,
        kia_bovengrens_cents=39_823_600,
        kia_pct=Decimal("28"),
        kia_max_cents=2_007_200,
        kilometervergoeding_cents=23,
        verified=True,
    ),
    2025: TaxYear(
        year=2025,
        zelfstandigenaftrek_cents=247_000,
        startersaftrek_cents=212_300,
        mkb_winstvrijstelling_pct=Decimal("12.70"),
        box1_brackets=(
            (3_844_100, Decimal("35.82")),
            (7_681_700, Decimal("37.48")),
            (None, Decimal("49.50")),
        ),
        algemene_heffingskorting=(
            (2_835_500, 306_800, Decimal(0), 0),
            (7_681_700, 306_800, Decimal("-6.337"), 2_835_500),
            (None, 0, Decimal(0), 0),
        ),
        arbeidskorting=(),  # niet ingevuld; 2025 wordt niet meer geschat
        zvw_pct=Decimal("5.26"),
        zvw_max_grondslag_cents=7_586_400,
        kor_omzetgrens_cents=2_000_000,
        investeringsgrens_cents=45_000,
        kia_ondergrens_cents=280_000,
        kilometervergoeding_cents=23,
        verified=False,
    ),
    2024: TaxYear(
        year=2024,
        zelfstandigenaftrek_cents=367_000,
        startersaftrek_cents=212_300,
        mkb_winstvrijstelling_pct=Decimal("13.31"),
        zvw_pct=Decimal("5.32"),
        zvw_max_grondslag_cents=7_138_700,
        kia_ondergrens_cents=255_000,
        kilometervergoeding_cents=23,
        verified=False,
    ),
    2023: TaxYear(
        year=2023,
        zelfstandigenaftrek_cents=507_000,
        startersaftrek_cents=212_300,
        mkb_winstvrijstelling_pct=Decimal("14.00"),
        zvw_pct=Decimal("5.43"),
        zvw_max_grondslag_cents=6_632_400,
        kia_ondergrens_cents=245_600,
        kilometervergoeding_cents=21,
        verified=False,
    ),
}


def tax_year(year: int) -> TaxYear:
    """Parameters for a year, falling back to the most recent year defined.

    The fallback is deliberate: the application must keep working in January before the
    new figures are published. Anything computed from a fallback or unverified year is
    labelled as an estimate in the interface.
    """
    if year in TAX_YEARS:
        return TAX_YEARS[year]
    latest = TAX_YEARS[max(TAX_YEARS)]
    return replace(latest, year=year, verified=False)


def is_estimate(year: int) -> bool:
    """True when the figures for this year have not been verified against the source."""
    return year not in TAX_YEARS or not TAX_YEARS[year].verified


def can_estimate_income_tax(year: int) -> bool:
    """Whether this year has enough data for a full income tax estimate."""
    parameters = tax_year(year)
    return bool(
        parameters.box1_brackets
        and parameters.algemene_heffingskorting
        and parameters.arbeidskorting
    )
