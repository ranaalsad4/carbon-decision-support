"""Workstream C, Phase 10 - uncertainty-aware decision analysis engine.

Source: the CORRECTED Phase 10 workbook (stress multipliers, Contractor B sensitivity inputs).
Financial base inputs come from Phase 9; avoided emissions from the Phase 8 scenario engine;
NPV and cost metrics from financial_engine.evaluate (one implementation for every phase).

Case definitions (Phase 10 'Cases' sheet):
  effectiveness = Phase 8 rate x effectiveness multiplier
  CAPEX         = CAPEX x CAPEX multiplier
  gross savings = savings x savings multiplier x effectiveness multiplier   (savings scale with effectiveness)
  OPEX          = OPEX x OPEX multiplier
Low/base/high are coherent joint stress cases, NOT statistical confidence intervals.

Contractor B (missing activity) - kept strictly separate:
  known avoided (A+C)      = effectiveness x known freight emissions   (scenario engine, activity records)
  hypothetical B avoided   = effectiveness x applicability x hypothetical Contractor B emissions
  workbook total           = known avoided + hypothetical B avoided
  Applicability is applied ONLY to the hypothetical B term, never to known freight.
  Hypothetical B values are SENSITIVITY ASSUMPTIONS, not inventory values; the baseline is never
  changed and no financial savings are assigned to Contractor B (no cost/activity data).

Note on the corrected workbook: its 'Base' freight case already includes 200 tCO2e/y of
hypothetical Contractor B (Cases!H8 = 58.96 tCO2e/y). This engine reports the known-data figure
(28.96 tCO2e/y, consistent with Phases 8-9) as primary and the workbook's B-inclusive figure
separately, labelled as a sensitivity.

    python uncertainty_engine.py       # writes outputs/workstream_c/{uncertainty,sensitivity,...}.csv
"""
from functools import lru_cache
from pathlib import Path

import calc_engine as ce
import confidence as cf
import financial_engine as fe
import scenario_engine as se
import workstream_c_inputs as wi

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs" / "workstream_c"
ENGINE_VERSION = "WSC-10.0"
CASES = ("Low", "Base", "High")
NAMES = {"A": "Diesel efficiency", "B": "Known freight optimisation", "C": "Electricity efficiency"}
# Ranges tested by the engine where the workbook gives none (documented as engine choices)
SWEEP_MULTIPLIERS = [round(0.5 + 0.05 * k, 2) for k in range(21)]          # 0.50 .. 1.50
SWEEP_RATES = [round(0.005 * k, 3) for k in range(31)]                      # 0% .. 15%
ONE_WAY_RATES = (0.03, 0.08)                                                # discount-rate low/high
ONE_WAY_DELAYS = (1, 2)                                                     # implementation lead time


# --------------------------------------------------------------------------- inputs
@lru_cache(maxsize=1)
def _baseline():
    return se.baseline()


@lru_cache(maxsize=512)
def avoided_known(iid, rate):
    """Annual avoided tCO2e for intervention iid at reduction `rate`, from activity records."""
    res = se.run_scenario([iid], {**{i: 0.0 for i in wi.IDS}, iid: rate}, _baseline())
    return round(sum(float(a["avoided_t"]) for a in res["audit"] if a["avoided_t"] != ""), 6)


def load():
    p8, p9, p10 = wi.load_all()
    _, _, sources = _baseline()
    tb = se.target_baseline(sources)
    qt, _ = ce.quantified_total(sources)
    checks = wi.check_consistency(p8, p9, p10, tb, qt)
    bad = [c for c in checks if c["status"] == "MISMATCH"]
    if bad:
        raise wi.WorkbookError(f"workbook inconsistencies: {bad}")
    return {"p8": p8, "p9": p9, "p10": p10, "target_baseline": tb, "quantified_total": qt, "checks": checks}


def multipliers(g, case):
    if case == "Base":
        return {"eff": 1.0, "capex": 1.0, "sav": 1.0, "opex": 1.0, "b": 1.0}
    k = case.lower()
    return {"eff": g[f"{k}_eff"], "capex": g[f"{k}_capex"], "sav": g[f"{k}_sav"], "opex": g[f"{k}_opex"],
            "b": g[f"b_{k}_mult"]}


