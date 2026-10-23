"""Phase 11 - audit trail, monitoring scorecard and the end-to-end run (writes outputs/phase11/).

    python supplier_audit.py          # or: python run_phase11.py

Audit records carry version metadata (register SHA-256 + engine version), never wall-clock time, so the
written outputs are reproducible; the dashboard adds a generation timestamp to its own downloads.
No verification certificates or audit findings are invented: verification fields report only what
the register states.
"""
import hashlib
import json
from datetime import date
from pathlib import Path

import calc_engine as ce
import supplier_carbon_engine as sce
import supplier_engagement_engine as see
import supplier_recommendation_engine as sre
import supplier_scoring_engine as ssc
import supplier_screening_engine as sse
import supplier_uncertainty_engine as sue
from supplier_data_loader import REGISTER, inventory_by_supplier, load_register
from supplier_financial_engine import appraise
from supplier_models import ENGINE_VERSION

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs" / "phase11"
PLAN_START = date(2026, 1, 1)   # deterministic default; editable in the dashboard


def analyse(data=None, weights=None, wtp="settings", hypothetical=None, start=PLAN_START):
    """Run every Phase 11 engine on one dataset. Pure function of its inputs."""
    data = data or load_register()
    inv = inventory_by_supplier()
    scr = sse.screen_all(data)
    eng = see.assess(data, inv, hypothetical=hypothetical, screening=scr, start=start)
    recs = sre.recommend_all(data, scr, eng, weights, wtp)
    scoring = {lid: ssc.score_lane(data, lid, scr, weights) for lid in sorted(data.lanes)}
    comps, fins = [], []
    for lid, lane in sorted(data.lanes.items()):
        inc = lane.incumbent_offer_id
        if inc not in data.offers:
            continue
        for o in data.lane_offers(lid):
            if o.offer_id == inc:
                continue
            c = sce.compare(data, inc, o.offer_id)
            comps.append(c)
            if c.comparable:
                fins.append(appraise(data, inc, o.offer_id, c.avoided_t))
    demo = ("OF-A-L1", "OF-D-L1") if {"OF-A-L1", "OF-D-L1"} <= set(data.offers) else None
    unc = {}
    if demo and sce.compare(data, *demo).comparable:
        base, ow = sue.one_way(data, *demo)
        unc = {"pair": demo, "base": base, "one_way": ow, "joint": sue.joint_cases(data, *demo),
               "breakevens": sue.breakevens(data, *demo), "grid": sue.grid(data, *demo, wtp=data.settings.willingness_to_pay
                                                                            if wtp == "settings" else wtp),
               "ranking_reversals": sue.ranking_reversals(data, "L1", *demo, scr, weights),
               "weight_sensitivity": ssc.weight_sensitivity(data, "L1", scr, weights),
               "robustness": sre.recommendation_robustness(data, "L1", scr, eng, wtp)}
    ledger = {b: sce.activity_ledger(data, basis=b) for b in ("decision", "inventory")}
    return {"data": data, "inventory": inv, "screening": scr, "engagement": eng, "recommendations": recs,
            "scoring": scoring, "comparisons": comps, "financials": fins, "uncertainty": unc, "ledger": ledger}


