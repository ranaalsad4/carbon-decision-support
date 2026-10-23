"""Phase 4 - data-quality validator and deterministic emissions calculator.

Implements data-quality rules DQ-01 to DQ-16 (DQ-01..13 from the Phase 3
specification; DQ-14..16 added in Phase 4) with PASS / WARN / BLOCK severity.

    python validate_phase4.py            # validates clean + test datasets

Outputs (written next to this script):
    validation_report.csv        one row per finding (both datasets) + PASS rows
    emissions_results.csv        record-level results for the clean dataset
    emissions_summary.csv        stream totals (Contractor B UNAVAILABLE, never 0)
    data/data_quality_test_cases.csv   actual outcome + PASS/FAIL filled in

Calculation:  emissions (t) = quantity x factor (kg per unit) / 1,000
Results keep the factor's gas label: tCO2e or tCO2 (never relabelled).
Missing activity is never replaced by zero.
v1.1: electricity factor FAC-ELEC-SEC-01 (SEC 2024, 550 kg CO2e/MWh, provisional
location-based Scope 2 proxy) replaces FAC-ELE-GRID-01 (614.2 kg CO2/MWh).
"""
import csv
import re
import statistics
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"

FACILITY = "FAC-RUH-01"
YEAR = 2025
EXPECTED_GEOGRAPHY = "Saudi Arabia"

# activity_type -> (scope, scope3_category, expected unit)
ACTIVITY = {
    "diesel_stationary": (1, "", "L"),
    "electricity_purchased": (2, "", "MWh"),
    "freight_road_outbound": (3, "4", "tonne-km"),
}
APPROVED_UNITS = {"L", "MWh", "tonne-km"}
# approved scale conversions of activity units: unit -> (target unit, multiplier)
SCALE = {"kWh": ("MWh", 0.001), "t-km": ("tonne-km", 1.0), "tkm": ("tonne-km", 1.0)}
DATA_STATUS = {"reported", "calculated", "estimated", "imputed", "missing"}
SOURCE_ORIGIN = {"synthetic"}  # prototype accepts synthetic data only
# Factor boundary compatibility per activity type: OK / WARN / BLOCK (anything unlisted = BLOCK)
BOUNDARY = {
    "diesel_stationary": {"combustion": "OK"},
    "electricity_purchased": {"grid_generation": "OK"},   # Phase 3 boundary value (v1.1)
    # Phase 3 preferred a life-cycle factor; a direct (tank-to-wheel) vehicle factor is an
    # accepted, documented deviation (WTT excluded, nothing double counted) -> WARN.
    "freight_road_outbound": {"lifecycle": "OK", "vehicle_direct": "WARN"},
}

RULES = {
    "DQ-01": "Missing quantity", "DQ-02": "Duplicate activity ID", "DQ-03": "Duplicate underlying activity",
    "DQ-04": "Invalid date", "DQ-05": "Negative or non-numeric quantity", "DQ-06": "Inconsistent unit",
    "DQ-07": "Missing supplier ID", "DQ-08": "Invalid factor reference", "DQ-09": "Factor/activity unit mismatch",
    "DQ-10": "Missing evidence", "DQ-11": "Outlier", "DQ-12": "Estimated or imputed record",
    "DQ-13": "Factor attribute mismatch", "DQ-14": "Inconsistent status fields",
    "DQ-15": "Invalid source origin", "DQ-16": "Scope classification inconsistency",
}
# Rules whose BLOCK makes a quantity unusable for the outlier distribution
VERIFICATION = {"verified_published", "verified_secondary", "provisional_proxy", "unverified_placeholder"}
ACCOUNTING_METHOD = {"location_based", "market_based", "not_applicable"}
SCOPE2_METHOD = "location_based"   # selected Scope 2 method (provisional, Phase 3)
INTEGRITY = {"DQ-02", "DQ-03", "DQ-04", "DQ-05", "DQ-06", "DQ-14", "DQ-15", "DQ-16"}


def read(name):
    with open(DATA / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)


def to_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def num(x):
    """Plain decimal formatting (no scientific notation)."""
    return f"{x:.6f}".rstrip("0").rstrip(".")


def factor_denominator(unit):
    return unit.split("/", 1)[1].strip() if "/" in unit else ""


def expected_warning(rule, rec, detail):
    """Warnings that follow from documented Phase 4 assumptions (not failures)."""
    if rule == "DQ-01" and rec.get("supplier_id") == "SUP-CARR-B" and rec.get("data_status") == "missing":
        return True
    if rule == "DQ-13" and "BLOCK" not in detail:
        return True  # documented proxy / historical / CO2-only / verification-status warnings
    return False


