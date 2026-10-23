"""Streamlit tab 9 - Supplier Decision & Engagement (Phase 11).

UI only: every number comes from the supplier_* engines. Edits made here (offers, weights, thresholds,
settings, action status) are SESSION-ONLY copies; the register workbook and the Workstream B inventory are
never modified. All supplier, cost and reliability values are synthetic demonstration data.
"""
import copy
import io
import json
import zipfile
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import supplier_audit as sa
import supplier_carbon_engine as sce
import supplier_engagement_engine as see
import supplier_recommendation_engine as sre
import supplier_scoring_engine as ssc
import supplier_screening_engine as sse
import supplier_uncertainty_engine as sue
import workstream_c_inputs as wi
from supplier_data_loader import CRITERIA, MATURITY_INDICATORS, OFFER_EDIT_FIELDS, apply_offer_edits, load_register, \
    offers_table
from supplier_financial_engine import appraise
from supplier_models import ENGINE_VERSION, WeightError

OBJECTIVE = ("Evaluate freight suppliers using comparable carbon, financial, operational and data-quality evidence; "
             "identify supplier engagement priorities; and support transparent decisions to retain, improve, consider "
             "switching or request additional information.")
ACTION_COLORS = {sre.RETAIN: "#3E8E7E", sre.IMPROVE: "#C98A1B", sre.SWITCH: "#2E6F9E", sre.DATA: "#6B5B95",
                 sre.INELIGIBLE: "#C8553D", sre.NONE: "#5A6C7D"}
QUAD_COLORS = {"Q1": "#F6D5CF", "Q2": "#FBE3C4", "Q3": "#FFF3C9", "Q4": "#D7EDDC"}
ELIG_COLORS = {"Eligible": "#D7EDDC", "Conditionally eligible": "#FFF1C9", "Insufficient evidence": "#E3E3E3",
               "Ineligible": "#F9D6D1"}
STATUS_COLORS = {"Pass": "#D7EDDC", "Fail": "#F9D6D1", "Missing": "#E3E3E3", "N/A": "#F3F5F8"}
DQ_COLORS = {"High": "#D7EDDC", "Medium": "#FFF1C9", "Low": "#F9D6D1", "Missing": "#E3E3E3"}
ACTION_STATUSES = ["Not started", "In progress", "Completed", "Blocked", "Cancelled"]
SYNTH = ("Synthetic demonstration data: supplier names, costs, reliability, emission factors and evidence statuses are "
         "illustrative project assumptions, not real supplier records, quotations or verified certificates.")


# ------------------------------------------------------------------ helpers
def _sar(x, d=0):
    return "—" if x is None else f"SAR {x:,.{d}f}"


def _t(x, d=1):
    return "—" if x is None else f"{x:,.{d}f} t"


def _pct(x, d=1):
    return "—" if x is None else f"{x:.{d}%}"


def _num(x, d=1):
    return "—" if x is None else f"{x:,.{d}f}"


@st.cache_data(show_spinner=False)
def _load(raw: bytes = None):
    return load_register(data=raw) if raw else load_register()


@st.cache_data(show_spinner=False)
def _b_hypothetical():
    """Hypothetical Contractor B emissions used ONLY as a labelled sensitivity (Phase 10 workbook, global input)."""
    return float(wi.load_phase10()["global"]["b_base_t"])


def _apply_editor_delta(rows, delta):
    """Rebuild the edited offers table from st.data_editor's session delta (so edits apply to every section)."""
    rows = [dict(r) for r in rows]
    if not delta:
        return rows, False
    for i, ch in (delta.get("edited_rows") or {}).items():
        i = int(i)
        if 0 <= i < len(rows):
            rows[i].update(ch)
    deleted = {int(i) for i in (delta.get("deleted_rows") or [])}
    rows = [r for i, r in enumerate(rows) if i not in deleted]
    rows += [dict(r) for r in (delta.get("added_rows") or [])]
    changed = bool(delta.get("edited_rows") or delta.get("added_rows") or delta.get("deleted_rows"))
    return rows, changed


def _init_state(base):
    defaults = {"p11_imp_thr": float(base.matrix.impact_threshold), "p11_mat_thr": float(base.matrix.maturity_threshold),
                "p11_b_sens": False}
    for c in CRITERIA:
        defaults[f"p11_w_{c}"] = round(base.scoring.weights[c] * 100, 2)
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


def _weights_from_state():
    raw = {c: st.session_state.get(f"p11_w_{c}") for c in CRITERIA}
    try:
        return ssc.validate_weights(raw), None
    except WeightError as e:
        return None, str(e)


def _safe(rows):
    """DataFrame with mixed-type columns rendered as text (avoids Arrow conversion warnings)."""
    df = pd.DataFrame(rows)
    for c in df.columns:
        if df[c].dtype == object and len({type(v) for v in df[c] if v is not None}) > 1:
            df[c] = df[c].map(lambda v: "" if v is None else str(v))
    return df


