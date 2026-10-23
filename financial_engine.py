"""Workstream C, Phase 9 - financial and operational evaluation engine.

Reproduces the Phase 9 workbook ('Assumptions' -> 'Cash Flows' -> 'Decision Summary') in Python.
All inputs are read from the workbook; annual avoided emissions come from the Phase 8 scenario
engine (activity-record calculation), not from the workbook's typed baseline.

Conventions (from Phase 9 'Assumptions'!B20 and 'Sources and Method'):
  * constant real SAR, end-of-year cash flows, no escalation, no residual value, no taxes/financing
  * CAPEX at year 0; net saving (gross savings - incremental OPEX) in year t if lead time < t <= life
    and t <= horizon
  * discount factor DF_t = 1 / (1 + r)^t            (real rate, illustrative 5%)
  * Financial NPV = -CAPEX + SUM_t DF_t x net_t      (company cash-flow perspective)
  * Net present cost (NPC) = -NPV
  * Cost per tonne = NPC / UNDISCOUNTED lifetime tCO2e avoided (SAR/tCO2e)
      numerator: discounted SAR (all money discounted); denominator: physical tonnes, undiscounted
      negative value = net financial saving per tonne (negative net abatement cost)
    A supplementary 'levelised' variant divides NPC by DISCOUNTED tonnes; it is reported
    separately and never mixed with the workbook convention.
  * Simple payback = CAPEX / annual net savings (workbook); payback from year 0 also adds the lead time.

Departures from the workbook formulas (edge cases only; identical at the workbook inputs):
  * payback and cost per tonne are None ('not reached' / 'not defined') where the workbook returns 0
  * a 0% discount rate is handled exactly (annuity factor = number of benefit years)

    python financial_engine.py         # writes outputs/workstream_c/financial_*.csv
"""
import math
from pathlib import Path

import scenario_engine as se
import workstream_c_inputs as wi

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs" / "workstream_c"
ENGINE_VERSION = "WSC-9.0"
PARAMS = ("capex", "savings", "opex", "delay", "life")


def benefit_years(delay, life, horizon):
    return max(0, int(min(horizon, life)) - int(delay))


def annuity_factor(rate, delay, life, horizon):
    """PV of 1 SAR per year received in years delay+1 .. min(life, horizon)."""
    n = benefit_years(delay, life, horizon)
    if n == 0:
        return 0.0
    if rate == 0:
        return float(n)
    return (1 - (1 + rate) ** (-n)) / rate / (1 + rate) ** delay


def _check(p):
    for k in ("delay", "life", "horizon"):
        if float(p[k]) != int(p[k]) or p[k] < 0:
            raise ValueError(f"{k} must be a non-negative whole number of years: {p[k]}")
    if p["rate"] <= -1:
        raise ValueError("discount rate must be > -100%")


def cash_flows(p):
    """Year-by-year table, years 0..horizon (mirrors 'Cash Flows' sheet)."""
    _check(p)
    rows, cum, cum_pv = [], 0.0, 0.0
    for t in range(0, int(p["horizon"]) + 1):
        capex = p["capex"] if t == 0 else 0.0
        active = t > 0 and p["delay"] < t <= p["life"]
        gross = p["savings"] if active else 0.0
        opex = p["opex"] if active else 0.0
        net = gross - opex - capex
        df = 1 / (1 + p["rate"]) ** t
        pv = net * df
        cum += net; cum_pv += pv
        rows.append({"year": t, "capex_sar": -capex, "gross_savings_sar": gross, "opex_sar": -opex,
                     "net_cash_flow_sar": net, "discount_factor": df, "pv_sar": pv,
                     "cumulative_net_sar": cum, "cumulative_pv_sar": cum_pv,
                     "avoided_tco2e": p.get("avoided_t", 0.0) if active else 0.0})
    return rows


def npv(p):
    return sum(r["pv_sar"] for r in cash_flows(p))


def npv_closed_form(p):
    """Same NPV through the annuity formula used in Phase 10 (independent check)."""
    return -p["capex"] + (p["savings"] - p["opex"]) * annuity_factor(p["rate"], p["delay"], p["life"], p["horizon"])