def load_registers():
    factors = {f["factor_id"]: f for f in read("emission_factors.csv")}
    suppliers = {s["supplier_id"]: s for s in read("suppliers.csv")}
    evidence = {e["evidence_id"]: e for e in read("provenance_register.csv")}
    return factors, suppliers, evidence


def check_registers(factors, suppliers, evidence):
    """Reference-register integrity (returns list of problems; empty = OK)."""
    problems = []
    for fid, f in factors.items():
        v = to_float(f["factor_value"])
        if v is None or v <= 0:
            problems.append(f"{fid}: factor_value not positive numeric")
        if not f["source_url"].startswith(("http://", "https://")):
            problems.append(f"{fid}: source_url invalid")
        for k in ("factor_name", "factor_unit", "source_organization", "source_title", "source_location",
                  "publication_year", "applicable_year", "geography", "gas_coverage", "boundary",
                  "factor_version", "verification_status", "activity_type", "accounting_scope",
                  "accounting_method"):
            if not f.get(k):
                # Phase 3 A-2: publication_year may stay blank only while the factor is a provisional proxy
                if k == "publication_year" and f.get("verification_status") == "provisional_proxy":
                    continue
                problems.append(f"{fid}: {k} blank")
        if f.get("verification_status") not in VERIFICATION:
            problems.append(f"{fid}: verification_status not in {sorted(VERIFICATION)}")
        if f.get("verification_status") != "verified_published" and not f.get("uncertainty_note"):
            problems.append(f"{fid}: uncertainty_note (limitations) required for non-verified factor")
        exp = ACTIVITY.get(f.get("activity_type"))
        if exp is None:
            problems.append(f"{fid}: activity_type not recognised")
        elif f.get("accounting_scope") != str(exp[0]):
            problems.append(f"{fid}: accounting_scope {f.get('accounting_scope')} != {exp[0]} for {f.get('activity_type')}")
        if f.get("accounting_method") not in ACCOUNTING_METHOD:
            problems.append(f"{fid}: accounting_method not in {sorted(ACCOUNTING_METHOD)}")
        if f.get("activity_type") == "electricity_purchased" and f.get("accounting_method") != SCOPE2_METHOD:
            problems.append(f"{fid}: electricity accounting_method must be {SCOPE2_METHOD}")
        if f["gas_coverage"] not in {"CO2", "CO2e"}:
            problems.append(f"{fid}: gas_coverage not CO2/CO2e")
        label = f["factor_unit"].split("/")[0].strip()
        if label not in {"kg CO2", "kg CO2e"} or label.split()[-1] != f["gas_coverage"]:
            problems.append(f"{fid}: factor_unit gas label does not match gas_coverage")
    for sid, s in suppliers.items():
        if s["supplier_type"] == "freight_carrier" and s["transport_mode"] != "road":
            problems.append(f"{sid}: carrier without road transport_mode")
        if "fictional" not in s["supplier_name"].lower():
            problems.append(f"{sid}: supplier not marked fictional")
    for eid, e in evidence.items():
        if not e["synthetic_status"].startswith("synthetic_"):
            problems.append(f"{eid}: synthetic_status invalid")
        if "FICTIONAL" not in e["source_description"]:
            problems.append(f"{eid}: source not labelled FICTIONAL")
    return problems


