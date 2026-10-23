"""Phase 11 - supplier engagement priority matrix (impact x maturity).

The UN Global Compact framework segments suppliers by impact and maturity into Priorities 1-4
(qualitative). The numeric scores and thresholds here are PROJECT-DESIGNED and editable.

Four separate concepts (never merged into one number):
  absolute impact   - attributable known freight emissions / volume / service materiality (calculate_supplier_impact)
  intensity         - kgCO2e per tonne-km (supplier_carbon_engine; NOT used for impact)
  maturity          - capability to measure, disclose, manage and improve (assess_supplier_maturity)
  data confidence   - strength of the evidence (supplier_screening_engine.data_quality)

Impact score (0-100) = w_e x share of KNOWN freight emissions x 100 + w_v x share of known tonne-km x 100
                       + w_m x materiality score.  Unknown activity -> UNCLASSIFIED (never a fabricated score).
Maturity score (0-100) = mean of assessed indicators (0-4) / 4 x 100, only if >= the minimum number assessed.
The matrix sets ENGAGEMENT priorities; it never triggers supplier replacement.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from supplier_models import MatrixRules, Phase11Data

UNCLASSIFIED = "UNCLASSIFIED"
UNCLASSIFIED_LABEL = "Unclassified - insufficient evidence"


@dataclass
class ImpactResult:
    supplier_id: str
    score: Optional[float]
    status: str                    # ASSESSED | UNCLASSIFIED | NOT APPLICABLE
    components: Dict[str, Optional[float]]
    basis: str
    reason: str = ""


@dataclass
class MaturityResult:
    supplier_id: str
    score: Optional[float]
    status: str
    assessed: int
    indicators: Dict[str, Optional[float]]
    reason: str = ""


@dataclass
class EngagementResult:
    supplier_id: str
    impact: ImpactResult
    maturity: MaturityResult
    quadrant: str
    priority: object
    label: str
    actions: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)


def calculate_supplier_impact(data: Phase11Data, inventory: dict, supplier_id: str, rules: MatrixRules = None,
                              hypothetical: Dict[str, float] = None) -> ImpactResult:
    """inventory: {inventory_supplier_id: {'emissions_t', 'tonne_km'}} from Workstream B (read-only).
    hypothetical: optional {inventory_supplier_id: tCO2e} SENSITIVITY values for missing suppliers (labelled)."""
    rules = rules or data.matrix
    s = data.suppliers[supplier_id]
    if not s.is_existing or not s.inventory_supplier_id:
        return ImpactResult(supplier_id, None, "NOT APPLICABLE", {}, "prospective supplier",
                            "no current spend or activity with the organisation")
    hyp = hypothetical or {}
    em = {k: (v["emissions_t"] if v["emissions_t"] is not None else hyp.get(k)) for k, v in inventory.items()}
    tk = {k: v["tonne_km"] for k, v in inventory.items()}
    sid = s.inventory_supplier_id
    basis = "inventory (known data)"
    if inventory.get(sid, {}).get("emissions_t") is None:
        if sid in hyp:
            basis = "SENSITIVITY - hypothetical emissions, not inventory"
        else:
            return ImpactResult(supplier_id, None, UNCLASSIFIED, {"emissions_t": None}, basis,
                                "attributable emissions UNAVAILABLE (missing activity); impact not classified")
    tot_e = sum(v for v in em.values() if v is not None)
    known_t = [v for v in tk.values() if v is not None]
    e_share = em[sid] / tot_e if tot_e > 0 else None
    v_share = (tk[sid] / sum(known_t)) if tk.get(sid) is not None and sum(known_t) > 0 else None
    mat = rules.materiality_scores.get(s.materiality or "", None)
    comps = {"emissions_t": em[sid], "emissions_share": e_share, "volume_share": v_share, "materiality_score": mat}
    if e_share is None or mat is None:
        return ImpactResult(supplier_id, None, UNCLASSIFIED, comps, basis, "impact inputs incomplete")
    wsum = rules.w_emissions_share + rules.w_volume_share + rules.w_materiality
    if v_share is None:   # volume unknown (e.g. sensitivity case): re-weight transparently over available components
        score = (rules.w_emissions_share * e_share * 100 + rules.w_materiality * mat) / (rules.w_emissions_share + rules.w_materiality)
        reason = "volume share unknown: score uses emissions share and materiality only"
    else:
        score = (rules.w_emissions_share * e_share * 100 + rules.w_volume_share * v_share * 100 + rules.w_materiality * mat) / wsum
        reason = ""
    return ImpactResult(supplier_id, score, "ASSESSED", comps, basis, reason)


def assess_supplier_maturity(data: Phase11Data, supplier_id: str, rules: MatrixRules = None) -> MaturityResult:
    rules = rules or data.matrix
    m = data.maturity.get(supplier_id)
    if m is None:
        return MaturityResult(supplier_id, None, UNCLASSIFIED, 0, {}, "no maturity assessment recorded")
    vals = [v for v in m.indicators.values() if v is not None]
    if len(vals) < rules.min_maturity_indicators:
        return MaturityResult(supplier_id, None, UNCLASSIFIED, len(vals), m.indicators,
                              f"only {len(vals)} of {len(m.indicators)} indicators assessed "
                              f"(minimum {rules.min_maturity_indicators})")
    return MaturityResult(supplier_id, sum(vals) / len(vals) / 4 * 100, "ASSESSED", len(vals), m.indicators)


def classify_engagement_quadrant(impact: Optional[float], maturity: Optional[float], rules: MatrixRules) -> str:
    if impact is None or maturity is None:
        return UNCLASSIFIED
    hi_i, hi_m = impact >= rules.impact_threshold, maturity >= rules.maturity_threshold
    return {(True, False): "Q1", (True, True): "Q2", (False, False): "Q3", (False, True): "Q4"}[(hi_i, hi_m)]


def determine_engagement_priority(quadrant: str, rules: MatrixRules):
    q = rules.quadrants.get(quadrant) or {}
    if quadrant == UNCLASSIFIED:
        return "Data engagement", UNCLASSIFIED_LABEL
    return q.get("priority"), q.get("label")


def generate_engagement_actions(data: Phase11Data, supplier_id: str, quadrant: str, screening=None,
                                start: date = None) -> List[dict]:
    """Action plan rows from the register templates. Deadlines are editable management assumptions."""
    start = start or date(2026, 1, 1)
    triggers = [quadrant if quadrant != UNCLASSIFIED else "UNCLASSIFIED"]
    if screening:
        offs = [r for r in screening.values() if r.supplier_id == supplier_id]
        if any(next(c for c in r.checks if c.check_no == 12).status != "Pass" for r in offs) and quadrant != UNCLASSIFIED:
            triggers.append("VERIFICATION_GAP")
        if any(r.eligibility == "Ineligible" for r in offs):
            triggers.append("INELIGIBLE")
    rows, k = [], 0
    for t in triggers:
        for tpl in data.action_templates:
            if tpl.trigger != t:
                continue
            k += 1
            days = int(tpl.days) if tpl.days is not None else 90
            due = start + timedelta(days=days)
            rows.append({"action_id": f"{supplier_id}-A{k:02d}", "supplier_id": supplier_id, "trigger": t,
                         "action": tpl.action, "responsible_role": tpl.role, "deadline_days": days,
                         "proposed_deadline": due.isoformat(), "required_evidence": tpl.evidence,
                         "success_indicator": tpl.success, "status": "Not started",
                         "follow_up_date": (due + timedelta(days=14)).isoformat(),
                         "verification_method": tpl.verification,
                         "deadline_basis": "editable management assumption (not a UN requirement)"})
    return rows


def assess(data: Phase11Data, inventory: dict, rules: MatrixRules = None, hypothetical=None, screening=None,
           start: date = None) -> Dict[str, EngagementResult]:
    rules = rules or data.matrix
    out = {}
    for sid, s in data.suppliers.items():
        if not s.is_existing:
            continue
        imp = calculate_supplier_impact(data, inventory, sid, rules, hypothetical)
        mat = assess_supplier_maturity(data, sid, rules)
        q = classify_engagement_quadrant(imp.score, mat.score, rules)
        pr, label = determine_engagement_priority(q, rules)
        lim = [x for x in (imp.reason, mat.reason) if x]
        if imp.basis.startswith("SENSITIVITY"):
            lim.append("impact uses a hypothetical sensitivity value, not inventory data")
        acts = (rules.quadrants.get(q) or {}).get("actions", []) if q != UNCLASSIFIED else \
            [t.action for t in data.action_templates if t.trigger == "UNCLASSIFIED"]
        res = EngagementResult(sid, imp, mat, q, pr, label, acts, lim)
        res.plan = generate_engagement_actions(data, sid, q, screening, start)
        out[sid] = res
    return out
