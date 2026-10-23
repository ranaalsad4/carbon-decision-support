"""Streamlit tabs 6-8 (Workstream C). Every number comes from the engines:
scenario_engine (Phase 8), financial_engine (Phase 9), uncertainty_engine (Phase 10).
Interactive changes are session-only: the workbooks in workbooks/ are never modified."""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import financial_engine as fe
import scenario_engine as se
import uncertainty_engine as ue
import workstream_c_inputs as wi

VERSION = "WSC-1.0"
COLORS = {"A": "#2E6F9E", "B": "#4E9A6B", "C": "#E07B39", "ABC": "#6B5B95"}
NAMES = ue.NAMES
CASE_COLORS = {"Low": "#C8553D", "Base": "#5A6C7D", "High": "#3E8E7E"}


def _sar(x, d=0):
    return "—" if x is None else f"SAR {x:,.{d}f}"


def _yrs(x):
    return "not reached" if x is None else f"{x:.2f} y"


# ------------------------------------------------------------------ cached engine calls
@st.cache_data(show_spinner=False)
def workbook_defaults():
    p8, p9, _ = wi.load_all()
    return ({i: p8[i]["reduction"] for i in wi.IDS},
            {i: {k: p9["interventions"][i][k] for k in fe.PARAMS} for i in wi.IDS},
            {"horizon": p9["global"]["horizon"], "rate": p9["global"]["rate"]})


@st.cache_data(show_spinner=False)
def scenarios(rates_tuple):
    r = se.run_all(rates=dict(rates_tuple))
    mon = {sid: se.monthly(res) for sid, res in r["results"].items()}
    streams = {sid: res["streams"] for sid, res in r["results"].items()}
    assum = se.assumptions_table(r["p8"], r["rates"], r["target_baseline"])
    return r["comparison"], streams, mon, assum, r["quantified_total"]


@st.cache_data(show_spinner=False)
def financials(params_tuple, combined_avoided):
    params = {i: dict(p) for i, p in params_tuple}
    res = {i: fe.evaluate(params[i]) for i in wi.IDS}
    return res, fe.portfolio(params, combined_avoided)


@st.cache_data(show_spinner=False)
def feasibility():
    p9 = wi.load_phase9()
    rows = fe.feasibility(p9)
    return rows, fe.feasibility_summary(rows, p9)


@st.cache_data(show_spinner=False)
def uncertainty():
    r = ue.run()
    r.pop("ctx")
    return r


def _rates():
    d, _, _ = workbook_defaults()
    return {i: st.session_state.get(f"sc_rate_{i}", round(100 * d[i])) / 100 for i in wi.IDS}