def validate(records, factors, suppliers, evidence):
    """Return (findings, per-record state). findings: list of dicts."""
    findings = []
    state = {i: {"block": set(), "warn": set(), "qty": None, "unit": None, "notes": []} for i in range(len(records))}

    def add(i, rule, sev, detail):
        r = records[i]
        findings.append({"row": i + 2, "activity_id": r["activity_id"], "rule_id": rule, "rule": RULES[rule],
                         "severity": sev, "detail": detail,
                         "expected_warning": "yes" if sev == "WARN" and expected_warning(rule, r, detail) else "no"})
        state[i]["block" if sev == "BLOCK" else "warn"].add(rule)

    # DQ-02 duplicate activity IDs (all occurrences blocked)
    ids = defaultdict(list)
    for i, r in enumerate(records):
        ids[r["activity_id"]].append(i)
    for aid, rows in ids.items():
        if len(rows) > 1:
            for i in rows:
                add(i, "DQ-02", "BLOCK", f"activity_id {aid} appears {len(rows)} times (rows {[x + 2 for x in rows]})")

    # DQ-03 duplicate underlying activity (keep first)
    seen_exact, seen_prob = {}, {}
    for i, r in enumerate(records):
        k = (r["period"], r["activity_type"], r["supplier_id"], r["activity_source_id"])
        if k in seen_exact:
            add(i, "DQ-03", "BLOCK", f"exact duplicate of {records[seen_exact[k]]['activity_id']}; first kept")
        else:
            seen_exact[k] = i
            if r["quantity"].strip() and r["evidence_id"].strip():
                kp = (r["activity_type"], r["quantity"].strip(), r["evidence_id"].strip())
                if kp in seen_prob:
                    add(i, "DQ-03", "WARN", f"probable duplicate of {records[seen_prob[kp]]['activity_id']} (same quantity and evidence)")
                else:
                    seen_prob[kp] = i

    for i, r in enumerate(records):
        atype, qraw = r["activity_type"], r["quantity"].strip()
        status = r["data_status"].strip()

        # DQ-16 scope classification / facility
        exp = ACTIVITY.get(atype)
        if exp is None:
            add(i, "DQ-16", "BLOCK", f"unknown activity_type '{atype}'")
        else:
            problems = []
            if r["scope"].strip() != str(exp[0]):
                problems.append(f"scope={r['scope']} (expected {exp[0]})")
            if r["scope3_category"].strip() != exp[1]:
                problems.append(f"scope3_category='{r['scope3_category']}' (expected '{exp[1]}')")
            if r["facility_id"] != FACILITY:
                problems.append(f"facility_id={r['facility_id']}")
            if problems:
                add(i, "DQ-16", "BLOCK", "; ".join(problems))

        # DQ-04 date
        m = re.fullmatch(r"(\d{4})-(\d{2})", r["period"].strip())
        if not m or not (1 <= int(m.group(2)) <= 12) or int(m.group(1)) != YEAR:
            add(i, "DQ-04", "BLOCK", f"period '{r['period']}' not a valid month in {YEAR}-01..{YEAR}-12")

        # DQ-01 missing / DQ-05 invalid quantity
        q = None
        if qraw == "":
            add(i, "DQ-01", "WARN", "quantity empty: excluded from sums, not treated as 0; stream INCOMPLETE")
        else:
            q = to_float(qraw)
            if q is None:
                add(i, "DQ-05", "BLOCK", f"quantity '{qraw}' is not numeric")
            elif q < 0:
                add(i, "DQ-05", "BLOCK", f"negative quantity {qraw}")

        # DQ-14 status consistency
        if status not in DATA_STATUS:
            add(i, "DQ-14", "BLOCK", f"data_status '{status}' not in {sorted(DATA_STATUS)}")
        elif qraw == "" and status != "missing":
            add(i, "DQ-14", "BLOCK", f"quantity empty but data_status='{status}'")
        elif qraw != "" and status == "missing":
            add(i, "DQ-14", "BLOCK", "quantity present but data_status='missing'")

        # DQ-12 estimated / imputed
        if status in {"estimated", "imputed"}:
            add(i, "DQ-12", "WARN", f"data_status={status}: result labelled {status}, not reported")

        # DQ-15 source origin
        if r["source_origin"].strip() not in SOURCE_ORIGIN:
            add(i, "DQ-15", "BLOCK", f"source_origin '{r['source_origin']}' not allowed (synthetic only)")

        # DQ-06 unit
        unit = r["unit"].strip()
        calc_unit, mult = unit, 1.0
        if unit in SCALE:
            calc_unit, mult = SCALE[unit]
            if exp and calc_unit == exp[2]:
                add(i, "DQ-06", "WARN", f"approved scale conversion {unit} -> {calc_unit} (x{mult}) applied and logged")
                state[i]["notes"].append(f"converted {unit}->{calc_unit}")
            else:
                add(i, "DQ-06", "BLOCK", f"unit '{unit}' not valid for {atype}")
        elif unit not in APPROVED_UNITS:
            add(i, "DQ-06", "BLOCK", f"unit '{unit}' not in approved list {sorted(APPROVED_UNITS)}")
        elif exp and unit != exp[2]:
            add(i, "DQ-06", "BLOCK", f"unit '{unit}' not the expected unit '{exp[2]}' for {atype}")
        unit_ok = "DQ-06" not in state[i]["block"]
        state[i]["unit"] = calc_unit
        if q is not None and q >= 0:
            state[i]["qty"] = q * mult

        # DQ-07 supplier
        sid = r["supplier_id"].strip()
        if not sid or sid not in suppliers:
            why = "empty" if not sid else f"'{sid}' not in suppliers"
            add(i, "DQ-07", "BLOCK" if atype == "freight_road_outbound" else "WARN", f"supplier_id {why}")

        # DQ-10 evidence
        eid = r["evidence_id"].strip()
        if not eid:
            add(i, "DQ-10", "WARN", "evidence_id empty: lower confidence")
        elif eid not in evidence:
            add(i, "DQ-10", "BLOCK", f"evidence_id '{eid}' not in provenance register")

        # DQ-08 factor reference
        fid = r["factor_id"].strip()
        f = factors.get(fid)
        if f is None:
            add(i, "DQ-08", "BLOCK", "factor_id empty (required before calculation)" if not fid
                else f"factor_id '{fid}' not in emission_factors")
            continue

        # DQ-09 unit compatibility (only meaningful when the activity unit itself is valid)
        if unit_ok and factor_denominator(f["factor_unit"]) != calc_unit:
            add(i, "DQ-09", "BLOCK", f"factor unit '{f['factor_unit']}' incompatible with activity unit '{calc_unit}'")

        # DQ-13 factor attributes
        if exp:
            reasons, sev = [], "WARN"
            if f.get("activity_type") and f["activity_type"] != atype:
                sev = "BLOCK"
                reasons.append(f"BLOCK factor activity_type '{f['activity_type']}' does not apply to {atype}")
            b = BOUNDARY.get(atype, {}).get(f["boundary"], "BLOCK")
            if b == "BLOCK":
                sev = "BLOCK"
                reasons.append(f"BLOCK boundary '{f['boundary']}' incompatible with {atype} (would mix/miss boundaries)")
            elif b == "WARN":
                reasons.append(f"boundary '{f['boundary']}' accepted proxy (upstream excluded)")
            if EXPECTED_GEOGRAPHY.lower() not in f["geography"].lower() or "proxy" in f["geography"].lower():
                reasons.append(f"geography '{f['geography']}'")
            if f["applicable_year"] != str(YEAR):
                reasons.append(f"applicable_year {f['applicable_year']} (activity year {YEAR})")
            if f["gas_coverage"] != "CO2e":
                reasons.append(f"gas_coverage {f['gas_coverage']} only: result labelled tCO2, not tCO2e")
            if f["verification_status"] != "verified_published":
                reasons.append(f"verification_status {f['verification_status']}")
            if reasons:
                add(i, "DQ-13", sev, "; ".join(reasons))

    # DQ-11 outliers: 1.5 x IQR within each series (activity_type + supplier), on usable values
    series = defaultdict(list)
    for i, r in enumerate(records):
        if state[i]["qty"] is not None and not (state[i]["block"] & INTEGRITY):
            series[(r["activity_type"], r["supplier_id"])].append(i)
    for key, rows in series.items():
        vals = [state[i]["qty"] for i in rows]
        if len(vals) < 4:
            continue
        q1, _, q3 = statistics.quantiles(vals, n=4, method="inclusive")
        lo, hi = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
        for i in rows:
            if not lo <= state[i]["qty"] <= hi:
                add(i, "DQ-11", "WARN", f"{state[i]['qty']:g} outside [{lo:g}, {hi:g}] (1.5 x IQR of series)")

    return findings, state