def base_inputs(ctx):
    """Base parameter set per intervention (Phase 9 money, Phase 8 rate, Phase 9 horizon/rate)."""
    p9, p8 = ctx["p9"], ctx["p8"]
    out = {}
    for iid in wi.IDS:
        a = p9["interventions"][iid]
        out[iid] = {"capex": a["capex"], "savings": a["savings"], "opex": a["opex"], "delay": a["delay"],
                    "life": a["life"], "horizon": p9["global"]["horizon"], "rate": p9["global"]["rate"],
                    "reduction": p8[iid]["reduction"]}
    return out


def evaluate_point(iid, b, eff_mult=1.0, capex_mult=1.0, sav_mult=1.0, opex_mult=1.0, rate=None, delay=None,
                   b_imputed_t=0.0, applicability=0.0, savings_scale_with_eff=True):
    """One intervention at one assumption set -> dict of NPV and abatement metrics."""
    eff = b["reduction"] * eff_mult
    if not 0 <= eff < 1:
        raise ValueError(f"effectiveness out of range for {iid}: {eff}")
    known = avoided_known(iid, round(eff, 12))
    hyp_b = eff * applicability * b_imputed_t if iid == "B" else 0.0
    p = {"capex": b["capex"] * capex_mult,
         "savings": b["savings"] * sav_mult * (eff_mult if savings_scale_with_eff else 1.0),
         "opex": b["opex"] * opex_mult, "delay": b["delay"] if delay is None else delay, "life": b["life"],
         "horizon": b["horizon"], "rate": b["rate"] if rate is None else rate, "avoided_t": known}
    r = fe.evaluate(p)
    yrs = r["benefit_years"]
    tot = known + hyp_b
    return {"effectiveness": eff, "capex_sar": p["capex"], "gross_savings_sar": p["savings"], "opex_sar": p["opex"],
            "discount_rate": p["rate"], "lead_time_y": p["delay"], "npv_sar": r["npv_sar"],
            "avoided_known_t": known, "hypothetical_b_imputed_t": b_imputed_t if iid == "B" else 0.0,
            "avoided_hypothetical_b_t": hyp_b, "avoided_incl_hypothetical_b_t": tot,
            "cost_per_t_known_sar": r["cost_per_t_sar"],
            "cost_per_t_incl_hyp_b_sar": (-r["npv_sar"] / (tot * yrs)) if tot * yrs > 0 else None,
            "simple_payback_y": r["simple_payback_y"], "irr": r["irr"]}


# --------------------------------------------------------------------------- 1. cases
def cases(ctx):
    g = ctx["p10"]["global"]
    bi = base_inputs(ctx)
    rows = []
    for case in CASES:
        m = multipliers(g, case)
        b_imp = g["b_base_t"] * m["b"]
        for iid in wi.IDS:
            r = evaluate_point(iid, bi[iid], m["eff"], m["capex"], m["sav"], m["opex"],
                               b_imputed_t=b_imp, applicability=g["b_applicability"])
            rows.append({"case": case, "id": iid, "intervention": NAMES[iid], **r})
    for case in CASES:
        grp = [r for r in rows if r["case"] == case]
        for r in grp:
            r["rank_by_npv"] = 1 + sum(o["npv_sar"] > r["npv_sar"] for o in grp)
            r["positive_npv"] = r["npv_sar"] > 0
    return rows


def reconcile_cases(rows, ctx):
    cached = {(c["case"], c["id"]): c for c in ctx["p10"]["cases_cached"]}
    out = []
    for r in rows:
        c = cached[(r["case"], r["id"])]
        for key, eng, wk in (("effectiveness", r["effectiveness"], "effectiveness"), ("capex", r["capex_sar"], "capex"),
                             ("savings", r["gross_savings_sar"], "savings"), ("opex", r["opex_sar"], "opex"),
                             ("b_imputed_t", r["hypothetical_b_imputed_t"], "b_imputed_t"),
                             ("avoided_t (workbook incl. hyp. B)", r["avoided_incl_hypothetical_b_t"], "avoided_t"),
                             ("npv", r["npv_sar"], "npv"),
                             ("cost_per_t (workbook incl. hyp. B)", r["cost_per_t_incl_hyp_b_sar"] or 0.0, "cost_per_t"),
                             ("rank", r["rank_by_npv"], "rank")):
            d = eng - c[wk]
            ok = abs(d) <= max(1e-5, 1e-6 * abs(c[wk]))
            out.append({"case": r["case"], "id": r["id"], "metric": key, "engine": eng, "workbook_cached": c[wk],
                        "workbook_ref": c["ref"], "difference": d, "status": "MATCH" if ok else "DIFFERENT"})
    return out