def monitoring_scorecard(res):
    data, inv, eng = res["data"], res["inventory"], res["engagement"]
    mon = {m["indicator"]: m for m in data.monitoring}
    rows = []
    for sid, e in eng.items():
        s = data.suppliers[sid]
        i = inv.get(s.inventory_supplier_id, {})
        offs = [o for o in data.supplier_offers(sid) if (o.role or "").lower() == "incumbent"]
        tk = sum(o.tonne_km for o in offs if o.tonne_km is not None)
        prim = sum(o.tonne_km for o in offs if o.tonne_km is not None and o.ef and o.ef.verification
                   and not o.ef.verification.startswith("Proxy"))
        plan = e.plan
        done = sum(1 for a in plan if a["status"] == "Completed")
        ver = sorted({o.ef.verification for o in offs if o.ef and o.ef.verification})
        tl = mon.get("reporting_timeliness_days", {}).get(sid)
        rows.append({
            "supplier_id": sid, "supplier": s.name,
            "data_completeness": f"{i.get('records_with_data', 0)}/{i.get('records', 0)} months",
            "primary_data_share": (f"{prim / tk:.0%} of tonne-km with supplier-specific factor" if tk else "n/a (no activity)"),
            "evidence_verification_status": ", ".join(ver) or "none recorded",
            "engagement_action_completion": f"{done}/{len(plan)} actions completed",
            "carbon_intensity_change": "n/a - first reporting year (no prior period)",
            "transport_activity_change": "n/a - first reporting year (no prior period)",
            "projected_reduction_tco2e": "see recommendations (projected, not verified)",
            "verified_actual_reduction_tco2e": "none - no post-implementation data",
            "financial_outcome": "n/a - no implemented change",
            "reporting_timeliness": (f"{tl:g} days late on average" if isinstance(tl, (int, float)) else "no reports received"),
            "maturity_score_baseline": (f"{e.maturity.score:.1f}" if e.maturity.score is not None else "unclassified"),
            "maturity_improvement": "n/a - baseline assessment",
        })
    return rows


def audit_records(res):
    data = res["data"]
    rows = []
    for lid, r in res["recommendations"].items():
        for oid in [r.incumbent_offer] + [o.offer_id for o in data.lane_offers(lid) if o.offer_id != r.incumbent_offer]:
            if oid not in data.offers:
                continue
            o = data.offers[oid]
            ef = o.ef
            rows.append({
                "input_version": data.input_version[:16], "engine_version": ENGINE_VERSION, "lane_id": lid,
                "offer_id": oid, "supplier_id": o.supplier_id, "role": o.role,
                "source": f"{Path(data.source_path).name}: Freight Activity / Emission Factors / Financial Inputs ({oid})",
                "reporting_period": o.period, "calculation_method": ef.method if ef else None,
                "emission_factor": (f"{ef.ef_id} {ef.value_kg_per_tkm:g} kgCO2e/t-km" if ef and ef.value_kg_per_tkm is not None
                                    else "missing"),
                "ef_verification": ef.verification if ef else None, "ef_note": ef.note if ef else "",
                "tonne_km": o.tonne_km, "emissions_t": o.emissions_t,
                "eligibility": res["screening"][oid].eligibility,
                "model_assumptions": " | ".join(r.material_assumptions),
                "recommendation_rule": f"{r.rule_id}: {r.rule}" if oid == r.incumbent_offer or oid == r.best_alternative else
                "not selected (see excluded alternatives)" if oid != r.incumbent_offer else "",
                "lane_action": r.action, "evidence_status": o.data_class,
                "synthetic": "yes - demonstration data",
            })
    return rows


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.6f}".rstrip("0").rstrip(".") if v == v else ""
    if isinstance(v, (list, tuple)):
        return " | ".join(str(x) for x in v)
    return v


def write_csv(path, rows):
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = []
    for r in rows:
        fields += [k for k in r if k not in fields]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields or ["empty"], restval="")
        w.writeheader()
        w.writerows({k: _fmt(v) for k, v in r.items()} for r in rows)
    return path


