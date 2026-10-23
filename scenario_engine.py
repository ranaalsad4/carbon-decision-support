"""Workstream C, Phase 8 - reduction scenario engine.

Applies the Phase 8 reduction assumptions to the Phase 4 activity RECORDS and recalculates each
scenario with the unchanged Workstream B / Phase 4 engine (calc_engine.run -> validate_phase4).
Emission factors, factor IDs, units, missing-data handling and audit fields are therefore exactly
those of the baseline. Nothing in phase4/data is modified: scenarios work on in-memory copies.

    python scenario_engine.py          # writes outputs/workstream_c/scenario_*.csv

Scenario quantity per record  = baseline quantity x PRODUCT over applicable interventions of (1 - rate)
Scenario emissions per record = scenario quantity x factor (kg/unit) / 1,000   (Phase 4 calculator)
Avoided                       = baseline emissions - scenario emissions

Why a product, not a sum: if two interventions ever acted on the same record, adding their rates
would double count (e.g. 10% + 10% = 20% instead of 1 - 0.9 x 0.9 = 19%). In the default
scenarios A, B and C act on different records, so the combined result equals the sum.

Contractor B has no activity data: its records stay NULL, are never scaled and never become zero.
Reduction rates are SYNTHETIC ASSUMPTIONS (Phase 8 'Evidence status'), not verified savings.
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

import calc_engine as ce
import workstream_c_inputs as wi

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs" / "workstream_c"
ENGINE_VERSION = "WSC-8.0"
COMBINED = "ABC"


def baseline():
    """Workstream B baseline (unchanged engine). Returns (records, audit, sources)."""
    records = ce.v.read("activity_data_clean.csv")
    audit, findings = ce.run(records)
    if [f for f in findings if f["severity"] == "BLOCK"]:
        raise RuntimeError("baseline has BLOCK findings - scenarios not calculated")
    return records, audit, ce.by_source(audit)


def target_baseline(sources):
    """Baseline tCO2e of each intervention's target records (quantified sources only)."""
    out = {}
    for iid, t in wi.TARGETS.items():
        out[iid] = round(sum(s["emissions_t"] for s in sources if s["activity_type"] == t["activity_type"]
                             and s["supplier_id"] in t["suppliers"] and s["emissions_t"] is not None), 6)
    return out


def default_rates(p8=None):
    p8 = p8 or wi.load_phase8()
    return {iid: p8[iid]["reduction"] for iid in wi.IDS}


def applies(iid, record):
    t = wi.TARGETS[iid]
    return record["activity_type"] == t["activity_type"] and record["supplier_id"] in t["suppliers"]


def scenario_records(records, rates, include):
    """In-memory copies with scaled quantities. Missing quantities stay missing (never 0)."""
    out, meta = [], []
    for r in records:
        new = dict(r)
        ivs = [i for i in include if applies(i, r)]
        mult = 1.0
        for i in ivs:
            mult *= (1.0 - rates[i])
        q = r["quantity"].strip()
        if ivs and q:
            new["quantity"] = ce.num(float(q) * mult)
        meta.append({"interventions": "+".join(ivs), "multiplier": mult if ivs else 1.0,
                     "missing": q == ""})
        out.append(new)
    return out, meta


def run_scenario(include, rates=None, base=None, p8=None):
    """Calculate one scenario. include: iterable of intervention IDs ('A','B','C')."""
    rates = rates or default_rates(p8)
    for i, v in rates.items():
        if not 0 <= v < 1:
            raise ValueError(f"reduction rate for {i} must be in [0, 1): {v}")
    include = [i for i in wi.IDS if i in include]
    records, b_audit, b_sources = base or baseline()
    recs, meta = scenario_records(records, rates, include)
    audit, findings = ce.run(recs)
    blocks = [f for f in findings if f["severity"] == "BLOCK"]
    if blocks:
        raise RuntimeError(f"scenario {include} produced BLOCK findings: {blocks[:3]}")
    sid = "".join(include) or "BASELINE"
    rows = []
    for b, s, m in zip(b_audit, audit, meta):
        assert b["activity_id"] == s["activity_id"]
        be = float(b["emissions_t"]) if b["emissions_t"] else None
        se = float(s["emissions_t"]) if s["emissions_t"] else None
        rows.append({
            "scenario_id": sid, "activity_id": b["activity_id"], "period": b["period"], "scope": b["scope"],
            "scope3_category": b["scope3_category"], "stream": b["stream"], "supplier_id": b["supplier_id"],
            "interventions_applied": m["interventions"] or "none",
            "reduction_rate_applied": round(1 - m["multiplier"], 10),
            "baseline_quantity": b["quantity_calc"], "scenario_quantity": s["quantity_calc"], "unit": s["unit_calc"],
            "factor_id": s["factor_id"], "factor_value": s["factor_value"], "factor_unit": s["factor_unit"],
            "gas_coverage": s["gas_coverage"], "factor_verification": s["factor_verification"],
            "factor_source": s["factor_source"], "factor_applicable_year": s["factor_applicable_year"],
            "baseline_emissions_t": "" if be is None else f"{be:.6f}",
            "scenario_emissions_t": "" if se is None else f"{se:.6f}",
            "avoided_t": "" if be is None else f"{be - se:.6f}",
            "emissions_unit": s["emissions_unit"], "calc_status": s["calc_status"],
            "missing_data_flag": "MISSING - not calculated, not zero" if m["missing"] else "",
            "quality_flags": s["quality_flags"], "formula": s["formula"],
            "record_type": "scenario (synthetic assumption)" if m["interventions"] else "baseline (unchanged)",
            "engine_version": ENGINE_VERSION,
        })
    return {"id": sid, "include": include, "rates": {i: rates[i] for i in include}, "audit": rows,
            "sources": ce.by_source(audit), "baseline_sources": b_sources}