# ------------------------------------------------------------------ Tab 6
def scenarios_tab():
    defaults, _, _ = workbook_defaults()
    st.markdown("**Phase 8 reduction scenarios.** Each scenario scales the relevant Phase 4 activity records and "
                "recalculates them with the unchanged Workstream B engine (same factor IDs, units and missing-data "
                "rules). Reduction rates are **synthetic assumptions** from the Phase 8 register, not verified savings.")
    c = st.columns(3)
    for col, iid in zip(c, wi.IDS):
        col.slider(f"{iid} · {NAMES[iid]} — activity reduction (%)", 0, 50, round(100 * defaults[iid]), 1,
                   key=f"sc_rate_{iid}", help=f"Workbook default {defaults[iid]:.0%} (Phase 8 Scenario Register)")
    rates = _rates()
    if any(abs(rates[i] - defaults[i]) > 1e-12 for i in wi.IDS):
        st.caption("Rates changed from the workbook defaults for this session only; the Phase 8 workbook is unchanged.")
    comp, streams, mon, assum, qt = scenarios(tuple(sorted(rates.items())))
    cmp = {c_["scenario_id"]: c_ for c_ in comp}
    k = st.columns(4)
    k[0].metric("Quantified baseline", f"{qt:,.1f} tCO₂e", help="Known data only; Contractor B unavailable")
    k[1].metric("Combined scenario (A+B+C)", f"{cmp['ABC']['quantified_scenario_t']:,.1f} tCO₂e")
    k[2].metric("Annual CO₂e avoided (combined)", f"{cmp['ABC']['avoided_t']:,.1f} tCO₂e",
                help="Modelled, not verified. Interventions act on different records, so no double counting.")
    k[3].metric("Reduction vs quantified baseline", f"{cmp['ABC']['reduction_pct_of_quantified']:.1f}%")
    st.warning("**Contractor B — missing data.** Its 12 freight records have no activity data, so they are neither "
               "reduced nor counted as zero. All totals here are the *quantified* known-data total, not complete "
               "corporate emissions.")

    df = pd.DataFrame(comp)
    show = pd.DataFrame({
        "Scenario": df["scenario_id"] + " · " + df["scenario"],
        "Affected baseline (tCO₂e)": df["affected_baseline_t"].map("{:,.3f}".format),
        "Avoided (tCO₂e/yr)": df["avoided_t"].map("{:,.3f}".format),
        "% of affected stream": df["reduction_pct_of_affected"].map("{:.1f}%".format),
        "% of quantified baseline": df["reduction_pct_of_quantified"].map("{:.2f}%".format),
        "Scenario quantified total (tCO₂e)": df["quantified_scenario_t"].map("{:,.3f}".format),
    })
    fig = go.Figure()
    fig.add_bar(x=df["scenario_id"], y=df["quantified_baseline_t"] - df["avoided_t"], name="Remaining quantified",
                marker_color="#9AA9B5")
    fig.add_bar(x=df["scenario_id"], y=df["avoided_t"], name="Avoided (modelled)", marker_color="#3E8E7E",
                text=[f"{v:,.1f}" for v in df["avoided_t"]], textposition="outside")
    fig.update_layout(barmode="stack", title="Quantified emissions by scenario (tCO₂e/yr)", height=380,
                      yaxis_title="tCO₂e", legend=dict(orientation="h", y=-0.15), margin=dict(t=50, b=10))
    st.plotly_chart(fig, width="stretch")
    st.subheader("Scenario comparison")
    st.dataframe(show, hide_index=True, width="stretch")
    st.caption("Scenarios A, B and C are evaluated separately; ABC applies all three together. Combined rates "
               "multiply per record (1 − r₁)(1 − r₂) so overlapping interventions could never be double counted.")

    st.subheader("Scope-level impact")
    sel = st.selectbox("Scenario", [c_["scenario_id"] for c_ in comp], index=len(comp) - 1, key="sc_select",
                       format_func=lambda s: f"{s} · {cmp[s]['scenario']}")
    sdf = pd.DataFrame(streams[sel])
    sdf["Baseline"] = sdf["baseline_t"].map(lambda v: "UNAVAILABLE" if pd.isna(v) else f"{v:,.3f}")
    sdf["Scenario"] = sdf["scenario_t"].map(lambda v: "UNAVAILABLE" if pd.isna(v) else f"{v:,.3f}")
    sdf["Avoided"] = sdf["avoided_t"].map(lambda v: "—" if pd.isna(v) else f"{v:,.3f}")
    sdf["Change"] = sdf["reduction_pct_of_stream"].map(lambda v: "—" if pd.isna(v) else f"−{v:.1f}%")
    st.dataframe(sdf[["scope", "stream", "Baseline", "Scenario", "Avoided", "Change", "status"]]
                 .rename(columns={"scope": "Scope", "stream": "Source", "status": "Status"}),
                 hide_index=True, width="stretch")
    m = pd.DataFrame(mon[sel])
    m = m[m["avoided_t"].notna()]
    m = m.groupby("period", as_index=False)[["baseline_t", "scenario_t", "avoided_t"]].sum()
    m["month"] = pd.to_datetime(m["period"] + "-01").dt.strftime("%b")
    f2 = go.Figure()
    f2.add_scatter(x=m["month"], y=m["baseline_t"], name="Baseline (quantified)", line=dict(color="#5A6C7D"))
    f2.add_scatter(x=m["month"], y=m["scenario_t"], name=f"Scenario {sel}", line=dict(color="#3E8E7E", dash="dash"))
    f2.update_layout(title=f"Monthly quantified emissions — scenario {sel} (tCO₂e)", height=330, yaxis_title="tCO₂e",
                     yaxis_rangemode="tozero", legend=dict(orientation="h", y=-0.2), margin=dict(t=50, b=10))
    st.plotly_chart(f2, width="stretch")
    st.caption(f"Monthly avoided emissions sum to the annual figure ({m['avoided_t'].sum():,.3f} tCO₂e for {sel}).")

    with st.expander("Intervention assumptions (Phase 8 register)", expanded=False):
        a = pd.DataFrame(assum)
        st.dataframe(a[["id", "intervention", "target_activity_type", "target_suppliers", "reduction_rate",
                        "reduction_rate_source", "mechanism", "evidence_status", "dependencies", "limitations"]],
                     hide_index=True, width="stretch")


