"""Phase 11 - load the supplier assumptions register and the (read-only) Workstream B inventory.

The historical inventory is taken from calc_engine (Phase 4 records); the register never stores
or overwrites it. Edited copies of the register (uploaded in the dashboard) are loaded from bytes.
"""
import copy
import hashlib
import io
from pathlib import Path

import openpyxl

import calc_engine as ce
import workstream_c_inputs as wi
from supplier_models import (ActionTemplate, EmissionFactor, Lane, MatrixRules, Maturity, Offer, Phase11Data,
                             ScoringConfig, ScreeningEvidence, Settings, SUPPORTED_MODES, Supplier, UncertaintyVar,
                             UnitError, ValidationIssue, normalise_ef, parse_number, text)

HERE = Path(__file__).resolve().parent
REGISTER = HERE / "phase11" / "Phase11_Supplier_Decision_Assumptions_Register.xlsx"
MATURITY_INDICATORS = ["measurement_practice", "data_completeness", "methodological_transparency", "improvement_targets",
                       "reporting_capability", "verification_evidence", "engagement_responsiveness"]
DQ_DIMENSIONS = ["dq_completeness", "dq_temporal", "dq_geographic", "dq_technological", "dq_methodological",
                 "dq_evidence_provenance", "dq_verification"]
CRITERIA = ["carbon_performance", "total_lifecycle_cost", "operational_reliability", "data_quality_transparency",
            "improvement_capability"]


class RegisterError(ValueError):
    """The register cannot be read (missing sheet or header)."""


def _table(ws, first_col_header, stop_label=None):
    """Rows (dicts) of the table whose header row has `first_col_header` in column A."""
    hdr_row = None
    for r in range(1, min(ws.max_row, 30) + 1):
        if ws.cell(row=r, column=1).value == first_col_header:
            hdr_row = r
            break
    if hdr_row is None:
        raise RegisterError(f"sheet '{ws.title}': header '{first_col_header}' not found")
    cols = []
    for c in range(1, ws.max_column + 1):
        v = ws.cell(row=hdr_row, column=c).value
        if v is None:
            break
        cols.append(str(v).strip())
    rows = []
    for r in range(hdr_row + 1, ws.max_row + 1):
        first = ws.cell(row=r, column=1).value
        if first is None or (isinstance(first, str) and not first.strip()):
            break
        if stop_label and first == stop_label:
            break
        rec = {cols[j]: ws.cell(row=r, column=j + 1).value for j in range(len(cols))}
        rec["_row"] = r
        rows.append(rec)
    return rows


def _bool(v, default):
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().upper() in ("TRUE", "YES", "1")