def summarise(result, quantified_total):
    """Annual totals by stream and scope for one scenario result."""
    rows = result["audit"]
    by_stream = defaultdict(lambda: {"baseline": 0.0, "scenario": 0.0, "missing": 0, "n": 0})
    for r in rows:
        k = (r["scope"], r["stream"])
        s = by_stream[k]
        s["n"] += 1
        if r["missing_data_flag"]:
            s["missing"] += 1
        else:
            s["baseline"] += float(r["baseline_emissions_t"]); s["scenario"] += float(r["scenario_emissions_t"])
    out = []
    for (scope, stream), s in sorted(by_stream.items()):
        if s["missing"] == s["n"]:
            out.append({"scope": scope, "stream": stream, "baseline_t": None, "scenario_t": None, "avoided_t": None,
                        "reduction_pct_of_stream": None, "status": "UNAVAILABLE - missing activity data (not zero)"})
            continue
        av = s["baseline"] - s["scenario"]
        out.append({"scope": scope, "stream": stream, "baseline_t": round(s["baseline"], 6),
                    "scenario_t": round(s["scenario"], 6), "avoided_t": round(av, 6),
                    "reduction_pct_of_stream": round(100 * av / s["baseline"], 6) if s["baseline"] else 0.0,
                    "status": "INCOMPLETE" if s["missing"] else "COMPLETE"})
    tot_b = sum(r["baseline_t"] for r in out if r["baseline_t"] is not None)
    tot_s = sum(r["scenario_t"] for r in out if r["scenario_t"] is not None)
    assert abs(tot_b - quantified_total) < 1e-6, (tot_b, quantified_total)
    return out, round(tot_b, 6), round(tot_s, 6)


def monthly(result):
    agg = defaultdict(lambda: [0.0, 0.0, False])
    for r in result["audit"]:
        k = (r["period"], r["scope"], r["stream"])
        if r["missing_data_flag"]:
            agg[k][2] = True
            continue
        agg[k][0] += float(r["baseline_emissions_t"]); agg[k][1] += float(r["scenario_emissions_t"])
    out = []
    for (p, scope, stream), (b, s, miss) in sorted(agg.items()):
        out.append({"scenario_id": result["id"], "period": p, "scope": scope, "stream": stream,
                    "baseline_t": None if miss else round(b, 6), "scenario_t": None if miss else round(s, 6),
                    "avoided_t": None if miss else round(b - s, 6), "emissions_unit": "tCO2e",
                    "status": "UNAVAILABLE (missing, not zero)" if miss else "calculated"})
    return out


