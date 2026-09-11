"""BTW treatments and their mapping onto the rubrieken of the aangifte omzetbelasting.

This module is the single place where "what kind of BTW is this?" is decided. Every
other part of the application refers to a treatment by name and never hard-codes a
percentage or a rubriek, so that when a rate changes there is exactly one file to edit.

Rates are in tenths of a percent (permille): 21% is 210, 9% is 90.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Rubriek(str, Enum):
    """The boxes on the Belastingdienst's aangifte omzetbelasting."""

    R1A = "1a"  # Leveringen/diensten belast met hoog tarief
    R1B = "1b"  # Leveringen/diensten belast met laag tarief
    R1C = "1c"  # Leveringen/diensten belast met overige tarieven, behalve 0%
    R1D = "1d"  # Privegebruik
    R1E = "1e"  # Leveringen/diensten belast met 0% of niet bij u belast
    R2A = "2a"  # Leveringen/diensten waarbij de heffing naar u is verlegd
    R3A = "3a"  # Leveringen naar landen buiten de EU (uitvoer)
    R3B = "3b"  # Leveringen naar of diensten in landen binnen de EU
    R3C = "3c"  # Installatie/afstandsverkopen binnen de EU
    R4A = "4a"  # Leveringen/diensten uit landen buiten de EU
    R4B = "4b"  # Leveringen/diensten uit landen binnen de EU
    R5A = "5a"  # Verschuldigde omzetbelasting (totaal)
    R5B = "5b"  # Voorbelasting


RUBRIEK_LABELS: dict[Rubriek, str] = {
    Rubriek.R1A: "Leveringen/diensten belast met hoog tarief",
    Rubriek.R1B: "Leveringen/diensten belast met laag tarief",
    Rubriek.R1C: "Leveringen/diensten belast met overige tarieven, behalve 0%",
    Rubriek.R1D: "Privegebruik",
    Rubriek.R1E: "Leveringen/diensten belast met 0% of niet bij u belast",
    Rubriek.R2A: "Leveringen/diensten waarbij de heffing naar u is verlegd",
    Rubriek.R3A: "Leveringen naar landen buiten de EU (uitvoer)",
    Rubriek.R3B: "Leveringen naar of diensten in landen binnen de EU",
    Rubriek.R3C: "Installatie/afstandsverkopen binnen de EU",
    Rubriek.R4A: "Leveringen/diensten uit landen buiten de EU",
    Rubriek.R4B: "Leveringen/diensten uit landen binnen de EU",
    Rubriek.R5A: "Verschuldigde omzetbelasting",
    Rubriek.R5B: "Voorbelasting",
}


@dataclass(frozen=True)
class TreatmentSpec:
    code: str
    label: str
    rate_permille: int
    rubriek: Rubriek
    #: Dutch name of the rate as it appears in an invoice totals block ("Btw hoog 21%").
    tarief_naam: str | None = None
    #: Reverse-charge style: BTW is owed by the recipient rather than charged on the
    #: invoice. For purchases this means self-assessment.
    reverse_charge: bool = False
    #: Belongs on the ICP-opgaaf (intracommunautaire prestaties).
    icp: bool = False
    #: The client's BTW number is legally required on the invoice.
    requires_customer_vat_number: bool = False
    #: Sentence that must appear on the invoice for this treatment.
    invoice_note: str | None = None


class SalesVat(str, Enum):
    """BTW treatment of a sales invoice line."""

    HOOG_21 = "hoog_21"
    LAAG_9 = "laag_9"
    NUL = "nul"
    VRIJGESTELD = "vrijgesteld"
    VERLEGD_BINNENLAND = "verlegd_binnenland"
    EU_DIENSTEN = "eu_diensten"
    EU_GOEDEREN = "eu_goederen"
    EU_AFSTANDSVERKOOP = "eu_afstandsverkoop"
    EXPORT_BUITEN_EU = "export_buiten_eu"
    PRIVEGEBRUIK = "privegebruik"