def load_register(path=REGISTER, data: bytes = None) -> Phase11Data:
    raw = data if data is not None else Path(path).read_bytes()
    version = hashlib.sha256(raw).hexdigest()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user as a load error
        raise RegisterError(f"cannot open workbook: {exc}") from exc
    need = ["Supplier Profiles", "Freight Activity", "Emission Factors", "Service Equivalence", "Financial Inputs",
            "Screening Evidence", "Supplier Maturity", "Engagement Matrix Rules", "Scoring Weights",
            "Uncertainty Assumptions", "Engagement Action Plans", "Monitoring Indicators", "Source Register",
            "Validation Cases"]
    missing = [s for s in need if s not in wb.sheetnames]
    if missing:
        raise RegisterError(f"missing sheets: {missing}")
    issues = []

    # suppliers
    suppliers = {}
    for r in _table(wb["Supplier Profiles"], "supplier_id"):
        sid = text(r["supplier_id"])
        if sid in suppliers:
            issues.append(ValidationIssue("ERROR", f"Supplier Profiles row {r['_row']}", f"duplicate supplier_id {sid}"))
            continue
        mode = text(r.get("transport_mode"))
        if mode and mode.lower() not in SUPPORTED_MODES:
            issues.append(ValidationIssue("ERROR", f"Supplier Profiles row {r['_row']}", f"unsupported transport mode '{mode}'"))
        suppliers[sid] = Supplier(sid, text(r.get("supplier_name")), text(r.get("relationship")),
                                  text(r.get("inventory_supplier_id")), mode.lower() if mode else None,
                                  text(r.get("fuel_technology")), text(r.get("service_geography")),
                                  text(r.get("service_materiality")), text(r.get("data_class")), text(r.get("notes")))

    # lanes
    lanes = {}
    for r in _table(wb["Service Equivalence"], "lane_id"):
        lid = text(r["lane_id"])
        w = f"Service Equivalence row {r['_row']}"
        if lid in lanes:
            issues.append(ValidationIssue("ERROR", w, f"duplicate lane_id {lid}"))
            continue
        mode = text(r.get("transport_mode"))
        lanes[lid] = Lane(lid, text(r.get("lane_name")), text(r.get("origin")), text(r.get("destination")),
                          mode.lower() if mode else None, text(r.get("cargo_type")),
                          parse_number(r.get("required_capacity_t_per_year"), w, issues),
                          parse_number(r.get("required_on_time_pct"), w, issues),
                          text(r.get("reporting_period")), text(r.get("incumbent_offer_id")), text(r.get("data_class")))

    # offers (activity)
    offers = {}
    for r in _table(wb["Freight Activity"], "offer_id"):
        oid = text(r["offer_id"])
        w = f"Freight Activity row {r['_row']} ({oid})"
        if oid in offers:
            issues.append(ValidationIssue("ERROR", w, f"duplicate offer_id {oid}"))
            continue
        n0 = len(issues)
        mass = parse_number(r.get("freight_mass_t"), w + " freight_mass_t", issues)
        dist = parse_number(r.get("avg_distance_km"), w + " avg_distance_km", issues)
        invalid = any(i.level == "ERROR" for i in issues[n0:])
        sid, lid = text(r.get("supplier_id")), text(r.get("lane_id"))
        if sid not in suppliers:
            issues.append(ValidationIssue("ERROR", w, f"unknown supplier_id {sid}"))
        if lid not in lanes:
            issues.append(ValidationIssue("ERROR", w, f"unknown lane_id {lid}"))
        if mass == 0 or dist == 0:
            issues.append(ValidationIssue("WARN", w, "zero activity: intensity comparison not possible"))
        cached = r.get("tonne_km")
        if isinstance(cached, (int, float)) and mass is not None and dist is not None and abs(cached - mass * dist) > 1e-6:
            issues.append(ValidationIssue("WARN", w, f"workbook tonne_km {cached} differs from mass x distance; engine uses mass x distance"))
        offers[oid] = Offer(oid, sid, lid, text(r.get("role")), mass, dist, text(r.get("reporting_period")),
                            parse_number(r.get("period_months"), w, issues),
                            parse_number(r.get("offered_capacity_t_per_year"), w, issues), text(r.get("cargo_types")),
                            text(r.get("service_origin")), text(r.get("service_destination")),
                            text(r.get("activity_source")), text(r.get("data_class")), activity_invalid=invalid)

    # emission factors (linked factors come from the Phase 4 library)
    p4_factors, _, _ = ce.v.load_registers()
    for r in _table(wb["Emission Factors"], "ef_id"):
        w = f"Emission Factors row {r['_row']} ({r['ef_id']})"
        oid = text(r.get("offer_id"))
        val = parse_number(r.get("value"), w, issues)
        unit, link, note, ok = text(r.get("unit")), text(r.get("linked_factor_id")), "", True
        if val is None and link:
            f = p4_factors.get(link)
            if f is None:
                issues.append(ValidationIssue("ERROR", w, f"linked factor {link} not in Phase 4 library"))
            else:
                val, unit = float(f["factor_value"]), f["factor_unit"]
                note = f"value read from Phase 4 library {link} ({f['factor_value']} {f['factor_unit']})"
        try:
            kg = normalise_ef(val, unit)
            if kg is not None and val is not None and abs(kg - val) > 1e-15:
                note = (note + "; " if note else "") + f"converted {val} {unit} -> {kg:g} kgCO2e/tonne-km"
        except UnitError as exc:
            issues.append(ValidationIssue("ERROR", w, str(exc)))
            kg, ok = None, False
        ef = EmissionFactor(text(r["ef_id"]), oid, kg, unit, text(r.get("calculation_method")), text(r.get("boundary")),
                            text(r.get("gas_coverage")), text(r.get("source")), text(r.get("reference_year")),
                            text(r.get("verification_status")), link, text(r.get("data_class")), ok, note)
        if oid in offers:
            if offers[oid].ef is not None:
                issues.append(ValidationIssue("ERROR", w, f"second emission factor for offer {oid}; first kept"))
            else:
                offers[oid].ef = ef
        else:
            issues.append(ValidationIssue("ERROR", w, f"unknown offer_id {oid}"))

    # financial inputs + global settings
    ws = wb["Financial Inputs"]
    for r in _table(ws, "offer_id"):
        oid = text(r["offer_id"])
        w = f"Financial Inputs row {r['_row']} ({oid})"
        if oid not in offers:
            issues.append(ValidationIssue("ERROR", w, f"unknown offer_id {oid}"))
            continue
        o = offers[oid]
        o.annual_cost = parse_number(r.get("annual_service_cost_sar"), w + " annual cost", issues)
        o.recurring_cost = parse_number(r.get("additional_recurring_cost_sar"), w + " recurring cost", issues)
        o.switching_cost = parse_number(r.get("one_time_switching_cost_sar"), w + " switching cost", issues)
        o.onboarding_cost = parse_number(r.get("one_time_onboarding_monitoring_sar"), w + " onboarding cost", issues)
        o.exit_cost = parse_number(r.get("contract_exit_cost_sar"), w + " exit cost", issues)
        o.on_time_pct = parse_number(r.get("on_time_delivery_pct"), w + " on-time %", issues)
        if o.on_time_pct is not None and o.on_time_pct > 100:
            issues.append(ValidationIssue("ERROR", w, "on-time delivery above 100% treated as missing"))
            o.on_time_pct = None
        o.cost_source = text(r.get("cost_source"))
    gs = {}
    for r in _table(ws, "parameter"):
        gs[text(r["parameter"])] = r.get("value")
    p9 = wi.load_phase9()
    st = Settings()
    rate = parse_number(gs.get("discount_rate"), "Financial Inputs discount_rate", issues)
    st.discount_rate = rate if rate is not None else p9["global"]["rate"]
    hz = parse_number(gs.get("horizon_years"), "Financial Inputs horizon_years", issues)
    st.horizon_years = int(hz) if hz is not None else int(p9["global"]["horizon"])
    dl = parse_number(gs.get("implementation_delay_years"), "Financial Inputs delay", issues)
    st.implementation_delay_years = int(dl or 0)
    sh = parse_number(gs.get("substitution_share"), "Financial Inputs substitution_share", issues)
    st.substitution_share = 1.0 if sh is None else min(max(sh, 0.0), 1.0)
    st.willingness_to_pay = parse_number(gs.get("willingness_to_pay_sar_per_t"), "Financial Inputs WTP", issues)
    st.verification_mandatory = _bool(gs.get("verification_mandatory"), False)
    st.cost_scales_with_demand = _bool(gs.get("cost_scales_with_demand"), True)

    # screening evidence
    screening = {}
    for r in _table(wb["Screening Evidence"], "offer_id"):
        oid = text(r["offer_id"])
        screening.setdefault(oid, []).append(ScreeningEvidence(
            oid, int(r["check_no"]), text(r.get("check")), text(r.get("category")), text(r.get("status")),
            text(r.get("evidence_reference"))))

    # maturity + data quality
    maturity = {}
    for r in _table(wb["Supplier Maturity"], "supplier_id"):
        sid = text(r["supplier_id"])
        w = f"Supplier Maturity row {r['_row']} ({sid})"
        ind = {}
        for k in MATURITY_INDICATORS:
            x = parse_number(r.get(k), f"{w} {k}", issues)
            if x is not None and x > 4:
                issues.append(ValidationIssue("ERROR", w, f"{k} above 4 treated as not assessed"))
                x = None
            ind[k] = x
        dq = {}
        for k in DQ_DIMENSIONS:
            v = text(r.get(k))
            if v is not None and v not in ("High", "Medium", "Low", "Missing"):
                issues.append(ValidationIssue("ERROR", w, f"{k} value '{v}' not High/Medium/Low/Missing; treated as missing"))
                v = None
            dq[k] = v
        maturity[sid] = Maturity(sid, ind, dq, text(r.get("assessment_source")), text(r.get("data_class")))

    # matrix rules
    ws = wb["Engagement Matrix Rules"]
    pr = {text(r["parameter"]): r.get("value") for r in _table(ws, "parameter")}
    mr = MatrixRules()
    for attr, key in (("impact_threshold", "impact_threshold"), ("maturity_threshold", "maturity_threshold"),
                      ("w_emissions_share", "impact_weight_emissions_share"), ("w_volume_share", "impact_weight_volume_share"),
                      ("w_materiality", "impact_weight_materiality")):
        x = parse_number(pr.get(key), f"Engagement Matrix Rules {key}", issues)
        if x is not None:
            setattr(mr, attr, x)
    for lvl in ("critical", "standard", "minor"):
        x = parse_number(pr.get(f"materiality_score_{lvl}"), "Engagement Matrix Rules materiality", issues)
        if x is not None:
            mr.materiality_scores[lvl.capitalize()] = x
    x = parse_number(pr.get("min_maturity_indicators"), "Engagement Matrix Rules min indicators", issues)
    if x is not None:
        mr.min_maturity_indicators = int(x)
    for r in _table(ws, "quadrant"):
        mr.quadrants[text(r["quadrant"])] = {
            "impact": text(r.get("impact")), "maturity": text(r.get("maturity")), "priority": r.get("priority"),
            "label": text(r.get("label")),
            "actions": [a.strip() for a in str(r.get("recommended actions (separated by ;)") or "").split(";") if a.strip()]}

    # scoring
    ws = wb["Scoring Weights"]
    weights, methods, bm = {}, {}, {}
    for r in _table(ws, "criterion"):
        c = text(r["criterion"])
        weights[c] = r.get("weight")
        methods[c] = text(r.get("scoring method (0-100)"))
        bm[c] = (r.get("benchmark_low"), r.get("benchmark_high"))
    sc = ScoringConfig(weights=weights, methods=methods)
    lo, hi = bm.get("carbon_performance", (None, None))
    sc.carbon_low = parse_number(lo, "Scoring carbon low", issues) or sc.carbon_low
    sc.carbon_high = parse_number(hi, "Scoring carbon high", issues) or sc.carbon_high
    band = bm.get("total_lifecycle_cost", (None, None))[1]
    sc.cost_band = parse_number(band, "Scoring cost band", issues) or sc.cost_band
    lo, hi = bm.get("operational_reliability", (None, None))
    sc.reliability_low = parse_number(lo, "Scoring reliability low", issues) or sc.reliability_low
    sc.reliability_high = parse_number(hi, "Scoring reliability high", issues) or sc.reliability_high

    # uncertainty
    unc = {}
    for r in _table(wb["Uncertainty Assumptions"], "variable"):
        w = f"Uncertainty Assumptions {r['variable']}"
        vals = [parse_number(r.get(k), w, issues, allow_zero=True) for k in ("low", "base", "high")]
        if any(v is None for v in vals):
            issues.append(ValidationIssue("ERROR", w, "low/base/high must all be numbers; variable skipped"))
            continue
        unc[text(r["variable"])] = UncertaintyVar(text(r["variable"]), text(r.get("applies_to")), *vals, text(r.get("unit")),
                                                  text(r.get("favourable_to_switching")), text(r.get("note")))

    templates = [ActionTemplate(text(r["trigger"]), text(r.get("action")), text(r.get("responsible_role")),
                                parse_number(r.get("deadline_days"), "Engagement Action Plans", issues),
                                text(r.get("required_evidence")), text(r.get("success_indicator")),
                                text(r.get("verification_method"))) for r in _table(wb["Engagement Action Plans"], "trigger")]
    monitoring = [{k: v for k, v in r.items() if k != "_row"} for r in _table(wb["Monitoring Indicators"], "indicator")]
    sources = [{k: v for k, v in r.items() if k != "_row"} for r in _table(wb["Source Register"], "id")]
    vc = {}
    for r in _table(wb["Validation Cases"], "item"):
        vc[text(r["item"])] = r.get("value") if isinstance(r.get("value"), (int, float)) else None

    data = Phase11Data(suppliers, lanes, offers, screening, maturity, st, mr, sc, unc, templates, monitoring, sources, vc,
                       issues, str(path), version)
    _check_against_inventory(data)
    return data


