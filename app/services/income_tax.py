"""Indicative inkomstenbelasting for an IB-ondernemer, to decide what to set aside.

This is an estimate, not an aangifte and not advice. It models the chain the
Belastingdienst applies to winst uit onderneming for someone under AOW age:

    winst uit onderneming
      - zelfstandigenaftrek        (only when the urencriterium is met)
      - startersaftrek             (optional, max 3x in the first 5 years)
    = winst na ondernemersaftrek
      - MKB-winstvrijstelling      (a percentage of the line above)
    = belastbare winst
      -> box 1 tarief in schijven
      - algemene heffingskorting   (tapers with verzamelinkomen)
      - arbeidskorting             (builds up, then tapers with arbeidsinkomen)
    = inkomstenbelasting           (never below zero)
      + Zvw-bijdrage               (a percentage of belastbare winst, capped)
    = totaal te reserveren

What this deliberately does NOT model, and why the number stays an estimate:
  * Other household income, a fiscal partner, and the partner's income, all of which
    move the heffingskortingen.
  * Aftrekposten outside the business: mortgage interest, giften, pensioen/lijfrente.
  * Box 2 and box 3.
  * The tariefsaanpassing: above the top bracket, deductions such as the
    MKB-winstvrijstelling only count against 37,56% rather than 49,50%. That makes this
    estimate slightly optimistic for profits above roughly EUR 78.000.
  * Heffingskortingen are treated as non-refundable, floored at the tax due.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app import money
from app.taxyears import TaxYear, can_estimate_income_tax, tax_year


@dataclass(frozen=True)
class Regel:
    """One line of the calculation, so the interface can show its working."""

    label: str
    bedrag_cents: int
    toelichting: str = ""
    #: Negative lines are deductions, shown as such.
    is_aftrek: bool = False


@dataclass(frozen=True)
class Schatting:
    jaar: int
    winst_cents: int
    ondernemersaftrek_cents: int
    mkb_vrijstelling_cents: int
    belastbare_winst_cents: int
    box1_belasting_cents: int
    algemene_heffingskorting_cents: int
    arbeidskorting_cents: int
    inkomstenbelasting_cents: int
    zvw_cents: int
    totaal_cents: int
    regels: list[Regel]
    urencriterium_gehaald: bool
    is_schatting: bool
    waarschuwingen: list[str]

    @property
    def effectief_tarief_pct(self) -> Decimal:
        """Total burden as a percentage of profit -- the number worth internalising."""
        if self.winst_cents <= 0:
            return Decimal(0)
        return (
            Decimal(self.totaal_cents) / Decimal(self.winst_cents) * 100
        ).quantize(Decimal("0.1"))


def _pct(bedrag_cents: int, percentage: Decimal) -> int:
    return money.round_half_up(Decimal(bedrag_cents) * percentage / 100)


def _bracket_tax(grondslag_cents: int, brackets: tuple) -> int:
    """Progressive tax: each bracket's rate applies only to the slice inside it."""
    if grondslag_cents <= 0 or not brackets:
        return 0
    belasting = Decimal(0)
    ondergrens = 0
    for bovengrens, tarief in brackets:
        if bovengrens is None:
            schijf = max(grondslag_cents - ondergrens, 0)
        else:
            schijf = max(min(grondslag_cents, bovengrens) - ondergrens, 0)
            ondergrens = bovengrens
        belasting += Decimal(schijf) * tarief / 100
        if bovengrens is not None and grondslag_cents <= bovengrens:
            break
    return money.round_half_up(belasting)


def _credit(inkomen_cents: int, brackets: tuple) -> int:
    """Evaluate a heffingskorting table: base + percentage x (income - threshold)."""
    if not brackets:
        return 0
    for bovengrens, basis_cents, percentage, drempel_cents in brackets:
        if bovengrens is None or inkomen_cents <= bovengrens:
            bedrag = Decimal(basis_cents) + Decimal(inkomen_cents - drempel_cents) * percentage / 100
            return max(money.round_half_up(bedrag), 0)
    return 0


def ondernemersaftrek(
    parameters: TaxYear, urencriterium_gehaald: bool, starter: bool
) -> tuple[int, list[Regel]]:
    """Zelfstandigenaftrek and startersaftrek, both gated on the urencriterium."""
    regels: list[Regel] = []
    if not urencriterium_gehaald:
        # Shown as an explicit zero rather than left out, so the table does not look
        # like a step was silently skipped.
        regels.append(
            Regel(
                "Zelfstandigenaftrek",
                0,
                f"vervalt: je haalt het urencriterium van {parameters.urencriterium} "
                "uur niet",
                is_aftrek=True,
            )
        )
        return 0, regels

    totaal = parameters.zelfstandigenaftrek_cents
    regels.append(
        Regel(
            "Zelfstandigenaftrek",
            -parameters.zelfstandigenaftrek_cents,
            f"je haalt het urencriterium van {parameters.urencriterium} uur",
            is_aftrek=True,
        )
    )
    if starter:
        totaal += parameters.startersaftrek_cents
        regels.append(
            Regel(
                "Startersaftrek",
                -parameters.startersaftrek_cents,
                "maximaal 3 keer in de eerste 5 jaar",
                is_aftrek=True,
            )
        )
    return totaal, regels


