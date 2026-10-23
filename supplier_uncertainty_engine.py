"""Phase 11 - uncertainty for a switching decision (low / base / high stress values, not probabilities).

Reuses the Phase 9 cash-flow engine through supplier_financial_engine and the Phase 10 convention of
one-way tests, joint stress cases and switching (break-even) values.

Variables (register 'Uncertainty Assumptions'): alternative EF, current EF, demand, alternative annual
cost, switching cost, monitoring (recurring) cost, implementation delay, alternative on-time %.
Joint cases set every variable with a stated favourable direction to its favourable / unfavourable
value; 'ambiguous' variables stay at base. Results are stress tests, not confidence intervals.
"""
from dataclasses import replace

from supplier_carbon_engine import compare
from supplier_financial_engine import appraise
from supplier_models import Phase11Data
from supplier_scoring_engine import score_lane

VAR_ORDER = ["alternative_ef", "current_ef", "demand_tonne_km", "alternative_annual_cost", "switching_cost",
             "monitoring_cost", "implementation_delay", "alternative_on_time"]


def applicable(data: Phase11Data, current_id, alternative_id):
    """Register variables that apply to this pair of offers or their lane (applies_to column)."""
    lane = data.offers[current_id].lane_id
    return {k: u for k, u in data.uncertainty.items() if u.applies_to in (current_id, alternative_id, lane)}


def evaluate(data: Phase11Data, current_id, alternative_id, v: dict, share=None):
    """One evaluation. v holds overrides only; anything not overridden uses the offers' own current data
    (so the base case always equals the deterministic comparison, even after user edits)."""
    p = dict(v)
    cur = data.offers[current_id]
    demand = p.get("demand_tonne_km", cur.tonne_km)
    dfac = demand / cur.tonne_km if cur.tonne_km else 1.0
    c = compare(data, current_id, alternative_id, share, ef_current=p.get("current_ef"),
                ef_alternative=p.get("alternative_ef"), demand_tkm=demand)
    if not c.comparable:
        return {"comparable": False, "limitations": c.limitations}
    a = appraise(data, current_id, alternative_id, c.avoided_t, share=share, delay=p.get("implementation_delay"),
                 alt_cost=p.get("alternative_annual_cost"), switching_cost=p.get("switching_cost"),
                 recurring_cost=p.get("monitoring_cost"), demand_factor=dfac)
    return {"comparable": True, "avoided_t": c.avoided_t, "reduction_pct": c.reduction_pct, "direction": c.direction,
            "annual_cost_difference": a.annual_cost_difference, "npv": a.npv, "annual_cost_per_t": a.annual_cost_per_t,
            "lifetime_cost_per_t": a.lifetime_discounted_cost_per_t, "breakeven_alt_cost": a.breakeven_alternative_cost,
            "alt_on_time": p.get("alternative_on_time", data.offers[alternative_id].on_time_pct)}


def one_way(data, current_id, alternative_id, share=None):
    base = evaluate(data, current_id, alternative_id, {}, share)
    rows = []
    app = applicable(data, current_id, alternative_id)
    for k in VAR_ORDER:
        if k not in app:
            continue
        u = app[k]
        for level, val in (("low", u.low), ("high", u.high)):
            r = evaluate(data, current_id, alternative_id, {k: val}, share)
            rows.append({"variable": k, "level": level, "value": val, "unit": u.unit,
                         "favourable_to_switching": u.favourable, **r,
                         "delta_npv": (r["npv"] - base["npv"]) if r.get("comparable") else None,
                         "delta_avoided_t": (r["avoided_t"] - base["avoided_t"]) if r.get("comparable") else None})
    return base, rows