def inventory_by_supplier():
    """Read-only historical inventory per freight supplier from the Workstream B engine."""
    audit, _ = ce.run()
    out = {}
    for s in ce.by_source(audit):
        if s["activity_type"] != "freight_road_outbound":
            continue
        out[s["supplier_id"]] = {"stream": s["stream"], "tonne_km": s["activity_total"], "emissions_t": s["emissions_t"],
                                 "records": s["records"], "records_with_data": s["records_with_data"],
                                 "records_missing": s["records_missing"], "status": s["status"],
                                 "factor_id": s["factor_id"]}
    return out


def _check_against_inventory(data):
    inv = inventory_by_supplier()
    for sid, s in data.suppliers.items():
        if not s.inventory_supplier_id or s.inventory_supplier_id not in inv:
            continue
        i = inv[s.inventory_supplier_id]
        offs = [o for o in data.supplier_offers(sid) if (o.role or "").lower() == "incumbent"]
        tk = [o.tonne_km for o in offs]
        if i["tonne_km"] is None:
            if any(t is not None for t in tk):
                data.issues.append(ValidationIssue("WARN", f"supplier {sid}",
                                                   "register gives activity for a supplier whose inventory activity is "
                                                   "UNAVAILABLE; the inventory is NOT changed (decision data only)"))
            continue
        if all(t is not None for t in tk) and abs(sum(tk) - i["tonne_km"]) > 1e-6:
            data.issues.append(ValidationIssue("WARN", f"supplier {sid}",
                                               f"incumbent lane tonne-km {sum(tk):,.0f} differ from inventory "
                                               f"{i['tonne_km']:,.0f}; inventory unchanged"))


