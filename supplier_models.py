"""Phase 11 - typed data models and value parsing for the supplier decision engine.

Missing values are None, never 0. Parsing never raises on bad user input: it returns None and
records a ValidationIssue so the screening engine can treat the item as missing or invalid.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

ENGINE_VERSION = "P11-1.0"
SUPPORTED_MODES = {"road", "rail", "sea", "air", "multimodal"}
REFERENCE_BOUNDARY = "Tank-to-wheel"   # inventory convention (Phase 4 freight factor: direct / tank-to-wheel)
# accepted emission-factor units -> multiplier to kgCO2e per tonne-km
EF_UNITS = {
    "kgco2e/tonne-km": 1.0, "kgco2e/t-km": 1.0, "kgco2e/tkm": 1.0, "kg co2e/tonne-km": 1.0, "kg co2e/t-km": 1.0,
    "kg co2e/tkm": 1.0, "gco2e/tonne-km": 0.001, "gco2e/t-km": 0.001, "gco2e/tkm": 0.001, "g co2e/tonne-km": 0.001,
    "g co2e/t-km": 0.001, "tco2e/tonne-km": 1000.0, "tco2e/t-km": 1000.0,
}
DATA_CLASSES = ("Existing synthetic baseline", "New synthetic assumption", "User-entered", "Calculated output",
                "Missing data", "Project-designed rule", "Reference")


@dataclass
class ValidationIssue:
    level: str          # ERROR | WARN
    where: str
    message: str


class UnitError(ValueError):
    pass


class WeightError(ValueError):
    pass


def parse_number(value, where, issues, *, allow_negative=False, allow_zero=True) -> Optional[float]:
    """Number or None. Blank -> None (missing). Non-numeric / negative -> None + ERROR issue."""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    if isinstance(value, bool):
        issues.append(ValidationIssue("ERROR", where, f"boolean {value!r} is not a number"))
        return None
    try:
        x = float(str(value).replace(",", "")) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        issues.append(ValidationIssue("ERROR", where, f"non-numeric value {value!r} treated as missing"))
        return None
    if x != x or x in (float("inf"), float("-inf")):
        issues.append(ValidationIssue("ERROR", where, f"invalid number {value!r} treated as missing"))
        return None
    if x < 0 and not allow_negative:
        issues.append(ValidationIssue("ERROR", where, f"negative value {x} is invalid; treated as missing"))
        return None
    if x == 0 and not allow_zero:
        issues.append(ValidationIssue("WARN", where, "zero value"))
    return x


def normalise_ef(value: Optional[float], unit: Optional[str]) -> Optional[float]:
    """Emission factor in kgCO2e per tonne-km. Raises UnitError for an unsupported unit."""
    if value is None:
        return None
    if unit is None or not str(unit).strip():
        raise UnitError("emission-factor unit missing")
    key = str(unit).strip().lower().replace("₂", "2").replace(".", "-")
    key = key.replace("tonne km", "tonne-km")
    if key not in EF_UNITS:
        raise UnitError(f"unsupported emission-factor unit '{unit}' (expected kgCO2e/tonne-km)")
    return value * EF_UNITS[key]


def text(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


@dataclass
class Supplier:
    supplier_id: str
    name: Optional[str]
    relationship: Optional[str]
    inventory_supplier_id: Optional[str]
    mode: Optional[str]
    fuel_technology: Optional[str]
    geography: Optional[str]
    materiality: Optional[str]
    data_class: Optional[str]
    notes: Optional[str] = None

    @property
    def is_existing(self) -> bool:
        return (self.relationship or "").lower().startswith("existing")


@dataclass
class Lane:
    lane_id: str
    name: Optional[str]
    origin: Optional[str]
    destination: Optional[str]
    mode: Optional[str]
    cargo_type: Optional[str]
    required_capacity_t: Optional[float]
    required_on_time_pct: Optional[float]
    period: Optional[str]
    incumbent_offer_id: Optional[str]
    data_class: Optional[str]


@dataclass
class EmissionFactor:
    ef_id: str
    offer_id: str
    value_kg_per_tkm: Optional[float]
    unit_raw: Optional[str]
    method: Optional[str]
    boundary: Optional[str]
    gas_coverage: Optional[str]
    source: Optional[str]
    reference_year: Optional[str]
    verification: Optional[str]
    linked_factor_id: Optional[str]
    data_class: Optional[str]
    unit_valid: bool = True
    note: str = ""


@dataclass
class Offer:
    offer_id: str
    supplier_id: str
    lane_id: str
    role: Optional[str]
    mass_t: Optional[float]
    distance_km: Optional[float]
    period: Optional[str]
    period_months: Optional[float]
    capacity_t: Optional[float]
    cargo_types: Optional[str]
    origin: Optional[str]
    destination: Optional[str]
    activity_source: Optional[str]
    data_class: Optional[str]
    ef: Optional[EmissionFactor] = None
    annual_cost: Optional[float] = None
    recurring_cost: Optional[float] = None
    switching_cost: Optional[float] = None
    onboarding_cost: Optional[float] = None
    exit_cost: Optional[float] = None
    on_time_pct: Optional[float] = None
    cost_source: Optional[str] = None
    activity_invalid: bool = False   # negative / non-numeric activity was entered

    @property
    def tonne_km(self) -> Optional[float]:
        if self.mass_t is None or self.distance_km is None:
            return None
        return self.mass_t * self.distance_km

    @property
    def emissions_t(self) -> Optional[float]:
        if self.tonne_km is None or self.ef is None or self.ef.value_kg_per_tkm is None:
            return None
        return self.tonne_km * self.ef.value_kg_per_tkm / 1000.0


@dataclass
class ScreeningEvidence:
    offer_id: str
    check_no: int
    check: str
    category: str
    status: Optional[str]
    evidence: Optional[str]


@dataclass
class Maturity:
    supplier_id: str
    indicators: Dict[str, Optional[float]]
    dq: Dict[str, Optional[str]]
    source: Optional[str]
    data_class: Optional[str]


@dataclass
class Settings:
    discount_rate: float = 0.05
    horizon_years: int = 10
    implementation_delay_years: int = 0
    substitution_share: float = 1.0
    willingness_to_pay: Optional[float] = None
    verification_mandatory: bool = False
    cost_scales_with_demand: bool = True


@dataclass
class MatrixRules:
    impact_threshold: float = 50.0
    maturity_threshold: float = 50.0
    w_emissions_share: float = 0.5
    w_volume_share: float = 0.3
    w_materiality: float = 0.2
    materiality_scores: Dict[str, float] = field(default_factory=lambda: {"Critical": 100.0, "Standard": 50.0, "Minor": 0.0})
    min_maturity_indicators: int = 5
    quadrants: Dict[str, dict] = field(default_factory=dict)


@dataclass
class ScoringConfig:
    weights: Dict[str, float]
    carbon_low: float = 0.05
    carbon_high: float = 0.15
    cost_band: float = 0.20
    reliability_low: float = 90.0
    reliability_high: float = 100.0
    methods: Dict[str, str] = field(default_factory=dict)


@dataclass
class UncertaintyVar:
    variable: str
    applies_to: Optional[str]
    low: float
    base: float
    high: float
    unit: Optional[str]
    favourable: Optional[str]
    note: Optional[str]


@dataclass
class ActionTemplate:
    trigger: str
    action: str
    role: Optional[str]
    days: Optional[float]
    evidence: Optional[str]
    success: Optional[str]
    verification: Optional[str]


@dataclass
class Phase11Data:
    suppliers: Dict[str, Supplier]
    lanes: Dict[str, Lane]
    offers: Dict[str, Offer]
    screening: Dict[str, List[ScreeningEvidence]]
    maturity: Dict[str, Maturity]
    settings: Settings
    matrix: MatrixRules
    scoring: ScoringConfig
    uncertainty: Dict[str, UncertaintyVar]
    action_templates: List[ActionTemplate]
    monitoring: List[dict]
    sources: List[dict]
    validation_cases: Dict[str, Optional[float]]
    issues: List[ValidationIssue]
    source_path: str
    input_version: str

    def supplier_offers(self, supplier_id):
        return [o for o in self.offers.values() if o.supplier_id == supplier_id]

    def lane_offers(self, lane_id):
        return [o for o in self.offers.values() if o.lane_id == lane_id]