def joint_cases(data, current_id, alternative_id, share=None):
    fav, unfav = {}, {}
    for k, u in applicable(data, current_id, alternative_id).items():
        d = (u.favourable or "").lower()
        if d.startswith("lower"):
            fav[k], unfav[k] = u.low, u.high
        elif d.startswith("higher"):
            fav[k], unfav[k] = u.high, u.low
    return {"Unfavourable to switching": evaluate(data, current_id, alternative_id, unfav, share) | {"values": unfav},
            "Base": evaluate(data, current_id, alternative_id, {}, share) | {"values": {}},
            "Favourable to switching": evaluate(data, current_id, alternative_id, fav, share) | {"values": fav}}


def breakevens(data, current_id, alternative_id, share=None):
    b = evaluate(data, current_id, alternative_id, {}, share)
    cur, alt = data.offers[current_id], data.offers[alternative_id]
    return {"financial_breakeven_alternative_annual_cost_sar": b.get("breakeven_alt_cost"),
            "carbon_breakeven_alternative_ef_kg_per_tkm": cur.ef.value_kg_per_tkm if cur.ef else None,
            "willingness_to_pay_needed_sar_per_t": b.get("lifetime_cost_per_t"),
            "base_alternative_annual_cost_sar": alt.annual_cost,
            "base_alternative_ef_kg_per_tkm": alt.ef.value_kg_per_tkm if alt.ef else None}


def grid(data, current_id, alternative_id, ef_values=None, cost_values=None, share=None, wtp=None):
    ef_values = ef_values or [0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12, 0.13]
    cost_values = cost_values or [280000, 290000, 300000, 310000, 320000, 330000, 340000, 350000]
    rows = []
    for e in ef_values:
        for cst in cost_values:
            r = evaluate(data, current_id, alternative_id, {"alternative_ef": e, "alternative_annual_cost": cst}, share)
            if not r.get("comparable"):
                continue
            if r["avoided_t"] <= 1e-12:
                zone = "No carbon benefit"
            elif r["npv"] >= 0:
                zone = "Carbon and financial gain"
            elif wtp is not None and r["lifetime_cost_per_t"] is not None and r["lifetime_cost_per_t"] <= wtp:
                zone = "Within willingness to pay"
            else:
                zone = "Carbon gain at net cost (management judgement)"
            rows.append({"alternative_ef": e, "alternative_annual_cost": cst, "avoided_t": r["avoided_t"], "npv": r["npv"],
                         "lifetime_cost_per_t": r["lifetime_cost_per_t"], "zone": zone})
    return rows


def ranking_reversals(data, lane_id, current_id, alternative_id, screening, weights=None):
    """Does the weighted-score order of the current and alternative offer change across each variable's range?"""
    out = []
    base = score_lane(data, lane_id, screening, weights)
    if base.ranking_status != "DEFINITIVE":
        return [{"variable": "all", "result": f"ranking {base.ranking_status.lower()}: reversal test not applicable"}]
    app = applicable(data, current_id, alternative_id)
    for k, attr in (("alternative_ef", "ef"), ("alternative_annual_cost", "annual_cost"), ("switching_cost", "switching_cost"),
                    ("alternative_on_time", "on_time_pct"), ("current_ef", "ef_cur")):
        if k not in app:
            continue
        u = app[k]
        tops = {"base": base.top()}
        for level, val in (("low", u.low), ("high", u.high)):
            d = _with(data, current_id, alternative_id, attr, val)
            tops[level] = score_lane(d, lane_id, screening, weights).top()
        rev = len(set(tops.values())) > 1
        out.append({"variable": k, "low_top": tops["low"], "base_top": tops["base"], "high_top": tops["high"],
                    "reversal": rev, "result": ("ranking changes within the tested range" if rev else
                                                "no ranking reversal within the tested range")})
    return out


def _with(data, current_id, alternative_id, attr, val):
    import copy
    d = copy.deepcopy(data)
    if attr == "ef":
        d.offers[alternative_id].ef = replace(d.offers[alternative_id].ef, value_kg_per_tkm=val)
    elif attr == "ef_cur":
        d.offers[current_id].ef = replace(d.offers[current_id].ef, value_kg_per_tkm=val)
    else:
        setattr(d.offers[alternative_id], attr, val)
    return d
