"""Phase 11 - explainable supplier recommendations (one per service lane / incumbent).

Decision hierarchy (project-designed, applied in order; the first rule that fires decides):
  1 Legal & safety eligibility of the incumbent        R1  -> INELIGIBLE / ESCALATE
  2 Evidence sufficiency of the incumbent             R2  -> REQUEST BETTER DATA
  3 Service equivalence + eligibility of alternatives  (excluded alternatives are listed with reasons)
  4 Comparable carbon and financial performance       R3  no viable alternative -> IMPROVE (low maturity) / RETAIN
  5 Operational risk (reliability, capacity)           recorded as implications and next steps
  6 Uncertainty: joint low/base/high cases             a CONSIDER SWITCHING that is not robust -> NO DEFENSIBLE
  7 Conditional recommendation:
      R4 no alternative reduces emissions              -> IMPROVE / RETAIN
      R5 lower emissions and NPV >= 0                  -> CONSIDER SWITCHING (if robust)
      R6 lower emissions, NPV < 0, no willingness-to-pay set -> NO DEFENSIBLE RECOMMENDATION YET
      R7 lower emissions, NPV < 0, discounted lifetime cost per tonne <= willingness to pay -> CONSIDER SWITCHING (if robust)
      R8 lower emissions, NPV < 0, cost per tonne > willingness to pay -> IMPROVE / RETAIN
      R9 higher emissions but NPV > 0 (financial-only gain)        -> NO DEFENSIBLE RECOMMENDATION YET
A weighted score never decides on its own and never overrides a failed gate. CONSIDER SWITCHING,
ESCALATE and NO DEFENSIBLE always require human procurement approval / judgement.
"""
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from supplier_carbon_engine import compare
from supplier_financial_engine import appraise, within_willingness_to_pay
from supplier_models import Phase11Data
from supplier_scoring_engine import score_lane
from supplier_uncertainty_engine import joint_cases

RETAIN, IMPROVE, SWITCH, DATA, INELIGIBLE, NONE = (
    "RETAIN EXISTING SUPPLIER", "IMPROVE EXISTING SUPPLIER", "CONSIDER SWITCHING", "REQUEST BETTER DATA",
    "INELIGIBLE / ESCALATE", "NO DEFENSIBLE RECOMMENDATION YET")
APPROVAL = {SWITCH: True, INELIGIBLE: True, NONE: True, RETAIN: False, IMPROVE: False, DATA: False}


@dataclass
class Recommendation:
    lane_id: str
    lane_name: str
    incumbent_offer: Optional[str]
    incumbent_supplier: Optional[str]
    action: str
    rule_id: str
    rule: str
    best_alternative: Optional[str] = None
    supporting_evidence: List[str] = field(default_factory=list)
    material_assumptions: List[str] = field(default_factory=list)
    carbon_implications: str = ""
    financial_implications: str = ""
    operational_implications: str = ""
    data_limitations: List[str] = field(default_factory=list)
    sensitivity: str = ""
    next_steps: List[str] = field(default_factory=list)
    human_approval_required: bool = False
    approval_note: str = ""
    excluded_alternatives: List[str] = field(default_factory=list)
    score_summary: str = ""
    engagement_priority: str = ""
    synthetic: bool = True

    def as_row(self):
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, list):
                d[k] = " | ".join(str(x) for x in v)
        return d


def _sar(x):
    return "n/a" if x is None else f"SAR {x:,.0f}"


def _num(x, fmt=",.0f", unit=""):
    return "not documented" if x is None else f"{x:{fmt}}{unit}"


def _improve_or_retain(engagement):
    pr = engagement.priority if engagement else None
    return IMPROVE if pr in (1, 3, "Data engagement") else RETAIN