def tables(res):
    """All Phase 11 result tables as lists of dicts (used for CSV files and dashboard downloads)."""
    data = res["data"]
    t = {}
    t["supplier_screening.csv"] = [
        {"offer_id": r.offer_id, "supplier_id": r.supplier_id, "lane_id": r.lane_id, "eligibility": r.eligibility,
         **{f"check_{c.check_no:02d}": f"{c.status}{' (auto)' if c.derived else ''}" for c in r.checks},
         "blocking_reasons": r.blocking_reasons, "missing_material": r.missing_material, "conditions": r.conditions,
         "carbon_comparable": r.carbon_comparable} for r in res["screening"].values()]
    t["supplier_data_quality.csv"] = []
    for sid in data.suppliers:
        dq = sse.data_quality(data, sid)
        t["supplier_data_quality.csv"].append({"supplier_id": sid, **{sse.DQ_LABELS[k]: v for k, v in dq.dimensions.items()},
                                               "score_0_100": dq.score, "usable_estimate": dq.usable_estimate, "note": dq.note})
    t["supplier_engagement_matrix.csv"] = [
        {"supplier_id": sid, "impact_score": e.impact.score, "impact_status": e.impact.status, "impact_basis": e.impact.basis,
         "emissions_share": e.impact.components.get("emissions_share"), "volume_share": e.impact.components.get("volume_share"),
         "materiality_score": e.impact.components.get("materiality_score"), "maturity_score": e.maturity.score,
         "maturity_status": e.maturity.status, "indicators_assessed": e.maturity.assessed, "quadrant": e.quadrant,
         "priority": e.priority, "label": e.label, "actions": e.actions, "limitations": e.limitations,
         "impact_threshold": data.matrix.impact_threshold, "maturity_threshold": data.matrix.maturity_threshold}
        for sid, e in res["engagement"].items()]
    t["engagement_action_plans.csv"] = [a for e in res["engagement"].values() for a in e.plan]
    t["supplier_comparison.csv"] = []
    for o in data.offers.values():
        s = data.suppliers.get(o.supplier_id)
        t["supplier_comparison.csv"].append({
            "offer_id": o.offer_id, "supplier": s.name if s else o.supplier_id, "relationship": s.relationship if s else None,
            "lane_id": o.lane_id, "role": o.role, "freight_mass_t": o.mass_t, "route_distance_km": o.distance_km,
            "tonne_km": o.tonne_km, "mode": s.mode if s else None, "fuel_technology": s.fuel_technology if s else None,
            "service_geography": f"{o.origin} -> {o.destination}", "offered_capacity_t": o.capacity_t,
            "reporting_period": o.period, "ef_kgco2e_per_tkm": o.ef.value_kg_per_tkm if o.ef else None,
            "annual_emissions_t": o.emissions_t, "annual_contract_cost_sar": o.annual_cost, "on_time_pct": o.on_time_pct,
            "eligibility": res["screening"][o.offer_id].eligibility,
            "data_confidence": sse.data_quality(data, o.supplier_id).score, "evidence_status": o.ef.verification if o.ef else None,
            "data_class": o.data_class,
            "inventory_note": ("inventory baseline unchanged (Workstream B)" if s and s.is_existing else "hypothetical")})
    t["switching_financials.csv"] = [
        {"current_offer": a.current_offer, "alternative_offer": a.alternative_offer, "share": a.share,
         "annual_cost_difference_sar": a.annual_cost_difference, "one_time_cost_sar": a.one_time_cost,
         "recurring_cost_sar": a.recurring_cost, "switching_npv_sar": a.npv, "payback_years": a.payback_years,
         "avoided_t_per_year": a.avoided_t, "annual_cost_per_t_sar": a.annual_cost_per_t,
         "discounted_lifetime_cost_per_t_sar": a.lifetime_discounted_cost_per_t,
         "breakeven_alternative_annual_cost_sar": a.breakeven_alternative_cost,
         "discount_rate": a.discount_rate, "horizon_years": a.horizon_years, "note": a.note} for a in res["financials"]]
    t["carbon_comparison.csv"] = [
        {"lane_id": c.lane_id, "current_offer": c.current_offer, "alternative_offer": c.alternative_offer,
         "comparable": c.comparable, "limitations": c.limitations, "substituted_tonne_km": c.substituted_tonne_km,
         "current_ef": c.current_ef, "alternative_ef": c.alternative_ef, "current_emissions_t": c.current_emissions_t,
         "alternative_emissions_t": c.alternative_emissions_t, "avoided_t": c.avoided_t, "reduction_pct": c.reduction_pct,
         "direction": c.direction} for c in res["comparisons"]]
    t["supplier_scores.csv"] = [
        {"lane_id": lid, "offer_id": r.offer_id, "eligibility": r.eligibility,
         **{f"score_{k}": v for k, v in r.scores.items()}, **{f"weight_{k}": s.weights[k] for k in s.weights},
         **{f"contribution_{k}": v for k, v in r.contributions.items()}, "total": r.total, "rank": r.rank,
         "ranking_status": s.ranking_status, "status": r.status, "missing": r.missing}
        for lid, s in res["scoring"].items() for r in s.rows]
    t["supplier_recommendations.csv"] = [r.as_row() for r in res["recommendations"].values()]
    t["activity_ledger.csv"] = [
        {"basis": b, "offer_id": r.offer_id, "supplier_id": r.supplier_id, "lane_id": r.lane_id, "tonne_km": r.tonne_km,
         "ef_current": r.ef_current, "ef_basis": r.ef_basis, "efficiency_rate": r.efficiency_rate,
         "switch_share": r.switch_share, "ef_alternative": r.ef_alternative, "baseline_t": r.baseline_t,
         "efficiency_only_t": r.efficiency_only_t, "switching_only_t": r.switching_only_t, "combined_t": r.combined_t,
         "status": r.status, "notes": r.notes} for b, (rows, _) in res["ledger"].items() for r in rows]
    t["activity_ledger_summary.csv"] = [{k: v for k, v in s.items()} for _, s in res["ledger"].values()]
    u = res["uncertainty"]
    if u:
        t["supplier_uncertainty_oneway.csv"] = u["one_way"]
        t["supplier_uncertainty_cases.csv"] = [{"case": k, **{kk: vv for kk, vv in v.items() if kk != "values"},
                                                "values": "; ".join(f"{a}={b:g}" for a, b in v["values"].items())}
                                               for k, v in u["joint"].items()]
        t["supplier_breakeven.csv"] = [u["breakevens"]]
        t["supplier_scenario_grid.csv"] = u["grid"]
        t["supplier_ranking_reversals.csv"] = u["ranking_reversals"] + [
            {"variable": f"weight {x['criterion']} {x['change_pp']:+d} pp", "result": "reversal" if x["reversal"] else
             "no reversal", "top_offer": x["top_offer"], "reversal": x["reversal"]} for x in u["weight_sensitivity"][0]]
        rb, robust = u["robustness"]
        t["recommendation_robustness.csv"] = [{**x, "robust_overall": robust} for x in rb]
    t["monitoring_scorecard.csv"] = monitoring_scorecard(res)
    t["supplier_audit_trail.csv"] = audit_records(res)
    t["validation_issues.csv"] = [{"level": i.level, "where": i.where, "message": i.message} for i in data.issues] or \
        [{"level": "", "where": "", "message": "no validation issues"}]
    return t