# --------------------------------------------------------------------------- 2-6. one-way sensitivity
def one_way(ctx):
    g = ctx["p10"]["global"]
    bi = base_inputs(ctx)
    base = {i: evaluate_point(i, bi[i]) for i in wi.IDS}
    tests = [
        ("CAPEX", "Low case CAPEX multiplier", {"capex_mult": g["low_capex"]}, g["low_capex_ref"]),
        ("CAPEX", "High case CAPEX multiplier", {"capex_mult": g["high_capex"]}, g["high_capex_ref"]),
        ("Annual gross savings", "Low case savings multiplier", {"sav_mult": g["low_sav"]}, g["low_sav_ref"]),
        ("Annual gross savings", "High case savings multiplier", {"sav_mult": g["high_sav"]}, g["high_sav_ref"]),
        ("OPEX", "Low case OPEX multiplier", {"opex_mult": g["low_opex"]}, g["low_opex_ref"]),
        ("OPEX", "High case OPEX multiplier", {"opex_mult": g["high_opex"]}, g["high_opex_ref"]),
        ("Reduction effectiveness", "Low case effectiveness multiplier (savings scale)", {"eff_mult": g["low_eff"]}, g["low_eff_ref"]),
        ("Reduction effectiveness", "High case effectiveness multiplier (savings scale)", {"eff_mult": g["high_eff"]}, g["high_eff_ref"]),
        ("Discount rate", f"{ONE_WAY_RATES[0]:.0%} real", {"rate": ONE_WAY_RATES[0]}, "engine-selected test value"),
        ("Discount rate", f"{ONE_WAY_RATES[1]:.0%} real", {"rate": ONE_WAY_RATES[1]}, "engine-selected test value"),
        ("Implementation lead time", f"{ONE_WAY_DELAYS[0]} year delay", {"delay": ONE_WAY_DELAYS[0]}, "engine-selected test value"),
        ("Implementation lead time", f"{ONE_WAY_DELAYS[1]} year delay", {"delay": ONE_WAY_DELAYS[1]}, "engine-selected test value"),
    ]
    rows = []
    for param, level, kw, src in tests:
        pts = {i: evaluate_point(i, bi[i], **kw) for i in wi.IDS}
        ranking = sorted(wi.IDS, key=lambda i: -pts[i]["npv_sar"])
        for iid in wi.IDS:
            # each intervention varied alone; the others stay at base for its rank
            others = {o: base[o]["npv_sar"] for o in wi.IDS if o != iid}
            rank_alone = 1 + sum(v > pts[iid]["npv_sar"] for v in others.values())
            rows.append({"id": iid, "intervention": NAMES[iid], "parameter": param, "level": level,
                         "value_source": src, "npv_sar": pts[iid]["npv_sar"], "base_npv_sar": base[iid]["npv_sar"],
                         "delta_npv_sar": pts[iid]["npv_sar"] - base[iid]["npv_sar"],
                         "avoided_known_t": pts[iid]["avoided_known_t"], "base_avoided_known_t": base[iid]["avoided_known_t"],
                         "cost_per_t_known_sar": pts[iid]["cost_per_t_known_sar"],
                         "positive_npv": pts[iid]["npv_sar"] > 0,
                         "rank_if_varied_alone": rank_alone,
                         "top_if_all_varied_together": ranking[0]})
    return rows