def irr(p, lo=-0.99, hi=10.0, tol=1e-10):
    """Discount rate at which NPV = 0 (switching value for the discount rate). None if no sign change."""
    def f(r):
        return npv_closed_form({**p, "rate": r})
    flo, fhi = f(lo), f(hi)
    if flo == 0:
        return lo
    if flo * fhi > 0:
        return None
    for _ in range(300):
        mid = (lo + hi) / 2
        fm = f(mid)
        if abs(fm) < tol or hi - lo < tol:
            return mid
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


def _discounted_payback(rows):
    for prev, cur in zip(rows, rows[1:]):
        if prev["cumulative_pv_sar"] < 0 <= cur["cumulative_pv_sar"]:
            return prev["year"] + (-prev["cumulative_pv_sar"]) / cur["pv_sar"]
    return None


def evaluate(p):
    """All Phase 9 metrics for one parameter set.
    p: capex, savings, opex, delay, life, horizon, rate, avoided_t (annual tCO2e)."""
    rows = cash_flows(p)
    v = sum(r["pv_sar"] for r in rows)
    net = p["savings"] - p["opex"]
    n = benefit_years(p["delay"], p["life"], p["horizon"])
    lifetime_t = p["avoided_t"] * n
    disc_t = p["avoided_t"] * annuity_factor(p["rate"], p["delay"], p["life"], p["horizon"])
    npc = -v
    simple = p["capex"] / net if net > 0 else None
    from_y0 = (p["delay"] + simple) if simple is not None else None
    if from_y0 is not None and from_y0 > p["delay"] + n:
        from_y0 = None  # not recovered within the benefit period
    cpt = npc / lifetime_t if lifetime_t > 0 else None
    return {
        "annual_avoided_t": p["avoided_t"], "capex_sar": p["capex"], "gross_savings_sar": p["savings"],
        "opex_sar": p["opex"], "net_savings_sar": net, "lead_time_y": p["delay"], "life_y": p["life"],
        "horizon_y": p["horizon"], "discount_rate": p["rate"], "benefit_years": n,
        "annuity_factor": annuity_factor(p["rate"], p["delay"], p["life"], p["horizon"]),
        "npv_sar": v, "npv_closed_form_sar": npv_closed_form(p), "npc_sar": npc,
        "lifetime_avoided_t_undiscounted": lifetime_t, "lifetime_avoided_t_discounted": disc_t,
        "cost_per_t_sar": cpt,
        "levelised_cost_per_t_sar": (npc / disc_t) if disc_t > 0 else None,
        "simple_payback_y": simple, "payback_from_year0_y": from_y0,
        "discounted_payback_y": _discounted_payback(rows),
        "irr": irr(p),
        "classification": "Positive financial NPV" if v > 0 else "Non-positive financial NPV",
        "abatement_cost_note": (None if cpt is None else
                                "negative net abatement cost: potential net financial saving per tonne" if cpt < 0
                                else "positive net abatement cost: net financial cost per tonne"),
        "cash_flows": rows,
    }


def base_params(p9=None, avoided=None):
    """Phase 9 inputs per intervention, with annual avoided tCO2e from the scenario engine."""
    p9 = p9 or wi.load_phase9()
    if avoided is None:
        sc = se.run_all(include_combined=False)
        avoided = {i: sc["comparison"][k]["avoided_t"] for k, i in enumerate(wi.IDS)}
    g = p9["global"]
    out = {}
    for iid in wi.IDS:
        a = p9["interventions"][iid]
        out[iid] = {k: a[k] for k in PARAMS}
        out[iid].update({"horizon": g["horizon"], "rate": g["rate"], "avoided_t": avoided[iid]})
    return out