# ------------------------------------------------------------------ Tab 7
def financial_tab():
    _, fdef, gdef = workbook_defaults()
    st.markdown("**Phase 9 financial evaluation** (company cash-flow perspective, constant real SAR, end-of-year "
                "cash flows). Inputs default to the Phase 9 workbook; edits here are **session-only**. All costs "
                "and savings are illustrative, not vendor quotations. Annual avoided emissions follow the reduction "
                "rates set in *Reduction scenarios*.")
    g1, g2 = st.columns(2)
    rate = g1.slider("Real discount rate (%)", 0.0, 15.0, 100 * gdef["rate"], 0.5, key="fin_rate") / 100
    horizon = g2.slider("Analysis horizon (years)", 1, 20, int(gdef["horizon"]), 1, key="fin_horizon")
    cols = st.columns(3)
    params = {}
    for col, iid in zip(cols, wi.IDS):
        d = fdef[iid]
        with col:
            st.markdown(f"**{iid} · {NAMES[iid]}**")
            params[iid] = {
                "capex": st.number_input("CAPEX at year 0 (SAR)", 0.0, 1e8, d["capex"], 5000.0, key=f"fin_capex_{iid}"),
                "savings": st.number_input("Gross annual savings (SAR/yr)", 0.0, 1e8, d["savings"], 1000.0, key=f"fin_sav_{iid}"),
                "opex": st.number_input("Incremental OPEX (SAR/yr)", 0.0, 1e8, d["opex"], 1000.0, key=f"fin_opex_{iid}"),
                "delay": float(st.number_input("Lead time (years)", 0, 10, int(d["delay"]), 1, key=f"fin_delay_{iid}")),
                "life": d["life"], "horizon": float(horizon), "rate": rate}
    comp, _, _, _, _ = scenarios(tuple(sorted(_rates().items())))
    cmp = {c_["scenario_id"]: c_ for c_ in comp}
    for iid in wi.IDS:
        params[iid]["avoided_t"] = cmp[iid]["avoided_t"]
    res, port = financials(tuple((i, tuple(sorted(params[i].items()))) for i in wi.IDS), cmp["ABC"]["avoided_t"])
    is_default = all(abs(params[i][k] - fdef[i][k]) < 1e-9 for i in wi.IDS for k in ("capex", "savings", "opex", "delay")) \
        and abs(rate - gdef["rate"]) < 1e-12 and horizon == gdef["horizon"] \
        and all(abs(_rates()[i] - workbook_defaults()[0][i]) < 1e-12 for i in wi.IDS)
    if is_default:
        st.success("Inputs equal the Phase 9 workbook: NPVs reconcile with 'Decision Summary'!B9:D9.")
    else:
        st.info("Inputs differ from the Phase 9 workbook (session-only what-if). The workbook is unchanged.")

    rows = []
    for iid in wi.IDS:
        r = res[iid]
        rows.append({"Intervention": f"{iid} · {NAMES[iid]}", "CAPEX": _sar(r["capex_sar"]),
                     "OPEX / yr": _sar(r["opex_sar"]), "Gross savings / yr": _sar(r["gross_savings_sar"]),
                     "Net savings / yr": _sar(r["net_savings_sar"]), "Financial NPV": _sar(r["npv_sar"]),
                     "Simple payback": _yrs(r["simple_payback_y"]), "Discounted payback": _yrs(r["discounted_payback_y"]),
                     "IRR": "—" if r["irr"] is None else f"{r['irr']:.1%}",
                     "Avoided (tCO₂e/yr)": f"{r['annual_avoided_t']:,.3f}",
                     "Net cost per tonne": "—" if r["cost_per_t_sar"] is None else f"SAR {r['cost_per_t_sar']:,.0f}/tCO₂e",
                     "Classification": r["classification"]})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Net cost per tonne = net present cost (−NPV, discounted SAR) ÷ lifetime tonnes avoided "
               "(undiscounted physical tonnes), as in the Phase 9 workbook. A negative value means a potential net "
               "financial saving per tonne, not a verified saving. Payback ignores discounting; "
               "'not reached' = not recovered within the benefit period.")
    k = st.columns(3)
    k[0].metric("Portfolio CAPEX (A+B+C)", _sar(port["capex_sar"]))
    k[1].metric("Portfolio NPV (additive)", _sar(port["npv_sar"]),
                help="Sum of the three cash flows; assumes no cost or saving interactions (not in the workbook)")
    k[2].metric("Portfolio avoided", f"{port['annual_avoided_t']:,.1f} tCO₂e/yr")

    c1, c2 = st.columns(2)
    f1 = go.Figure()
    for iid in wi.IDS:
        cf = pd.DataFrame(res[iid]["cash_flows"])
        f1.add_scatter(x=cf["year"], y=cf["cumulative_pv_sar"], name=f"{iid} · {NAMES[iid]}", mode="lines+markers",
                       line=dict(color=COLORS[iid]))
    f1.add_hline(y=0, line_color="#888", line_width=1)
    f1.update_layout(title="Cumulative discounted cash flow (SAR)", xaxis_title="Year", yaxis_title="SAR",
                     height=380, legend=dict(orientation="h", y=-0.2), margin=dict(t=50, b=10))
    c1.plotly_chart(f1, width="stretch")
    f2 = go.Figure()
    for iid in wi.IDS:
        cf = pd.DataFrame(res[iid]["cash_flows"])
        f2.add_bar(x=cf["year"], y=cf["net_cash_flow_sar"], name=f"{iid}", marker_color=COLORS[iid])
    f2.update_layout(title=f"Annual net cash flow, years 0–{horizon} (SAR)", barmode="group", xaxis_title="Year",
                     yaxis_title="SAR", height=380, legend=dict(orientation="h", y=-0.2), margin=dict(t=50, b=10))
    c2.plotly_chart(f2, width="stretch")

    st.subheader("Operational feasibility (Phase 9 checklist)")
    frows, fsum = feasibility()
    k = st.columns(3)
    for col, iid in zip(k, wi.IDS):
        s = fsum[iid]
        col.metric(f"{iid} · checks validated", f"{s['validated']}/{s['checks']}",
                   help=f"Screening: {s['screening']}. Main dependency: {s['main_dependency']}")
    st.dataframe(pd.DataFrame(frows)[["id", "check", "evidence_needed", "current_status", "decision_implication"]],
                 hide_index=True, width="stretch")
    st.caption("No feasibility check has been validated; operational feasibility is not demonstrated by these "
               "synthetic scenarios.")