# --------------------------------------------------------------------------- 7. switching values
def switching(ctx):
    bi = base_inputs(ctx)
    rows = []
    base_npv = {i: evaluate_point(i, bi[i])["npv_sar"] for i in wi.IDS}
    for iid in wi.IDS:
        b = bi[iid]
        af = fe.annuity_factor(b["rate"], b["delay"], b["life"], b["horizon"])
        req_sav = b["opex"] + b["capex"] / af
        be_capex = (b["savings"] - b["opex"]) * af
        max_opex = b["savings"] - b["capex"] / af
        r_irr = fe.irr({**b, "avoided_t": 0})
        max_delay = None
        for d in range(0, int(min(b["life"], b["horizon"])) + 1):
            if fe.npv_closed_form({**b, "delay": d}) >= 0:
                max_delay = d
        for name, val, base_val, unit, note in (
            ("Gross annual savings at NPV = 0", req_sav, b["savings"], "SAR/year", "other inputs at base"),
            ("Savings ratio at NPV = 0 (also effectiveness multiplier, as savings scale with effectiveness)",
             req_sav / b["savings"], 1.0, "ratio", "savings may fall by (1 - ratio) before NPV <= 0"),
            ("CAPEX at NPV = 0", be_capex, b["capex"], "SAR", "other inputs at base"),
            ("Annual OPEX at NPV = 0", max_opex, b["opex"], "SAR/year", "other inputs at base"),
            ("Discount rate at NPV = 0 (IRR)", r_irr, b["rate"], "real rate", "NPV > 0 for any lower rate"),
            ("Longest whole-year lead time with NPV >= 0", max_delay, b["delay"], "years", "benefits end at technical life"),
        ):
            rows.append({"type": "NPV break-even", "id": iid, "versus": "", "metric": name, "switching_value": val,
                         "base_value": base_val, "unit": unit,
                         "margin_vs_base": (None if val is None else (val - base_val) / base_val if base_val else None),
                         "note": note})
    for i in wi.IDS:
        for j in wi.IDS:
            if i == j:
                continue
            b = bi[i]
            af = fe.annuity_factor(b["rate"], b["delay"], b["life"], b["horizon"])
            rows.append({"type": "Ranking tie", "id": i, "versus": j,
                         "metric": f"{NAMES[i]} gross savings at which NPV equals {NAMES[j]} base NPV",
                         "switching_value": b["opex"] + (base_npv[j] + b["capex"]) / af, "base_value": b["savings"],
                         "unit": "SAR/year", "margin_vs_base": None,
                         "note": "one-way; all other inputs at base"})
            rows.append({"type": "Ranking tie", "id": i, "versus": j,
                         "metric": f"{NAMES[i]} CAPEX at which NPV equals {NAMES[j]} base NPV",
                         "switching_value": b["capex"] + base_npv[i] - base_npv[j], "base_value": b["capex"],
                         "unit": "SAR", "margin_vs_base": None, "note": "one-way; all other inputs at base"})
    for r in rows:
        if r["type"] == "Ranking tie" and r["base_value"]:
            r["margin_vs_base"] = (r["switching_value"] - r["base_value"]) / r["base_value"]
    return rows


def reconcile_switching(rows, ctx):
    sw, rk = ctx["p10"]["switching_cached"], ctx["p10"]["ranking_cached"]
    get = {(r["id"], r["versus"], r["metric"]): r["switching_value"] for r in rows}
    pairs = []
    for iid in wi.IDS:
        pairs += [(get[(iid, "", "Gross annual savings at NPV = 0")], sw[iid]["required_savings"], sw[iid]["required_savings_ref"]),
                  (get[(iid, "", "Savings ratio at NPV = 0 (also effectiveness multiplier, as savings scale with effectiveness)")],
                   sw[iid]["required_savings_ratio"], sw[iid]["required_savings_ratio_ref"]),
                  (get[(iid, "", "CAPEX at NPV = 0")], sw[iid]["breakeven_capex"], sw[iid]["breakeven_capex_ref"])]
    pairs += [(get[("C", "B", f"{NAMES['C']} gross savings at which NPV equals {NAMES['B']} base NPV")],
               rk["elec_savings_tie_freight"], rk["elec_savings_tie_freight_ref"]),
              (get[("C", "B", f"{NAMES['C']} CAPEX at which NPV equals {NAMES['B']} base NPV")],
               rk["elec_capex_tie_freight"], rk["elec_capex_tie_freight_ref"]),
              (get[("B", "C", f"{NAMES['B']} gross savings at which NPV equals {NAMES['C']} base NPV")],
               rk["freight_savings_tie_elec"], rk["freight_savings_tie_elec_ref"])]
    return [{"engine": e, "workbook_cached": w, "workbook_ref": ref, "difference": e - w,
             "status": "MATCH" if abs(e - w) <= max(1e-6, 1e-9 * abs(w)) else "DIFFERENT"} for e, w, ref in pairs]