def portfolio(params, combined_avoided_t):
    """All three interventions together: cash flows add (assumes NO cost or saving interactions -
    not specified in the workbook). Emissions use the combined scenario (no double counting)."""
    per = {i: evaluate(params[i]) for i in params}
    rows = []
    for t in range(len(per[wi.IDS[0]]["cash_flows"])):
        rows.append({k: sum(per[i]["cash_flows"][t][k] for i in per) for k in
                     ("capex_sar", "gross_savings_sar", "opex_sar", "net_cash_flow_sar", "pv_sar")})
    v = sum(r["pv_sar"] for r in rows)
    life_t = sum(per[i]["lifetime_avoided_t_undiscounted"] for i in per)
    assert abs(sum(params[i]["avoided_t"] for i in params) - combined_avoided_t) < 1e-6, "combined overlap"
    return {"npv_sar": v, "capex_sar": sum(params[i]["capex"] for i in params),
            "annual_avoided_t": combined_avoided_t, "lifetime_avoided_t_undiscounted": life_t,
            "cost_per_t_sar": (-v / life_t) if life_t > 0 else None}


def feasibility(p9):
    key = {"Diesel A": ["A"], "Freight B": ["B"], "Electricity C": ["C"], "All": list(wi.IDS)}
    rows = []
    for f in p9["feasibility"]:
        for iid in key.get(f["scenario"], []):
            rows.append({"id": iid, "intervention_column": f["scenario"], **{k: f[k] for k in
                         ("check", "evidence_needed", "current_status", "decision_implication", "source_ref")}})
    return rows


def feasibility_summary(rows, p9):
    out = {}
    for iid in wi.IDS:
        r = [x for x in rows if x["id"] == iid]
        st = [x["current_status"] for x in r]
        out[iid] = {"checks": len(r), "validated": sum(s == "Validated" for s in st),
                    "not_validated": sum(s == "Not validated" for s in st),
                    "other_status": "; ".join(sorted({s for s in st if s not in ("Validated", "Not validated")})),
                    "screening": p9["interventions"][iid]["feasibility"],
                    "main_dependency": p9["interventions"][iid]["dependency"],
                    "status": "Not demonstrated - all checks unvalidated (synthetic screening only)"
                    if not any(s == "Validated" for s in st) else "Partially validated"}
    return out


def run(params=None, p9=None, avoided=None, combined_avoided=None):
    p9 = p9 or wi.load_phase9()
    if params is None:
        sc = se.run_all()
        avoided = {i: sc["results"][i]["avoided_t"] for i in wi.IDS}
        combined_avoided = sc["results"][se.COMBINED]["avoided_t"]
        params = base_params(p9, avoided)
    res = {i: evaluate(params[i]) for i in wi.IDS}
    port = portfolio(params, combined_avoided) if combined_avoided is not None else None
    return {"params": params, "results": res, "portfolio": port, "p9": p9}


def reconciliation(res, p9):
    rows = []
    for iid in wi.IDS:
        r, c = res[iid], p9["cached"][iid]
        for key, eng in (("avoided_t", r["annual_avoided_t"]), ("net_savings", r["net_savings_sar"]),
                         ("npv", r["npv_sar"]), ("lifetime_t", r["lifetime_avoided_t_undiscounted"]),
                         ("npc", r["npc_sar"]), ("cost_per_t", r["cost_per_t_sar"]),
                         ("payback", r["simple_payback_y"]), ("classification", r["classification"])):
            wb = c[key]
            if isinstance(wb, str):
                diff, ok = "", wb == eng
            else:
                diff = eng - wb
                ok = abs(diff) <= max(1e-6, 1e-6 * abs(wb))
            rows.append({"id": iid, "metric": key, "engine": eng, "workbook_cached": wb, "workbook_ref": c[key + "_ref"],
                         "difference": diff, "status": "MATCH" if ok else "DIFFERENT"})
        for e, w in zip(r["cash_flows"], p9["cash_flows_cached"][iid]):
            for key, wk in (("net_cash_flow_sar", "net"), ("discount_factor", "df"), ("pv_sar", "pv")):
                d = e[key] - w[wk]
                rows.append({"id": iid, "metric": f"year{e['year']}_{wk}", "engine": e[key], "workbook_cached": w[wk],
                             "workbook_ref": "Cash Flows", "difference": d,
                             "status": "MATCH" if abs(d) <= 1e-6 else "DIFFERENT"})
    return rows