# ------------------------------------------------------------------ main entry
def render():
    st.markdown(
        f"<div style='border-left:6px solid #1F3A5F;background:#F3F5F8;padding:14px 18px;border-radius:4px;"
        f"margin-bottom:8px'><div style='font-size:0.8rem;letter-spacing:.06em;color:#1F3A5F;font-weight:700'>"
        f"OBJECTIVE</div><div style='font-size:1.08rem;color:#1b1b1b;margin-top:4px'>{OBJECTIVE}</div></div>",
        unsafe_allow_html=True)
    st.warning(SYNTH + " The engagement matrix sets engagement priorities only; it never triggers supplier "
               "replacement. The model never awards contracts: any switch needs human procurement approval.")

    # ---------------- decision settings (session only)
    with st.expander("Data source (optional upload; session only — the bundled register is never modified)"):
        up = st.file_uploader("Optional: upload an edited Phase11_Supplier_Decision_Assumptions_Register.xlsx",
                              type=["xlsx"], key="p11_upload")
        raw = up.getvalue() if up is not None else None
    try:
        base = _load(raw)
    except Exception as e:  # noqa: BLE001 - show a readable message for a malformed upload
        st.error(f"Register could not be loaded: {e}. Using the bundled register instead.")
        base = _load(None)
    _init_state(base)
    s = base.settings
    with st.expander("Financial and decision settings (editable management assumptions)"):
        c = st.columns(4)
        rate = c[0].number_input("Real discount rate (%)", value=s.discount_rate * 100, step=0.5, key="p11_rate") / 100
        horizon = int(c[1].number_input("Horizon (years)", min_value=1, max_value=30, value=int(s.horizon_years),
                                        key="p11_horizon"))
        delay = int(c[2].number_input("Implementation delay (years)", min_value=0, max_value=5,
                                      value=int(s.implementation_delay_years), key="p11_delay"))
        share = c[3].slider("Substitution share of lane tonne-km", 0.05, 1.0, float(s.substitution_share), 0.05,
                            key="p11_share", help="Partial substitution: the share of the current lane's tonne-km "
                                                  "moved to the alternative (functional unit = tonne-km of the service).")
        c = st.columns(4)
        set_wtp = c[0].checkbox("Management has set a willingness to pay", value=s.willingness_to_pay is not None,
                                key="p11_wtp_set")
        wtp = c[1].number_input("Willingness to pay (SAR/tCO₂e, discounted lifetime basis)", min_value=0.0,
                                value=float(s.willingness_to_pay or 0.0), step=50.0, key="p11_wtp",
                                disabled=not set_wtp)
        wtp = wtp if set_wtp else None
        ver_mand = c[2].checkbox("Third-party verification mandatory", value=s.verification_mandatory, key="p11_vmand")
        start = c[3].date_input("Action-plan start date", value=sa.PLAN_START, key="p11_start")
        st.caption("These are editable management assumptions. No willingness to pay is set in the register, so a "
                   "lower-carbon option with a net cost gives 'NO DEFENSIBLE RECOMMENDATION YET' until management sets one.")

    # ---------------- edited offers (data_editor lives in section 4; its delta is applied here first)
    base_rows = offers_table(base)
    rows, edited = _apply_editor_delta(base_rows, st.session_state.get("p11_offer_editor"))
    data = apply_offer_edits(base, rows) if edited else copy.deepcopy(base)
    data.settings.discount_rate, data.settings.horizon_years = rate, horizon
    data.settings.implementation_delay_years, data.settings.substitution_share = delay, share
    data.settings.willingness_to_pay, data.settings.verification_mandatory = wtp, ver_mand
    data.matrix.impact_threshold = float(st.session_state["p11_imp_thr"])
    data.matrix.maturity_threshold = float(st.session_state["p11_mat_thr"])
    weights, werr = _weights_from_state()
    hyp = None
    if st.session_state["p11_b_sens"]:
        b = next((x for x in data.suppliers.values() if x.is_existing and x.inventory_supplier_id
                  and x.supplier_id.endswith("B")), None)
        if b is not None:
            hyp = {b.inventory_supplier_id: _b_hypothetical()}
    res = sa.analyse(data, weights=weights, wtp="settings", hypothetical=hyp, start=start)
    if edited:
        st.info("Session edits to supplier offers are active (section 4). Results below use the edited copy; "
                "the register and the historical inventory are unchanged.")

    t = st.tabs(["1 · Overview", "2 · Screening & data quality", "3 · Engagement matrix", "4 · Alternatives",
                 "5 · Carbon & financial trade-off", "6 · Recommendations", "7 · Action plans",
                 "8 · Monitoring & audit"])
    with t[0]:
        _overview(res)
    with t[1]:
        _screening(res)
    with t[2]:
        _matrix(res, hyp)
    with t[3]:
        _alternatives(res, base_rows, weights, werr)
    with t[4]:
        _tradeoff(res, weights)
    with t[5]:
        _recommendations(res)
    with t[6]:
        plan = _actions(res)
    with t[7]:
        _monitoring(res, plan)


# ------------------------------------------------------------------ 1 overview
def _overview(res):
    data, inv = res["data"], res["inventory"]
    st.subheader("Supplier overview")
    st.markdown("Historical freight emissions come **read-only** from the Workstream B inventory (Scope 3 Category 4, "
                "downstream road freight). Phase 11 never rewrites them.")
    known = sum(v["emissions_t"] for v in inv.values() if v["emissions_t"] is not None)
    k = st.columns(5)
    k[0].metric("Known freight (Scope 3 Cat. 4)", _t(known, 3), help="Contractors with activity data only; incomplete")
    for col, sid in zip(k[1:4], sorted(inv)):
        v = inv[sid]
        col.metric(f"{sid} (inventory)", _t(v["emissions_t"], 3) if v["emissions_t"] is not None else "UNAVAILABLE",
                   help=f"{v['records_with_data']}/{v['records']} months with data · factor {v['factor_id']}")
    exist = [x for x in data.suppliers.values() if x.is_existing]
    k[4].metric("Suppliers in scope", f"{len(exist)} current · {len(data.suppliers) - len(exist)} alternative")

    rows = []
    for sid, sp in data.suppliers.items():
        i = inv.get(sp.inventory_supplier_id or "", {})
        offs = data.supplier_offers(sid)
        dec = [o.emissions_t for o in offs if (o.role or "").lower() == "incumbent"]
        rows.append({"Supplier": sid, "Name": sp.name, "Relationship": sp.relationship, "Mode": sp.mode,
                     "Fuel / technology": sp.fuel_technology, "Materiality": sp.materiality,
                     "Lanes": ", ".join(sorted({o.lane_id for o in offs})),
                     "Inventory tCO₂e (historical)": ("UNAVAILABLE" if sp.inventory_supplier_id and i.get("emissions_t") is None
                                                       else _num(i.get("emissions_t"), 3) if i else "n/a (prospective)"),
                     "Decision-basis tCO₂e/yr": ("UNAVAILABLE" if dec and any(x is None for x in dec)
                                                 else _num(sum(dec), 3) if dec else "n/a (offer only)"),
                     "Data class": sp.data_class})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    c1, c2 = st.columns([3, 2])
    names = [x for x in sorted(inv)]
    vals = [inv[x]["emissions_t"] or 0 for x in names]
    f = go.Figure(go.Bar(x=names, y=vals, marker_color=["#2E6F9E" if inv[x]["emissions_t"] is not None else "#BBBBBB"
                                                         for x in names],
                         text=[_num(inv[x]["emissions_t"], 1) if inv[x]["emissions_t"] is not None else "UNAVAILABLE"
                               for x in names], textposition="outside"))
    f.update_layout(title="Historical freight emissions by contractor (inventory, tCO₂e)", yaxis_title="tCO₂e",
                    xaxis_title="Inventory supplier", height=340, margin=dict(t=50, b=10))
    c1.plotly_chart(f, width="stretch")
    c2.markdown("**Two bases, kept apart**")
    c2.markdown("- **Inventory basis**: Phase 4 proxy factor for every contractor — the reported baseline.\n"
                "- **Decision basis**: each lane's own factor (supplier-specific where documented) — used only to compare "
                "suppliers. A difference between the two is a **methodology difference, not a reduction**.\n"
                "- Contractor B has no activity data: its emissions are **UNAVAILABLE, not zero**, and are never imputed "
                "into any total.")
    if data.issues:
        with st.expander(f"Input validation messages ({len(data.issues)})"):
            st.dataframe(pd.DataFrame([{"level": i.level, "where": i.where, "message": i.message} for i in data.issues]),
                         hide_index=True, width="stretch")


