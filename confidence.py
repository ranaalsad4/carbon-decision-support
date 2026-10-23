"""Workstream B, Phase 7 - transparent data-confidence indicators.

Confidence is a LABEL derived from explicit, inspectable criteria. No statistical
confidence percentage is produced or implied.

Criteria (each scored Met / Partial / Not met), per emission source:
  C1 Activity completeness   Met: all 12 months have data | Partial: some | Not met: none
  C2 Factor age              Met: factor year = 2025 | Partial: 1-2 years older | Not met: >= 3 years older
  C3 Factor geography        Met: Saudi-specific | Partial: documented foreign proxy
  C4 Gas coverage            Met: CO2e (CO2, CH4, N2O) | Not met: CO2 only
  C5 Factor verification     Met: verified against published source | Partial: secondary copy | Not met: unverified
                             (unverified_placeholder, or provisional_proxy: a structurally valid factor whose value
                             has not been checked against its source - never treated as verified)
  C6 Boundary / method fit   Met: boundary matches Phase 3 expectation | Partial: accepted proxy boundary

Label rule (applied in this order):
  NOT QUANTIFIED  C1 = Not met (no activity data at all)
  LOW             two or more 'Not met', or one 'Not met' plus two or more 'Partial'
  HIGH            every criterion Met
  MODERATE        otherwise
All activity data is synthetic, so every label is additionally capped as
"demonstration only" - none describes the confidence of a real inventory.
"""
REPORTING_YEAR = 2025
VERIFICATION_SCORE = {"verified_published": "Met", "verified_secondary": "Partial",
                      "provisional_proxy": "Not met", "unverified_placeholder": "Not met"}
CRITERIA = {
    "C1": "Activity completeness", "C2": "Factor age", "C3": "Factor geography",
    "C4": "Gas coverage", "C5": "Factor verification", "C6": "Boundary / method fit",
}
# Phase 3 v1.1 boundary values (electricity: grid_generation, location-based Scope 2)
BOUNDARY_EXPECTED = {"diesel_stationary": "combustion", "electricity_purchased": "grid_generation",
                     "freight_road_outbound": "lifecycle"}


def score_source(src, audit_rows):
    rows = [a for a in audit_rows if a["stream"] == src["stream"]]
    a0 = rows[0]
    n, have = len(rows), src["records_with_data"]
    sc, why = {}, {}
    sc["C1"] = "Met" if have == n else ("Not met" if have == 0 else "Partial")
    why["C1"] = f"{have}/{n} monthly records have activity data"
    age = REPORTING_YEAR - int(a0["factor_applicable_year"])
    sc["C2"] = "Met" if age <= 0 else ("Partial" if age <= 2 else "Not met")
    why["C2"] = f"factor year {a0['factor_applicable_year']} ({age} yr before {REPORTING_YEAR})" if age else "factor year matches 2025"
    geo = a0["factor_geography"]
    sc["C3"] = "Partial" if "proxy" in geo.lower() or "saudi" not in geo.lower() else "Met"
    why["C3"] = geo
    sc["C4"] = "Met" if a0["gas_coverage"] == "CO2e" else "Not met"
    why["C4"] = (f"CO2e ({a0.get('factor_gases_included') or 'CO2, CH4, N2O'})" if sc["C4"] == "Met"
                 else "CO2 only - CH4 and N2O omitted; result in tCO2")
    ver = a0["factor_verification"]
    sc["C5"] = VERIFICATION_SCORE.get(ver, "Not met")
    why["C5"] = ver + (": value not yet checked against the primary source" if ver == "provisional_proxy" else "")
    exp = BOUNDARY_EXPECTED[a0["activity_type"]]
    sc["C6"] = "Met" if a0["factor_boundary"] == exp else "Partial"
    why["C6"] = (f"'{a0['factor_boundary']}' as expected" if sc["C6"] == "Met"
                 else f"'{a0['factor_boundary']}' used; Phase 3 expected '{exp}' (upstream WTT excluded)")
    return sc, why


def label(sc):
    vals = list(sc.values())
    nm, pa = vals.count("Not met"), vals.count("Partial")
    if sc["C1"] == "Not met":
        return "NOT QUANTIFIED", "no activity data: emissions unavailable"
    if nm >= 2 or (nm == 1 and pa >= 2):
        return "LOW", f"{nm} not met, {pa} partial"
    if nm == 0 and pa == 0:
        return "HIGH", "all criteria met"
    return "MODERATE", f"{nm} not met, {pa} partial"


def assess(audit_rows, sources):
    streams = []
    for s in sources:
        sc, why = score_source(s, audit_rows)
        lab, rule = label(sc)
        row = {"stream": s["stream"], "scope": s["scope"],
               "emissions_t": s["emissions_t"], "emissions_unit": s["emissions_unit"]}
        for c in CRITERIA:
            row[f"{c} {CRITERIA[c]}"] = sc[c]
            row[f"{c} evidence"] = why[c]
        row["confidence_label"] = lab
        row["label_rule"] = rule
        row["caveat"] = "Synthetic activity data - demonstration only"
        streams.append(row)

    total = len(audit_rows)
    with_data = sum(a["calc_status"].startswith("CALCULATED") for a in audit_rows)
    missing = sum(a["calc_status"] == "NOT_CALCULATED_MISSING" for a in audit_rows)
    quantified = [s for s in sources if s["emissions_t"] is not None]
    carriers = [s for s in sources if s["activity_type"] == "freight_road_outbound"]
    return {
        "streams": streams,
        "record_completeness": {"with_data": with_data, "total": total, "missing": missing,
                                "pct": round(100 * with_data / total, 1),
                                "label": f"{with_data}/{total} = {100 * with_data / total:.0f}%"},
        # Emissions coverage is about SOURCES, not records; its % of true emissions is unknown
        "emissions_coverage": {
            "sources_quantified": len(quantified), "sources_total": len(sources),
            "carriers_quantified": sum(s["emissions_t"] is not None for s in carriers), "carriers_total": len(carriers),
            "scope1": "fully quantified", "scope2": "fully quantified (CO2e; provisional SEC 2024 factor)",
            "scope3_cat4": "partial - Contractor B missing",
            "share_of_true_total": "unknown (Contractor B emissions cannot be bounded without its activity data)",
        },
    }