def recommend_lane(data: Phase11Data, lane_id: str, screening: dict, engagement: dict, weights=None,
                   wtp="settings") -> Recommendation:
    wtp = data.settings.willingness_to_pay if wtp == "settings" else wtp
    lane = data.lanes[lane_id]
    inc_id = lane.incumbent_offer_id
    inc = data.offers.get(inc_id)
    rec = Recommendation(lane_id, lane.name or lane_id, inc_id, inc.supplier_id if inc else None, NONE, "R0", "")
    assumptions = [f"Discount rate {data.settings.discount_rate:.1%} real, horizon {data.settings.horizon_years} years, "
                   f"implementation delay {data.settings.implementation_delay_years} year(s)",
                   f"Substitution share {data.settings.substitution_share:.0%} of lane tonne-km",
                   "Willingness to pay: " + (f"SAR {wtp:,.0f}/tCO2e (discounted lifetime basis)" if wtp is not None
                                             else "NOT SET by management"),
                   "All supplier, cost and reliability values are synthetic demonstration data"]
    rec.material_assumptions = assumptions
    if inc is None:
        rec.rule_id, rec.rule = "R0", "No incumbent offer for the lane: nothing to compare"
        rec.next_steps = ["Define the incumbent service before evaluating alternatives"]
        rec.human_approval_required = True
        return rec
    eng = engagement.get(inc.supplier_id)
    rec.engagement_priority = f"{eng.priority} - {eng.label}" if eng else "n/a (not an existing supplier)"
    si = screening[inc_id]
    rec.supporting_evidence.append(f"Incumbent {inc_id} screening: {si.eligibility}")
    rec.data_limitations += si.missing_material + si.conditions

    # 1 legal / safety
    if si.eligibility == "Ineligible":
        rec.action, rec.rule_id = INELIGIBLE, "R1"
        rec.rule = "Incumbent fails a mandatory legal / safety / service gate"
        rec.supporting_evidence += si.blocking_reasons
        rec.next_steps = ["Escalate to procurement and HSE", "Resolve the failed gate or plan an orderly exit",
                          "Do not rely on weighted scores while a gate is failed"]
        return _finish(rec)
    # 2 evidence sufficiency
    if si.eligibility == "Insufficient evidence" or inc.tonne_km is None:
        rec.action, rec.rule_id = DATA, "R2"
        rec.rule = "Incumbent evidence insufficient (missing material information); no comparison is defensible"
        rec.carbon_implications = "Emissions UNAVAILABLE (missing activity) - not zero; not included in any total"
        rec.financial_implications = "Not assessable: cost and service data missing"
        rec.operational_implications = "Not assessable: reliability, capacity and service details not documented"
        rec.next_steps = [a["action"] for a in (eng.plan if eng else [])][:5] or ["Request missing activity and evidence"]
        return _finish(rec)

    # 3 alternatives: eligibility + equivalence + comparability
    viable = []
    for o in data.lane_offers(lane_id):
        if o.offer_id == inc_id:
            continue
        so = screening[o.offer_id]
        if so.eligibility == "Ineligible":
            rec.excluded_alternatives.append(f"{o.offer_id}: INELIGIBLE - " + "; ".join(so.blocking_reasons))
            continue
        if so.eligibility == "Insufficient evidence":
            rec.excluded_alternatives.append(f"{o.offer_id}: insufficient evidence - " + "; ".join(so.missing_material))
            continue
        c = compare(data, inc_id, o.offer_id)
        if not c.comparable:
            rec.excluded_alternatives.append(f"{o.offer_id}: comparison limitation - " + "; ".join(c.limitations))
            continue
        a = appraise(data, inc_id, o.offer_id, c.avoided_t)
        if not a.complete:
            rec.excluded_alternatives.append(f"{o.offer_id}: {a.note}")
            continue
        viable.append((o, so, c, a))
    sc = score_lane(data, lane_id, screening, weights)
    rows = {r.offer_id: r for r in sc.rows}
    rec.score_summary = (f"Weighted score ranking {sc.ranking_status.lower()}: " + "; ".join(
        f"{r.offer_id} {('%.1f' % r.total) if r.total is not None else 'no total'}"
        + (f" (rank {r.rank})" if r.rank else "") for r in sc.rows) + " - supporting evidence only")
    if not viable:
        rec.action, rec.rule_id = _improve_or_retain(eng), "R3"
        rec.rule = "No eligible, equivalent and comparable alternative for this service"
        rec.carbon_implications = (f"Current lane emissions {inc.emissions_t:,.1f} tCO2e/yr at "
                                   f"{inc.ef.value_kg_per_tkm:g} kgCO2e/t-km ({inc.ef.verification})"
                                   if inc.emissions_t is not None and inc.ef is not None
                                   and inc.ef.value_kg_per_tkm is not None else "Current emissions not quantified")
        rec.financial_implications = f"Current annual service cost {_sar(inc.annual_cost)}; no switching appraisal"
        rec.operational_implications = (f"Incumbent on-time delivery {inc.on_time_pct:g}%" if inc.on_time_pct is not None
                                         else "Reliability not documented")
        rec.next_steps = ([a["action"] for a in eng.plan][:4] if eng and rec.action == IMPROVE else
                          ["Continue monitoring under the supplier scorecard"])
        return _finish(rec)

    # 4 best alternative on carbon (largest avoided), tie -> higher NPV
    o, so, c, a = sorted(viable, key=lambda t: (-t[2].avoided_t, -t[3].npv))[0]
    rec.best_alternative = o.offer_id
    sr = rows.get(o.offer_id)
    rec.supporting_evidence += [
        f"Alternative {o.offer_id} ({data.suppliers[o.supplier_id].name}) screening: {so.eligibility}",
        f"Equivalent service on lane {lane_id}: {c.substituted_tonne_km:,.0f} tonne-km compared",
        f"Emission factors: current {c.current_ef:g} vs alternative {c.alternative_ef:g} kgCO2e/t-km "
        f"({inc.ef.verification if inc.ef else 'n/a'} / {o.ef.verification if o.ef else 'n/a'})"]
    rec.carbon_implications = (f"{c.current_emissions_t:,.1f} -> {c.alternative_emissions_t:,.1f} tCO2e/yr: "
                               f"{'avoids' if c.avoided_t > 0 else 'adds'} {abs(c.avoided_t):,.1f} tCO2e/yr "
                               f"({(c.reduction_pct or 0):.1%} of the substituted service). Projected, not verified.")
    rec.financial_implications = (
        f"Annual cost difference {a.annual_cost_difference:+,.0f} SAR/yr (+ = alternative costs more); one-time costs "
        f"{_sar(a.one_time_cost)}; switching NPV {_sar(a.npv)} over {a.horizon_years} years at {a.discount_rate:.0%}; "
        f"break-even alternative cost {_sar(a.breakeven_alternative_cost)}/yr; "
        + (f"incremental annual cost {a.annual_cost_per_t:,.0f} SAR/tCO2e (excl. one-time), discounted lifetime cost "
           f"{a.lifetime_discounted_cost_per_t:,.0f} SAR/tCO2e" if a.annual_cost_per_t is not None else a.note))
    rel_c, rel_a = inc.on_time_pct, o.on_time_pct
    rec.operational_implications = (f"On-time delivery {_num(rel_c, 'g', '%')} -> {_num(rel_a, 'g', '%')} (stated, unverified); "
                                    f"capacity {_num(o.capacity_t)} t/yr vs required {_num(lane.required_capacity_t)} t/yr; "
                                    "transition requires onboarding and service-level agreement")
    rec.data_limitations += [f"{o.offer_id}: {x}" for x in so.conditions]
    # 6 uncertainty
    jc = joint_cases(data, inc_id, o.offer_id)
    signs = {k: v.get("avoided_t", 0) > 0 for k, v in jc.items() if v.get("comparable")}
    robust_carbon = all(signs.values())
    rec.sensitivity = ("Joint cases: " + "; ".join(
        f"{k}: avoided {jc[k]['avoided_t']:,.1f} t, NPV {_sar(jc[k]['npv'])}" for k in jc if jc[k].get("comparable"))
        + (". Carbon benefit holds in all cases." if robust_carbon else ". Carbon benefit does NOT hold in all cases."))
    within = within_willingness_to_pay(a, wtp)
    # 7 decision
    if c.avoided_t <= 1e-12:
        if a.npv is not None and a.npv > 0:
            rec.action, rec.rule_id = NONE, "R9"
            rec.rule = "Alternative is cheaper but does not reduce emissions: financial-only gain needs management judgement"
        else:
            rec.action, rec.rule_id = _improve_or_retain(eng), "R4"
            rec.rule = "No eligible alternative reduces emissions for the equivalent service"
    elif a.npv >= 0:
        rec.action, rec.rule_id = (SWITCH, "R5") if robust_carbon else (NONE, "R5u")
        rec.rule = ("Lower emissions and non-negative switching NPV" if robust_carbon else
                    "Lower emissions and NPV >= 0 in base, but the carbon benefit is not robust across cases")
    elif wtp is None:
        rec.action, rec.rule_id = NONE, "R6"
        rec.rule = ("Lower emissions at a net financial cost and no management willingness-to-pay threshold set: "
                    "the trade-off needs management judgement")
    elif within:
        rec.action, rec.rule_id = (SWITCH, "R7") if robust_carbon else (NONE, "R7u")
        rec.rule = ("Lower emissions; discounted lifetime cost per tonne within the stated willingness to pay"
                    + ("" if robust_carbon else ", but the carbon benefit is not robust across cases"))
    else:
        rec.action, rec.rule_id = _improve_or_retain(eng), "R8"
        rec.rule = "Lower emissions, but the cost per tonne exceeds the stated willingness to pay"
    steps = []
    if rec.action == SWITCH:
        steps += ["Verify the alternative's emission factor (fuel records or assurance) before any contract decision",
                  "Confirm service-level, capacity and transition plan; obtain formal quotation",
                  "Obtain procurement approval (the model does not award contracts)"]
    elif rec.action == NONE:
        steps += ["Management to set an explicit willingness to pay (SAR per tCO2e) and acceptable risks",
                  f"Compare with the discounted lifetime cost of {_sar(a.lifetime_discounted_cost_per_t)}/tCO2e",
                  "Verify the alternative's claimed emission factor before re-evaluating"]
    if eng and eng.priority in (1, 3):
        steps += [f"In parallel: incumbent engagement ({eng.label}) - " + "; ".join(x["action"] for x in eng.plan[:2])]
    rec.next_steps = steps or ["Continue monitoring under the supplier scorecard"]
    if sr is not None and sr.total is not None:
        rec.supporting_evidence.append(f"Weighted score {o.offer_id} {sr.total:.1f} (supporting evidence only)")
    return _finish(rec)