# ------------------------------------------------------------------ 2 screening
def _screening(res):
    data, scr = res["data"], res["screening"]
    st.subheader("Screening & data quality")
    st.markdown("Fourteen screening checks per offer. Checks 3–10 are **derived automatically** from the offer data; the "
                "others come from documented evidence in the register. **Eligibility overrides any weighted score.**")
    counts = pd.Series([r.eligibility for r in scr.values()]).value_counts()
    k = st.columns(4)
    for col, lab in zip(k, ["Eligible", "Conditionally eligible", "Insufficient evidence", "Ineligible"]):
        col.metric(lab, int(counts.get(lab, 0)))
    tab = []
    for r in scr.values():
        row = {"Offer": r.offer_id, "Supplier": r.supplier_id, "Lane": r.lane_id, "Eligibility": r.eligibility}
        for c in r.checks:
            row[f"{c.check_no}"] = c.status
        tab.append(row)
    df = pd.DataFrame(tab)
    chk_cols = [str(i) for i in range(1, 15)]
    st.dataframe(df.style.map(lambda v: f"background-color: {STATUS_COLORS.get(v, '')}", subset=chk_cols)
                 .map(lambda v: f"background-color: {ELIG_COLORS.get(v, '')}", subset=["Eligibility"]),
                 hide_index=True, width="stretch")
    with st.expander("What the 14 checks are"):
        st.dataframe(pd.DataFrame([{"No.": i, "Check": n, "Category": cat} for i, n, cat in sse.CHECKS]),
                     hide_index=True, width="stretch")
    oid = st.selectbox("Explain the screening of offer", list(scr), key="p11_scr_sel")
    r = scr[oid]
    c1, c2 = st.columns(2)
    c1.markdown(f"**{oid}: {r.eligibility}**")
    for lab, items in (("Blocking reasons", r.blocking_reasons), ("Missing material information", r.missing_material),
                       ("Conditions / limitations", r.conditions)):
        if items:
            c1.markdown(f"*{lab}*\n" + "\n".join(f"- {x}" for x in items))
    c1.caption("Carbon comparable: " + ("yes" if r.carbon_comparable else "no — boundary or factor not comparable"))
    c2.dataframe(pd.DataFrame([{"No.": c.check_no, "Check": c.check, "Status": c.status,
                                "Source": "auto" if c.derived else "evidence", "Reason": c.reason} for c in r.checks]),
                 hide_index=True, width="stretch", height=300)

    st.markdown("#### Data quality (7 dimensions)")
    dq = []
    for sid in data.suppliers:
        q = sse.data_quality(data, sid)
        dq.append({"Supplier": sid, **{sse.DQ_LABELS[k]: (v or "Missing") for k, v in q.dimensions.items()},
                   "Score (0–100)": _num(q.score, 0) if q.score is not None else "not scored",
                   "Usable estimate": "yes" if q.usable_estimate else "no", "Note": q.note})
    dqdf = pd.DataFrame(dq)
    st.dataframe(dqdf.style.map(lambda v: f"background-color: {DQ_COLORS.get(v, '')}",
                                subset=list(sse.DQ_LABELS.values())), hide_index=True, width="stretch")
    st.caption("Scoring: High 100, Medium 60, Low 20, Missing 0 (project-designed). An unverified but documented "
               "estimate stays usable with its uncertainty; missing data is never treated as zero.")


