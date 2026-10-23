"""Workstream C (Phases 8-10) tests.   Run:  python -m pytest -v
The Workstream B (test_workstream_b.py) and Phase 4 (phase4/test_phase4.py) suites run alongside."""
import csv
import hashlib
import json
from math import isclose
from pathlib import Path

import pytest

import calc_engine as ce
import financial_engine as fe
import run_workstream_c as rwc
import scenario_engine as se
import uncertainty_engine as ue
import workstream_c_inputs as wi

HERE = Path(__file__).resolve().parent
# SHA-256 of the three workbooks as uploaded (the engines must never modify them)
WORKBOOK_SHA256 = {
    "Phase8_Scenario_Assumptions_Register.xlsx": "a94ce48d4ce0ee37ca84aa86d3c340fa273feef7354ce056f3402507816b6cb4",
    "Phase9_Financial_Operational_Evaluation.xlsx": "37d8d4d662a7141dc5a8994e0ad476450a51755ceb2af6f27fdc4bb7f56e2df5",
    "Phase10_Uncertainty_Aware_Decision_Analysis_Corrected.xlsx":
        "d539bebe626d9c0b0394fb136b7fb88e1a03c937892ac53545ed36b45f1b3637",
}


@pytest.fixture(scope="module")
def sc():
    return se.run_all()


@pytest.fixture(scope="module")
def fin():
    return fe.run()


@pytest.fixture(scope="module")
def unc():
    return ue.run()


def _src(sources):
    return {s["stream"]: s for s in sources}


# ------------------------------------------------------------------ inputs and baseline
def test_workbooks_unchanged():
    for name, h in WORKBOOK_SHA256.items():
        assert hashlib.sha256((wi.INPUT_DIR / name).read_bytes()).hexdigest() == h, name


def test_workbooks_consistent_with_each_other_and_baseline(sc):
    p8, p9, p10 = wi.load_all()
    checks = wi.check_consistency(p8, p9, p10, sc["target_baseline"], sc["quantified_total"])
    assert not [c for c in checks if c["status"] == "MISMATCH"]
    assert sum(c["status"] == "OK" for c in checks) >= 30


def test_baseline_unchanged_after_all_workstream_c_runs(sc, fin, unc):
    audit, findings = ce.run()
    s = _src(ce.by_source(audit))
    sc_ = {x["scope"]: x["emissions_t"] for x in ce.by_scope(ce.by_source(audit))}
    assert isclose(sc_["1"], 266.155, abs_tol=1e-9) and isclose(sc_["2"], 4400.0, abs_tol=1e-9)
    assert isclose(sc_["3"], 193.097, abs_tol=1e-9)
    assert isclose(ce.quantified_total(ce.by_source(audit))[0], 4859.252, abs_tol=1e-9)
    assert s["Freight - Contractor B"]["emissions_t"] is None
    assert sum(a["calc_status"].startswith("CALCULATED") for a in audit) == 48
    assert not [f for f in findings if f["severity"] == "BLOCK"]


# ------------------------------------------------------------------ Phase 8
def test_default_scenario_reductions(sc):
    av = {c["scenario_id"]: c["avoided_t"] for c in sc["comparison"]}
    assert isclose(av["A"], 26.6155, abs_tol=1e-5)
    assert isclose(av["B"], 28.96455, abs_tol=1e-5)
    assert isclose(av["C"], 440.0, abs_tol=1e-9)


def test_scenario_reductions_reconcile_with_activity_records(sc):
    for sid, res in sc["results"].items():
        tot = 0.0
        for a in res["audit"]:
            if a["missing_data_flag"]:
                continue
            q0, q1, f = float(a["baseline_quantity"]), float(a["scenario_quantity"]), float(a["factor_value"])
            assert isclose(float(a["baseline_emissions_t"]), q0 * f / 1000, abs_tol=1e-6)
            assert isclose(float(a["scenario_emissions_t"]), q1 * f / 1000, abs_tol=1e-6)
            assert isclose(q1, q0 * (1 - a["reduction_rate_applied"]), rel_tol=1e-9)
            tot += float(a["avoided_t"])
        assert isclose(tot, res["avoided_t"], abs_tol=1e-6), sid


