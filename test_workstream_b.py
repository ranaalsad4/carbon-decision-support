"""Workstream B (Phases 6-7) tests.   Run:  python -m pytest -v"""
import csv
import hashlib
import json
from math import isclose
from pathlib import Path

import pytest

import calc_engine as ce
import confidence as cf

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def results():
    audit, findings = ce.run()
    sources = ce.by_source(audit)
    return audit, findings, sources, ce.by_scope(sources), cf.assess(audit, sources)


def test_no_block_on_clean_data(results):
    assert not [f for f in results[1] if f["severity"] == "BLOCK"]


def test_independent_hand_calculated_cases(results):
    audit, _, sources, scopes, _ = results
    rec = {a["activity_id"]: a for a in audit}
    src = {s["stream"]: s for s in sources}
    scp = {s["scope"]: s for s in scopes}
    for c in csv.DictReader(open(HERE / "calculation_test_cases.csv", encoding="utf-8")):
        if c["level"] == "record":
            got, unit = (rec[c["key"]]["emissions_t"] or None), rec[c["key"]]["emissions_unit"]
            got = float(got) if got else None
        elif c["level"] == "source":
            got, unit = src[c["key"]]["emissions_t"], src[c["key"]]["emissions_unit"]
        else:
            got, unit = scp[c["key"]]["emissions_t"], scp[c["key"]]["emissions_unit"]
        assert unit == c["expected_unit"], c["case_id"]
        if c["expected_emissions_t"] == "UNAVAILABLE":
            assert got is None, c["case_id"]
        else:
            assert isclose(got, float(c["expected_emissions_t"]), abs_tol=1e-6), c["case_id"]


def test_reproducible_identical_outputs(tmp_path, monkeypatch):
    def run_once(d):
        monkeypatch.setattr(ce, "OUT", d)
        assert ce.main() == 0
        return json.loads((d / "run_manifest.json").read_text())["outputs"]
    a = run_once(tmp_path / "a"); b = run_once(tmp_path / "b")
    assert a == b and len(a) == 6


def test_audit_trail_preserves_ids_units_sources(results):
    audit = results[0]
    clean = ce.v.read("activity_data_clean.csv")
    factors, _, evidence = ce.v.load_registers()
    assert [a["activity_id"] for a in audit] == [r["activity_id"] for r in clean]
    for a, r in zip(audit, clean):
        f = factors[r["factor_id"]]
        assert a["factor_id"] == r["factor_id"] and a["unit_raw"] == r["unit"] and a["evidence_id"] == r["evidence_id"]
        assert a["factor_value"] == f["factor_value"] and a["factor_source_url"] == f["source_url"]
        assert a["evidence_reference"] == evidence[r["evidence_id"]]["source_reference"]
        assert a["formula"] and a["engine_version"] == ce.ENGINE_VERSION
        if a["emissions_t"]:  # recompute from the audit trail alone
            assert isclose(float(a["quantity_calc"]) * float(a["factor_value"]) / 1000, float(a["emissions_t"]), abs_tol=1e-6)


def test_contractor_b_unavailable_never_zero(results):
    audit, _, sources, _, _ = results
    b = [a for a in audit if a["supplier_id"] == "SUP-CARR-B"]
    assert len(b) == 12 and all(a["emissions_t"] == "" for a in b)
    s = next(s for s in sources if s["supplier_id"] == "SUP-CARR-B")
    assert s["emissions_t"] is None and s["activity_total"] is None and s["status"] == "UNAVAILABLE"
    assert all(m["emissions_t"] is None for m in ce.monthly(audit) if m["stream"] == "Freight - Contractor B")


def test_gas_labels_separate(results):
    _, _, sources, scopes, _ = results
    assert {s["scope"]: s["emissions_unit"] for s in scopes} == {"1": "tCO2e", "2": "tCO2e", "3": "tCO2e"}
    assert next(s for s in sources if s["stream"] == "Grid electricity")["emissions_unit"] == "tCO2e"
    # every result keeps the gas label of its own factor
    factors, _, _ = ce.v.load_registers()
    for a in results[0]:
        assert a["emissions_unit"] == "t" + factors[a["factor_id"]]["gas_coverage"]


def test_record_completeness_and_coverage(results):
    conf = results[4]
    rc, ec = conf["record_completeness"], conf["emissions_coverage"]
    assert (rc["with_data"], rc["total"], rc["missing"], rc["pct"]) == (48, 60, 12, 80.0)
    assert ec["sources_quantified"] == 4 and ec["carriers_quantified"] == 2
    assert "unknown" in ec["share_of_true_total"]