# ------------------------------------------------------------------ 3 matrix
def _matrix(res, hyp):
    data, eng = res["data"], res["engagement"]
    st.subheader("Supplier engagement priority matrix")
    st.markdown("**Impact** (absolute: share of known freight emissions, share of tonne-km, service materiality) against "
                "**maturity** (capability to measure, disclose, manage and improve). The segmentation follows the UN "
                "Global Compact impact × maturity idea; the **scores, weights and thresholds are project-designed and "
                "editable — not official UN rules**.")
    c = st.columns([1, 1, 1.4])
    c[0].slider("Impact threshold (high ≥)", 0.0, 100.0, step=1.0, key="p11_imp_thr")
    c[1].slider("Maturity threshold (high ≥)", 0.0, 100.0, step=1.0, key="p11_mat_thr")
    c[2].checkbox("Contractor B sensitivity (labelled, hypothetical)", key="p11_b_sens",
                  help=f"Uses a hypothetical {_b_hypothetical():,.0f} tCO₂e/yr for Contractor B from the Phase 10 workbook "
                       "global inputs. It is NOT inventory data and never enters any total.")
    ti, tm = data.matrix.impact_threshold, data.matrix.maturity_threshold
    f = go.Figure()
    for q, (x0, x1, y0, y1) in {"Q1": (0, tm, ti, 100), "Q2": (tm, 100, ti, 100), "Q3": (0, tm, 0, ti),
                                "Q4": (tm, 100, 0, ti)}.items():
        f.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1, fillcolor=QUAD_COLORS[q], line_width=0, layer="below")
        qd = data.matrix.quadrants.get(q, {})
        f.add_annotation(x=x0 + 1.5, y=y1 - 1.5, text=f"<b>{q} · Priority {qd.get('priority')}</b><br>{qd.get('label')}",
                         showarrow=False, font=dict(size=11, color="#333"), xanchor="left", yanchor="top", align="left")
    pts = [(sid, e) for sid, e in eng.items() if e.quadrant != see.UNCLASSIFIED]
    for sid, e in pts:
        sens = e.impact.basis.startswith("SENSITIVITY")
        f.add_trace(go.Scatter(
            x=[e.maturity.score], y=[e.impact.score], mode="markers+text", name=sid,
            text=[f"{data.suppliers[sid].name}{' (SENSITIVITY)' if sens else ''}"], textposition="bottom center", textfont=dict(size=12, color="#1b1b1b"),
            customdata=[sid],
            marker=dict(size=18, color="white" if sens else "#1F3A5F", line=dict(color="#1F3A5F", width=2),
                        symbol="diamond" if sens else "circle"),
            hovertemplate=f"{sid}<br>impact %{{y:.1f}}<br>maturity %{{x:.1f}}<br>{e.quadrant} · {e.label}<extra></extra>"))
    f.add_hline(y=ti, line_dash="dash", line_color="#555")
    f.add_vline(x=tm, line_dash="dash", line_color="#555")
    f.update_layout(title="Engagement priority matrix (click a supplier for details)", height=520, showlegend=False,
                    xaxis=dict(title="Maturity score (0–100)", range=[0, 100]),
                    yaxis=dict(title="Impact score (0–100)", range=[0, 100]), margin=dict(t=50, b=10))
    c1, c2 = st.columns([3, 2])
    with c1:
        ev = st.plotly_chart(f, width="stretch", on_select="rerun", selection_mode="points", key="p11_matrix_chart")
    try:
        p = ev.selection.points if ev else []
        if p and p[0].get("customdata"):
            cd = p[0]["customdata"]
            st.session_state["p11_mx_sel"] = cd[0] if isinstance(cd, (list, tuple)) else cd
    except AttributeError:
        pass
    un = [sid for sid, e in eng.items() if e.quadrant == see.UNCLASSIFIED]
    with c2:
        if un:
            st.markdown(f"**{see.UNCLASSIFIED_LABEL}**")
            for sid in un:
                e = eng[sid]
                st.markdown(f"- **{sid}** ({data.suppliers[sid].name}): " + "; ".join(e.limitations))
            st.caption("Not plotted: a position would require inventing data. Priority: data engagement. The B "
                       "sensitivity changes only the impact score (labelled SENSITIVITY); a quadrant also needs a "
                       f"maturity assessment with at least {data.matrix.min_maturity_indicators} indicators.")
        tab = pd.DataFrame([{"Supplier": sid, "Impact": _num(e.impact.score), "Maturity": _num(e.maturity.score),
                             "Quadrant": e.quadrant, "Priority": str(e.priority), "Engagement": e.label}
                            for sid, e in eng.items()])
        st.dataframe(tab, hide_index=True, width="stretch")
        st.caption("High engagement priority ≠ replacement. Replacement is assessed only in sections 4–6.")
    sel = st.selectbox("Supplier details", list(eng), key="p11_mx_sel")
    e = eng[sel]
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"**Impact: {_num(e.impact.score)}** ({e.impact.status}; basis: {e.impact.basis})")
    comp = e.impact.components
    c1.markdown("\n".join([f"- Emissions: {_num(comp.get('emissions_t'), 3)} tCO₂e",
                           f"- Share of known freight emissions: {_pct(comp.get('emissions_share'))}",
                           f"- Share of known tonne-km: {_pct(comp.get('volume_share'))}",
                           f"- Materiality score: {_num(comp.get('materiality_score'), 0)}"]))
    c1.caption(f"Weights: emissions {data.matrix.w_emissions_share:.0%}, volume {data.matrix.w_volume_share:.0%}, "
               f"materiality {data.matrix.w_materiality:.0%} (project-designed)")
    c2.markdown(f"**Maturity: {_num(e.maturity.score)}** ({e.maturity.status}; {e.maturity.assessed} of "
                f"{len(MATURITY_INDICATORS)} indicators)")
    c2.markdown("\n".join(f"- {k.replace('_', ' ')}: {'not assessed' if v is None else f'{v:g} / 4'}"
                          for k, v in e.maturity.indicators.items()))
    c3.markdown(f"**{e.quadrant} — Priority {e.priority}: {e.label}**")
    c3.markdown("\n".join(f"- {a}" for a in e.actions))
    if e.limitations:
        c3.caption("Limitations: " + "; ".join(e.limitations))