def test_scenarios_use_existing_factor_ids_and_values(sc):
    factors, _, _ = ce.v.load_registers()
    base = {r["activity_id"]: r["factor_id"] for r in ce.v.read("activity_data_clean.csv")}
    for res in sc["results"].values():
        for a in res["audit"]:
            assert a["factor_id"] == base[a["activity_id"]]
            assert a["factor_value"] == factors[a["factor_id"]]["factor_value"]
    elec = [a for a in sc["results"]["C"]["audit"] if a["stream"] == "Grid electricity"]
    assert {(a["factor_id"], a["factor_value"], a["factor_unit"], a["factor_verification"]) for a in elec} == \
        {("FAC-ELEC-SEC-01", "550", "kg CO2e/MWh", "provisional_proxy")}


def test_contractor_b_never_converted_to_zero(sc):
    for res in sc["results"].values():
        b = [a for a in res["audit"] if a["supplier_id"] == "SUP-CARR-B"]
        assert len(b) == 12
        assert all(a["scenario_quantity"] == "" and a["scenario_emissions_t"] == "" and a["avoided_t"] == ""
                   and a["calc_status"] == "NOT_CALCULATED_MISSING" and a["interventions_applied"] == "none" for a in b)
        st = next(s for s in res["streams"] if s["stream"] == "Freight - Contractor B")
        assert st["baseline_t"] is None and st["scenario_t"] is None and st["avoided_t"] is None
        assert all(m["avoided_t"] is None for m in se.monthly(res) if m["stream"] == "Freight - Contractor B")


def test_combined_scenario_has_no_double_counting(sc):
    av = {c["scenario_id"]: c["avoided_t"] for c in sc["comparison"]}
    assert isclose(av["ABC"], av["A"] + av["B"] + av["C"], abs_tol=1e-6)


def test_overlapping_interventions_multiply_not_add(monkeypatch):
    """If two interventions targeted the same record, the reduction is 1-(1-a)(1-b), not a+b."""
    monkeypatch.setitem(wi.TARGETS, "A", {**wi.TARGETS["A"], "activity_type": "electricity_purchased",
                                          "suppliers": ("SUP-UTIL-01",)})
    records = ce.v.read("activity_data_clean.csv")
    recs, meta = se.scenario_records(records, {"A": 0.1, "B": 0.0, "C": 0.1}, ["A", "C"])
    e = [(r, m) for r, m in zip(recs, meta) if r["activity_type"] == "electricity_purchased"]
    assert all(isclose(m["multiplier"], 0.81) for _, m in e)
    assert isclose(sum(float(r["quantity"]) for r, _ in e), 8000 * 0.81, abs_tol=1e-6)


def test_monthly_and_annual_scenario_totals_reconcile(sc):
    for sid, res in sc["results"].items():
        mon = se.monthly(res)
        assert isclose(sum(m["avoided_t"] for m in mon if m["avoided_t"] is not None), res["avoided_t"], abs_tol=1e-6)
        assert isclose(sum(m["scenario_t"] for m in mon if m["scenario_t"] is not None), res["total_scenario_t"],
                       abs_tol=1e-6)
        assert {m["period"] for m in mon} == {f"2025-{k:02d}" for k in range(1, 13)}


def test_original_records_not_modified(sc):
    before = (ce.PHASE4 / "data" / "activity_data_clean.csv").read_bytes()
    se.run_scenario(["A", "B", "C"], {"A": 0.3, "B": 0.3, "C": 0.3})
    assert (ce.PHASE4 / "data" / "activity_data_clean.csv").read_bytes() == before


# ------------------------------------------------------------------ Phase 9
def _independent_npv(capex, savings, opex, delay, life, horizon, rate):
    total = -capex
    for t in range(1, horizon + 1):
        if delay < t <= life:
            total += (savings - opex) / (1 + rate) ** t
    return total


def test_npv_independently_verified(fin):
    for iid, p in fin["params"].items():
        exp = _independent_npv(p["capex"], p["savings"], p["opex"], int(p["delay"]), int(p["life"]),
                               int(p["horizon"]), p["rate"])
        r = fin["results"][iid]
        assert isclose(r["npv_sar"], exp, abs_tol=1e-6) and isclose(r["npv_closed_form_sar"], exp, abs_tol=1e-6)


def test_financial_results_reconcile_with_phase9_workbook(fin):
    rows = fe.reconciliation(fin["results"], fin["p9"])
    assert rows and all(r["status"] == "MATCH" for r in rows)
    npv = {i: fin["results"][i]["npv_sar"] for i in wi.IDS}
    assert round(npv["A"]) == 17217 and round(npv["B"]) == 96209 and round(npv["C"]) == 619652