def clone(data: Phase11Data) -> Phase11Data:
    return copy.deepcopy(data)


OFFER_EDIT_FIELDS = ["offer_id", "supplier_id", "supplier_name", "lane_id", "role", "freight_mass_t", "avg_distance_km",
                     "reporting_period", "offered_capacity_t_per_year", "ef_kgco2e_per_tkm", "ef_boundary",
                     "ef_verification", "annual_service_cost_sar", "additional_recurring_cost_sar",
                     "one_time_switching_cost_sar", "on_time_delivery_pct", "safety_legal_status"]


def offers_table(data):
    rows = []
    for o in data.offers.values():
        s = data.suppliers.get(o.supplier_id)
        gate = {e.check_no: e.status for e in data.screening.get(o.offer_id, [])}.get(2)
        rows.append({"offer_id": o.offer_id, "supplier_id": o.supplier_id, "supplier_name": s.name if s else None,
                     "lane_id": o.lane_id, "role": o.role, "freight_mass_t": o.mass_t, "avg_distance_km": o.distance_km,
                     "reporting_period": o.period, "offered_capacity_t_per_year": o.capacity_t,
                     "ef_kgco2e_per_tkm": o.ef.value_kg_per_tkm if o.ef else None,
                     "ef_boundary": o.ef.boundary if o.ef else None, "ef_verification": o.ef.verification if o.ef else None,
                     "annual_service_cost_sar": o.annual_cost, "additional_recurring_cost_sar": o.recurring_cost,
                     "one_time_switching_cost_sar": o.switching_cost, "on_time_delivery_pct": o.on_time_pct,
                     "safety_legal_status": gate})
    return rows