def calculate(records, state, factors):
    """Deterministic calculation for records with a quantity and no BLOCK."""
    out = []
    for i, r in enumerate(records):
        s, f = state[i], factors.get(r["factor_id"].strip())
        flags = sorted(s["block"] | s["warn"])
        rec = {"activity_id": r["activity_id"], "period": r["period"], "activity_type": r["activity_type"],
               "scope": r["scope"], "scope3_category": r["scope3_category"], "supplier_id": r["supplier_id"],
               "quantity": "" if s["qty"] is None else num(s["qty"]), "unit": s["unit"],
               "factor_id": r["factor_id"], "factor_value": f["factor_value"] if f else "",
               "factor_unit": f["factor_unit"] if f else "", "emissions_t": "", "emissions_unit": "",
               "calc_status": "", "quality_flag": ";".join(flags) if flags else "OK"}
        if s["block"]:
            rec["calc_status"] = "BLOCKED"
        elif s["qty"] is None:
            rec["calc_status"] = "NOT_CALCULATED_MISSING"
            rec["emissions_unit"] = "t" + f["gas_coverage"] if f else ""
        else:
            rec["emissions_t"] = f"{round(s['qty'] * float(f['factor_value']) / 1000, 6):.6f}"
            rec["emissions_unit"] = "t" + f["gas_coverage"]
            rec["calc_status"] = "CALCULATED_WITH_WARNINGS" if s["warn"] else "CALCULATED"
        out.append(rec)
    return out


