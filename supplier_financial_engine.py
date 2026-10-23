"""Phase 11 - switching appraisal, reusing the Phase 9 cash-flow engine (financial_engine.evaluate).

  annual financial savings = current annual cost - alternative annual cost - additional recurring costs
  switching NPV            = -(one-time switching + onboarding/monitoring + contract exit) + SUM_t savings / (1+r)^t
  break-even alternative annual cost (NPV = 0) = current - recurring - one-time / annuity factor
  incremental ANNUAL cost per tonne avoided   = annual cost difference / annual tCO2e avoided   (excl. one-time costs)
  discounted LIFETIME cost per tonne avoided  = net present cost / (annual tCO2e avoided x annuity factor)
                                                (money AND tonnes discounted at the same rate over the same horizon)
Constant real SAR, end-of-year cash flows, costs scale with the substituted share of the lane.
Both cost-per-tonne measures are undefined (None) when avoided emissions are zero or negative.
"""
from dataclasses import dataclass
from typing import Optional

import financial_engine as fe
from supplier_models import Phase11Data


@dataclass
class SwitchingAppraisal:
    current_offer: str
    alternative_offer: str
    share: float
    discount_rate: float
    horizon_years: int
    delay_years: int
    current_annual_cost: Optional[float]
    alternative_annual_cost: Optional[float]
    recurring_cost: float
    one_time_cost: float
    annual_cost_difference: Optional[float] = None     # + = alternative costs more per year
    annual_savings: Optional[float] = None
    npv: Optional[float] = None
    npc: Optional[float] = None
    payback_years: Optional[float] = None
    annuity_factor: Optional[float] = None
    avoided_t: Optional[float] = None
    annual_cost_per_t: Optional[float] = None
    lifetime_discounted_cost_per_t: Optional[float] = None
    breakeven_alternative_cost: Optional[float] = None
    breakeven_switching_cost: Optional[float] = None
    complete: bool = False
    note: str = ""


def appraise(data: Phase11Data, current_id, alternative_id, avoided_t, share=None, rate=None, horizon=None, delay=None,
             alt_cost=None, switching_cost=None, recurring_cost=None, demand_factor=1.0) -> SwitchingAppraisal:
    st = data.settings
    share = st.substitution_share if share is None else share
    rate = st.discount_rate if rate is None else rate
    horizon = st.horizon_years if horizon is None else int(horizon)
    delay = st.implementation_delay_years if delay is None else int(delay)
    cur, alt = data.offers[current_id], data.offers[alternative_id]
    scale = share * (demand_factor if st.cost_scales_with_demand else 1.0)
    alt_full = alt.annual_cost if alt_cost is None else alt_cost
    rec = (alt.recurring_cost or 0.0) if recurring_cost is None else recurring_cost
    one = ((alt.switching_cost or 0.0) if switching_cost is None else switching_cost) + (alt.onboarding_cost or 0.0) \
        + (cur.exit_cost or 0.0)
    a = SwitchingAppraisal(current_id, alternative_id, share, rate, horizon, delay,
                           None if cur.annual_cost is None else cur.annual_cost * scale,
                           None if alt_full is None else alt_full * scale, rec, one)
    if cur.annual_cost is None or alt_full is None:
        a.note = "annual contract cost missing: financial appraisal not possible"
        return a
    p = {"capex": one, "savings": a.current_annual_cost, "opex": a.alternative_annual_cost + rec, "delay": delay,
         "life": horizon, "horizon": horizon, "rate": rate, "avoided_t": avoided_t if avoided_t and avoided_t > 0 else 0.0}
    r = fe.evaluate(p)
    a.annual_savings = a.current_annual_cost - a.alternative_annual_cost - rec
    a.annual_cost_difference = -a.annual_savings
    a.npv, a.npc, a.annuity_factor = r["npv_sar"], r["npc_sar"], r["annuity_factor"]
    a.payback_years = r["simple_payback_y"] if a.annual_savings > 0 else None
    a.avoided_t = avoided_t
    if avoided_t is not None and avoided_t > 1e-12:
        a.annual_cost_per_t = a.annual_cost_difference / avoided_t
        a.lifetime_discounted_cost_per_t = (a.npc / (avoided_t * a.annuity_factor)) if a.annuity_factor > 0 else None
    else:
        a.note = ("no emissions reduction: cost per tonne not defined" if avoided_t is not None and abs(avoided_t) <= 1e-12
                  else "alternative has HIGHER emissions: cost per tonne not defined" if avoided_t is not None
                  else "avoided emissions unknown")
    if a.annuity_factor and a.annuity_factor > 0:
        a.breakeven_alternative_cost = (a.current_annual_cost - rec - one / a.annuity_factor) / scale if scale else None
        # largest one-time cost still giving NPV >= 0; none exists when annual savings are not positive
        a.breakeven_switching_cost = a.annual_savings * a.annuity_factor if a.annual_savings > 0 else None
    a.complete = True
    return a


def within_willingness_to_pay(appraisal: SwitchingAppraisal, wtp: Optional[float]):
    """True/False when a management willingness-to-pay (SAR per tCO2e, discounted lifetime basis) is set; None if not set."""
    if wtp is None or appraisal.lifetime_discounted_cost_per_t is None:
        return None
    return appraisal.lifetime_discounted_cost_per_t <= wtp