def test_confidence_labels_follow_criteria(results):
    labels = {s["stream"]: s["confidence_label"] for s in results[4]["streams"]}
    assert labels == {"Diesel generators": "MODERATE", "Grid electricity": "MODERATE",
                      "Freight - Contractor A": "LOW", "Freight - Contractor B": "NOT QUANTIFIED",
                      "Freight - Contractor C": "LOW"}
    for s in results[4]["streams"]:
        assert not any("%" in str(v) for k, v in s.items() if k.startswith("C") or k == "confidence_label")


def test_label_rule_unit():
    allmet = {c: "Met" for c in cf.CRITERIA}
    assert cf.label(allmet)[0] == "HIGH"
    assert cf.label({**allmet, "C3": "Partial"})[0] == "MODERATE"
    assert cf.label({**allmet, "C2": "Not met", "C4": "Not met"})[0] == "LOW"
    assert cf.label({**allmet, "C1": "Not met"})[0] == "NOT QUANTIFIED"


def test_phase4_inputs_unchanged():
    """Phase 4 data files are reused, not regenerated (hashes match the shipped Phase 4 package)."""
    manifest = json.loads((HERE / "outputs" / "run_manifest.json").read_text())
    for n, h in manifest["inputs"].items():
        assert hashlib.sha256((ce.PHASE4 / "data" / n).read_bytes()).hexdigest() == h


def test_dashboard_runs_without_errors():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(HERE / "app.py"), default_timeout=60).run()
    assert not at.exception
    assert any("80%" in m.value for m in at.metric)
    assert any("Contractor B" in w.value for w in at.warning)


# ---------- v6.1: revised electricity factor (Phase 3 / Phase 4 alignment)
def test_electricity_factor_loaded_from_phase4_library(results):
    """The engine takes the factor from the Phase 4 register; it is the SEC 2024 provisional proxy."""
    factors, _, _ = ce.v.load_registers()
    f = factors["FAC-ELEC-SEC-01"]
    elec = [a for a in results[0] if a["activity_type"] == "electricity_purchased"]
    assert len(elec) == 12 and {a["factor_id"] for a in elec} == {"FAC-ELEC-SEC-01"}
    for a in elec:
        assert (a["factor_value"], a["factor_unit"]) == (f["factor_value"], f["factor_unit"]) == ("550", "kg CO2e/MWh")
        assert a["factor_source"] == "Saudi Electricity Company (SEC)" and a["factor_applicable_year"] == "2024"
        assert a["factor_boundary"] == "grid_generation" and a["factor_accounting_method"] == "location_based"
        assert a["factor_accounting_scope"] == "2" and a["factor_verification"] == "provisional_proxy"
    src = next(s for s in results[2] if s["stream"] == "Grid electricity")
    assert src["activity_total"] == 8000 and isclose(src["emissions_t"], 8000 * float(f["factor_value"]) / 1000)


def test_no_superseded_electricity_factor_in_active_outputs():
    for name in ("calculation_audit_trail.csv", "emissions_by_source.csv", "emissions_by_scope.csv",
                 "emissions_monthly.csv", "hotspot_ranking.csv", "data_confidence.csv"):
        text = (HERE / "outputs" / name).read_text(encoding="utf-8")
        assert "FAC-ELE-GRID-01" not in text and "614.2" not in text and "4913.6" not in text, name


def test_quantified_total_reconciles_with_sources_and_shares(results):
    _, _, sources, scopes, _ = results
    total, units = ce.quantified_total(sources)
    assert units == ["tCO2e"]
    assert isclose(total, sum(s["emissions_t"] for s in scopes), abs_tol=1e-6)
    assert isclose(total, 266.155 + 4400 + 121.956 + 71.141, abs_tol=1e-6)
    ranked, t2 = ce.hotspots(sources)
    assert t2 == total and ranked[0]["stream"] == "Grid electricity"
    assert isclose(sum(h["share_of_quantified_pct"] for h in ranked if h["emissions_t"] is not None), 100, abs_tol=0.2)


def test_provisional_factor_not_scored_as_verified(results):
    elec = next(s for s in results[4]["streams"] if s["stream"] == "Grid electricity")
    assert elec["C5 Factor verification"] == "Not met" and elec["confidence_label"] != "HIGH"
