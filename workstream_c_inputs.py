"""Workstream C - read the Phase 8, 9 and 10 workbooks (the documented source of assumptions).

Cells are located by their row labels (column A), not by hard-coded addresses, and every value
is returned with its sheet!cell reference so outputs can cite where each assumption came from.

Two views of each workbook are read:
  * input values  - constants typed into the workbook (the assumptions used by the engines)
  * cached values - the workbook's own formula results, used ONLY to reconcile the Python engines
                    against the spreadsheets (never as engine inputs)

Source of truth (documented in the README and report):
  emissions baseline        -> Workstream B engine (calc_engine.py), computed from Phase 4 records
  reduction rates (A, B, C) -> Phase 8 'Scenario Register'!G
  CAPEX, savings, OPEX, lead time, life, horizon, discount rate -> Phase 9 'Assumptions'
  low/high multipliers and Contractor B sensitivity inputs      -> Phase 10 'Inputs'
Copies of the same numbers in other workbooks are checked for consistency, not used.

Naming warning: in Phases 9 and 10 the column "Freight B" means intervention B (freight
optimisation for Contractors A + C). It does NOT refer to Contractor B.
"""
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
INPUT_DIR = HERE / "workbooks"
PHASE8 = INPUT_DIR / "Phase8_Scenario_Assumptions_Register.xlsx"
PHASE9 = INPUT_DIR / "Phase9_Financial_Operational_Evaluation.xlsx"
PHASE10 = INPUT_DIR / "Phase10_Uncertainty_Aware_Decision_Analysis_Corrected.xlsx"
WORKBOOKS = {"phase8": PHASE8, "phase9": PHASE9, "phase10": PHASE10}

IDS = ("A", "B", "C")
# Phase 9 / Phase 10 column per intervention (column headers: Diesel A | Freight B | Electricity C)
COL = {"A": "B", "B": "C", "C": "D"}
HEADER = {"A": "Diesel A", "B": "Freight B", "C": "Electricity C"}

# Which Workstream B activity records each intervention acts on. Defined here (code), checked
# against the workbook's 'Scope / stream' text and baseline tCO2e at load time.
TARGETS = {
    "A": {"activity_type": "diesel_stationary", "suppliers": ("SUP-FUEL-01",), "scope": "1",
          "stream_label": "Diesel generators", "keyword": "diesel"},
    "B": {"activity_type": "freight_road_outbound", "suppliers": ("SUP-CARR-A", "SUP-CARR-C"), "scope": "3",
          "stream_label": "Known freight (Contractors A + C)", "keyword": "contractors a+c"},
    "C": {"activity_type": "electricity_purchased", "suppliers": ("SUP-UTIL-01",), "scope": "2",
          "stream_label": "Grid electricity", "keyword": "electricity"},
}


class WorkbookError(ValueError):
    """Raised when a workbook does not contain an expected label or values are inconsistent."""


def _open(path):
    return (openpyxl.load_workbook(path, data_only=False), openpyxl.load_workbook(path, data_only=True))


def _labels(ws, col="A"):
    out = {}
    for row in range(1, ws.max_row + 1):
        v = ws[f"{col}{row}"].value
        if isinstance(v, str) and v.strip():
            out.setdefault(v.strip(), row)
    return out


def _row(ws, label):
    rows = _labels(ws)
    if label not in rows:
        raise WorkbookError(f"label '{label}' not found in sheet '{ws.title}'")
    return rows[label]


def _cell(wf, wv, sheet, ref):
    """(input_value, cached_value, 'Sheet!REF')."""
    return wf[sheet][ref].value, wv[sheet][ref].value, f"{sheet}!{ref}"


def _num(v, ref):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise WorkbookError(f"{ref}: expected a number, found {v!r}")
    return float(v)