def apply_offer_edits(data: Phase11Data, rows) -> Phase11Data:
    """Session copy with edited / added offers. Historical inventory is never touched. New suppliers become
    'User-added' hypothetical alternatives whose undocumented checks are Missing (never silently passed)."""
    d = clone(data)
    seen = set()
    for i, r in enumerate(rows):
        oid = text(r.get("offer_id"))
        w = f"edited row {i + 1}"
        if not oid:
            continue
        if oid in seen:
            d.issues.append(ValidationIssue("ERROR", w, f"duplicate offer_id {oid}; later row ignored"))
            continue
        seen.add(oid)
        sid = text(r.get("supplier_id"))
        if not sid:
            d.issues.append(ValidationIssue("ERROR", w, "supplier_id missing; row ignored"))
            continue
        if sid not in d.suppliers:
            d.suppliers[sid] = Supplier(sid, text(r.get("supplier_name")) or sid, "User-added", None, "road", None, None,
                                        "Standard", "User-entered", "Added in the dashboard (hypothetical)")
        lid = text(r.get("lane_id"))
        if lid not in d.lanes:
            d.issues.append(ValidationIssue("ERROR", w, f"unknown lane_id {lid}; row ignored"))
            continue
        o = d.offers.get(oid)
        new = o is None
        if new:
            o = Offer(oid, sid, lid, text(r.get("role")) or "Alternative", None, None, None, 12, None,
                      d.lanes[lid].cargo_type, d.lanes[lid].origin, d.lanes[lid].destination, "Entered in dashboard",
                      "User-entered")
            d.offers[oid] = o
        n0 = len(d.issues)
        o.supplier_id, o.lane_id = sid, lid
        o.mass_t = parse_number(r.get("freight_mass_t"), w + " mass", d.issues)
        o.distance_km = parse_number(r.get("avg_distance_km"), w + " distance", d.issues)
        o.activity_invalid = any(x.level == "ERROR" for x in d.issues[n0:])
        o.period = text(r.get("reporting_period"))
        o.capacity_t = parse_number(r.get("offered_capacity_t_per_year"), w + " capacity", d.issues)
        efv = parse_number(r.get("ef_kgco2e_per_tkm"), w + " EF", d.issues)
        if o.ef is None or new:
            o.ef = EmissionFactor(f"USER-EF-{oid}", oid, efv, "kgCO2e/tonne-km", "Entered in dashboard",
                                  text(r.get("ef_boundary")), "CO2e", "User-entered (unverified)", None,
                                  text(r.get("ef_verification")) or "Unverified - claimed", None, "User-entered")
        else:
            o.ef.value_kg_per_tkm = efv
            o.ef.boundary = text(r.get("ef_boundary"))
            o.ef.verification = text(r.get("ef_verification"))
            o.ef.linked_factor_id = None if efv is not None else o.ef.linked_factor_id
        o.annual_cost = parse_number(r.get("annual_service_cost_sar"), w + " cost", d.issues)
        o.recurring_cost = parse_number(r.get("additional_recurring_cost_sar"), w + " recurring", d.issues)
        o.switching_cost = parse_number(r.get("one_time_switching_cost_sar"), w + " switching", d.issues)
        o.on_time_pct = parse_number(r.get("on_time_delivery_pct"), w + " on-time", d.issues)
        gate = text(r.get("safety_legal_status"))
        ev = d.screening.setdefault(oid, [])
        if new and not ev:
            from supplier_screening_engine import CHECKS   # local import avoids a cycle
            for no, name, cat in CHECKS:
                st = "Pass" if no == 1 else "Auto" if cat == "Auto" else "Missing"
                ev.append(ScreeningEvidence(oid, no, name, cat, st, "Entered in dashboard"))
        for e in ev:
            if e.check_no == 2:
                e.status = gate if gate in ("Pass", "Fail", "Missing", "N/A") else "Missing"
    for oid in list(d.offers):
        if oid not in seen and rows:
            del d.offers[oid]
    return d