def run_all(rates=None, include_combined=True):
    """Default scenarios A, B, C (+ combined). Returns dict with per-scenario results and comparison table."""
    p8 = wi.load_phase8()
    rates = rates or default_rates(p8)
    base = baseline()
    _, _, sources = base
    qt, units = ce.quantified_total(sources)
    assert units == ["tCO2e"], units
    tb = target_baseline(sources)
    ids = [[i] for i in wi.IDS] + ([list(wi.IDS)] if include_combined else [])
    results = {}
    comparison = []
    for inc in ids:
        res = run_scenario(inc, rates, base, p8)
        streams, tot_b, tot_s = summarise(res, qt)
        avoided = round(tot_b - tot_s, 6)
        aff_base = round(sum(tb[i] for i in inc), 6)
        res.update({"streams": streams, "total_baseline_t": tot_b, "total_scenario_t": tot_s, "avoided_t": avoided})
        results[res["id"]] = res
        names = " + ".join(p8[i]["Intervention"] for i in inc)
        comparison.append({
            "scenario_id": res["id"], "scenario": names if len(inc) == 1 else f"Combined ({names})",
            "interventions": "+".join(inc), "reduction_rates": "; ".join(f"{i}={rates[i]:.4g}" for i in inc),
            "affected_streams": "; ".join(wi.TARGETS[i]["stream_label"] for i in inc),
            "affected_baseline_t": aff_base, "avoided_t": avoided,
            "reduction_pct_of_affected": round(100 * avoided / aff_base, 6) if aff_base else 0.0,
            "quantified_baseline_t": tot_b, "quantified_scenario_t": tot_s,
            "reduction_pct_of_quantified": round(100 * avoided / tot_b, 6),
            "scope1_avoided_t": round(sum(s["avoided_t"] or 0 for s in streams if s["scope"] == "1"), 6),
            "scope2_avoided_t": round(sum(s["avoided_t"] or 0 for s in streams if s["scope"] == "2"), 6),
            "scope3_avoided_t": round(sum(s["avoided_t"] or 0 for s in streams if s["scope"] == "3"), 6),
            "contractor_b": "UNAVAILABLE - not quantified, not reduced, not zero",
            "evidence_status": "; ".join(f"{i}: {p8[i]['Evidence status']}" for i in inc),
            "coverage_note": "Quantified known-data total only (excludes Contractor B); not complete corporate emissions",
        })
    return {"rates": rates, "p8": p8, "baseline_sources": sources, "quantified_total": qt,
            "target_baseline": tb, "results": results, "comparison": comparison}


def assumptions_table(p8, rates, tb):
    rows = []
    for iid in wi.IDS:
        r = p8[iid]
        t = wi.TARGETS[iid]
        rows.append({
            "id": iid, "intervention": r["Intervention"], "scope_stream_workbook": r["Scope / stream"],
            "target_activity_type": t["activity_type"], "target_suppliers": ";".join(t["suppliers"]),
            "reduction_rate": rates[iid], "reduction_rate_source": r["Reduction assumption ref"],
            "workbook_default_rate": r["reduction"],
            "baseline_t_engine": tb[iid], "baseline_t_workbook": r["baseline_t_workbook"],
            "baseline_t_workbook_ref": r["Baseline tCO2e ref"],
            "workbook_avoided_t_cached": r["Avoided tCO2e cached"], "workbook_avoided_ref": r["Avoided tCO2e ref"],
            "activity_unit_workbook": r["Activity unit"], "mechanism": r["Mechanism / theory of change"],
            "evidence_basis": r["Evidence basis"], "evidence_status": r["Evidence status"],
            "dependencies": r["Key dependencies"], "limitations": r["Limitations / validation needed"],
            "source_url": r["Source URL"],
        })
    return rows


def _fmt(v):
    if v is None:
        return "UNAVAILABLE"
    if isinstance(v, float):
        return f"{v:.6f}".rstrip("0").rstrip(".") if v == v else ""
    return v


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = []
    for r in rows:
        fields += [k for k in r if k not in fields]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, restval="")
        w.writeheader()
        w.writerows({k: _fmt(v) for k, v in r.items()} for r in rows)
    return path


def main(out_dir=None):
    out = Path(out_dir) if out_dir else OUT
    res = run_all()
    files = {}
    files["scenario_assumptions.csv"] = write_csv(out / "scenario_assumptions.csv",
                                                  assumptions_table(res["p8"], res["rates"], res["target_baseline"]))
    files["scenario_comparison.csv"] = write_csv(out / "scenario_comparison.csv", res["comparison"])
    mon = [m for r in res["results"].values() for m in monthly(r)]
    files["scenario_monthly.csv"] = write_csv(out / "scenario_monthly.csv", mon)
    aud = [a for r in res["results"].values() for a in r["audit"]]
    files["scenario_audit_trail.csv"] = write_csv(out / "scenario_audit_trail.csv", aud)
    print(f"Quantified baseline: {res['quantified_total']:,.3f} tCO2e (Contractor B unavailable)")
    for c in res["comparison"]:
        print(f"  {c['scenario_id']:<4} avoided {c['avoided_t']:>10,.4f} tCO2e  "
              f"({c['reduction_pct_of_affected']:.2f}% of affected, {c['reduction_pct_of_quantified']:.3f}% of quantified)")
    return files


if __name__ == "__main__":
    main()