def summarise(results):
    """Per-stream totals; never sums across different gas labels."""
    streams = defaultdict(lambda: {"activity": 0.0, "emissions": 0.0, "unit": "", "missing": 0, "blocked": 0, "n": 0})
    for r in results:
        key = (r["scope"], r["activity_type"], r["supplier_id"])
        s = streams[key]
        s["n"] += 1
        if r["calc_status"] == "BLOCKED":
            s["blocked"] += 1
        elif r["calc_status"] == "NOT_CALCULATED_MISSING":
            s["missing"] += 1
            s["unit"] = r["emissions_unit"]
        else:
            s["activity"] += float(r["quantity"]); s["emissions"] += float(r["emissions_t"]); s["unit"] = r["emissions_unit"]
    for s in streams.values():
        s["status"] = "BLOCKED" if s["blocked"] else ("INCOMPLETE" if s["missing"] else "COMPLETE")
        if s["missing"] + s["blocked"] == s["n"]:   # nothing calculable: unavailable, never zero
            s["activity"] = s["emissions"] = None
        else:
            s["emissions"] = round(s["emissions"], 6)
    return dict(streams)


def quantified_total(streams):
    """Total of calculable stream results, only when all share one gas label (else None)."""
    vals = [s for s in streams.values() if s["emissions"] is not None]
    units = {s["unit"] for s in vals}
    if len(units) != 1:
        return None, units
    return round(sum(s["emissions"] for s in vals), 6), units


def write_summary(streams):
    rows = []
    total, units = quantified_total(streams)

    def share(x):
        return "" if (x is None or not total) else f"{100 * x / total:.2f}"
    for (scope, atype, sup), s in sorted(streams.items()):
        rows.append({"scope": scope, "activity_type": atype, "supplier_id": sup, "records": s["n"],
                     "missing_records": s["missing"], "blocked_records": s["blocked"], "stream_status": s["status"],
                     "activity_total": "UNAVAILABLE" if s["activity"] is None else num(s["activity"]),
                     "emissions_t": "UNAVAILABLE" if s["emissions"] is None else f"{s['emissions']:.3f}",
                     "emissions_unit": s["unit"], "share_of_quantified_total_pct": share(s["emissions"])})
    known = [s for (sc, _, _), s in streams.items() if sc == "3" and s["emissions"] is not None]
    rows.append({"scope": "3", "activity_type": "freight_road_outbound", "supplier_id": "KNOWN A+C SUBTOTAL",
                 "records": sum(s["n"] for (sc, _, _), s in streams.items() if sc == "3"),
                 "missing_records": sum(s["missing"] for (sc, _, _), s in streams.items() if sc == "3"),
                 "blocked_records": 0, "stream_status": "INCOMPLETE (Contractor B missing) - not a complete Scope 3 baseline",
                 "activity_total": num(sum(s["activity"] for s in known)),
                 "emissions_t": f"{sum(s['emissions'] for s in known):.3f}", "emissions_unit": "tCO2e",
                 "share_of_quantified_total_pct": share(sum(s["emissions"] for s in known))})
    n_all = sum(s["n"] for s in streams.values())
    rows.append({"scope": "ALL", "activity_type": "all_streams", "supplier_id": "QUANTIFIED TOTAL (Scopes 1+2+3 A+C)",
                 "records": n_all, "missing_records": sum(s["missing"] for s in streams.values()),
                 "blocked_records": sum(s["blocked"] for s in streams.values()),
                 "stream_status": ("INCOMPLETE (Contractor B unavailable) - indicative quantified total, not a complete inventory"
                                   if total is not None else "NOT SUMMED - mixed gas labels " + "/".join(sorted(units))),
                 "activity_total": "",
                 "emissions_t": "" if total is None else f"{total:.3f}",
                 "emissions_unit": "" if total is None else next(iter(units)),
                 "share_of_quantified_total_pct": "" if total is None else "100.00"})
    write(HERE / "emissions_summary.csv", rows, list(rows[0].keys()))
    return rows


def run_dataset(name, factors, suppliers, evidence):
    records = read(name)
    findings, state = validate(records, factors, suppliers, evidence)
    return records, findings, state