SALES_SPECS: dict[SalesVat, TreatmentSpec] = {
    SalesVat.HOOG_21: TreatmentSpec("hoog_21", "21% (hoog)", 210, Rubriek.R1A, "hoog"),
    SalesVat.LAAG_9: TreatmentSpec("laag_9", "9% (laag)", 90, Rubriek.R1B, "laag"),
    SalesVat.NUL: TreatmentSpec("nul", "0%", 0, Rubriek.R1E),
    # Vrijgestelde omzet in 1e is genuinely contested. The rubriek is worded "belast met
    # 0% of niet bij u belast", and vrijgestelde prestaties are strictly neither: they
    # fall outside the heffing rather than being taxed at zero. Sources disagree, and
    # the Belastingdienst's own toelichting does not settle it in either direction.
    #
    # Reporting it in 1e is the common practice in bookkeeping software and costs
    # nothing (there is no BTW attached either way, so no rubriek total changes), so
    # that is what this does -- but the interface warns when it is used, because for a
    # consultancy like mine an "exempt" invoice is almost always a mistake for a
    # 0%-tarief or a verlegging.
    SalesVat.VRIJGESTELD: TreatmentSpec(
        "vrijgesteld", "Vrijgesteld van btw (let op)", 0, Rubriek.R1E
    ),
    SalesVat.VERLEGD_BINNENLAND: TreatmentSpec(
        "verlegd_binnenland",
        "Btw verlegd (binnenland)",
        0,
        Rubriek.R1E,
        reverse_charge=True,
        requires_customer_vat_number=True,
        invoice_note="Btw verlegd",
    ),
    SalesVat.EU_DIENSTEN: TreatmentSpec(
        "eu_diensten",
        "Diensten binnen de EU (btw verlegd)",
        0,
        Rubriek.R3B,
        reverse_charge=True,
        icp=True,
        requires_customer_vat_number=True,
        invoice_note="Btw verlegd - intracommunautaire dienst",
    ),
    SalesVat.EU_GOEDEREN: TreatmentSpec(
        "eu_goederen",
        "Intracommunautaire levering (goederen)",
        0,
        Rubriek.R3B,
        reverse_charge=True,
        icp=True,
        requires_customer_vat_number=True,
        invoice_note="Btw verlegd - intracommunautaire levering",
    ),
    SalesVat.EU_AFSTANDSVERKOOP: TreatmentSpec(
        "eu_afstandsverkoop", "Afstandsverkoop binnen de EU", 0, Rubriek.R3C
    ),
    SalesVat.EXPORT_BUITEN_EU: TreatmentSpec(
        "export_buiten_eu",
        "Uitvoer buiten de EU",
        0,
        Rubriek.R3A,
        invoice_note="Uitvoer - 0% btw",
    ),
    SalesVat.PRIVEGEBRUIK: TreatmentSpec("privegebruik", "Privegebruik", 210, Rubriek.R1D),
}


class PurchaseVat(str, Enum):
    """BTW treatment of a purchase invoice or receipt."""

    BINNENLAND_21 = "binnenland_21"
    BINNENLAND_9 = "binnenland_9"
    BINNENLAND_0 = "binnenland_0"
    GEEN_BTW = "geen_btw"
    VERLEGD_BINNENLAND = "verlegd_binnenland"
    EU_VERWERVING = "eu_verwerving"
    IMPORT_BUITEN_EU = "import_buiten_eu"


@dataclass(frozen=True)
class PurchaseSpec:
    code: str
    label: str
    rate_permille: int
    #: Where the self-assessed BTW is declared as owed. None means nothing is owed;
    #: the supplier charged the BTW and it is only deductible.
    owed_rubriek: Rubriek | None = None
    #: BTW on this purchase can be reclaimed as voorbelasting (rubriek 5b), subject to
    #: the deductible percentage recorded on the expense itself.
    deductible: bool = True


PURCHASE_SPECS: dict[PurchaseVat, PurchaseSpec] = {
    PurchaseVat.BINNENLAND_21: PurchaseSpec("binnenland_21", "21% (hoog)", 210),
    PurchaseVat.BINNENLAND_9: PurchaseSpec("binnenland_9", "9% (laag)", 90),
    PurchaseVat.BINNENLAND_0: PurchaseSpec("binnenland_0", "0%", 0),
    PurchaseVat.GEEN_BTW: PurchaseSpec("geen_btw", "Geen btw / vrijgesteld", 0, deductible=False),
    PurchaseVat.VERLEGD_BINNENLAND: PurchaseSpec(
        "verlegd_binnenland",
        "Btw naar mij verlegd (binnenland)",
        210,
        owed_rubriek=Rubriek.R2A,
    ),
    PurchaseVat.EU_VERWERVING: PurchaseSpec(
        "eu_verwerving",
        "Verwerving uit een EU-land",
        210,
        owed_rubriek=Rubriek.R4B,
    ),
    PurchaseVat.IMPORT_BUITEN_EU: PurchaseSpec(
        "import_buiten_eu",
        "Invoer van buiten de EU",
        210,
        owed_rubriek=Rubriek.R4A,
    ),
}


def sales_spec(treatment: SalesVat | str) -> TreatmentSpec:
    return SALES_SPECS[SalesVat(treatment)]


def purchase_spec(treatment: PurchaseVat | str) -> PurchaseSpec:
    return PURCHASE_SPECS[PurchaseVat(treatment)]


#: Treatments where nothing is charged on the invoice but a note is legally required.
def invoice_notes(treatments: set[SalesVat]) -> list[str]:
    notes = []
    for treatment in treatments:
        note = sales_spec(treatment).invoice_note
        if note and note not in notes:
            notes.append(note)
    return notes


EU_COUNTRY_CODES = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR",
    "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK",
}


def is_eu(country_code: str) -> bool:
    return (country_code or "").strip().upper() in EU_COUNTRY_CODES
