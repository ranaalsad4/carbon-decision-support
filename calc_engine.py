"""Workstream B, Phase 6 - emissions calculation engine.

Reuses the Phase 4 data (phase4/data/*.csv) and validator (phase4/validate_phase4.py)
without modifying them. Adds a full calculation audit trail, aggregation by
source / scope / month, and a reproducibility manifest (SHA-256 of inputs and outputs).

    python calc_engine.py      # writes outputs/*.csv and outputs/run_manifest.json

Rules carried over from Phase 4:
  * emissions (t) = quantity x factor (kg per unit) / 1,000, one factor per record
  * BLOCKED records are not calculated; missing activity is never replaced by zero
  * the factor's gas label is kept (tCO2 or tCO2e); totals are only formed within one gas label.
    Since v6.1 all three factors are CO2e, so an indicative quantified total is formed.

v6.1: the electricity factor is read from the updated Phase 4 library (FAC-ELEC-SEC-01,
SEC 2024, provisional location-based Scope 2 proxy). No factor value is hard-coded here.
"""
import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
PHASE4 = HERE / "phase4"
OUT = HERE / "outputs"
sys.path.insert(0, str(PHASE4))
import validate_phase4 as v  # noqa: E402  (Phase 4 validator, reused unchanged)

ENGINE_VERSION = "WSB-6.1"
INPUT_FILES = ["activity_data_clean.csv", "emission_factors.csv", "suppliers.csv", "provenance_register.csv"]
STREAM_LABEL = {
    ("diesel_stationary", "SUP-FUEL-01"): "Diesel generators",
    ("electricity_purchased", "SUP-UTIL-01"): "Grid electricity",
    ("freight_road_outbound", "SUP-CARR-A"): "Freight - Contractor A",
    ("freight_road_outbound", "SUP-CARR-B"): "Freight - Contractor B",
    ("freight_road_outbound", "SUP-CARR-C"): "Freight - Contractor C",
}
AUDIT_FIELDS = [
    "activity_id", "period", "scope", "scope3_category", "activity_type", "stream", "supplier_id",
    "quantity_raw", "unit_raw", "quantity_calc", "unit_calc", "unit_conversion",
    "factor_id", "factor_value", "factor_unit", "gas_coverage", "factor_boundary", "factor_applicable_year",
    "factor_geography", "factor_verification", "factor_source", "factor_source_url", "factor_source_location",
    "factor_source_title", "factor_version", "factor_gases_included", "factor_accounting_scope",
    "factor_accounting_method", "factor_publication_year",
    "evidence_id", "evidence_reference", "evidence_synthetic_status", "data_status", "source_origin",
    "formula", "emissions_t", "emissions_unit", "calc_status", "quality_flags", "engine_version",
]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def num(x):
    return v.num(x)


def run(records=None):
    """Validate + calculate. Returns (audit_rows, findings). Pure function of the input files."""
    factors, suppliers, evidence = v.load_registers()
    records = records if records is not None else v.read("activity_data_clean.csv")
    findings, state = v.validate(records, factors, suppliers, evidence)
    base = v.calculate(records, state, factors)  # Phase 4 deterministic calculation
    audit = []
    for r, b, i in zip(records, base, range(len(records))):
        f = factors.get(r["factor_id"].strip(), {})
        e = evidence.get(r["evidence_id"].strip(), {})
        stream = STREAM_LABEL.get((r["activity_type"], r["supplier_id"]), r["activity_type"])
        if b["calc_status"].startswith("CALCULATED"):
            formula = f"{b['quantity']} {b['unit']} x {f['factor_value']} {f['factor_unit']} / 1000"
        elif b["calc_status"] == "NOT_CALCULATED_MISSING":
            formula = "not calculated: activity quantity missing (NULL) - emissions UNAVAILABLE, not 0"
        else:
            formula = "not calculated: BLOCK finding(s) " + ";".join(sorted(state[i]["block"]))
        audit.append({
            "activity_id": r["activity_id"], "period": r["period"], "scope": r["scope"],
            "scope3_category": r["scope3_category"], "activity_type": r["activity_type"], "stream": stream,
            "supplier_id": r["supplier_id"], "quantity_raw": r["quantity"], "unit_raw": r["unit"],
            "quantity_calc": b["quantity"], "unit_calc": b["unit"],
            "unit_conversion": ";".join(state[i]["notes"]),
            "factor_id": r["factor_id"], "factor_value": f.get("factor_value", ""),
            "factor_unit": f.get("factor_unit", ""), "gas_coverage": f.get("gas_coverage", ""),
            "factor_boundary": f.get("boundary", ""), "factor_applicable_year": f.get("applicable_year", ""),
            "factor_geography": f.get("geography", ""), "factor_verification": f.get("verification_status", ""),
            "factor_source": f.get("source_organization", ""), "factor_source_url": f.get("source_url", ""),
            "factor_source_location": f.get("source_location", ""),
            "factor_source_title": f.get("source_title", ""), "factor_version": f.get("factor_version", ""),
            "factor_gases_included": f.get("gases_included", ""),
            "factor_accounting_scope": f.get("accounting_scope", ""),
            "factor_accounting_method": f.get("accounting_method", ""),
            "factor_publication_year": f.get("publication_year", ""),
            "evidence_id": r["evidence_id"], "evidence_reference": e.get("source_reference", ""),
            "evidence_synthetic_status": e.get("synthetic_status", ""), "data_status": r["data_status"],
            "source_origin": r["source_origin"], "formula": formula,
            "emissions_t": b["emissions_t"], "emissions_unit": b["emissions_unit"],
            "calc_status": b["calc_status"], "quality_flags": b["quality_flag"], "engine_version": ENGINE_VERSION,
        })
    return audit, findings