# --------------------------------------------------------------------------- Phase 8
def load_phase8(path=PHASE8):
    wf, wv = _open(path)
    sh = "Scenario Register"
    ws = wf[sh]
    hdr = {ws.cell(1, c).value: c for c in range(1, ws.max_column + 1)}
    need = ["ID", "Intervention", "Scope / stream", "Baseline activity", "Activity unit", "Baseline tCO2e",
            "Reduction assumption", "Avoided tCO2e", "Mechanism / theory of change", "Evidence basis",
            "Evidence status", "Key dependencies", "Limitations / validation needed", "Source URL"]
    for n in need:
        if n not in hdr:
            raise WorkbookError(f"Phase 8 header '{n}' missing")
    letter = {n: openpyxl.utils.get_column_letter(hdr[n]) for n in need}
    out = {}
    for r in range(2, ws.max_row + 1):
        iid = ws[f"{letter['ID']}{r}"].value
        if iid not in IDS:
            continue
        rec = {"id": iid, "row": r}
        for n in need[1:]:
            ref = f"{letter[n]}{r}"
            rec[n] = wf[sh][ref].value
            rec[n + " cached"] = wv[sh][ref].value
            rec[n + " ref"] = f"{sh}!{ref}"
        rec["reduction"] = _num(rec["Reduction assumption"], rec["Reduction assumption ref"])
        rec["baseline_t_workbook"] = _num(rec["Baseline tCO2e"], rec["Baseline tCO2e ref"])
        kw = TARGETS[iid]["keyword"]
        if kw not in str(rec["Scope / stream"]).lower():
            raise WorkbookError(f"Phase 8 row {iid}: scope/stream '{rec['Scope / stream']}' does not match target '{kw}'")
        out[iid] = rec
    if set(out) != set(IDS):
        raise WorkbookError(f"Phase 8 interventions found: {sorted(out)}")
    ds = wf["Decision Summary"]
    rows = _labels(ds)
    out["_decision_summary"] = {
        "baseline_quantified_t": _num(ds[f"B{rows['Baseline quantified emissions (tCO2e)']}"].value, "Decision Summary!B3"),
        "notes": [ds[f"A{r}"].value for r in range(15, ds.max_row + 1) if ds[f"A{r}"].value],
    }
    out["_method"] = [(wf["Method & Sources"][f"A{r}"].value, wf["Method & Sources"][f"B{r}"].value,
                       wf["Method & Sources"][f"C{r}"].value) for r in range(2, wf["Method & Sources"].max_row + 1)]
    return out


# --------------------------------------------------------------------------- Phase 9
P9_FIELDS = {  # key: (row label in 'Assumptions', numeric?)
    "baseline_t": ("Baseline emissions (tCO2e/year)", True),
    "reduction": ("Activity reduction assumption", True),
    "capex": ("CAPEX at year 0 (SAR)", True),
    "savings": ("Gross annual operating savings (SAR/year)", True),
    "opex": ("Incremental recurring OPEX (SAR/year)", True),
    "delay": ("Implementation lead time (years)", True),
    "life": ("Technical life (years)", True),
    "scenario": ("Scenario", False),
    "feasibility": ("Operational feasibility", False),
    "dependency": ("Main dependency", False),
    "evidence": ("Evidence status", False),
}
P9_RESULTS = {  # Decision Summary rows reproduced by the engine (cached values for reconciliation)
    "avoided_t": "Annual emissions avoided (tCO2e)",
    "net_savings": "Annual net operating savings (SAR)",
    "npv": "Financial NPV (SAR)",
    "lifetime_t": "Undiscounted lifetime avoided (tCO2e)",
    "npc": "Net present cost (SAR)",
    "cost_per_t": "Net present cost / lifetime tCO2e (SAR/tCO2e)",
    "payback": "Simple payback (years)",
    "classification": "Financial classification",
}