def _finish(rec):
    rec.human_approval_required = APPROVAL.get(rec.action, True)
    rec.approval_note = ("Human procurement approval / management judgement required before any action"
                         if rec.human_approval_required else "Routine engagement action; no contract change implied")
    return rec


def recommend_all(data: Phase11Data, screening: dict, engagement: dict, weights=None, wtp="settings"):
    return {lid: recommend_lane(data, lid, screening, engagement, weights, wtp) for lid in sorted(data.lanes)}


def recommendation_robustness(data, lane_id, screening, engagement, wtp="settings"):
    """Recommendation under each one-way low/high value and joint case (same WTP). Robust = action unchanged."""
    import copy
    from dataclasses import replace

    from supplier_uncertainty_engine import applicable
    base = recommend_lane(data, lane_id, screening, engagement, wtp=wtp)
    out = [{"case": "Base", "action": base.action, "rule": base.rule_id}]
    if not base.best_alternative:
        return out, True
    cur, alt = base.incumbent_offer, base.best_alternative
    field_map = {"alternative_ef": ("alt", "ef"), "current_ef": ("cur", "ef"), "alternative_annual_cost": ("alt", "annual_cost"),
                 "switching_cost": ("alt", "switching_cost"), "monitoring_cost": ("alt", "recurring_cost"),
                 "implementation_delay": ("settings", "implementation_delay_years")}
    for k, u in applicable(data, cur, alt).items():
        if k not in field_map:
            continue
        who, attr = field_map[k]
        for level, val in (("low", u.low), ("high", u.high)):
            d = copy.deepcopy(data)
            if who == "settings":
                setattr(d.settings, attr, int(val))
            else:
                o = d.offers[alt if who == "alt" else cur]
                if attr == "ef":
                    o.ef = replace(o.ef, value_kg_per_tkm=val)
                else:
                    setattr(o, attr, val)
            r = recommend_lane(d, lane_id, screening, engagement, wtp=wtp)
            out.append({"case": f"{k} {level} ({val:g})", "action": r.action, "rule": r.rule_id})
    robust = len({x["action"] for x in out}) == 1
    return out, robust