# ------------------------------------------------------------------ 4 alternatives + scoring
def _alternatives(res, base_rows, weights, werr):
    data, scr = res["data"], res["screening"]
    st.subheader("Alternatives comparison")
    st.markdown("Functional unit: **tonne-km of the same lane service** (same origin, destination, cargo and period). "
                "Offers on different lanes are not substitutes. Emissions = tonne-km × factor ÷ 1,000.")
    lanes = sorted(data.lanes)
    lid = st.selectbox("Service lane", lanes, key="p11_alt_lane",
                       format_func=lambda x: f"{x} · {data.lanes[x].name}")
    lane = data.lanes[lid]
    st.caption(f"Requirement: {lane.origin} → {lane.destination}, {lane.cargo_type}, capacity ≥ "
               f"{_num(lane.required_capacity_t, 0)} t/yr, on-time ≥ {_num(lane.required_on_time_pct, 0)}%, "
               f"period {lane.period}. Incumbent offer: {lane.incumbent_offer_id}.")
    rows = []
    for o in data.lane_offers(lid):
        sp = data.suppliers.get(o.supplier_id)
        dq = sse.data_quality(data, o.supplier_id)
        rows.append({"Offer": o.offer_id, "Supplier": sp.name if sp else o.supplier_id, "Role": o.role,
                     "Tonne-km": _num(o.tonne_km, 0), "EF (kgCO₂e/t-km)": (f"{o.ef.value_kg_per_tkm:g}" if o.ef and
                                                                         o.ef.value_kg_per_tkm is not None else "missing"),
                     "Evidence": o.ef.verification if o.ef else "missing", "Boundary": o.ef.boundary if o.ef else None,
                     "Emissions (t/yr)": _num(o.emissions_t, 2) if o.emissions_t is not None else "UNAVAILABLE",
                     "Annual cost": _sar(o.annual_cost), "One-time switch": _sar(o.switching_cost),
                     "On-time %": _num(o.on_time_pct, 0), "Capacity (t/yr)": _num(o.capacity_t, 0),
                     "Eligibility": scr[o.offer_id].eligibility,
                     "Data confidence": _num(dq.score, 0) if dq.score is not None else "not scored"})
    st.dataframe(pd.DataFrame(rows).style.map(lambda v: f"background-color: {ELIG_COLORS.get(v, '')}",
                                              subset=["Eligibility"]), hide_index=True, width="stretch")
    offs = [o for o in data.lane_offers(lid) if o.ef and o.ef.value_kg_per_tkm is not None]
    if offs:
        f = go.Figure(go.Bar(x=[o.offer_id for o in offs], y=[o.ef.value_kg_per_tkm for o in offs],
                             marker_color=["#1F3A5F" if o.offer_id == lane.incumbent_offer_id else "#7FA7C9" for o in offs],
                             text=[f"{o.ef.value_kg_per_tkm:g}" for o in offs], textposition="outside"))
        f.update_layout(title=f"Carbon intensity by offer — lane {lid} (kgCO₂e per tonne-km; dark = incumbent)",
                        xaxis_title="Offer", yaxis_title="kgCO₂e / tonne-km", height=320, margin=dict(t=50, b=10))
        st.plotly_chart(f, width="stretch")
    inc = lane.incumbent_offer_id
    if inc in data.offers:
        for o in data.lane_offers(lid):
            if o.offer_id == inc:
                continue
            eq = sse.equivalence(data, inc, o.offer_id, data.settings.substitution_share)
            if not eq.equivalent:
                st.warning(f"**{o.offer_id}** — incompatibility shown as a limitation: " + "; ".join(eq.limitations))
            if scr[o.offer_id].eligibility == "Ineligible":
                st.error(f"**{o.offer_id}** is INELIGIBLE (" + "; ".join(scr[o.offer_id].blocking_reasons)
                         + "). It is excluded whatever its score.")

    with st.expander("Edit or add supplier offers (session only)"):
        st.caption("Add a row to test a user-entered alternative (it becomes a hypothetical 'User-added' supplier whose "
                   "undocumented checks are Missing, never silently passed). Invalid, negative or non-numeric entries are "
                   "rejected and reported. The register and the historical inventory are not changed.")
        df = pd.DataFrame(base_rows, columns=OFFER_EDIT_FIELDS)
        st.data_editor(df, num_rows="dynamic", hide_index=True, width="stretch", key="p11_offer_editor",
                       column_config={"safety_legal_status": st.column_config.SelectboxColumn(
                           options=["Pass", "Fail", "Missing"]),
                           "ef_verification": st.column_config.SelectboxColumn(
                               options=["Verified - third party", "Unverified - documented", "Unverified - claimed",
                                        "Proxy - inventory factor", "Missing"])})
        if st.button("Reset edits", key="p11_reset_edits"):
            st.session_state.pop("p11_offer_editor", None)
            st.rerun()

    st.markdown("#### Weighted scoring (supporting evidence only)")
    st.caption("Default weights are **illustrative project assumptions** (carbon 35, cost 25, reliability 20, data "
               "quality 15, improvement 5), not UN percentages. Weights are validated and normalised to 100%.")
    cols = st.columns(5)
    for col, cr in zip(cols, CRITERIA):
        col.number_input(f"{ssc.LABELS[cr]} (%)", step=5.0, key=f"p11_w_{cr}")
    if werr:
        st.error(f"Invalid weights — {werr}. Scores below use the register defaults until corrected.")
        weights = None
    else:
        st.caption("Normalised: " + ", ".join(f"{ssc.LABELS[c]} {weights[c]:.1%}" for c in CRITERIA))
    sc = ssc.score_lane(data, lid, scr, weights)
    st.markdown(f"Ranking status for {lid}: **{sc.ranking_status}**" + (" — " + "; ".join(sc.reasons) if sc.reasons else ""))
    tab = []
    for r in sc.rows:
        tab.append({"Offer": r.offer_id, "Eligibility": r.eligibility,
                    **{ssc.LABELS[c]: _num(r.scores.get(c), 1) if r.scores.get(c) is not None else "missing" for c in CRITERIA},
                    "Total": _num(r.total, 2) if r.total is not None else "no total", "Rank": str(r.rank) if r.rank else "—",
                    "Status": r.status})
    st.dataframe(pd.DataFrame(tab), hide_index=True, width="stretch")
    scored = [r for r in sc.rows if r.total is not None]
    if scored:
        f = go.Figure()
        for cr in CRITERIA:
            f.add_bar(name=ssc.LABELS[cr], x=[r.offer_id + ("" if r.rank else " (not ranked)") for r in scored],
                      y=[r.contributions[cr] for r in scored])
        f.update_layout(barmode="stack", title=f"Weighted score contributions — lane {lid}", xaxis_title="Offer",
                        yaxis_title="Weighted points (0–100)", height=360, legend=dict(orientation="h", y=-0.25),
                        margin=dict(t=50, b=10))
        st.plotly_chart(f, width="stretch")
    if sc.ranking_status == "DEFINITIVE":
        ws, sw = ssc.weight_sensitivity(data, lid, scr, weights)
        rv = [x for x in ws if x["reversal"]]
        st.markdown("**Ranking sensitivity (±10 pp per weight):** " +
                    ("no reversal" if not rv else "; ".join(f"{ssc.LABELS[x['criterion']]} {x['change_pp']:+d} pp → "
                                                            f"{x['top_offer']} first" for x in rv)) +
                    (f". Carbon-weight switch point: at {sw['carbon_weight']:.0%} the top offer changes from "
                     f"{sw['top_below']} to {sw['top_from']}." if sw else ". No carbon-weight switch point in 0–100%."))
    with st.expander("Scoring method"):
        cfg = data.scoring
        st.markdown(f"- Carbon = 100 × ({cfg.carbon_high} − EF) / ({cfg.carbon_high} − {cfg.carbon_low}), clamped 0–100\n"
                    f"- Cost = 50 + 50 × (incumbent − offer annualised cost) / ({cfg.cost_band:.0%} × incumbent)\n"
                    f"- Reliability = 100 × (on-time − {cfg.reliability_low:g}) / ({cfg.reliability_high:g} − "
                    f"{cfg.reliability_low:g})\n- Data quality = mean of 7 dimensions; improvement = (targets + "
                    "responsiveness) / 8 × 100\n- A missing mandatory input gives **no total** (never zero) and suppresses "
                    "the definitive ranking.")