def estimate(
    winst_cents: int,
    jaar: int,
    *,
    urencriterium_gehaald: bool = True,
    starter: bool = False,
) -> Schatting:
    """What to set aside on a given profit. See the module docstring for the caveats."""
    parameters = tax_year(jaar)
    waarschuwingen: list[str] = []
    regels: list[Regel] = [Regel("Winst uit onderneming", winst_cents)]

    if not can_estimate_income_tax(jaar):
        waarschuwingen.append(
            f"Voor {jaar} staan de schijven en heffingskortingen niet in taxyears.py; "
            "er kan geen volledige schatting gemaakt worden."
        )

    winst_cents = max(winst_cents, 0)

    # -- Ondernemersaftrek ------------------------------------------------------------
    aftrek, aftrek_regels = ondernemersaftrek(parameters, urencriterium_gehaald, starter)
    aftrek = min(aftrek, winst_cents)  # kan de winst niet negatief maken
    regels.extend(aftrek_regels)
    if not urencriterium_gehaald:
        waarschuwingen.append(
            f"Zonder het urencriterium ({parameters.urencriterium} uur) vervalt de "
            "zelfstandigenaftrek. Dat scheelt honderden euro's."
        )
    na_aftrek = winst_cents - aftrek
    regels.append(Regel("Winst na ondernemersaftrek", na_aftrek))

    # -- MKB-winstvrijstelling --------------------------------------------------------
    mkb = _pct(na_aftrek, parameters.mkb_winstvrijstelling_pct)
    regels.append(
        Regel(
            "MKB-winstvrijstelling",
            -mkb,
            f"{parameters.mkb_winstvrijstelling_pct}% van de winst na ondernemersaftrek",
            is_aftrek=True,
        )
    )
    belastbare_winst = na_aftrek - mkb
    regels.append(Regel("Belastbare winst", belastbare_winst))

    # -- Box 1 ------------------------------------------------------------------------
    box1 = _bracket_tax(belastbare_winst, parameters.box1_brackets)
    regels.append(Regel("Inkomstenbelasting box 1", box1, "volgens de schijven"))

    ahk = _credit(belastbare_winst, parameters.algemene_heffingskorting)
    arbeidskorting = _credit(belastbare_winst, parameters.arbeidskorting)
    if parameters.arbeidskorting_max_cents:
        arbeidskorting = min(arbeidskorting, parameters.arbeidskorting_max_cents)

    # Heffingskortingen are not refundable: they can bring the tax to zero but no
    # further. Showing the full entitlement as a deduction produces a table that does
    # not add up -- at a low profit the credits are many times the tax due -- so what
    # is shown is the part actually used, with the entitlement in the explanation.
    recht_op = ahk + arbeidskorting
    verrekend = min(recht_op, box1)
    inkomstenbelasting = box1 - verrekend

    if recht_op > verrekend:
        toelichting = (
            f"je hebt recht op {money.format_euro(recht_op)} "
            f"({money.format_euro(ahk)} algemeen + {money.format_euro(arbeidskorting)} "
            "arbeidskorting), maar een heffingskorting wordt niet uitbetaald: er gaat "
            "niet meer af dan je aan belasting verschuldigd bent"
        )
    else:
        toelichting = (
            f"{money.format_euro(ahk)} algemene heffingskorting + "
            f"{money.format_euro(arbeidskorting)} arbeidskorting"
        )
    regels.append(Regel("Heffingskortingen", -verrekend, toelichting, is_aftrek=True))
    regels.append(Regel("Inkomstenbelasting", inkomstenbelasting))

    # -- Zvw --------------------------------------------------------------------------
    zvw_grondslag = min(belastbare_winst, parameters.zvw_max_grondslag_cents)
    zvw = _pct(zvw_grondslag, parameters.zvw_pct)
    regels.append(
        Regel(
            "Bijdrage Zorgverzekeringswet",
            zvw,
            f"{parameters.zvw_pct}% over {money.format_euro(zvw_grondslag)}",
        )
    )

    totaal = inkomstenbelasting + zvw
    regels.append(Regel("Totaal over het hele jaar", totaal))

    if belastbare_winst > (parameters.box1_brackets[-2][0] if len(parameters.box1_brackets) > 1 else 0):
        waarschuwingen.append(
            "Boven de hoogste schijf telt de MKB-winstvrijstelling maar tegen 37,56% mee "
            "(tariefsaanpassing). Deze schatting houdt daar geen rekening mee en valt "
            "daardoor iets te laag uit."
        )

    return Schatting(
        jaar=jaar,
        winst_cents=winst_cents,
        ondernemersaftrek_cents=aftrek,
        mkb_vrijstelling_cents=mkb,
        belastbare_winst_cents=belastbare_winst,
        box1_belasting_cents=box1,
        algemene_heffingskorting_cents=ahk,
        arbeidskorting_cents=arbeidskorting,
        inkomstenbelasting_cents=inkomstenbelasting,
        zvw_cents=zvw,
        totaal_cents=totaal,
        regels=regels,
        urencriterium_gehaald=urencriterium_gehaald,
        is_schatting=True,
        waarschuwingen=waarschuwingen,
    )


def annualise(winst_tot_nu_cents: int, dagen_verstreken: int, dagen_in_jaar: int = 365) -> int:
    """Extrapolate year-to-date profit to a full year.

    The reservation has to be based on the expected annual profit, because both the
    brackets and the heffingskortingen are annual: reserving on a quarter of the profit
    and multiplying by four gets the progression wrong in both directions.
    """
    if dagen_verstreken <= 0:
        return 0
    return money.round_half_up(
        Decimal(winst_tot_nu_cents) * Decimal(dagen_in_jaar) / Decimal(dagen_verstreken)
    )