# ------------------------------------------------------------------ Tab 8
def decision_tab():
    u = uncertainty()
    st.markdown("**Phase 10 uncertainty-aware decision analysis** using the corrected Phase 10 workbook. "
                "Low/base/high are joint stress cases, not statistical confidence intervals. This tab uses the "
                "workbook inputs (what-if edits in tabs 6–7 are not applied here).")
    st.subheader("Conditional findings")
    for s in u["statements"]:
        st.markdown(f"- {s}")

    cases = pd.DataFrame(u["cases"])
    c1, c2 = st.columns([3, 2])
    f = go.Figure()
    for case in ue.CASES:
        g = cases[cases["case"] == case]
        f.add_bar(x=g["id"] + " · " + g["intervention"], y=g["npv_sar"], name=case, marker_color=CASE_COLORS[case])
    f.add_hline(y=0, line_color="#444", line_width=1)
    f.update_layout(title="Financial NPV by case (SAR)", barmode="group", height=380, yaxis_title="SAR",
                    legend=dict(orientation="h", y=-0.2), margin=dict(t=50, b=10))
    c1.plotly_chart(f, width="stretch")
    t = cases[["case", "id", "npv_sar", "rank_by_npv", "avoided_known_t", "avoided_hypothetical_b_t",
               "cost_per_t_known_sar"]].copy()
    t["npv_sar"] = t["npv_sar"].map("{:,.0f}".format)
    t["avoided_known_t"] = t["avoided_known_t"].map("{:,.2f}".format)
    t["avoided_hypothetical_b_t"] = t["avoided_hypothetical_b_t"].map(lambda v: "—" if v == 0 else f"{v:,.2f} (hyp.)")
    t["cost_per_t_known_sar"] = t["cost_per_t_known_sar"].map("{:,.0f}".format)
    c2.dataframe(t.rename(columns={"case": "Case", "id": "ID", "npv_sar": "NPV (SAR)", "rank_by_npv": "Rank",
                                   "avoided_known_t": "Avoided, known (t/yr)",
                                   "avoided_hypothetical_b_t": "+ hyp. Contractor B (t/yr)",
                                   "cost_per_t_known_sar": "SAR/tCO₂e (known)"}),
                 hide_index=True, width="stretch", height=360)
    c2.caption("Rank 1 = highest NPV within the case, even when all NPVs are negative (low case).")

    st.subheader("One-way sensitivity (tornado)")
    ow = pd.DataFrame(u["one_way"])
    iid = st.selectbox("Intervention", list(wi.IDS), index=2, key="dec_tornado",
                       format_func=lambda i: f"{i} · {NAMES[i]}")
    d = ow[ow["id"] == iid].copy()
    d["label"] = d["parameter"] + " — " + d["level"]
    d = d.reindex(d["delta_npv_sar"].abs().sort_values().index)
    ft = go.Figure(go.Bar(x=d["delta_npv_sar"], y=d["label"], orientation="h",
                          marker_color=["#C8553D" if v < 0 else "#3E8E7E" for v in d["delta_npv_sar"]],
                          text=[f"{v:,.0f}" for v in d["delta_npv_sar"]], textposition="outside"))
    ft.update_layout(title=f"Change in NPV vs base (SAR) — {NAMES[iid]}", height=460, xaxis_title="SAR",
                     margin=dict(l=10, r=40, t=50, b=10))
    st.plotly_chart(ft, width="stretch")

    st.subheader("Financial switching values")
    sw = pd.DataFrame(u["switching"])
    c1, c2 = st.columns([2, 3])
    be = sw[sw["type"] == "NPV break-even"].copy()
    be["value"] = [("—" if v is None or pd.isna(v) else f"{v:.1%}" if "rate" in un or "ratio" in un else
                    f"{v:,.0f} year(s)" if un == "years" else f"{v:,.0f} {un}")
                   for v, un in zip(be["switching_value"], be["unit"])]
    c1.dataframe(be[["id", "metric", "value"]].rename(columns={"id": "ID", "metric": "NPV = 0 when…", "value": "Value"}),
                 hide_index=True, width="stretch", height=420)
    tie = sw[(sw["type"] == "Ranking tie") & (sw["id"] == "C") & (sw["versus"] == "B")
             & sw["metric"].str.contains("gross savings")]["switching_value"].iloc[0]
    xs = [r["elec_savings_sar"] for r in u["sweep_curve"]]
    ys = [r["elec_npv_sar"] for r in u["sweep_curve"]]
    fb = cases[(cases["case"] == "Base") & (cases["id"] == "B")]["npv_sar"].iloc[0]
    fs = go.Figure()
    fs.add_scatter(x=xs, y=ys, name="Electricity NPV", line=dict(color=COLORS["C"]))
    fs.add_hline(y=fb, line_dash="dash", line_color=COLORS["B"], annotation_text="Freight base NPV")
    fs.add_vline(x=tie, line_dash="dot", line_color="#444", annotation_text=f"tie ≈ SAR {tie:,.0f}")
    fs.update_layout(title="Electricity annual gross savings vs NPV (one-way)", xaxis_title="SAR/yr",
                     yaxis_title="NPV (SAR)", height=420, margin=dict(t=50, b=10), showlegend=False)
    c2.plotly_chart(fs, width="stretch")

    st.subheader("Ranking reversal tests")
    rv = pd.DataFrame(u["reversals"])
    st.dataframe(rv[["varied_intervention", "parameter", "tested_range", "reversal_found", "interpretation"]]
                 .rename(columns={"varied_intervention": "Varied", "parameter": "Parameter", "tested_range": "Range",
                                  "reversal_found": "Reversal?", "interpretation": "Result"}),
                 hide_index=True, width="stretch", height=36 * (len(rv) + 1) + 4)

    st.subheader("Contractor B missing-data sensitivity")
    st.warning("Values below are **sensitivity assumptions**, not measured inventory values. The quantified baseline "
               "is unchanged and Contractor B remains UNAVAILABLE. No financial savings are assigned to Contractor B.")
    ms = pd.DataFrame(u["missing"])
    c1, c2 = st.columns(2)
    case = c1.radio("Hypothetical Contractor B emissions case", list(ue.CASES), index=1, horizontal=True,
                    key="dec_b_case")
    app = c2.select_slider("Share of Contractor B eligible for the freight intervention",
                           options=sorted(ms["applicability_to_b"].unique()), value=1.0, key="dec_b_app")
    row = ms[(ms["b_case"] == case) & (ms["applicability_to_b"] == app)].iloc[0]
    k = st.columns(4)
    k[0].metric("Known freight (A+C)", f"{row['known_freight_emissions_t']:,.1f} tCO₂e")
    k[1].metric("Hypothetical Contractor B", f"{row['hypothetical_b_emissions_t']:,.0f} tCO₂e (assumed)")
    k[2].metric("Avoided — known", f"{row['avoided_known_t']:,.2f} tCO₂e/yr")
    k[3].metric("Avoided — hypothetical B", f"{row['avoided_hypothetical_b_t']:,.2f} tCO₂e/yr")
    st.caption("Avoided = reduction rate × (known eligible freight + applicability × hypothetical Contractor B). "
               "Applicability applies to the hypothetical Contractor B term only.")

    st.subheader("Carbon impact, financial attractiveness, feasibility and uncertainty")
    rb = pd.DataFrame(u["robustness"])
    base = cases[cases["case"] == "Base"].set_index("id")
    mc = pd.DataFrame({
        "Intervention": rb["id"] + " · " + rb["intervention"],
        "Avoided, base (tCO₂e/yr, known)": [f"{base.loc[i, 'avoided_known_t']:,.1f}" for i in rb["id"]],
        "NPV base (SAR)": rb["npv_base_sar"].map("{:,.0f}".format),
        "NPV range low → high (SAR)": [f"{a:,.0f} → {b:,.0f}" for a, b in zip(rb["npv_low_sar"], rb["npv_high_sar"])],
        "SAR/tCO₂e (base)": [f"{base.loc[i, 'cost_per_t_known_sar']:,.0f}" for i in rb["id"]],
        "Savings may fall by": rb["savings_can_fall_before_npv_zero"].map("{:.0%}".format),
        "Financial robustness": rb["financial_robustness"],
        "Feasibility": ["Not demonstrated" if s.startswith("Not demonstrated") else s
                        for s in rb["operational_feasibility"]],
        "Data confidence": rb["data_confidence"],
    })
    st.dataframe(mc, hide_index=True, width="stretch")
    st.error("**Data-confidence warnings.** Electricity uses a provisional SEC 2024 Scope 2 proxy (550 kgCO₂e/MWh, "
             "not independently verified); diesel and freight use UK proxy factors (freight unverified); Contractor B "
             "is unquantified; all activity, cost and savings data are synthetic. No result here is an investment "
             "recommendation.")