# ------------------------------------------------------------------ 5 trade-off
def _tradeoff(res, weights):
    data, scr = res["data"], res["screening"]
    st.subheader("Carbon & financial trade-off")
    pairs = []
    for lid, lane in sorted(data.lanes.items()):
        inc = lane.incumbent_offer_id
        for o in data.lane_offers(lid):
            if inc in data.offers and o.offer_id != inc:
                pairs.append((lid, inc, o.offer_id))
    if not pairs:
        st.info("No lane has both an incumbent and an alternative offer.")
        return
    labels = [f"{l}: {c} → {a}" for l, c, a in pairs]
    k = st.selectbox("Comparison", range(len(pairs)), format_func=lambda i: labels[i], key="p11_pair")
    lid, cur, alt = pairs[k]
    c = sce.compare(data, cur, alt)
    if not c.comparable:
        st.error("Not comparable: " + "; ".join(c.limitations))
        return
    a = appraise(data, cur, alt, c.avoided_t)
    if scr[alt].eligibility == "Ineligible":
        st.error(f"{alt} is INELIGIBLE — figures shown for transparency only; it cannot be recommended.")
    st.markdown("**Formulas** — emissions = tonne-km × EF ÷ 1,000; avoided = current − alternative; annual cost "
                "difference = alternative + recurring − current; NPV = −one-time + (current − alternative − recurring) × "
                "annuity factor; annual cost per tonne = annual cost difference ÷ avoided; discounted lifetime cost per "
                "tonne = net present cost ÷ (avoided × annuity factor).")
    m = st.columns(4)
    m[0].metric("Avoided emissions (projected)", _t(c.avoided_t, 2), help="Projected, not verified")
    m[1].metric("Reduction on substituted service", _pct(c.reduction_pct, 2))
    m[2].metric("Annual cost difference", _sar(a.annual_cost_difference), help="+ = the alternative costs more per year")
    m[3].metric("One-time switching costs", _sar(a.one_time_cost))
    m = st.columns(4)
    m[0].metric(f"Switching NPV ({a.horizon_years} y, {a.discount_rate:.1%})", _sar(a.npv, 2))
    m[1].metric("Annual cost per tCO₂e", _sar(a.annual_cost_per_t), help="Excludes one-time costs")
    m[2].metric("Discounted lifetime cost per tCO₂e", _sar(a.lifetime_discounted_cost_per_t, 2))
    m[3].metric("Break-even alternative cost", _sar(a.breakeven_alternative_cost), help="Annual cost at which NPV = 0")
    if a.npv is not None and a.npv < 0 and c.avoided_t > 0:
        st.info("A negative switching NPV is **not an automatic rejection**: it is the price of the carbon reduction. "
                "Compare the discounted lifetime cost per tonne with a management willingness to pay.")
    if a.note:
        st.caption(a.note)

    st.markdown("#### Uncertainty (low / base / high stress values — not probabilities)")
    base, ow = sue.one_way(data, cur, alt)
    if ow:
        d = pd.DataFrame([r for r in ow if r.get("comparable")])
        if not d.empty:
            d["label"] = d["variable"] + " — " + d["level"] + " (" + d["value"].map(lambda v: f"{v:,.0f}" if abs(v) >= 1000 else f"{v:g}") + ")"
            d = d.reindex(d["delta_npv"].abs().sort_values().index)
            ft = go.Figure(go.Bar(x=d["delta_npv"], y=d["label"], orientation="h",
                                  marker_color=["#C8553D" if v < 0 else "#3E8E7E" for v in d["delta_npv"]],
                                  text=[f"{v:,.0f}" for v in d["delta_npv"]], textposition="outside"))
            ft.update_layout(title="One-way sensitivity: change in switching NPV vs base (SAR)", xaxis_title="SAR",
                             yaxis_title="Variable — level", height=420, margin=dict(l=10, r=40, t=50, b=10))
            st.plotly_chart(ft, width="stretch")
            st.caption("Emission-factor variables change avoided tonnes and the cost per tonne, not the NPV (a zero bar). "
                       "Their effect is shown in the joint cases and the grid below.")
    else:
        st.caption("No uncertainty ranges are registered for this pair.")
    jc = sue.joint_cases(data, cur, alt)
    st.dataframe(pd.DataFrame([{"Case": n, "Avoided (t/yr)": _num(v.get("avoided_t"), 2), "NPV": _sar(v.get("npv")),
                                "Lifetime cost/tCO₂e": _sar(v.get("lifetime_cost_per_t")),
                                "Values": "; ".join(f"{x}={y:g}" for x, y in v["values"].items()) or "base"}
                               for n, v in jc.items() if v.get("comparable")]), hide_index=True, width="stretch")
    be = sue.breakevens(data, cur, alt)
    st.markdown(f"- **Financial break-even**: alternative annual cost {_sar(be['financial_breakeven_alternative_annual_cost_sar'])} "
                f"(base {_sar(be['base_alternative_annual_cost_sar'])})\n"
                f"- **Carbon break-even**: alternative EF {be['carbon_breakeven_alternative_ef_kg_per_tkm']} kgCO₂e/t-km "
                f"(base {be['base_alternative_ef_kg_per_tkm']})\n"
                f"- **Willingness to pay needed**: {_sar(be['willingness_to_pay_needed_sar_per_t'], 2)} per tCO₂e")
    g = pd.DataFrame(sue.grid(data, cur, alt, wtp=data.settings.willingness_to_pay))
    if not g.empty:
        zones = ["No carbon benefit", "Carbon gain at net cost (management judgement)", "Within willingness to pay",
                 "Carbon and financial gain"]
        g["z"] = g["zone"].map({z: i for i, z in enumerate(zones)})
        pv = g.pivot(index="alternative_ef", columns="alternative_annual_cost", values="z")
        tx = g.pivot(index="alternative_ef", columns="alternative_annual_cost", values="npv").map(lambda v: f"{v / 1000:,.0f}k")
        hm = go.Figure(go.Heatmap(z=pv.values, x=[f"{v / 1000:,.0f}k" for v in pv.columns], y=[f"{v:g}" for v in pv.index],
                                  text=tx.values, texttemplate="%{text}", zmin=0, zmax=3, showscale=False,
                                  colorscale=[[0, "#E3E3E3"], [0.33, "#FFF1C9"], [0.67, "#CFE3F1"], [1, "#D7EDDC"]]))
        hm.update_layout(title="Two-variable grid: switching NPV (SAR) by alternative EF × alternative annual cost",
                         xaxis_title="Alternative annual cost (SAR)", yaxis_title="Alternative EF (kgCO₂e/t-km)",
                         yaxis=dict(type="category", dtick=1), xaxis=dict(type="category"), height=420, margin=dict(t=50, b=10))
        st.plotly_chart(hm, width="stretch")
        st.caption("Colour = decision zone: grey no carbon benefit · amber carbon gain at a net cost (management "
                   "judgement) · blue within the stated willingness to pay · green carbon and financial gain.")
    rr = sue.ranking_reversals(data, lid, cur, alt, scr, weights)
    with st.expander("Ranking reversals across the tested ranges"):
        st.dataframe(_safe(rr), hide_index=True, width="stretch")

    st.markdown("#### Double-counting control: shared activity ledger")
    st.markdown("Workstream C's freight optimisation (efficiency) and supplier switching act on **the same tonne-km**. "
                "The combined effect is computed jointly (adjusted activity × alternative factor), never by adding the "
                "two separate reductions. The baseline is not rewritten and Contractor B is never inserted.")
    for basis, lab in (("inventory", "Inventory basis (Phase 4 proxy factor — reproduces Workstream C)"),
                       ("decision", "Decision basis (lane-specific factors)")):
        rows, s = sce.activity_ledger(data, basis=basis, switch_lane=lid, alternative_id=alt)
        st.markdown(f"**{lab}**")
        k = st.columns(5)
        k[0].metric("Baseline (known)", _t(s["baseline_t"], 3))
        k[1].metric("Efficiency only", _t(s["efficiency_avoided_t"], 3))
        k[2].metric("Switching only", _t(s["switching_avoided_t"], 3))
        k[3].metric("Combined (joint)", _t(s["combined_avoided_t"], 3))
        k[4].metric("Overlap removed", _t(s["overlap_t"], 3))
    st.caption("Scope 3 Category 4 boundary is kept; rows with missing activity (Contractor B) are reported as "
               "UNAVAILABLE and excluded from every ledger total.")