def evaluate_test_cases(findings):
    cases = read("data_quality_test_cases.csv")
    by_id = defaultdict(list)
    for f in findings:
        by_id[f["activity_id"]].append(f)
    for c in cases:
        hits = by_id.get(c["activity_id"], [])
        rule_hits = [f for f in hits if f["rule_id"] == c["rule_id"]]
        sevs = {f["severity"] for f in rule_hits}
        c["actual_outcome"] = "BLOCK" if "BLOCK" in sevs else ("WARN" if "WARN" in sevs else "PASS")
        c["actual_flags"] = ";".join(sorted({f"{f['rule_id']}:{f['severity']}" for f in hits
                                              if not (f["rule_id"] == "DQ-13" and f["severity"] == "WARN")}))
        c["test_result"] = "PASS" if c["expected_outcome"] in sevs else "FAIL"
    write(DATA / "data_quality_test_cases.csv", cases, list(cases[0].keys()))
    return cases


def main():
    factors, suppliers, evidence = load_registers()
    reg_problems = check_registers(factors, suppliers, evidence)

    report = []
    for ds in ("activity_data_clean.csv", "activity_data_test.csv"):
        records, findings, state = run_dataset(ds, factors, suppliers, evidence)
        for f in findings:
            report.append({"dataset": ds, **f})
        flagged = {f["activity_id"] for f in findings}
        for r in records:
            if r["activity_id"] not in flagged:
                report.append({"dataset": ds, "row": "", "activity_id": r["activity_id"], "rule_id": "ALL",
                               "rule": "All rules", "severity": "PASS", "detail": "no findings",
                               "expected_warning": "no"})
        if ds == "activity_data_clean.csv":
            clean_findings = findings
            results = calculate(records, state, factors)
            write(HERE / "emissions_results.csv", results, list(results[0].keys()))
            streams = summarise(results)
            write_summary(streams)
        else:
            test_findings = findings
    for p in reg_problems:
        report.append({"dataset": "registers", "row": "", "activity_id": "", "rule_id": "REG", "rule": "Register integrity",
                       "severity": "BLOCK", "detail": p, "expected_warning": "no"})
    write(HERE / "validation_report.csv", report,
          ["dataset", "row", "activity_id", "rule_id", "rule", "severity", "detail", "expected_warning"])
    cases = evaluate_test_cases(test_findings)

    # ---- console summary
    cb = [f for f in clean_findings if f["severity"] == "BLOCK"]
    cw = [f for f in clean_findings if f["severity"] == "WARN"]
    unexpected = [f for f in cw if f["expected_warning"] == "no"]
    print("=== Register integrity:", "OK" if not reg_problems else reg_problems)
    print(f"=== Clean dataset: {len(read('activity_data_clean.csv'))} records | BLOCK={len(cb)} | "
          f"WARN={len(cw)} (expected={len(cw) - len(unexpected)}, unexpected={len(unexpected)})")
    print("=== Stream results (clean data; gas labels kept separate)")
    for (scope, atype, sup), s in sorted(streams.items()):
        act = "UNAVAILABLE" if s["activity"] is None else f"{s['activity']:,.0f}"
        em = "UNAVAILABLE" if s["emissions"] is None else f"{s['emissions']:,.3f}"
        print(f"  Scope {scope} {atype:<22} {sup:<12} {s['status']:<10} activity={act:>12} "
              f"emissions={em:>11} {s['unit']}  missing={s['missing']}")
    total, units = quantified_total(streams)
    if total is None:
        print("=== Quantified total: NOT SUMMED (mixed gas labels)", sorted(units))
    else:
        print(f"=== Quantified total (indicative, Contractor B unavailable): {total:,.3f} {next(iter(units))}")
        for (scope, atype, sup), s in sorted(streams.items()):
            if s["emissions"] is not None:
                print(f"  share Scope {scope} {sup:<12} {100 * s['emissions'] / total:6.2f} %")
    passed = sum(c["test_result"] == "PASS" for c in cases)
    print(f"=== Seeded test cases: {passed}/{len(cases)} PASS; rules covered: "
          f"{len({c['rule_id'] for c in cases if c['test_result'] == 'PASS'})}/16")
    for c in cases:
        if c["test_result"] != "PASS":
            print("  FAIL", c["test_case_id"], c["rule_id"], c["actual_flags"])
    return 0 if (not cb and not unexpected and not reg_problems and passed == len(cases)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
