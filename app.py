"""Carbon Decision Assistant - emissions hotspots, data confidence (Workstream B, Phases 6-7) and
reduction scenarios, financial evaluation and decision analysis (Workstream C, Phases 8-10), and
supplier decision & engagement (Phase 11, tab 9: supplier_* engines + phase11_tab.py).

Run:  streamlit run app.py
All numbers are computed live: emissions from phase4/data/*.csv by calc_engine.py, and Workstream C
results by scenario_engine.py, financial_engine.py and uncertainty_engine.py from the workbooks in
workbooks/ (no hard-coded results). Tabs 1-5 are the unchanged Workstream B dashboard.
"""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import calc_engine as ce
import confidence as cf
import phase11_tab as p11
import workstream_c_tabs as wct

st.set_page_config(page_title="Carbon Hotspots & Data Confidence", layout="wide")

SCOPE_COLORS = {"1": "#2E6F9E", "2": "#E07B39", "3": "#4E9A6B"}
LABEL_COLORS = {"HIGH": "#D7EDDC", "MODERATE": "#FFF1C9", "LOW": "#F9D6D1", "NOT QUANTIFIED": "#E3E3E3"}
CRIT_COLORS = {"Met": "#D7EDDC", "Partial": "#FFF1C9", "Not met": "#F9D6D1"}


@st.cache_data
def load():
    audit, findings = ce.run()
    sources = ce.by_source(audit)
    return audit, findings, sources, ce.by_scope(sources), ce.monthly(audit), ce.hotspots(sources), cf.assess(audit, sources)


audit, findings, sources, scopes, monthly, (hotspots, quant_total), conf = load()
qt_value, qt_units = ce.quantified_total(sources)
qt_unit = qt_units[0] if len(qt_units) == 1 else "t (mixed gas labels)"
elec = next(s for s in sources if s["activity_type"] == "electricity_purchased")
elec_factor = ce.v.load_registers()[0][elec["factor_id"]]
blocks = [f for f in findings if f["severity"] == "BLOCK"]
factors, _, _ = ce.v.load_registers()

# ------------------------------------------------------------------ header
st.title("Carbon Decision Assistant: emissions hotspots & data confidence")
st.caption("Fictional manufacturing facility, Riyadh Region · reporting year 2025 · operational control · "
           "synthetic activity data · engine " + ce.ENGINE_VERSION + " · Workstream C " + wct.VERSION)
st.info("**Preliminary, demonstration-only results — not a verified 2025 corporate GHG inventory.** "
        f"Electricity uses the **{elec_factor['source_organization']}** factor ({elec_factor['factor_value']} "
        f"{elec_factor['factor_unit'].replace('CO2e', 'CO₂e')}, reference year {elec_factor['applicable_year']}), a "
        f"**provisional** location-based Scope 2 proxy (`{elec_factor['verification_status']}`); diesel and freight use "
        "**UK proxy** factors; Contractor B's activity data is missing, so the quantified total is incomplete.")
if blocks:
    st.error(f"{len(blocks)} BLOCK findings in clean data — results withheld."); st.stop()

sc = {s["scope"]: s for s in scopes}
rc = conf["record_completeness"]
k = st.columns(6)
k[0].metric("Scope 1 · diesel", f"{sc['1']['emissions_t']:,.1f} tCO₂e")
k[1].metric("Scope 2 · electricity", f"{sc['2']['emissions_t']:,.1f} tCO₂e",
            help=f"{elec['activity_total']:,.0f} MWh × {elec_factor['factor_value']} {elec_factor['factor_unit']} ÷ 1,000; "
                 "provisional SEC 2024 location-based proxy")
k[2].metric("Scope 3 Cat. 4 · known freight", f"{sc['3']['emissions_t']:,.1f} tCO₂e", help="Contractors A + C only; incomplete")
k[3].metric("Quantified total (indicative)", f"{qt_value:,.1f} {qt_unit.replace('CO2e', 'CO₂e')}",
            help="Sum of quantified sources; excludes Contractor B, so it is incomplete and not an inventory total")
k[4].metric("Record completeness", rc["label"])
k[5].metric("Missing Contractor B records", rc["missing"])

st.warning("**Contractor B — missing data.** No mass, distance or tonne-km received for any of 12 months. "
           "Its emissions are **unavailable (not zero)**, so Scope 3 Category 4 = **193.1 tCO₂e is a known-data "
           "subtotal, not a complete baseline**. Any future estimate must be labelled estimated/imputed (rule DQ-12).")

tabs = st.tabs(["Hotspots", "Monthly trends", "Data confidence", "Emission factors", "Audit trail",
                "Reduction scenarios", "Financial evaluation", "Decision intelligence",
                "Supplier Decision & Engagement"])

