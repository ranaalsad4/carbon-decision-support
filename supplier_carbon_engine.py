"""Phase 11 - supplier carbon comparison and the shared activity ledger (double-counting control).

  tonne-km           = freight mass (t) x distance (km)
  emissions (tCO2e)  = tonne-km x EF (kgCO2e/t-km) / 1,000
  intensity          = emissions x 1,000 / tonne-km   (kgCO2e/t-km)
  avoided            = current equivalent-service emissions - alternative equivalent-service emissions
                       (only the substituted share of the lane is changed)

Shared activity ledger: every intervention is a transformation of the SAME activity rows.
  freight efficiency (Workstream C, Phase 8 rate)  -> activity x (1 - rate)
  supplier switching (Phase 11)                    -> factor of the substituted share = alternative EF
  combined emissions = adjusted activity x applicable factor; combined avoided = baseline - combined.
The overlap (sum of separate avoided - combined avoided) is reported and never double counted.
The historical inventory is not modified; Contractor B (no activity) is never added.
"""
from dataclasses import dataclass, field
from typing import List, Optional

import calc_engine as ce
import workstream_c_inputs as wi
from supplier_models import REFERENCE_BOUNDARY, Phase11Data
from supplier_screening_engine import equivalence


def tonne_km(mass_t, distance_km):
    if mass_t is None or distance_km is None:
        return None
    if mass_t < 0 or distance_km < 0:
        raise ValueError("mass and distance must be non-negative")
    return mass_t * distance_km


def emissions_t(tkm, ef_kg_per_tkm):
    if tkm is None or ef_kg_per_tkm is None:
        return None
    if tkm < 0 or ef_kg_per_tkm < 0:
        raise ValueError("activity and emission factor must be non-negative")
    return tkm * ef_kg_per_tkm / 1000.0


def intensity(emissions, tkm):
    """kgCO2e per tonne-km; None when activity is zero or unknown (no division by zero)."""
    if emissions is None or tkm is None or tkm <= 0:
        return None
    return emissions * 1000.0 / tkm


@dataclass
class CarbonComparison:
    lane_id: str
    current_offer: str
    alternative_offer: str
    comparable: bool
    limitations: List[str]
    share: float
    substituted_tonne_km: Optional[float] = None
    current_ef: Optional[float] = None
    alternative_ef: Optional[float] = None
    current_emissions_t: Optional[float] = None       # substituted volume, current supplier
    alternative_emissions_t: Optional[float] = None   # substituted volume, alternative
    avoided_t: Optional[float] = None
    reduction_pct: Optional[float] = None
    direction: Optional[str] = None                   # reduction | no change | increase
    current_intensity: Optional[float] = None
    alternative_intensity: Optional[float] = None


def compare(data: Phase11Data, current_id: str, alternative_id: str, share: float = None, ef_current=None,
            ef_alternative=None, demand_tkm=None) -> CarbonComparison:
    share = data.settings.substitution_share if share is None else share
    cur, alt = data.offers[current_id], data.offers[alternative_id]
    eq = equivalence(data, current_id, alternative_id, share)
    lim = list(eq.limitations)
    for tag, o in (("current", cur), ("alternative", alt)):
        if o.ef is None or o.ef.value_kg_per_tkm is None:
            lim.append(f"{tag} emission factor missing")
        elif not o.ef.unit_valid:
            lim.append(f"{tag} emission-factor unit invalid")
        elif o.ef.boundary is None or o.ef.boundary.lower() != REFERENCE_BOUNDARY.lower():
            lim.append(f"{tag} boundary '{o.ef.boundary}' differs from '{REFERENCE_BOUNDARY}': not comparable")
        elif (o.ef.gas_coverage or "CO2e").upper() != "CO2E":
            lim.append(f"{tag} factor gas coverage is not CO2e")
    c = CarbonComparison(cur.lane_id, current_id, alternative_id, not lim, lim, share)
    if lim:
        return c
    efc = cur.ef.value_kg_per_tkm if ef_current is None else ef_current
    efa = alt.ef.value_kg_per_tkm if ef_alternative is None else ef_alternative
    base_tkm = cur.tonne_km if demand_tkm is None else demand_tkm
    sub = base_tkm * share
    ec, ea = emissions_t(sub, efc), emissions_t(sub, efa)
    av = ec - ea
    c.substituted_tonne_km, c.current_ef, c.alternative_ef = sub, efc, efa
    c.current_emissions_t, c.alternative_emissions_t, c.avoided_t = ec, ea, av
    c.reduction_pct = (av / ec) if ec > 0 else None
    c.direction = "reduction" if av > 1e-12 else "increase" if av < -1e-12 else "no change"
    c.current_intensity, c.alternative_intensity = intensity(ec, sub), intensity(ea, sub)
    return c