def load_phase9(path=PHASE9):
    wf, wv = _open(path)
    sh = "Assumptions"
    ws = wf[sh]
    for iid in IDS:
        if ws[f"{COL[iid]}3"].value != HEADER[iid]:
            raise WorkbookError(f"Phase 9 {sh}!{COL[iid]}3 expected '{HEADER[iid]}'")
    per = {iid: {} for iid in IDS}
    for key, (label, numeric) in P9_FIELDS.items():
        r = _row(ws, label)
        for iid in IDS:
            ref = f"{COL[iid]}{r}"
            v = ws[ref].value
            per[iid][key] = _num(v, f"{sh}!{ref}") if numeric else v
            per[iid][key + "_ref"] = f"{sh}!{ref}"
            per[iid][key + "_label"] = label
    g = {}
    for key, label in (("horizon", "Analysis horizon (years)"), ("rate", "Real discount rate (illustrative)")):
        r = _row(ws, label)
        g[key] = _num(ws[f"B{r}"].value, f"{sh}!B{r}")
        g[key + "_ref"] = f"{sh}!B{r}"
    for key, label in (("basis", "Cash-flow basis"), ("baseline_status", "Baseline status")):
        r = _row(ws, label)
        g[key] = ws[f"B{r}"].value
        g[key + "_ref"] = f"{sh}!B{r}"
    # cached results for reconciliation
    ds = wf["Decision Summary"]
    cached = {iid: {} for iid in IDS}
    for key, label in P9_RESULTS.items():
        r = _row(ds, label)
        for iid in IDS:
            cached[iid][key] = wv["Decision Summary"][f"{COL[iid]}{r}"].value
            cached[iid][key + "_ref"] = f"Decision Summary!{COL[iid]}{r}"
    cf = wf["Cash Flows"]
    cf_cols = {"A": ("B", "F"), "B": ("C", "G"), "C": ("D", "H")}
    flows = {iid: [] for iid in IDS}
    for r in range(4, cf.max_row + 1):
        yr = cf[f"A{r}"].value
        if not isinstance(yr, (int, float)):
            continue
        for iid in IDS:
            c_net, c_pv = cf_cols[iid]
            flows[iid].append({"year": int(yr), "net": wv["Cash Flows"][f"{c_net}{r}"].value,
                               "df": wv["Cash Flows"][f"E{r}"].value, "pv": wv["Cash Flows"][f"{c_pv}{r}"].value})
    fz = wf["Feasibility"]
    feas = []
    for r in range(4, fz.max_row + 1):
        if fz[f"A{r}"].value:
            feas.append({"scenario": fz[f"A{r}"].value, "check": fz[f"B{r}"].value, "evidence_needed": fz[f"C{r}"].value,
                         "current_status": fz[f"D{r}"].value, "decision_implication": fz[f"E{r}"].value,
                         "source_ref": f"Feasibility!A{r}:E{r}"})
    sm = wf["Sources and Method"]
    sources = [{"item": sm[f"A{r}"].value, "provenance": sm[f"B{r}"].value, "how_used": sm[f"C{r}"].value,
                "does_not_establish": sm[f"D{r}"].value} for r in range(4, sm.max_row + 1) if sm[f"A{r}"].value]
    return {"interventions": per, "global": g, "cached": cached, "cash_flows_cached": flows,
            "feasibility": feas, "sources": sources}


# --------------------------------------------------------------------------- Phase 10
P10_PER = {
    "baseline_t": "Baseline annual emissions (tCO2e)", "reduction": "Base reduction effectiveness",
    "capex": "Base upfront CAPEX (SAR)", "savings": "Base annual gross savings (SAR)", "opex": "Base annual OPEX (SAR)",
    "life": "Project life (years)", "delay": "Implementation delay (years)",
    "unused_b_share": "Annual freight share eligible for Contractor B",
}
P10_GLOBAL = {
    "horizon": "Shared analysis horizon (years)", "rate": "Real discount rate",
    "low_eff": "Low case: effectiveness multiplier", "high_eff": "High case: effectiveness multiplier",
    "low_capex": "Low case: CAPEX multiplier", "high_capex": "High case: CAPEX multiplier",
    "low_sav": "Low case: savings multiplier", "high_sav": "High case: savings multiplier",
    "low_opex": "Low case: OPEX multiplier", "high_opex": "High case: OPEX multiplier",
    "b_base_t": "Missing Contractor B: illustrative base annual tCO2e",
    "b_low_mult": "Contractor B low multiplier", "b_high_mult": "Contractor B high multiplier",
    "b_applicability": "Freight reduction applicability to B",
}