# --------------------------------------------------------------------------- 8. ranking reversals
def _top(npvs):
    best = max(npvs.values())
    tops = [i for i, v in npvs.items() if abs(v - best) < 1e-9]
    return tops[0] if len(tops) == 1 else "TIE(" + "+".join(tops) + ")"


def reversal_scans(ctx):
    """One-way scans: does the highest-NPV intervention change? Each intervention's parameter is varied
    alone (others at base). Exact switch points are also computed analytically where linear."""
    bi = base_inputs(ctx)
    base_npv = {i: evaluate_point(i, bi[i])["npv_sar"] for i in wi.IDS}
    base_top = _top(base_npv)
    rows = []
    specs = [("CAPEX multiplier", "capex_mult"), ("Gross savings multiplier", "sav_mult"),
             ("OPEX multiplier", "opex_mult"), ("Effectiveness multiplier (savings scale)", "eff_mult")]
    for iid in wi.IDS:
        others_best = max(v for o, v in base_npv.items() if o != iid)
        for label, kw in specs:
            tops = []
            for m in SWEEP_MULTIPLIERS:
                if kw == "eff_mult" and bi[iid]["reduction"] * m >= 1:
                    continue
                npvs = dict(base_npv)
                npvs[iid] = evaluate_point(iid, bi[iid], **{kw: m})["npv_sar"]
                tops.append((m, _top(npvs)))
            flipped = [m for m, t in tops if t != base_top]
            changed = sorted({t for m, t in tops if t != base_top})
            # NPV is linear in each of these multipliers -> exact switch point
            n1 = evaluate_point(iid, bi[iid], **{kw: 1.0})["npv_sar"]
            n2 = evaluate_point(iid, bi[iid], **{kw: 1.1})["npv_sar"]
            slope = (n2 - n1) / 0.1
            m_star = (1 + (others_best - n1) / slope) if slope else None
            inside = m_star is not None and SWEEP_MULTIPLIERS[0] <= m_star <= SWEEP_MULTIPLIERS[-1]
            rows.append({"varied_intervention": iid, "parameter": label,
                         "tested_range": f"{SWEEP_MULTIPLIERS[0]}x-{SWEEP_MULTIPLIERS[-1]}x (step 0.05)",
                         "base_top": base_top, "reversal_found": bool(changed),
                         "reversal_multipliers": (f"{min(flipped)}x-{max(flipped)}x" if flipped else ""),
                         "analytic_switch_multiplier": m_star,
                         "switch_inside_tested_range": inside,
                         "tops_seen": "; ".join(sorted({t for _, t in tops})),
                         "interpretation": (
                             f"Ranking changes within tested range: top becomes {', '.join(changed)} at "
                             f"{min(flipped)}x-{max(flipped)}x (exact switch at {m_star:.3f}x)" if changed else
                             "No ranking reversal within the tested range" +
                             (f" (exact switch at {m_star:.3f}x, outside the range)" if m_star and m_star > 0 else
                              " (no switch point at a positive multiplier)"))})
    # shared discount rate (applies to all interventions at once)
    tops = []
    for r in SWEEP_RATES:
        npvs = {i: evaluate_point(i, bi[i], rate=r)["npv_sar"] for i in wi.IDS}
        tops.append((r, _top(npvs), {i: npvs[i] > 0 for i in wi.IDS}))
    changed = sorted({t for _, t, _ in tops if t != base_top})
    rows.append({"varied_intervention": "ALL", "parameter": "Shared real discount rate",
                 "tested_range": f"{SWEEP_RATES[0]:.1%}-{SWEEP_RATES[-1]:.1%} (step 0.5 pp)", "base_top": base_top,
                 "reversal_found": bool(changed), "reversal_multipliers": "",
                 "tops_seen": "; ".join(sorted({t for _, t, _ in tops})),
                 "interpretation": ("Ranking changes within tested range" if changed else
                                    "No ranking reversal within the tested range (top unchanged at every rate)")})
    # shared lead time
    tops = []
    for d in range(0, 4):
        npvs = {i: evaluate_point(i, bi[i], delay=d)["npv_sar"] for i in wi.IDS}
        tops.append((d, _top(npvs)))
    changed = sorted({t for _, t in tops if t != base_top})
    rows.append({"varied_intervention": "ALL", "parameter": "Shared implementation lead time",
                 "tested_range": "0-3 years", "base_top": base_top, "reversal_found": bool(changed),
                 "reversal_multipliers": "", "tops_seen": "; ".join(sorted({t for _, t in tops})),
                 "interpretation": "Ranking changes within tested range" if changed else
                 "No ranking reversal within the tested range"})
    return rows