def test_discounting_and_timing_consistent():
    p = {"capex": 100000.0, "savings": 30000.0, "opex": 5000.0, "delay": 2, "life": 10, "horizon": 10,
         "rate": 0.05, "avoided_t": 10.0}
    r = fe.evaluate(p)
    cf = r["cash_flows"]
    assert cf[1]["net_cash_flow_sar"] == cf[2]["net_cash_flow_sar"] == 0 and cf[3]["net_cash_flow_sar"] == 25000
    assert r["benefit_years"] == 8 and isclose(r["lifetime_avoided_t_undiscounted"], 80)
    assert isclose(r["npv_sar"], r["npv_closed_form_sar"], abs_tol=1e-6)
    assert isclose(r["npv_sar"], _independent_npv(100000, 30000, 5000, 2, 10, 10, 0.05), abs_tol=1e-6)
    assert all(isclose(x["discount_factor"], 1.05 ** -x["year"]) for x in cf)
    z = fe.evaluate({**p, "rate": 0.0})   # workbook formula returns -CAPEX at 0%; engine is exact
    assert isclose(z["npv_sar"], -100000 + 25000 * 8)


def test_cost_per_tonne_definition_and_edge_cases(fin):
    for r in fin["results"].values():
        assert isclose(r["cost_per_t_sar"], -r["npv_sar"] / r["lifetime_avoided_t_undiscounted"])
        assert r["cost_per_t_sar"] < 0 and "negative net abatement cost" in r["abatement_cost_note"]
    bad = fe.evaluate({"capex": 1000.0, "savings": 100.0, "opex": 200.0, "delay": 0, "life": 10, "horizon": 10,
                       "rate": 0.05, "avoided_t": 0.0})
    assert bad["simple_payback_y"] is None and bad["cost_per_t_sar"] is None   # workbook would show 0


# ------------------------------------------------------------------ Phase 10
def test_uncertainty_cases_reconcile_with_corrected_workbook(unc):
    assert unc["cases_recon"] and all(r["status"] == "MATCH" for r in unc["cases_recon"])
    assert all(r["status"] == "MATCH" for r in unc["switching_recon"] + unc["missing_recon"])


def test_switching_values_are_mathematically_correct(unc):
    ctx = ue.load()
    bi = ue.base_inputs(ctx)
    sw = unc["switching"]
    for iid in wi.IDS:
        req = next(r["switching_value"] for r in sw if r["id"] == iid and r["metric"] == "Gross annual savings at NPV = 0")
        assert isclose(fe.npv_closed_form({**bi[iid], "savings": req}), 0, abs_tol=1e-6)
        irr = next(r["switching_value"] for r in sw if r["id"] == iid and r["metric"].startswith("Discount rate"))
        assert isclose(fe.npv_closed_form({**bi[iid], "rate": irr}), 0, abs_tol=1e-3)
    tie = next(r["switching_value"] for r in sw if r["id"] == "C" and r["versus"] == "B" and "gross savings" in r["metric"])
    assert round(tie) == 92212
    assert isclose(fe.npv_closed_form({**bi["C"], "savings": tie}), fe.npv_closed_form(bi["B"]), abs_tol=1e-6)


def test_sensitivity_results_reproducible(unc):
    again = ue.run()
    for k in ("cases", "one_way", "switching", "reversals", "missing", "robustness", "statements"):
        assert again[k] == unc[k], k


def test_ranking_handles_negative_npvs(unc):
    low = [r for r in unc["ranking"] if r["case"] == "Low"]
    assert all(r["npv_sar"] < 0 for r in low) and not any(r["eligible_for_financial_recommendation"] for r in low)
    top = next(r for r in low if r["highest_relative_npv"])
    assert top["id"] == "A" and "NOT a recommendation" in top["note"]
    assert any("not recommended" in s for s in unc["statements"])
    assert not any("best investment" in s.lower() or "will save" in s.lower() for s in unc["statements"])


def test_ranking_reversal_detection(unc):
    rv = {(r["varied_intervention"], r["parameter"]): r for r in unc["reversals"]}
    assert rv[("C", "Gross savings multiplier")]["reversal_found"]
    assert isclose(rv[("C", "Gross savings multiplier")]["analytic_switch_multiplier"], 92211.73848687354 / 160000, rel_tol=1e-9)
    assert not rv[("C", "CAPEX multiplier")]["reversal_found"]
    assert not rv[("ALL", "Shared real discount rate")]["reversal_found"]