# ------------------------------------------------------------------ hotspots
with tabs[0]:
    c1, c2 = st.columns([3, 2])
    df = pd.DataFrame(sources)
    q = df[df["emissions_t"].notna()].sort_values("emissions_t")
    fig = go.Figure()
    for scope, g in q.groupby("scope"):
        fig.add_bar(y=g["stream"], x=g["emissions_t"], orientation="h", name=f"Scope {scope}",
                    marker_color=SCOPE_COLORS[scope],
                    text=[f"{e:,.1f} {u}" for e, u in zip(g["emissions_t"], g["emissions_unit"])],
                    textposition="auto", insidetextanchor="end", cliponaxis=False)
    fig.add_bar(y=["Freight - Contractor B"], x=[0], orientation="h", name="Unavailable", marker_color="#BBBBBB",
                text=["UNAVAILABLE — missing activity data"], textposition="outside", cliponaxis=False)
    fig.update_layout(title="Emissions by source (annual 2025)", barmode="stack", height=380,
                      xaxis_title="tCO₂e",
                      xaxis_range=[0, q["emissions_t"].max() * 1.35], margin=dict(l=10, r=140, t=50, b=40),
                      yaxis=dict(categoryorder="array", categoryarray=["Freight - Contractor B"] + list(q["stream"])))
    c1.plotly_chart(fig, width="stretch")

    hs = pd.DataFrame(hotspots)
    hs["rank"] = hs["rank"].astype(str)  # mixed int / "-" (unavailable) -> text for Arrow
    hs["emissions"] = [("UNAVAILABLE" if pd.isna(e) else f"{e:,.3f} {u}") for e, u in zip(hs["emissions_t"], hs["emissions_unit"])]
    hs["share of quantified (indicative)"] = ["—" if pd.isna(p) else f"{p:.1f}%" for p in hs["share_of_quantified_pct"]]
    c2.subheader("Hotspot ranking")
    c2.dataframe(hs[["rank", "stream", "scope", "emissions", "share of quantified (indicative)"]], hide_index=True,
                 width="stretch")
    c2.caption(f"Shares are of the quantified total ({quant_total:,.1f} {qt_unit.replace('CO2e', 'CO₂e')}), which "
               "excludes Contractor B. It is an indicative, incomplete total, not a corporate inventory.")

    st.subheader("Emissions by Scope (all tCO₂e)")
    sdf = pd.DataFrame(scopes)
    sdf["Scope"] = ["Scope " + s + (f" Cat. {c}" if c else "") for s, c in zip(sdf["scope"], sdf["scope3_category"])]
    sdf["Emissions"] = [f"{e:,.3f} {u}" for e, u in zip(sdf["emissions_t"], sdf["emissions_unit"])]
    sdf["Sources quantified"] = [f"{a}/{a + b}" for a, b in zip(sdf["sources_quantified"], sdf["sources_unavailable"])]
    st.dataframe(sdf[["Scope", "Emissions", "Sources quantified", "status"]], hide_index=True, width="stretch")
    st.markdown("**Reading:** grid electricity is the clear hotspot of the quantified emissions. Freight is small in "
                "the known data but carries the greatest completeness risk: one of three carriers is unquantified.")

# ------------------------------------------------------------------ monthly
with tabs[1]:
    m = pd.DataFrame(monthly)
    m["month"] = pd.to_datetime(m["period"] + "-01").dt.strftime("%b")
    c1, c2 = st.columns(2)
    e = m[m["stream"] == elec["stream"]]
    f1 = px.line(e, x="month", y="emissions_t", markers=True, title="Scope 2 electricity — tCO₂e (provisional SEC factor)",
                 color_discrete_sequence=[SCOPE_COLORS["2"]])
    f1.update_layout(yaxis_title="tCO₂e", xaxis_title="", height=360, yaxis_rangemode="tozero")
    c1.plotly_chart(f1, width="stretch")
    o = m[(m["stream"] != elec["stream"]) & m["emissions_t"].notna()]
    f2 = px.bar(o, x="month", y="emissions_t", color="stream", title="Diesel and known freight — tCO₂e",
                color_discrete_map={"Diesel generators": SCOPE_COLORS["1"], "Freight - Contractor A": "#4E9A6B",
                                    "Freight - Contractor C": "#9BCB9F"})
    f2.update_layout(yaxis_title="tCO₂e", xaxis_title="", height=360, legend_title="")
    c2.plotly_chart(f2, width="stretch")
    st.caption("Electricity is plotted separately because each month it is more than 15 times any other single stream. "
               "Contractor B has no monthly values (missing in all 12 months) and is not plotted as zero.")
    piv = m.pivot(index="stream", columns="period", values="emissions_t")
    st.dataframe(piv.map(lambda x: "missing" if pd.isna(x) else f"{x:,.2f}"), width="stretch")