def sweep_electricity_savings(ctx, values=None):
    """Reproduces 'Ranking & Switching' rows 17-23 (electricity savings vs freight base NPV)."""
    bi = base_inputs(ctx)
    fb = evaluate_point("B", bi["B"])["npv_sar"]
    values = values or [r["elec_savings"] for r in ctx["p10"]["sweep_cached"]]
    out = []
    for s in values:
        e = evaluate_point("C", bi["C"], sav_mult=s / bi["C"]["savings"])["npv_sar"]
        out.append({"elec_savings_sar": s, "elec_npv_sar": e, "freight_base_npv_sar": fb,
                    "preferred_on_npv": "Electricity" if e > fb else "Freight" if e < fb else "Tie"})
    return out


# --------------------------------------------------------------------------- 9. missing Contractor B
def missing_supplier(ctx, applicabilities=(0.0, 0.25, 0.5, 0.75, 1.0)):
    g = ctx["p10"]["global"]
    bi = base_inputs(ctx)
    known_t = ctx["target_baseline"]["B"]
    eff = bi["B"]["reduction"]
    known_av = avoided_known("B", eff)
    rows = []
    for case in CASES:
        b_imp = g["b_base_t"] * multipliers(g, case)["b"]
        for app in sorted(set(applicabilities) | {g["b_applicability"]}):
            hyp = eff * app * b_imp
            rows.append({"b_case": case, "applicability_to_b": app,
                         "workbook_default_applicability": app == g["b_applicability"],
                         "hypothetical_b_emissions_t": b_imp, "known_freight_emissions_t": known_t,
                         "illustrative_freight_total_t": known_t + b_imp,
                         "hypothetical_b_share_of_illustrative_total": b_imp / (known_t + b_imp),
                         "reduction_rate": eff, "avoided_known_t": known_av, "avoided_hypothetical_b_t": hyp,
                         "avoided_total_t": known_av + hyp,
                         "financial_npv_effect_sar": 0.0,
                         "label": "SENSITIVITY ASSUMPTION - hypothetical Contractor B, not a measured inventory value",
                         "baseline_effect": "none - quantified baseline unchanged; Contractor B remains UNAVAILABLE"})
    return rows


def reconcile_missing(rows, ctx):
    cached = {c["case"]: c for c in ctx["p10"]["missing_cached"]}
    app = ctx["p10"]["global"]["b_applicability"]
    out = []
    for r in rows:
        if r["applicability_to_b"] != app:
            continue
        c = cached[r["b_case"]]
        for key, eng, wk in (("hypothetical_b_t", r["hypothetical_b_emissions_t"], "b_imputed_t"),
                             ("known_t", r["known_freight_emissions_t"], "known_t"),
                             ("illustrative_total_t", r["illustrative_freight_total_t"], "illustrative_total_t"),
                             ("avoided_total_t", r["avoided_total_t"], "avoided_t")):
            d = eng - c[wk]
            out.append({"case": r["b_case"], "metric": key, "engine": eng, "workbook_cached": c[wk], "workbook_ref": c["ref"],
                        "difference": d, "status": "MATCH" if abs(d) <= 1e-5 else "DIFFERENT"})
    return out


# --------------------------------------------------------------------------- 10. robustness and ranking
def confidence_labels():
    audit, _ = ce.run()
    conf = cf.assess(audit, ce.by_source(audit))
    lab = {s["stream"]: s["confidence_label"] for s in conf["streams"]}
    return {"A": lab["Diesel generators"],
            "B": f"{lab['Freight - Contractor A']} (A), {lab['Freight - Contractor C']} (C); "
                 f"Contractor B {lab['Freight - Contractor B']}",
            "C": lab["Grid electricity"]}