def by_source(audit):
    """Source-level (stream) totals. Emissions stay None (UNAVAILABLE) when nothing was calculable."""
    agg = {}
    for a in audit:
        k = (a["scope"], a["scope3_category"], a["stream"])
        s = agg.setdefault(k, {"scope": a["scope"], "scope3_category": a["scope3_category"], "stream": a["stream"],
                               "activity_type": a["activity_type"], "supplier_id": a["supplier_id"],
                               "factor_id": a["factor_id"], "unit": a["unit_calc"], "emissions_unit": a["emissions_unit"],
                               "records": 0, "records_with_data": 0, "records_missing": 0, "records_blocked": 0,
                               "activity_total": 0.0, "emissions_t": 0.0})
        s["records"] += 1
        if a["calc_status"].startswith("CALCULATED"):
            s["records_with_data"] += 1
            s["activity_total"] += float(a["quantity_calc"]); s["emissions_t"] += float(a["emissions_t"])
        elif a["calc_status"] == "NOT_CALCULATED_MISSING":
            s["records_missing"] += 1
        else:
            s["records_blocked"] += 1
    rows = []
    for s in agg.values():
        if s["records_with_data"] == 0:
            s["activity_total"] = s["emissions_t"] = None
        else:
            s["activity_total"] = round(s["activity_total"], 6); s["emissions_t"] = round(s["emissions_t"], 6)
        s["status"] = ("BLOCKED" if s["records_blocked"] else "UNAVAILABLE" if s["emissions_t"] is None
                       else "INCOMPLETE" if s["records_missing"] else "COMPLETE")
        rows.append(s)
    return sorted(rows, key=lambda r: (r["scope"], r["stream"]))


def by_scope(sources):
    """Scope totals, formed only within a single gas label."""
    out = {}
    for s in sources:
        k = (s["scope"], s["scope3_category"], s["emissions_unit"])
        o = out.setdefault(k, {"scope": s["scope"], "scope3_category": s["scope3_category"],
                               "emissions_unit": s["emissions_unit"], "emissions_t": 0.0,
                               "sources_quantified": 0, "sources_unavailable": 0, "status": "COMPLETE"})
        if s["emissions_t"] is None:
            o["sources_unavailable"] += 1
        else:
            o["emissions_t"] = round(o["emissions_t"] + s["emissions_t"], 6); o["sources_quantified"] += 1
        if s["status"] != "COMPLETE":
            o["status"] = "INCOMPLETE (known-data subtotal)" if s["status"] in {"UNAVAILABLE", "INCOMPLETE"} else "BLOCKED"
    if len({k[2] for k in out}) > 1:
        assert all(len({kk[2] for kk in out if kk[0] == k[0]}) == 1 for k in out), "mixed gas labels inside one scope"
    return list(out.values())


def monthly(audit):
    rows = defaultdict(lambda: None)
    for a in audit:
        k = (a["period"], a["stream"])
        if a["calc_status"].startswith("CALCULATED"):
            rows[k] = round((rows[k] or 0.0) + float(a["emissions_t"]), 6)
        else:
            rows.setdefault(k, None)
    units = {a["stream"]: a["emissions_unit"] for a in audit}
    scopes = {a["stream"]: a["scope"] for a in audit}
    return [{"period": p, "scope": scopes[s], "stream": s, "emissions_t": e, "emissions_unit": units[s]}
            for (p, s), e in sorted(rows.items())]