def main(out_dir=None):
    out = Path(out_dir) if out_dir else OUT
    r = run()
    p9, params, res = r["p9"], r["params"], r["results"]
    units = {"capex": "SAR (year 0)", "savings": "SAR/year", "opex": "SAR/year", "delay": "years", "life": "years"}
    assum = []
    for iid in wi.IDS:
        a = p9["interventions"][iid]
        for k in PARAMS:
            assum.append({"id": iid, "parameter": k, "label": a[k + "_label"], "value": a[k], "unit": units[k],
                          "source_ref": a[k + "_ref"], "evidence_status": a["evidence"]})
        assum.append({"id": iid, "parameter": "annual_avoided_t", "label": "Annual emissions avoided",
                      "value": params[iid]["avoided_t"], "unit": "tCO2e/year",
                      "source_ref": "scenario_engine (Phase 8 rate x Phase 4 activity records)",
                      "evidence_status": "Synthetic assumption"})
    g = p9["global"]
    for k, unit in (("horizon", "years"), ("rate", "real, per year")):
        assum.append({"id": "ALL", "parameter": k, "label": k, "value": g[k], "unit": unit,
                      "source_ref": g[k + "_ref"], "evidence_status": "Illustrative"})
    assum.append({"id": "ALL", "parameter": "basis", "label": "Cash-flow basis", "value": g["basis"], "unit": "",
                  "source_ref": g["basis_ref"], "evidence_status": "Workbook convention"})
    se.write_csv(out / "financial_assumptions.csv", assum)
    cf = [{"id": iid, **{k: v for k, v in row.items()}} for iid in wi.IDS for row in res[iid]["cash_flows"]]
    se.write_csv(out / "financial_cash_flows.csv", cf)
    comp = []
    for iid in wi.IDS:
        m = {k: v for k, v in res[iid].items() if k != "cash_flows"}
        comp.append({"id": iid, "intervention": p9["interventions"][iid]["scenario"], **m,
                     "npv_workbook_sar": p9["cached"][iid]["npv"], "npv_workbook_ref": p9["cached"][iid]["npv_ref"],
                     "evidence_status": p9["interventions"][iid]["evidence"],
                     "caveat": "Synthetic illustrative inputs; not a vendor quotation or investment approval"})
    if r["portfolio"]:
        pf = r["portfolio"]
        comp.append({"id": "ABC", "intervention": "Portfolio A+B+C (additive cash flows, no interactions assumed)",
                     "annual_avoided_t": pf["annual_avoided_t"], "capex_sar": pf["capex_sar"], "npv_sar": pf["npv_sar"],
                     "lifetime_avoided_t_undiscounted": pf["lifetime_avoided_t_undiscounted"],
                     "cost_per_t_sar": pf["cost_per_t_sar"], "caveat": "Not in the Phase 9 workbook; additive illustration"})
    keys = list(comp[0].keys())
    comp = [{k: c.get(k, "") for k in keys} for c in comp]
    se.write_csv(out / "financial_comparison.csv", comp)
    fz = feasibility(p9)
    summ = feasibility_summary(fz, p9)
    fz_rows = fz + [{"id": iid, "intervention_column": "SUMMARY", "check": f"{s['checks']} checks",
                     "evidence_needed": s["main_dependency"],
                     "current_status": f"{s['validated']} validated / {s['not_validated']} not validated"
                     + (f" / {s['other_status']}" if s["other_status"] else ""),
                     "decision_implication": s["status"], "source_ref": "Feasibility sheet (summary)"}
                    for iid, s in summ.items()]
    se.write_csv(out / "operational_feasibility.csv", fz_rows)
    se.write_csv(out / "financial_reconciliation.csv", reconciliation(res, p9))
    for iid in wi.IDS:
        x = res[iid]
        print(f"  {iid}: NPV {x['npv_sar']:>12,.2f} SAR | payback {x['simple_payback_y']:.2f} y | "
              f"{x['cost_per_t_sar']:,.2f} SAR/tCO2e | IRR {x['irr']:.2%}")
    return r


if __name__ == "__main__":
    main()