# ----------------------------------------------------------------------------- activity ledger
@dataclass
class LedgerRow:
    offer_id: str
    supplier_id: str
    lane_id: str
    tonne_km: Optional[float]
    ef_current: Optional[float]
    ef_basis: str
    efficiency_rate: float
    switch_share: float
    ef_alternative: Optional[float]
    baseline_t: Optional[float] = None
    efficiency_only_t: Optional[float] = None
    switching_only_t: Optional[float] = None
    combined_t: Optional[float] = None
    status: str = "quantified"
    notes: List[str] = field(default_factory=list)


def _row_emissions(tkm, ef_cur, ef_alt, eff, share):
    adj = tkm * (1 - eff)
    return emissions_t(adj * (1 - share), ef_cur) + (emissions_t(adj * share, ef_alt) if share else 0.0)


def activity_ledger(data: Phase11Data, basis="decision", switch_lane="L1", alternative_id="OF-D-L1", share=None,
                    efficiency_rate=None, include_efficiency=True, include_switching=True):
    """Ledger over the known incumbent freight activity (Contractors A and C; B has none).
    basis 'decision': each lane's own factor (supplier-specific where documented, else proxy).
    basis 'inventory': the Phase 4 proxy factor for every row (reproduces the inventory and Workstream C)."""
    share = data.settings.substitution_share if share is None else share
    if efficiency_rate is None:
        efficiency_rate = wi.load_phase8()["B"]["reduction"]   # Workstream C freight optimisation (15%)
    proxy_id = "FAC-FRT-ROAD-01"
    proxy = float(ce.v.load_registers()[0][proxy_id]["factor_value"])
    targets = set(wi.TARGETS["B"]["suppliers"])               # suppliers in the Workstream C freight scenario
    alt = data.offers.get(alternative_id)
    ef_alt = alt.ef.value_kg_per_tkm if alt and alt.ef else None
    rows = []
    for o in sorted(data.offers.values(), key=lambda x: x.offer_id):
        if (o.role or "").lower() != "incumbent":
            continue
        s = data.suppliers.get(o.supplier_id)
        inv_id = s.inventory_supplier_id if s else None
        if basis == "inventory":
            ef_c, ef_basis = (proxy, f"inventory proxy {proxy_id}") if o.tonne_km is not None else (None, "n/a")
        else:
            ef_c = o.ef.value_kg_per_tkm if o.ef else None
            ef_basis = (o.ef.verification or "") + (f" ({o.ef.linked_factor_id})" if o.ef and o.ef.linked_factor_id else "") if o.ef else "missing"
        eff = efficiency_rate if include_efficiency and inv_id in targets else 0.0
        sw = share if include_switching and o.lane_id == switch_lane and ef_alt is not None else 0.0
        row = LedgerRow(o.offer_id, o.supplier_id, o.lane_id, o.tonne_km, ef_c, ef_basis, eff, sw, ef_alt if sw else None)
        if o.tonne_km is None or ef_c is None:
            row.status = "UNAVAILABLE - missing activity or factor (not zero, not added to the ledger totals)"
            rows.append(row)
            continue
        row.baseline_t = emissions_t(o.tonne_km, ef_c)
        row.efficiency_only_t = _row_emissions(o.tonne_km, ef_c, ef_alt, eff, 0.0)
        row.switching_only_t = _row_emissions(o.tonne_km, ef_c, ef_alt, 0.0, sw)
        row.combined_t = _row_emissions(o.tonne_km, ef_c, ef_alt, eff, sw)
        if eff and sw:
            row.notes.append("OVERLAP: efficiency and switching act on the same activity; combined computed jointly")
        rows.append(row)
    q = [r for r in rows if r.baseline_t is not None]
    tot = {k: sum(getattr(r, k) for r in q) for k in ("baseline_t", "efficiency_only_t", "switching_only_t", "combined_t")}
    eff_av = tot["baseline_t"] - tot["efficiency_only_t"]
    sw_av = tot["baseline_t"] - tot["switching_only_t"]
    comb_av = tot["baseline_t"] - tot["combined_t"]
    summary = {"basis": basis, "efficiency_rate": efficiency_rate, "switch_lane": switch_lane, "switch_share": share,
               "alternative_offer": alternative_id, "alternative_ef": ef_alt, **tot,
               "efficiency_avoided_t": eff_av, "switching_avoided_t": sw_av, "combined_avoided_t": comb_av,
               "sum_of_separate_avoided_t": eff_av + sw_av, "overlap_t": eff_av + sw_av - comb_av,
               "unavailable_rows": [r.offer_id for r in rows if r.baseline_t is None]}
    return rows, summary