def hotspots(sources):
    """Ranking of quantified sources with shares of the quantified total.
    The total excludes unavailable sources (Contractor B), so it is INCOMPLETE - not a corporate inventory.
    If gas labels ever differ again, the sum is mixed-gas and only usable for ranking (see quantified_total)."""
    q = [s for s in sources if s["emissions_t"] is not None]
    total = sum(s["emissions_t"] for s in q)
    ranked = sorted(q, key=lambda s: -s["emissions_t"])
    out = [{"rank": i + 1, "stream": s["stream"], "scope": s["scope"], "emissions_t": s["emissions_t"],
            "emissions_unit": s["emissions_unit"],
            "share_of_quantified_pct": round(100 * s["emissions_t"] / total, 1)} for i, s in enumerate(ranked)]
    for s in sources:
        if s["emissions_t"] is None:
            out.append({"rank": "-", "stream": s["stream"], "scope": s["scope"], "emissions_t": None,
                        "emissions_unit": s["emissions_unit"], "share_of_quantified_pct": None})
    return out, round(total, 6)


def quantified_total(sources):
    """Sum of quantified sources and its gas label(s). Single label -> indicative total; several -> mixed."""
    q = [s for s in sources if s["emissions_t"] is not None]
    units = sorted({s["emissions_unit"] for s in q})
    return round(sum(s["emissions_t"] for s in q), 6), units


def _fmt(x):
    return "UNAVAILABLE" if x is None else (num(x) if isinstance(x, float) else x)


def _write(name, rows):
    OUT.mkdir(exist_ok=True)
    with open(OUT / name, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows({k: _fmt(val) for k, val in r.items()} for r in rows)
    return OUT / name


def main():
    audit, findings = run()
    blocks = [f for f in findings if f["severity"] == "BLOCK"]
    if blocks:
        print(f"ERROR: {len(blocks)} BLOCK findings in clean data - results not published"); return 1
    sources = by_source(audit)
    scopes = by_scope(sources)
    hs, mixed_total = hotspots(sources)
    files = {
        "calculation_audit_trail.csv": _write("calculation_audit_trail.csv", audit),
        "emissions_by_source.csv": _write("emissions_by_source.csv", sources),
        "emissions_by_scope.csv": _write("emissions_by_scope.csv", scopes),
        "emissions_monthly.csv": _write("emissions_monthly.csv", monthly(audit)),
        "hotspot_ranking.csv": _write("hotspot_ranking.csv", hs),
    }
    import confidence
    conf = confidence.assess(audit, sources)
    files["data_confidence.csv"] = _write("data_confidence.csv", conf["streams"])
    manifest = {
        "engine_version": ENGINE_VERSION,
        "inputs": {n: sha256(PHASE4 / "data" / n) for n in INPUT_FILES},
        "outputs": {n: sha256(p) for n, p in files.items()},
        "records": len(audit), "block_findings": 0,
        "note": "Re-running with identical inputs must reproduce identical output hashes.",
    }
    (OUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Records: {len(audit)} | calculated: {sum(a['calc_status'].startswith('CALCULATED') for a in audit)} | "
          f"missing (unavailable): {sum(a['calc_status'] == 'NOT_CALCULATED_MISSING' for a in audit)}")
    for s in scopes:
        cat = f" Cat.{s['scope3_category']}" if s["scope3_category"] else ""
        print(f"  Scope {s['scope']}{cat}: {s['emissions_t']:,.3f} {s['emissions_unit']}  [{s['status']}]")
    qt, units = quantified_total(sources)
    print(f"  Quantified total (indicative, Contractor B unavailable): {qt:,.3f} {'/'.join(units)}"
          + ("" if len(units) == 1 else "  [MIXED GAS LABELS - ranking only]"))
    for h in hs:
        e = "UNAVAILABLE" if h["emissions_t"] is None else f"{h['emissions_t']:,.3f} {h['emissions_unit']}"
        print(f"  #{h['rank']} {h['stream']:<24} {e:<20} {'' if h['share_of_quantified_pct'] is None else str(h['share_of_quantified_pct']) + '%'}")
    print(f"Record completeness: {conf['record_completeness']['label']}")
    print("Outputs written to", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