def load_phase10(path=PHASE10):
    wf, wv = _open(path)
    sh = "Inputs"
    ws = wf[sh]
    for iid in IDS:
        if ws[f"{COL[iid]}3"].value != HEADER[iid]:
            raise WorkbookError(f"Phase 10 {sh}!{COL[iid]}3 expected '{HEADER[iid]}'")
    per = {iid: {} for iid in IDS}
    for key, label in P10_PER.items():
        r = _row(ws, label)
        for iid in IDS:
            ref = f"{COL[iid]}{r}"
            per[iid][key] = _num(ws[ref].value, f"{sh}!{ref}")
            per[iid][key + "_ref"] = f"{sh}!{ref}"
    g = {}
    for key, label in P10_GLOBAL.items():
        r = _row(ws, label)
        g[key] = _num(ws[f"B{r}"].value, f"{sh}!B{r}")
        g[key + "_ref"] = f"{sh}!B{r}"
    g["notes"] = [ws[f"A{r}"].value for r in range(_row(ws, "INTERPRETATION NOTES") + 1, ws.max_row + 1) if ws[f"A{r}"].value]
    # cached Cases sheet
    cs = wv["Cases"]
    name_to_id = {v: k for k, v in HEADER.items()}
    cases = []
    for r in range(4, cs.max_row + 1):
        if cs[f"A{r}"].value in ("Low", "Base", "High"):
            cases.append({"case": cs[f"A{r}"].value, "id": name_to_id[cs[f"B{r}"].value],
                          "effectiveness": cs[f"C{r}"].value, "capex": cs[f"D{r}"].value, "savings": cs[f"E{r}"].value,
                          "opex": cs[f"F{r}"].value, "b_imputed_t": cs[f"G{r}"].value, "avoided_t": cs[f"H{r}"].value,
                          "npv": cs[f"I{r}"].value, "cost_per_t": cs[f"J{r}"].value, "rank": cs[f"K{r}"].value,
                          "ref": f"Cases!A{r}:K{r}"})
    ds = wf["Decision Summary"]
    sw = {}
    for key, label in (("required_savings", "Annual gross savings required for NPV = 0 (SAR/year)"),
                       ("required_savings_ratio", "Required savings as % of current base savings"),
                       ("breakeven_capex", "CAPEX at financial break-even (SAR)")):
        r = _row(ds, label)
        for iid in IDS:
            sw.setdefault(iid, {})[key] = wv["Decision Summary"][f"{COL[iid]}{r}"].value
            sw[iid][key + "_ref"] = f"Decision Summary!{COL[iid]}{r}"
    rs = wf["Ranking & Switching"]
    rk = {}
    for key, label in (("elec_savings_tie_freight", "Electricity gross savings needed to tie freight NPV"),
                       ("elec_savings_ratio_tie", "Electricity savings ratio at tie"),
                       ("elec_capex_tie_freight", "Electricity CAPEX needed to tie freight NPV"),
                       ("freight_savings_tie_elec", "Freight gross savings needed to tie electricity NPV"),
                       ("low_top", "Low-case highest NPV"), ("base_top", "Base-case highest NPV"),
                       ("high_top", "High-case highest NPV")):
        r = _row(rs, label)
        rk[key] = wv["Ranking & Switching"][f"B{r}"].value
        rk[key + "_ref"] = f"Ranking & Switching!B{r}"
    sweep = []
    start = _row(rs, "INDEPENDENT ONE-WAY SENSITIVITY | Electricity annual savings") + 1
    for r in range(start, rs.max_row + 1):
        a = rs[f"A{r}"].value
        if isinstance(a, (int, float)):
            sweep.append({"elec_savings": float(a), "elec_npv": wv["Ranking & Switching"][f"B{r}"].value,
                          "freight_npv": wv["Ranking & Switching"][f"C{r}"].value,
                          "preferred": wv["Ranking & Switching"][f"D{r}"].value})
    ms = wv["Missing Supplier"]
    missing = []
    for r in range(4, 10):
        if ms[f"A{r}"].value in ("Low", "Base", "High"):
            missing.append({"case": ms[f"A{r}"].value, "b_imputed_t": ms[f"B{r}"].value, "known_t": ms[f"C{r}"].value,
                            "illustrative_total_t": ms[f"D{r}"].value, "avoided_t": ms[f"E{r}"].value,
                            "ref": f"Missing Supplier!A{r}:E{r}"})
    priorities = [wf["Missing Supplier"][f"A{r}"].value for r in range(10, wf["Missing Supplier"].max_row + 1)
                  if wf["Missing Supplier"][f"A{r}"].value]
    msrc = wf["Methods Sources"]
    corrections = [{"item": msrc[f"A{r}"].value, "where": msrc[f"B{r}"].value, "what": msrc[f"C{r}"].value,
                    "note": msrc[f"D{r}"].value} for r in range(4, msrc.max_row + 1)
                   if isinstance(msrc[f"A{r}"].value, str) and msrc[f"A{r}"].value.startswith("Correction")]
    return {"interventions": per, "global": g, "cases_cached": cases, "switching_cached": sw,
            "ranking_cached": rk, "sweep_cached": sweep, "missing_cached": missing,
            "data_priorities": priorities, "corrections": corrections}