def test_missing_supplier_separated_and_does_not_contaminate_baseline(unc):
    ms = unc["missing"]
    assert len({r["avoided_known_t"] for r in ms}) == 1          # applicability never touches known freight
    for r in ms:
        exp = r["reduction_rate"] * r["applicability_to_b"] * r["hypothetical_b_emissions_t"]
        assert isclose(r["avoided_hypothetical_b_t"], exp, abs_tol=1e-9)
        assert r["financial_npv_effect_sar"] == 0 and "SENSITIVITY ASSUMPTION" in r["label"]
    base = [c for c in unc["cases"] if c["case"] == "Base" and c["id"] == "B"][0]
    assert isclose(base["avoided_known_t"], 28.96455, abs_tol=1e-5)          # primary figure: known data only
    assert isclose(base["avoided_incl_hypothetical_b_t"], 58.96455, abs_tol=1e-5)  # workbook figure, labelled
    audit, _ = ce.run()
    assert _src(ce.by_source(audit))["Freight - Contractor B"]["emissions_t"] is None


# ------------------------------------------------------------------ outputs, factor, reproducibility
def test_no_superseded_electricity_factor_in_active_calculations(tmp_path):
    rwc.main(tmp_path)
    for p in tmp_path.iterdir():
        txt = p.read_text(encoding="utf-8")
        assert "FAC-ELE-GRID-01" not in txt and "614.2" not in txt, p.name
    factors, _, _ = ce.v.load_registers()
    assert "FAC-ELE-GRID-01" not in factors and factors["FAC-ELEC-SEC-01"]["factor_value"] == "550"


def test_workstream_c_outputs_reproducible(tmp_path):
    assert rwc.main(tmp_path / "a") == 0 and rwc.main(tmp_path / "b") == 0
    a = json.loads((tmp_path / "a" / "run_manifest_c.json").read_text())
    b = json.loads((tmp_path / "b" / "run_manifest_c.json").read_text())
    assert a["outputs"] == b["outputs"] and a["reconciliation"]["not_matching"] == 0
    names = set(a["outputs"])
    for n in ("scenario_assumptions.csv", "scenario_comparison.csv", "scenario_monthly.csv", "scenario_audit_trail.csv",
              "financial_assumptions.csv", "financial_cash_flows.csv", "financial_comparison.csv",
              "operational_feasibility.csv", "uncertainty_cases.csv", "sensitivity_results.csv",
              "switching_values.csv", "ranking_analysis.csv", "missing_supplier_sensitivity.csv"):
        assert n in names, n


# ------------------------------------------------------------------ dashboard
def _app():
    from streamlit.testing.v1 import AppTest
    return AppTest.from_file(str(HERE / "app.py"), default_timeout=180)


def test_dashboard_all_tabs_present_and_no_exceptions():
    at = _app().run()
    assert not at.exception
    # Phase 11 adds a 9th top-level tab (whose own section tabs follow); the original 8 are unchanged and in order
    labels = [t.label for t in at.tabs]
    assert labels[:8] == ["Hotspots", "Monthly trends", "Data confidence", "Emission factors",
                          "Audit trail", "Reduction scenarios", "Financial evaluation", "Decision intelligence"]
    assert labels[8] == "Supplier Decision & Engagement"
    vals = {m.label: m.value for m in at.metric}
    assert vals["Scope 2 · electricity"] == "4,400.0 tCO₂e" and vals["Record completeness"] == "48/60 = 80%"
    assert any("Contractor B" in w.value for w in at.warning)


def test_dashboard_interactive_values_use_the_engines():
    at = _app().run()
    at.slider(key="sc_rate_C").set_value(20).run()
    assert not at.exception
    exp = se.run_all(rates={"A": 0.10, "B": 0.15, "C": 0.20})["results"]["ABC"]["avoided_t"]
    vals = {m.label: m.value for m in at.metric}
    assert vals["Annual CO₂e avoided (combined)"] == f"{exp:,.1f} tCO₂e"
    at.number_input(key="fin_capex_C").set_value(600000.0).run()
    p = fe.base_params(avoided={"A": 26.6155, "B": 28.964552, "C": 880.0})
    p["C"]["capex"] = 600000.0
    exp_npv = fe.evaluate(p["C"])["npv_sar"]
    tables = [d.value for d in at.dataframe]
    assert any("Financial NPV" in t.columns and f"SAR {exp_npv:,.0f}" in list(t["Financial NPV"]) for t in tables)
    assert any("session-only" in i.value for i in at.info)