# ------------------------------------------------------------------ 6 recommendations
def _recommendations(res):
    data = res["data"]
    st.subheader("Explainable recommendations")
    st.markdown("One recommendation per service lane, from a **project-designed 7-step hierarchy**: legal & safety → "
                "evidence sufficiency → service equivalence → comparable carbon & cost → operational risk → uncertainty "
                "→ conditional recommendation. Weighted scores are supporting evidence only and never override a failed gate.")
    w = data.settings.willingness_to_pay
    st.caption("Willingness to pay: " + (f"SAR {w:,.0f}/tCO₂e" if w is not None else "NOT SET by management") +
               " (change it in the financial and decision settings above).")
    for lid, r in res["recommendations"].items():
        col = ACTION_COLORS.get(r.action, "#555")
        with st.container(border=True):
            st.markdown(f"<div style='display:flex;gap:12px;align-items:center'><span style='background:{col};color:white;"
                        f"padding:4px 10px;border-radius:4px;font-weight:700'>{r.action}</span>"
                        f"<span style='font-weight:600'>{lid} · {r.lane_name}</span>"
                        f"<span style='color:#666'>incumbent {r.incumbent_offer} · rule {r.rule_id}"
                        f"{' · best alternative ' + r.best_alternative if r.best_alternative else ''}</span></div>",
                        unsafe_allow_html=True)
            st.markdown(f"**Why:** {r.rule}")
            if r.human_approval_required:
                st.markdown(f"⚠️ **Human approval required** — {r.approval_note}")
            else:
                st.caption(r.approval_note)
            c1, c2 = st.columns(2)
            c1.markdown("**Carbon:** " + (r.carbon_implications or "—"))
            c1.markdown("**Financial:** " + (r.financial_implications or "—"))
            c1.markdown("**Operational:** " + (r.operational_implications or "—"))
            c2.markdown("**Next steps**\n" + "\n".join(f"- {x}" for x in r.next_steps))
            c2.markdown(f"**Engagement priority:** {r.engagement_priority}")
            with st.expander("Evidence, assumptions, data limits and sensitivity"):
                st.markdown("**Supporting evidence**\n" + "\n".join(f"- {x}" for x in r.supporting_evidence))
                st.markdown("**Material assumptions**\n" + "\n".join(f"- {x}" for x in r.material_assumptions))
                if r.data_limitations:
                    st.markdown("**Data-quality limitations**\n" + "\n".join(f"- {x}" for x in r.data_limitations))
                if r.excluded_alternatives:
                    st.markdown("**Excluded alternatives**\n" + "\n".join(f"- {x}" for x in r.excluded_alternatives))
                if r.sensitivity:
                    st.markdown("**Sensitivity:** " + r.sensitivity)
                if r.score_summary:
                    st.caption(r.score_summary)
                if r.best_alternative:
                    rb, robust = sre.recommendation_robustness(data, lid, res["screening"], res["engagement"], "settings")
                    st.markdown(f"**Robustness:** {'robust — same action in every tested case' if robust else 'NOT robust — the action changes in some cases'}")
                    st.dataframe(_safe(rb), hide_index=True, width="stretch")
    st.caption("Action types: RETAIN EXISTING SUPPLIER · IMPROVE EXISTING SUPPLIER · CONSIDER SWITCHING · REQUEST BETTER "
               "DATA · INELIGIBLE / ESCALATE · NO DEFENSIBLE RECOMMENDATION YET. No recommendation awards a contract or "
               "certifies a supplier as sustainable.")