def ranking_analysis(case_rows, ctx, feas_summary, conf_labels):
    out = []
    for case in CASES:
        grp = {r["id"]: r for r in case_rows if r["case"] == case}
        any_pos = any(r["positive_npv"] for r in grp.values())
        top = min(grp.values(), key=lambda r: r["rank_by_npv"])["id"]
        most_t = max(grp.values(), key=lambda r: r["avoided_known_t"])["id"]
        cpts = {i: r["cost_per_t_known_sar"] for i, r in grp.items() if r["cost_per_t_known_sar"] is not None}
        low_cpt = min(cpts, key=cpts.get) if cpts else None
        for iid, r in grp.items():
            out.append({
                "case": case, "id": iid, "intervention": NAMES[iid], "npv_sar": r["npv_sar"],
                "rank_by_npv": r["rank_by_npv"], "positive_npv": r["positive_npv"],
                "highest_relative_npv": iid == top,
                "eligible_for_financial_recommendation": r["positive_npv"],
                "case_has_any_positive_npv": any_pos,
                "avoided_known_t": r["avoided_known_t"], "greatest_emissions_avoided": iid == most_t,
                "cost_per_t_known_sar": r["cost_per_t_known_sar"], "lowest_net_cost_per_t": iid == low_cpt,
                "operational_feasibility": feas_summary[iid]["status"],
                "data_confidence": conf_labels[iid],
                "note": ("All options have negative NPV in this case: highest relative NPV is NOT a recommendation"
                         if not any_pos and iid == top else ""),
            })
    return out


def robustness(case_rows, sw_rows, feas_summary, conf_labels):
    out = []
    for iid in wi.IDS:
        npv = {r["case"]: r["npv_sar"] for r in case_rows if r["id"] == iid}
        pos = [c for c in CASES if npv[c] > 0]
        ratio = next(r["switching_value"] for r in sw_rows if r["id"] == iid and r["metric"].startswith("Savings ratio"))
        if len(pos) == 3:
            cls = "Financially robust across low/base/high"
        elif npv["Base"] > 0:
            cls = "Conditional: positive NPV in base" + (" and high" if npv["High"] > 0 else "") + ", negative in low case"
        else:
            cls = "Not supported: non-positive NPV in base case"
        top_cases = [r["case"] for r in case_rows if r["id"] == iid and r["rank_by_npv"] == 1]
        out.append({"id": iid, "intervention": NAMES[iid], "npv_low_sar": npv["Low"], "npv_base_sar": npv["Base"],
                    "npv_high_sar": npv["High"], "positive_npv_cases": ", ".join(pos) or "none",
                    "highest_npv_in_cases": ", ".join(top_cases) or "none",
                    "savings_can_fall_before_npv_zero": 1 - ratio, "financial_robustness": cls,
                    "operational_feasibility": feas_summary[iid]["status"], "data_confidence": conf_labels[iid]})
    return out