# ------------------------------------------------------------------ confidence
with tabs[2]:
    ec = conf["emissions_coverage"]
    c = st.columns(4)
    c[0].metric("Record completeness", rc["label"], help="Monthly records with activity data / all records")
    c[1].metric("Sources quantified", f"{ec['sources_quantified']}/{ec['sources_total']}")
    c[2].metric("Freight carriers quantified", f"{ec['carriers_quantified']}/{ec['carriers_total']}")
    c[3].metric("Share of true total covered", "Unknown",
                help="Cannot be stated: Contractor B's emissions cannot be bounded without its activity data")
    st.markdown(f"**Record completeness ≠ emissions coverage.** {rc['pct']:.0f}% of *records* have data, but that does not mean "
                f"{rc['pct']:.0f}% of *emissions* are covered: the missing records all belong to one freight carrier, whose share "
                "of true emissions is unknown. Scope 1 and Scope 2 are fully quantified; Scope 3 Category 4 is partial.")
    cdf = pd.DataFrame(conf["streams"])
    crit_cols = [f"{c} {n}" for c, n in cf.CRITERIA.items()]
    show = cdf[["stream", "scope"] + crit_cols + ["confidence_label", "label_rule"]]
    st.dataframe(show.style.map(lambda x: f"background-color: {CRIT_COLORS.get(x, LABEL_COLORS.get(x, ''))}"),
                 hide_index=True, width="stretch")
    with st.expander("Criteria evidence per source"):
        ev = cdf[["stream"] + [f"{c} evidence" for c in cf.CRITERIA]]
        st.dataframe(ev, hide_index=True, width="stretch")
    with st.expander("How labels are assigned (no statistical confidence percentages)", expanded=True):
        st.markdown("""
| Criterion | Met | Partial | Not met |
|---|---|---|---|
| C1 Activity completeness | 12/12 months | some months | no data |
| C2 Factor age | factor year = 2025 | 1–2 years older | ≥ 3 years older |
| C3 Geography | Saudi-specific | documented foreign proxy | — |
| C4 Gas coverage | CO₂e (CO₂, CH₄, N₂O) | — | CO₂ only |
| C5 Verification | checked against published source | secondary copy | unverified (placeholder or provisional proxy) |
| C6 Boundary fit | matches Phase 3 expectation | accepted proxy boundary | — |

**NOT QUANTIFIED** = no activity data · **LOW** = ≥ 2 *Not met*, or 1 *Not met* + ≥ 2 *Partial* ·
**HIGH** = all *Met* · **MODERATE** = otherwise. Every label is capped as *demonstration only* because activity data is synthetic.
""")

# ------------------------------------------------------------------ factors
with tabs[3]:
    fdf = pd.DataFrame(factors.values())
    fdf["Factor"] = fdf["factor_value"] + " " + fdf["factor_unit"]
    cols = {"factor_id": "ID", "factor_name": "Factor name", "Factor": "Value", "gases_included": "Gases",
            "geography": "Geography", "applicable_year": "Data year", "publication_year": "Pub. year",
            "boundary_note": "Boundary", "source_organization": "Publisher", "source_location": "Exact location",
            "verification_status": "Verification", "uncertainty_note": "Limitation", "source_url": "Source URL"}
    st.dataframe(fdf[list(cols)].rename(columns=cols), hide_index=True, width="stretch",
                 column_config={"Source URL": st.column_config.LinkColumn("Source URL")})
    for f in factors.values():
        st.markdown(f"- **{f['factor_id']}** — {f['verification_note']}")

# ------------------------------------------------------------------ audit
with tabs[4]:
    adf = pd.DataFrame(audit)
    sel = st.multiselect("Filter sources", sorted(adf["stream"].unique()), default=sorted(adf["stream"].unique()))
    view = adf[adf["stream"].isin(sel)]
    st.dataframe(view[["activity_id", "period", "stream", "quantity_calc", "unit_calc", "factor_id", "formula",
                       "emissions_t", "emissions_unit", "calc_status", "evidence_id", "quality_flags"]],
                 hide_index=True, width="stretch", height=420)
    st.download_button("Download full audit trail (CSV)", adf.to_csv(index=False).encode("utf-8"),
                       "calculation_audit_trail.csv", "text/csv")
    st.caption("Each record keeps its activity ID, factor ID, units, factor source and evidence reference. "
               "Validator flags: DQ-01 = missing quantity (Contractor B), DQ-13 = documented factor warnings "
               "(UK proxies, electricity reference year 2024 and provisional status).")

# ------------------------------------------------------------------ Workstream C (Phases 8-10)
with tabs[5]:
    wct.scenarios_tab()
with tabs[6]:
    wct.financial_tab()
with tabs[7]:
    wct.decision_tab()

# ------------------------------------------------------------------ Phase 11
with tabs[8]:
    p11.render()