# ------------------------------------------------------------------ 7 action plans
def _actions(res):
    eng = res["engagement"]
    st.subheader("Engagement action plans")
    st.markdown("Generated from the register templates by quadrant and screening triggers. **Deadlines (30/60/90 days) are "
                "editable management assumptions, not UN requirements.** Status changes are session-only and never modify "
                "the inventory.")
    plan = pd.DataFrame([a for e in eng.values() for a in e.plan])
    if plan.empty:
        st.info("No actions generated.")
        return plan
    sup = st.multiselect("Suppliers", sorted(plan["supplier_id"].unique()), default=sorted(plan["supplier_id"].unique()),
                         key="p11_act_sup")
    view = plan[plan["supplier_id"].isin(sup)].reset_index(drop=True)
    show = ["action_id", "supplier_id", "trigger", "action", "responsible_role", "deadline_days", "proposed_deadline",
            "status", "required_evidence", "success_indicator", "follow_up_date", "verification_method"]
    ed = st.data_editor(view[show], hide_index=True, width="stretch", key="p11_act_editor",
                        disabled=[c for c in show if c not in ("status", "proposed_deadline", "responsible_role")],
                        column_config={"status": st.column_config.SelectboxColumn(options=ACTION_STATUSES, required=True),
                                       "action": st.column_config.TextColumn(width="large")})
    st.caption("deadline_days is the template assumption; proposed_deadline = plan start + days and can be overwritten.")
    upd = dict(zip(ed["action_id"], ed["status"]))
    plan["status"] = plan["action_id"].map(upd).fillna(plan["status"])
    dl = dict(zip(ed["action_id"], ed["proposed_deadline"]))
    plan["proposed_deadline"] = plan["action_id"].map(dl).fillna(plan["proposed_deadline"])
    b = [sid for sid, e in eng.items() if e.quadrant == see.UNCLASSIFIED]
    if b:
        st.markdown("**Default data requests for unclassified suppliers** (" + ", ".join(b) + ")")
        st.markdown("\n".join(f"- {a['action']} — evidence: {a['required_evidence']}" for sid in b for a in eng[sid].plan))
    st.download_button("Download action plans (CSV)", plan.to_csv(index=False).encode(), "engagement_action_plans.csv",
                       "text/csv", key="p11_dl_actions")
    return plan


# ------------------------------------------------------------------ 8 monitoring & audit
def _monitoring(res, plan):
    data, eng = res["data"], res["engagement"]
    st.subheader("Monitoring, verification & audit")
    if plan is not None and not plan.empty:
        for sid, e in eng.items():
            st_map = dict(zip(plan["action_id"], plan["status"]))
            for a in e.plan:
                a["status"] = st_map.get(a["action_id"], a["status"])
    sc = sa.monitoring_scorecard(res)
    st.markdown("**Supplier scorecard** (first reporting year: change indicators need a later period)")
    st.dataframe(_safe(sc), hide_index=True, width="stretch")
    st.markdown("**Projected vs verified**")
    pv = []
    for lid, r in res["recommendations"].items():
        if r.best_alternative:
            c = sce.compare(data, r.incumbent_offer, r.best_alternative)
            pv.append({"Lane": lid, "Change": f"{r.incumbent_offer} → {r.best_alternative}", "Recommendation": r.action,
                       "Projected avoided (t/yr)": _num(c.avoided_t, 2) if c.comparable else "not comparable",
                       "Verified actual (t/yr)": "none — no post-implementation data",
                       "Evidence status": data.offers[r.best_alternative].ef.verification})
    if pv:
        st.dataframe(pd.DataFrame(pv), hide_index=True, width="stretch")
    st.caption("No verification certificate or audit finding is assumed: evidence statuses are exactly as recorded in "
               "the register (e.g. 'Unverified - claimed').")
    au = sa.audit_records(res)
    with st.expander(f"Audit trail ({len(au)} records)"):
        st.dataframe(_safe(au), hide_index=True, width="stretch")
    st.markdown(f"Input version (register SHA-256): `{data.input_version[:16]}…` · engine `{ENGINE_VERSION}` · "
                f"source `{data.source_path.split('/')[-1]}`")

    tabs = sa.tables(res)
    tabs["engagement_action_plans.csv"] = plan.to_dict("records") if plan is not None and not plan.empty else []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, rows in tabs.items():
            sio = io.StringIO()
            pd.DataFrame(rows).to_csv(sio, index=False)
            z.writestr(name, sio.getvalue())
        z.writestr("manifest.json", json.dumps({
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "engine_version": ENGINE_VERSION,
            "input_version": data.input_version, "settings": {
                "discount_rate": data.settings.discount_rate, "horizon_years": data.settings.horizon_years,
                "substitution_share": data.settings.substitution_share,
                "willingness_to_pay": data.settings.willingness_to_pay,
                "impact_threshold": data.matrix.impact_threshold, "maturity_threshold": data.matrix.maturity_threshold},
            "note": "Synthetic demonstration data; session edits included."}, indent=2))
    c = st.columns(3)
    c[0].download_button("Download all Phase 11 tables (ZIP)", buf.getvalue(), "phase11_results.zip", "application/zip",
                         key="p11_dl_zip")
    c[1].download_button("Download audit trail (CSV)", pd.DataFrame(au).to_csv(index=False).encode(),
                         "supplier_audit_trail.csv", "text/csv", key="p11_dl_audit")
    c[2].download_button("Download recommendations (CSV)",
                         pd.DataFrame(tabs["supplier_recommendations.csv"]).to_csv(index=False).encode(),
                         "supplier_recommendations.csv", "text/csv", key="p11_dl_recs")
    with st.expander("Methodology & sources"):
        st.markdown(
            "- **Emissions**: tonne-km × kgCO₂e/t-km ÷ 1,000 (GHG Protocol Scope 3 Category 4 distance-based method; "
            "tank-to-wheel boundary as in the inventory).\n"
            "- **Engagement matrix**: impact × maturity segmentation inspired by the UN Global Compact supplier "
            "engagement approach; numeric scores, thresholds and weights are **project-designed**.\n"
            "- **Finance**: Phase 9 cash-flow engine (real discount rate, annuity factor); NPV = −one-time + annual "
            "savings × annuity factor.\n- **Uncertainty**: low/base/high stress values from the register; one-way, joint "
            "cases, break-evens and a 2-variable grid — not probabilities.\n"
            "- **Double counting**: one shared activity ledger; combined = adjusted activity × alternative factor.")
        if data.sources:
            st.dataframe(_safe(data.sources), hide_index=True, width="stretch")