def statements(case_rows, sw_rows, rev_rows, ctx):
    """Conditional decision statements generated from results (no unconditional recommendation)."""
    base = {r["id"]: r for r in case_rows if r["case"] == "Base"}
    low = {r["id"]: r for r in case_rows if r["case"] == "Low"}
    top = min(base.values(), key=lambda r: r["rank_by_npv"])["id"]
    second = sorted(base.values(), key=lambda r: r["rank_by_npv"])[1]["id"]
    tie = next(r for r in sw_rows if r["type"] == "Ranking tie" and r["id"] == top and r["versus"] == second
               and "gross savings" in r["metric"])
    req = next(r for r in sw_rows if r["id"] == top and r["metric"] == "Gross annual savings at NPV = 0")
    s = []
    s.append(f"{NAMES[top]} has the highest modelled financial NPV under the base assumptions "
             f"(SAR {base[top]['npv_sar']:,.0f}), but its attractiveness depends on achieving the assumed operating "
             f"savings: it would fall to the same NPV as {NAMES[second].lower()} if its annual gross savings were "
             f"SAR {tie['switching_value']:,.0f} instead of SAR {tie['base_value']:,.0f}, and to zero NPV at "
             f"SAR {req['switching_value']:,.0f}. Results are illustrative and require engineering and financial validation.")
    if not any(r["positive_npv"] for r in low.values()):
        lt = min(low.values(), key=lambda r: r["rank_by_npv"])["id"]
        s.append(f"In the low case all three interventions have negative financial NPV; {NAMES[lt].lower()} is only "
                 f"the least negative (SAR {low[lt]['npv_sar']:,.0f}) and is not recommended on financial grounds.")
    most = max(base.values(), key=lambda r: r["avoided_known_t"])["id"]
    s.append(f"{NAMES[most]} gives the largest modelled annual abatement ({base[most]['avoided_known_t']:,.1f} tCO2e/yr "
             f"on known data), which is a synthetic assumption, not a verified saving; its emission factor is a "
             f"provisional SEC 2024 Scope 2 proxy.")
    cheapest = min((r for r in base.values() if r["cost_per_t_known_sar"] is not None),
                   key=lambda r: r["cost_per_t_known_sar"])["id"]
    s.append(f"{NAMES[cheapest]} has the lowest net cost per tonne (SAR {base[cheapest]['cost_per_t_known_sar']:,.0f}/tCO2e, "
             f"a potential net saving) but the smallest absolute scale, and it covers known freight only (Contractor B missing).")
    rev = [r for r in rev_rows if r["reversal_found"]]
    if rev:
        s.append("One-way ranking reversals within the tested 0.5x-1.5x range occur only for: " + "; ".join(
            f"{NAMES[r['varied_intervention']].lower()} {r['parameter'].lower()} below {r['analytic_switch_multiplier']:.3f}x"
            for r in rev if r["varied_intervention"] in NAMES) + ". No reversal was found for CAPEX, OPEX, the shared "
            "discount rate (0-15%) or lead time (0-3 years) within the tested ranges.")
    s.append("No option has validated operational feasibility; all checks in the Phase 9 feasibility register are "
             "unvalidated or provisional, so no intervention is recommended for procurement.")
    return s


# --------------------------------------------------------------------------- run / write
def run():
    ctx = load()
    case_rows = cases(ctx)
    sw = switching(ctx)
    rev = reversal_scans(ctx)
    p9 = ctx["p9"]
    feas = fe.feasibility_summary(fe.feasibility(p9), p9)
    labels = confidence_labels()
    return {"ctx": ctx, "cases": case_rows, "cases_recon": reconcile_cases(case_rows, ctx),
            "one_way": one_way(ctx), "switching": sw, "switching_recon": reconcile_switching(sw, ctx),
            "reversals": rev, "sweep": sweep_electricity_savings(ctx),
            "sweep_curve": sweep_electricity_savings(ctx, [float(x) for x in range(40000, 200001, 5000)]),
            "missing": (m := missing_supplier(ctx)), "missing_recon": reconcile_missing(m, ctx),
            "ranking": ranking_analysis(case_rows, ctx, feas, labels),
            "robustness": robustness(case_rows, sw, feas, labels), "confidence_labels": labels,
            "statements": statements(case_rows, sw, rev, ctx)}


def main(out_dir=None):
    out = Path(out_dir) if out_dir else OUT
    r = run()
    se.write_csv(out / "uncertainty_cases.csv", r["cases"])
    se.write_csv(out / "sensitivity_results.csv", r["one_way"])
    se.write_csv(out / "switching_values.csv", r["switching"])
    se.write_csv(out / "ranking_analysis.csv", r["ranking"])
    se.write_csv(out / "ranking_reversal_tests.csv", r["reversals"])
    se.write_csv(out / "missing_supplier_sensitivity.csv", r["missing"])
    se.write_csv(out / "decision_robustness.csv", r["robustness"])
    se.write_csv(out / "uncertainty_reconciliation.csv",
                 [{"table": "Cases", **x} for x in r["cases_recon"]] +
                 [{"table": "Switching", "case": "", "id": "", "metric": x["workbook_ref"], **x} for x in r["switching_recon"]] +
                 [{"table": "Missing Supplier", "id": "B", **x} for x in r["missing_recon"]])
    (out / "decision_statements.txt").write_text("\n\n".join(r["statements"]) + "\n", encoding="utf-8")
    for c in r["cases"]:
        print(f"  {c['case']:<4} {c['id']} NPV {c['npv_sar']:>14,.2f}  rank {c['rank_by_npv']}  known {c['avoided_known_t']:8.3f} t"
              f"  +hypB {c['avoided_hypothetical_b_t']:7.3f} t")
    return r


if __name__ == "__main__":
    main()