def main(out_dir=None):
    out = Path(out_dir) if out_dir else OUT
    res = analyse()
    t = tables(res)
    for name, rows in t.items():
        write_csv(out / name, rows)
    files = sorted(p for p in out.iterdir() if p.is_file() and p.name != "run_manifest_p11.json")
    manifest = {"engine_version": ENGINE_VERSION,
                "inputs": {REGISTER.name: hashlib.sha256(REGISTER.read_bytes()).hexdigest(),
                           **{f"phase4/data/{n}": hashlib.sha256((ce.PHASE4 / "data" / n).read_bytes()).hexdigest()
                              for n in ce.INPUT_FILES}},
                "outputs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                "note": "Synthetic demonstration. Identical inputs reproduce identical output hashes."}
    (out / "run_manifest_p11.json").write_text(json.dumps(manifest, indent=2))
    for lid, r in res["recommendations"].items():
        print(f"  {lid} {r.incumbent_offer:<8} -> {r.action:<34} [{r.rule_id}] alt={r.best_alternative}")
    led = res["ledger"]["decision"][1]
    print(f"  ledger (decision basis): efficiency {led['efficiency_avoided_t']:.3f} + switching {led['switching_avoided_t']:.3f}"
          f" = {led['sum_of_separate_avoided_t']:.3f} vs combined {led['combined_avoided_t']:.3f} (overlap {led['overlap_t']:.3f})")
    print("Outputs written to", out)
    return res


if __name__ == "__main__":
    main()