# --------------------------------------------------------------------------- consistency
def check_consistency(p8, p9, p10, baseline_by_id, quantified_total, tol=1e-9):
    """Return a list of findings. Each: {check, status (OK/MISMATCH/NOTE), detail}.
    baseline_by_id: tCO2e computed by the Workstream B engine for each intervention's target."""
    out = []

    def add(check, ok, detail, note=False):
        out.append({"check": check, "status": "NOTE" if note else ("OK" if ok else "MISMATCH"), "detail": detail})

    for iid in IDS:
        b = baseline_by_id[iid]
        for name, v, ref in (("Phase 8", p8[iid]["baseline_t_workbook"], p8[iid]["Baseline tCO2e ref"]),
                             ("Phase 9", p9["interventions"][iid]["baseline_t"], p9["interventions"][iid]["baseline_t_ref"]),
                             ("Phase 10", p10["interventions"][iid]["baseline_t"], p10["interventions"][iid]["baseline_t_ref"])):
            add(f"{iid} baseline: {name} vs Workstream B engine", abs(v - b) <= 1e-6,
                f"{ref} = {v} ; engine = {b:.6f} tCO2e")
        r8 = p8[iid]["reduction"]
        for name, v, ref in (("Phase 9", p9["interventions"][iid]["reduction"], p9["interventions"][iid]["reduction_ref"]),
                             ("Phase 10", p10["interventions"][iid]["reduction"], p10["interventions"][iid]["reduction_ref"])):
            add(f"{iid} reduction rate: {name} vs Phase 8", abs(v - r8) <= tol, f"{ref} = {v} ; Phase 8 = {r8}")
        for key in ("capex", "savings", "opex", "life", "delay"):
            v9, v10 = p9["interventions"][iid][key], p10["interventions"][iid][key]
            add(f"{iid} {key}: Phase 10 copy vs Phase 9", abs(v9 - v10) <= tol,
                f"{p10['interventions'][iid][key + '_ref']} = {v10} ; {p9['interventions'][iid][key + '_ref']} = {v9}")
    add("Horizon: Phase 10 vs Phase 9", p9["global"]["horizon"] == p10["global"]["horizon"],
        f"{p10['global']['horizon']} vs {p9['global']['horizon']}")
    add("Discount rate: Phase 10 vs Phase 9", abs(p9["global"]["rate"] - p10["global"]["rate"]) <= tol,
        f"{p10['global']['rate']} vs {p9['global']['rate']}")
    add("Phase 8 quantified baseline vs engine", abs(p8["_decision_summary"]["baseline_quantified_t"] - quantified_total) <= 1e-6,
        f"{p8['_decision_summary']['baseline_quantified_t']} vs {quantified_total:.6f}")
    shares = {iid: p10["interventions"][iid]["unused_b_share"] for iid in IDS}
    add("Phase 10 'Annual freight share eligible for Contractor B' (Inputs row 11)", True,
        f"values {shares} are not referenced by any Phase 10 formula; Contractor B applicability is taken from "
        f"{p10['global']['b_applicability_ref']} = {p10['global']['b_applicability']}", note=True)
    for iid in ("A", "B"):
        if p8[iid]["Baseline activity"] in (None, ""):
            add(f"Phase 8 {iid} baseline activity", True,
                f"{p8[iid]['Baseline activity ref']} is blank; activity is taken from Phase 4 records instead", note=True)
    return out


def load_all():
    return load_phase8(), load_phase9(), load_phase10()
