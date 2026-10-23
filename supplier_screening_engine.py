"""Phase 11 - supplier screening (14 checks), eligibility, data quality and service equivalence.

Eligibility rules (project-designed, applied in this order):
  1. Gate checks 1-2 (identity, legal/safety): Fail -> INELIGIBLE; Missing -> INSUFFICIENT EVIDENCE.
  2. Capacity (3) or comparable route/specification (4) Fail -> INELIGIBLE for this service.
  3. Material checks 5-8, 10, 11 Missing or invalid -> INSUFFICIENT EVIDENCE (never silently passed).
  4. Boundary check 9 Fail -> CONDITIONALLY ELIGIBLE with the carbon comparison blocked.
  5. Verification (12) Missing -> CONDITIONALLY ELIGIBLE (confidence enhancement), unless the
     organisation's policy makes verification mandatory -> INSUFFICIENT EVIDENCE.
  6. History (13) / willingness (14) not Pass -> CONDITIONALLY ELIGIBLE.
  7. Otherwise ELIGIBLE.
Checks 3-10 are derived from the data ('Auto'): a value the data do not support can never pass.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from supplier_models import REFERENCE_BOUNDARY, SUPPORTED_MODES, Phase11Data

CHECKS = [
    (1, "Supplier identity and service description", "Gate"),
    (2, "Legal and transportation safety requirements", "Gate"),
    (3, "Required transport capacity", "Auto"),
    (4, "Comparable routes and freight specifications", "Auto"),
    (5, "Freight mass and distance", "Auto"),
    (6, "Reporting period", "Auto"),
    (7, "Calculation methodology (fuel- or distance-based)", "Auto"),
    (8, "Emission-factor source and units", "Auto"),
    (9, "Accounting boundaries", "Auto"),
    (10, "Contract price and relevant cost information", "Auto"),
    (11, "Supporting evidence", "Material"),
    (12, "Third-party verification", "Enhancement"),
    (13, "Historical data completeness", "Enhancement"),
    (14, "Willingness to improve disclosure", "Enhancement"),
]
ELIGIBLE, CONDITIONAL, INSUFFICIENT, INELIGIBLE = ("Eligible", "Conditionally eligible", "Insufficient evidence",
                                                   "Ineligible")
DQ_SCORE = {"High": 100.0, "Medium": 60.0, "Low": 20.0, "Missing": 0.0}
DQ_LABELS = {"dq_completeness": "Completeness", "dq_temporal": "Temporal representativeness",
             "dq_geographic": "Geographic representativeness", "dq_technological": "Technological representativeness",
             "dq_methodological": "Methodological consistency", "dq_evidence_provenance": "Evidence and provenance",
             "dq_verification": "Verification status"}


@dataclass
class CheckResult:
    check_no: int
    check: str
    category: str
    status: str            # Pass | Fail | Missing | N/A
    derived: bool
    reason: str


@dataclass
class ScreeningResult:
    offer_id: str
    supplier_id: str
    lane_id: str
    eligibility: str
    checks: List[CheckResult]
    blocking_reasons: List[str] = field(default_factory=list)
    missing_material: List[str] = field(default_factory=list)
    conditions: List[str] = field(default_factory=list)
    carbon_comparable: bool = True
    cost_available: bool = True

    @property
    def selectable(self):
        return self.eligibility in (ELIGIBLE, CONDITIONAL)


def _same(a, b):
    return a is not None and b is not None and a.strip().lower() == b.strip().lower()


def derived_checks(o, lane) -> Dict[int, CheckResult]:
    out = {}

    def put(no, status, reason):
        name, cat = CHECKS[no - 1][1], CHECKS[no - 1][2]
        out[no] = CheckResult(no, name, cat, status, True, reason)

    # 3 capacity
    req = lane.required_capacity_t if lane else None
    if o.capacity_t is None or req is None:
        put(3, "Missing", "offered or required capacity not stated")
    else:
        put(3, "Pass" if o.capacity_t >= req else "Fail", f"offered {o.capacity_t:,.0f} t/yr vs required {req:,.0f} t/yr")
    # 4 comparable route / specification
    if lane is None:
        put(4, "Fail", "lane not defined")
    else:
        problems, unknown = [], []
        if lane.mode and lane.mode not in SUPPORTED_MODES:
            problems.append(f"unsupported lane mode '{lane.mode}'")
        for label, a, b in (("origin", o.origin, lane.origin), ("destination", o.destination, lane.destination),
                            ("cargo", o.cargo_types, lane.cargo_type)):
            if a is None or b is None:
                unknown.append(label)
            elif label == "cargo" and b.lower() not in a.lower():
                problems.append(f"cargo '{a}' does not cover '{b}'")
            elif label != "cargo" and not _same(a, b):
                problems.append(f"{label} '{a}' differs from lane '{b}'")
        if problems:
            put(4, "Fail", "; ".join(problems))
        elif unknown:
            put(4, "Missing", "not stated: " + ", ".join(unknown))
        else:
            put(4, "Pass", f"{lane.origin} -> {lane.destination}, {lane.cargo_type}")
    # 5 mass and distance
    if o.activity_invalid:
        put(5, "Fail", "invalid (negative or non-numeric) mass or distance entered")
    elif o.mass_t is None or o.distance_km is None:
        put(5, "Missing", "freight mass and/or distance not provided")
    elif o.mass_t == 0 or o.distance_km == 0:
        put(5, "Fail", "zero activity: no comparable service volume")
    else:
        put(5, "Pass", f"{o.mass_t:,.0f} t x {o.distance_km:,.0f} km = {o.tonne_km:,.0f} t-km")
    # 6 reporting period
    if o.period is None:
        put(6, "Missing", "reporting period not stated")
    elif lane and lane.period and o.period != lane.period:
        put(6, "Fail", f"period {o.period} incompatible with lane period {lane.period}")
    else:
        put(6, "Pass", f"period {o.period}")
    ef = o.ef
    # 7 methodology
    if ef is None or ef.method is None:
        put(7, "Missing", "calculation methodology not documented")
    else:
        put(7, "Pass", ef.method + (" (spend-based: low quality)" if "spend" in ef.method.lower() else ""))
    # 8 factor source and units
    if ef is None or (ef.value_kg_per_tkm is None and ef.unit_valid):
        put(8, "Missing", "emission factor not provided")
    elif not ef.unit_valid:
        put(8, "Fail", f"unsupported unit '{ef.unit_raw}'")
    elif ef.source is None:
        put(8, "Missing", "emission-factor source not documented")
    else:
        put(8, "Pass", f"{ef.value_kg_per_tkm:g} kgCO2e/t-km; {ef.source}")
    # 9 boundary
    if ef is None or ef.boundary is None:
        put(9, "Missing", "accounting boundary not stated")
    elif not _same(ef.boundary, REFERENCE_BOUNDARY):
        put(9, "Fail", f"boundary '{ef.boundary}' inconsistent with inventory convention '{REFERENCE_BOUNDARY}'")
    elif ef.gas_coverage and ef.gas_coverage.upper() != "CO2E":
        put(9, "Fail", f"gas coverage '{ef.gas_coverage}' is not CO2e")
    else:
        put(9, "Pass", f"{ef.boundary}, {ef.gas_coverage or 'CO2e'}")
    # 10 cost
    if o.annual_cost is None:
        put(10, "Missing", "annual contract cost not provided")
    else:
        put(10, "Pass", f"SAR {o.annual_cost:,.0f}/yr")
    return out


def screen_offer(data: Phase11Data, offer_id: str) -> ScreeningResult:
    o = data.offers[offer_id]
    lane = data.lanes.get(o.lane_id)
    der = derived_checks(o, lane)
    ev = {e.check_no: e for e in data.screening.get(offer_id, [])}
    checks = []
    for no, name, cat in CHECKS:
        if no in der:
            checks.append(der[no])
        else:
            e = ev.get(no)
            st = e.status if e and e.status in ("Pass", "Fail", "Missing", "N/A") else "Missing"
            checks.append(CheckResult(no, name, cat, st, False, (e.evidence if e and e.evidence else
                                                                  "no evidence recorded" if st == "Missing" else "")))
    c = {x.check_no: x for x in checks}
    res = ScreeningResult(offer_id, o.supplier_id, o.lane_id, ELIGIBLE, checks)
    for no in (1, 2):
        if c[no].status == "Fail":
            res.blocking_reasons.append(f"check {no} failed: {c[no].check} ({c[no].reason})")
        elif c[no].status == "Missing":
            res.missing_material.append(f"check {no}: {c[no].check}")
    for no in (3, 4):
        if c[no].status == "Fail":
            res.blocking_reasons.append(f"check {no} failed: {c[no].check} ({c[no].reason})")
        elif c[no].status == "Missing":
            res.missing_material.append(f"check {no}: {c[no].check} ({c[no].reason})")
    for no in (5, 6, 7, 8, 10, 11):
        if c[no].status in ("Missing", "Fail"):
            res.missing_material.append(f"check {no}: {c[no].check} ({c[no].reason})")
    if c[9].status == "Fail":
        res.carbon_comparable = False
        res.conditions.append(f"carbon comparison blocked: {c[9].reason}")
    elif c[9].status == "Missing":
        res.missing_material.append(f"check 9: {c[9].check} ({c[9].reason})")
    if c[8].status != "Pass" or c[5].status != "Pass":
        res.carbon_comparable = False
    res.cost_available = c[10].status == "Pass"
    if c[12].status != "Pass":
        if data.settings.verification_mandatory:
            res.missing_material.append("check 12: third-party verification (mandatory under organisational policy)")
        else:
            res.conditions.append("no third-party verification (confidence enhancement only)")
    for no in (13, 14):
        if c[no].status != "Pass":
            res.conditions.append(f"check {no} {c[no].check}: {c[no].status}")
    if res.blocking_reasons:
        res.eligibility = INELIGIBLE
    elif res.missing_material:
        res.eligibility = INSUFFICIENT
    elif res.conditions or not res.carbon_comparable:
        res.eligibility = CONDITIONAL
    return res


def screen_all(data: Phase11Data) -> Dict[str, ScreeningResult]:
    return {oid: screen_offer(data, oid) for oid in data.offers}


@dataclass
class DataQuality:
    supplier_id: str
    dimensions: Dict[str, Optional[str]]
    score: Optional[float]
    assessed: int
    usable_estimate: bool
    note: str


def data_quality(data: Phase11Data, supplier_id: str) -> DataQuality:
    m = data.maturity.get(supplier_id)
    dims = {k: (m.dq.get(k) if m else None) for k in DQ_LABELS}
    vals = [DQ_SCORE[v] for v in dims.values() if v is not None]
    score = sum(vals) / len(vals) if len(vals) == len(dims) else None
    offs = data.supplier_offers(supplier_id)
    usable = any(o.emissions_t is not None for o in offs)
    note = ("Unverified but documented estimate: usable with its uncertainty (never treated as zero)"
            if usable and dims.get("dq_verification") in ("Low", "Missing") else
            "No usable emissions estimate: emissions UNAVAILABLE (not zero)" if not usable else "")
    return DataQuality(supplier_id, dims, score, len(vals), usable, note)


@dataclass
class Equivalence:
    lane_id: str
    current_offer: str
    alternative_offer: str
    equivalent: bool
    limitations: List[str]
    substitutable_tonne_km: Optional[float]


def equivalence(data: Phase11Data, current_id: str, alternative_id: str, share: float = 1.0) -> Equivalence:
    """Two offers are substitutes only for the same lane requirements (functional unit: tonne-km of that service)."""
    cur, alt = data.offers[current_id], data.offers[alternative_id]
    lim = []
    if cur.lane_id != alt.lane_id:
        lim.append(f"different lanes ({cur.lane_id} vs {alt.lane_id}): services are not substitutes")
    lane = data.lanes.get(cur.lane_id)
    da = derived_checks(alt, lane)
    for no in (3, 4, 6):
        if da[no].status != "Pass":
            lim.append(f"alternative check {no} {da[no].check}: {da[no].status} ({da[no].reason})")
    if cur.tonne_km is None:
        lim.append("current activity unknown: equivalent demand cannot be defined")
    if alt.tonne_km is None:
        lim.append("alternative activity not stated")
    elif cur.tonne_km is not None and alt.tonne_km + 1e-9 < cur.tonne_km * share:
        lim.append(f"alternative covers {alt.tonne_km:,.0f} t-km, less than the {cur.tonne_km * share:,.0f} t-km to substitute")
    if not 0 < share <= 1:
        lim.append(f"substitution share {share} outside (0, 1]")
    sub = cur.tonne_km * share if cur.tonne_km is not None and 0 < share <= 1 else None
    return Equivalence(cur.lane_id, current_id, alternative_id, not lim, lim, sub)
