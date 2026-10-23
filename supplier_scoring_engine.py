"""Phase 11 - configurable weighted supplier scoring (supporting evidence only).

Default weights (PROJECT ASSUMPTIONS, not UN percentages): carbon 35%, total lifecycle cost 25%,
reliability 20%, data quality 15%, improvement capability 5%. Weights must be numeric and non-negative;
they are normalised to 100% before any total is produced.

Criterion scores (0-100, fixed disclosed benchmarks):
  carbon      = 100 x (high - EF) / (high - low), EF in kgCO2e/t-km (intensity), benchmarks 0.05 / 0.15
  cost        = 50 + 50 x (incumbent annualised cost - offer annualised cost) / (band x incumbent annualised cost),
                annualised cost = annual cost + recurring + one-time costs / annuity factor, band 20%
  reliability = 100 x (on-time % - 90) / (100 - 90)
  data quality= mean of 7 dimensions (High 100, Medium 60, Low 20, Missing 0)
  improvement = (improvement targets + engagement responsiveness) / 8 x 100
All clamped to 0-100. A missing mandatory input gives no total (never zero) and suppresses the
definitive ranking. Ineligible or insufficient-evidence offers are scored for transparency but never ranked.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import financial_engine as fe
from supplier_data_loader import CRITERIA
from supplier_models import Phase11Data, WeightError
from supplier_screening_engine import DQ_SCORE

DEFAULT_WEIGHTS = {"carbon_performance": 0.35, "total_lifecycle_cost": 0.25, "operational_reliability": 0.20,
                   "data_quality_transparency": 0.15, "improvement_capability": 0.05}
LABELS = {"carbon_performance": "Carbon performance", "total_lifecycle_cost": "Total lifecycle cost",
          "operational_reliability": "Operational reliability", "data_quality_transparency": "Data quality & transparency",
          "improvement_capability": "Improvement capability"}


def validate_weights(weights: Dict[str, object]) -> Dict[str, float]:
    """Return weights normalised to sum 1.0. Raise WeightError for missing, non-numeric, negative or all-zero."""
    out = {}
    for c in CRITERIA:
        if c not in weights:
            raise WeightError(f"weight for '{c}' missing")
        v = weights[c]
        if isinstance(v, bool):
            raise WeightError(f"weight for '{c}' is not numeric")
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise WeightError(f"weight for '{c}' is not numeric: {v!r}") from None
        if x != x or x < 0:
            raise WeightError(f"weight for '{c}' must be a non-negative number: {v!r}")
        out[c] = x
    extra = set(weights) - set(CRITERIA)
    if extra:
        raise WeightError(f"unknown criteria: {sorted(extra)}")
    tot = sum(out.values())
    if tot <= 0:
        raise WeightError("weights sum to zero")
    return {c: v / tot for c, v in out.items()}


def _clamp(x):
    return max(0.0, min(100.0, x))


def annualised_cost(o, rate, horizon):
    if o.annual_cost is None:
        return None
    af = fe.annuity_factor(rate, 0, horizon, horizon)
    one = (o.switching_cost or 0.0) + (o.onboarding_cost or 0.0)
    return o.annual_cost + (o.recurring_cost or 0.0) + (one / af if af > 0 else 0.0)


def criterion_scores(data: Phase11Data, offer_id: str, incumbent_id: str):
    cfg, st = data.scoring, data.settings
    o, inc = data.offers[offer_id], data.offers[incumbent_id]
    s, miss = {}, []
    ef = o.ef.value_kg_per_tkm if o.ef else None
    if ef is None:
        s["carbon_performance"] = None; miss.append("emission factor")
    else:
        s["carbon_performance"] = _clamp(100 * (cfg.carbon_high - ef) / (cfg.carbon_high - cfg.carbon_low))
    ac, ref = annualised_cost(o, st.discount_rate, st.horizon_years), annualised_cost(inc, st.discount_rate, st.horizon_years)
    if ac is None or ref is None or ref <= 0:
        s["total_lifecycle_cost"] = None; miss.append("annual cost (offer or incumbent)")
    else:
        s["total_lifecycle_cost"] = _clamp(50 + 50 * (ref - ac) / (cfg.cost_band * ref))
    if o.on_time_pct is None:
        s["operational_reliability"] = None; miss.append("on-time delivery")
    else:
        s["operational_reliability"] = _clamp(100 * (o.on_time_pct - cfg.reliability_low) / (cfg.reliability_high - cfg.reliability_low))
    m = data.maturity.get(o.supplier_id)
    dq = [m.dq.get(k) for k in m.dq] if m else []
    if not dq or any(v is None for v in dq):
        s["data_quality_transparency"] = None; miss.append("data-quality assessment")
    else:
        s["data_quality_transparency"] = sum(DQ_SCORE[v] for v in dq) / len(dq)
    t = m.indicators.get("improvement_targets") if m else None
    r = m.indicators.get("engagement_responsiveness") if m else None
    if t is None or r is None:
        s["improvement_capability"] = None; miss.append("improvement-capability indicators")
    else:
        s["improvement_capability"] = (t + r) / 8 * 100
    return s, miss


@dataclass
class ScoreRow:
    offer_id: str
    supplier_id: str
    eligibility: str
    scores: Dict[str, Optional[float]]
    contributions: Dict[str, Optional[float]]
    total: Optional[float]
    missing: List[str]
    rank: Optional[int] = None
    status: str = ""


@dataclass
class LaneScoring:
    lane_id: str
    weights: Dict[str, float]
    rows: List[ScoreRow]
    ranking_status: str           # DEFINITIVE | SUPPRESSED | NOT APPLICABLE
    reasons: List[str] = field(default_factory=list)

    def top(self):
        r = [x for x in self.rows if x.rank == 1]
        return r[0].offer_id if r else None


def score_lane(data: Phase11Data, lane_id: str, screening: dict, weights=None) -> LaneScoring:
    w = validate_weights(weights if weights is not None else data.scoring.weights)
    lane = data.lanes[lane_id]
    inc = lane.incumbent_offer_id
    offs = [o for o in data.lane_offers(lane_id)]
    rows, reasons = [], []
    if inc not in data.offers:
        return LaneScoring(lane_id, w, [], "NOT APPLICABLE", ["incumbent offer missing"])
    for o in offs:
        sc, miss = criterion_scores(data, o.offer_id, inc)
        el = screening[o.offer_id].eligibility
        if miss:
            tot, contrib, status = None, {c: None for c in w}, "No total: missing " + ", ".join(miss)
        else:
            contrib = {c: w[c] * sc[c] for c in w}
            tot = sum(contrib.values())
            status = "Scored"
        if el in ("Ineligible", "Insufficient evidence"):
            status = f"{el}: score shown for transparency, NOT ranked" + (f" ({status})" if miss else "")
        rows.append(ScoreRow(o.offer_id, o.supplier_id, el, sc, contrib, tot, miss, None, status))
    rankable = [r for r in rows if r.eligibility in ("Eligible", "Conditionally eligible")]
    incomplete = [r for r in rankable if r.total is None]
    if len(rankable) < 2:
        st = "NOT APPLICABLE"
        reasons.append("fewer than two eligible offers for this lane: no ranking")
    elif incomplete:
        st = "SUPPRESSED"
        reasons.append("mandatory inputs missing for " + ", ".join(r.offer_id for r in incomplete)
                       + ": no definitive ranking (missing values are never scored as zero)")
    else:
        st = "DEFINITIVE"
        for k, r in enumerate(sorted(rankable, key=lambda x: -x.total), start=1):
            r.rank = k
    for r in rows:
        if r.eligibility == "Ineligible":
            reasons.append(f"{r.offer_id} ineligible: excluded regardless of score")
    return LaneScoring(lane_id, w, rows, st, reasons)


def weight_sensitivity(data: Phase11Data, lane_id: str, screening: dict, weights=None, step=0.10):
    """Shift each weight by +/- step (others rescaled proportionally); report the top offer each time,
    and the carbon weight at which the top two eligible offers swap (scan 0-100% in 1 pp steps)."""
    base = validate_weights(weights if weights is not None else data.scoring.weights)
    ref = score_lane(data, lane_id, screening, base)
    out = []
    if ref.ranking_status != "DEFINITIVE":
        return out, None
    for c in CRITERIA:
        for d in (-step, step):
            nw = dict(base)
            nw[c] = min(max(base[c] + d, 0.0), 1.0)
            rest = sum(v for k, v in base.items() if k != c)
            for k in nw:
                if k != c:
                    nw[k] = base[k] / rest * (1 - nw[c]) if rest > 0 else 0.0
            s = score_lane(data, lane_id, screening, nw)
            out.append({"criterion": c, "change_pp": round(d * 100), "new_weight": nw[c], "top_offer": s.top(),
                        "base_top_offer": ref.top(), "reversal": s.top() != ref.top()})
    switch = None
    prev = None
    for k in range(0, 101):
        wc = k / 100
        rest = sum(v for kk, v in base.items() if kk != "carbon_performance")
        nw = {kk: (wc if kk == "carbon_performance" else base[kk] / rest * (1 - wc)) for kk in base}
        t = score_lane(data, lane_id, screening, nw).top()
        if prev is not None and t != prev and switch is None:
            switch = {"carbon_weight": wc, "top_below": prev, "top_from": t}
        prev = t
    return out, switch
