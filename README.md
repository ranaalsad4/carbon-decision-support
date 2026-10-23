# Carbon Decision-Support Assistant — Workstreams B + C + Phase 11 (Phases 4–11)

Synthetic demonstration for a **fictional** manufacturing facility in Riyadh Region (reporting year 2025).
**Preliminary, demonstration-only results — not a verified corporate GHG inventory and not investment advice.**

* **Workstream B (Phases 5–7, unchanged):** data-quality engine (Phase 4 validator, DQ-01…DQ-16), emissions
  calculation engine, hotspots and data-confidence labels.
* **Workstream C (Phases 8–10, new):** reduction scenarios, financial evaluation (NPV, payback, SAR/tCO₂e,
  feasibility) and uncertainty-aware decision analysis (low/base/high, one-way sensitivity, switching values,
  ranking reversals, missing Contractor B sensitivity).
* **Phase 11 (new): Supplier Decision & Engagement** — dashboard tab 9. Screening (14 checks), data quality
  (7 dimensions), an interactive impact × maturity engagement matrix, alternatives comparison per tonne-km,
  carbon/financial trade-off, explainable recommendations, action plans, monitoring and audit trail. Inputs:
  `phase11/Phase11_Supplier_Decision_Assumptions_Register.xlsx` (synthetic). Matrix scores, thresholds and
  scoring weights are **project-designed assumptions, not official UN rules**.

The software is deterministic Python (no machine-learning or AI component). No paid APIs or credentials are needed.

## Key facts carried through every phase

| Item | Value |
|---|---|
| Scope 1 / Scope 2 / Scope 3 Cat. 4 (known A + C) | 266.155 / 4,400.000 / 193.097 tCO₂e |
| Quantified total (indicative, Contractor B unavailable) | 4,859.252 tCO₂e |
| Record completeness | 48/60 = 80% |
| Electricity factor | `FAC-ELEC-SEC-01`, 550 kg CO₂e/MWh, SEC 2024, **provisional** location-based Scope 2 proxy |
| Contractor B | 12 records with no activity data → UNAVAILABLE, never zero, never reduced |
| Contractor A / C (inventory) | 121.956 / 71.141 tCO₂e — Phase 11 reads these, never rewrites them |
| Workstream C freight optimisation | 28.965 tCO₂e — shared with Phase 11 through one activity ledger (no double counting) |

## Run on your own computer

```bash
pip install -r requirements.txt
python -m pytest -v               # 170 tests: 35 Phase 4 + 15 Workstream B + 25 Workstream C + 95 Phase 11
python calc_engine.py             # Workstream B -> outputs/*.csv + outputs/run_manifest.json
python run_workstream_c.py        # Workstream C -> outputs/workstream_c/*.csv + run_manifest_c.json
python run_phase11.py             # Phase 11 -> outputs/phase11/*.csv + run_manifest_p11.json
streamlit run app.py              # dashboard at http://localhost:8501 (9 tabs)
```

Windows: run the same commands in a terminal opened in this folder (use `py` instead of `python` if needed).

## Run in Google Colab

Run each block in its own Colab cell, in order.

**1. Upload the ZIP**

```python
from google.colab import files
uploaded = files.upload()            # choose Workstream_BC_Phase11_Integrated.zip
```

**2. Extract the project and move into it**

```python
!unzip -q -o Workstream_BC_Phase11_Integrated.zip -d /content
%cd /content/Workstream_BC
!ls
```

**3. Install requirements**

```python
!pip install -q -r requirements.txt
```

**4. Run all tests (Phase 4, Workstream B, Workstream C, Phase 11)**

```python
!python -m pytest -v
```

Expected final line: `170 passed`. To run one part only:
`!python -m pytest -v test_workstream_b.py phase4/test_phase4.py`, `!python -m pytest -v test_workstream_c.py`
or `!python -m pytest -v test_phase11.py`.

**5. Run the calculation engines**

```python
!python phase4/validate_phase4.py    # Phase 5 data-quality rules on the Phase 4 datasets
!python calc_engine.py               # Workstream B baseline
!python run_workstream_c.py          # Workstream C: scenarios, financials, uncertainty (+ reconciliation)
!python run_phase11.py               # Phase 11: supplier screening, matrix, recommendations, audit
```

`run_workstream_c.py` prints `Reconciliation vs workbooks: 228/228 match` when the engines reproduce the workbooks.

**6. Open the Streamlit dashboard**

Start Streamlit in the background:

```python
!nohup streamlit run app.py --server.port 8501 --server.headless true > streamlit.log 2>&1 &
import time; time.sleep(8); print(open("streamlit.log").read())
```

Then open it with **one** of these options:

*Option A — Colab's built-in port proxy (no extra software):*

```python
from google.colab.output import eval_js
print(eval_js("google.colab.kernel.proxyPort(8501)"))   # click the printed link
```

*Option B — a free public tunnel (if Option A shows a blank page):*

```python
!curl -s https://ipv4.icanhazip.com        # copy this IP: localtunnel asks for it as the "tunnel password"
!npx --yes localtunnel --port 8501         # open the printed https://...loca.lt link
```

Option B makes the dashboard reachable by anyone with the link while the cell runs; stop the cell to close it.
These two options were written for Colab but could not be tested from the build environment.

**7. Export the results**

```python
!zip -q -r results.zip outputs
from google.colab import files
files.download("results.zip")
```

## What is where

| Path | Purpose |
|---|---|
| `phase4/` | Phase 4 package v1.1 (datasets, emission-factor library, validator = Phase 5 data-quality engine). **Not modified.** |
| `calc_engine.py`, `confidence.py` | Workstream B engine and confidence labels (unchanged) |
| `workbooks/` | The three uploaded Excel workbooks (Phase 8, Phase 9, corrected Phase 10) — source of assumptions, never modified (SHA-256 checked by tests) |
| `workstream_c_inputs.py` | Reads the workbooks by row label; cross-checks them against each other and the computed baseline |
| `scenario_engine.py` | Phase 8: record-level reduction scenarios through the unchanged Workstream B engine |
| `financial_engine.py` | Phase 9: cash flows, NPV, payback, NPC, SAR/tCO₂e, IRR, feasibility |
| `uncertainty_engine.py` | Phase 10: cases, sensitivity, switching values, ranking reversals, Contractor B sensitivity, robustness |
| `run_workstream_c.py` | Runs Phases 8–10, writes outputs and a SHA-256 manifest |
| `app.py` + `workstream_c_tabs.py` + `phase11_tab.py` | Dashboard: tabs 1–5 Workstream B (unchanged), tabs 6–8 Workstream C, tab 9 Phase 11 |
| `phase11/` | Phase 11 assumptions register (15 sheets) and its generator `build_phase11_register.py` |
| `supplier_models.py`, `supplier_data_loader.py` | Phase 11 data classes, validation, register loader, session edits |
| `supplier_screening_engine.py` | 14 screening checks, eligibility, 7 data-quality dimensions, service equivalence |
| `supplier_carbon_engine.py` | Tonne-km comparison, partial substitution, shared activity ledger (double-counting control) |
| `supplier_financial_engine.py` | Switching NPV, cost per tonne, break-evens (reuses `financial_engine.py`) |
| `supplier_engagement_engine.py` | Impact, maturity, quadrant, priority and action plans |
| `supplier_scoring_engine.py` | Weight validation and normalisation, weighted scores, ranking, weight sensitivity |
| `supplier_uncertainty_engine.py` | One-way, joint cases, break-evens, 2-variable grid, ranking reversals |
| `supplier_recommendation_engine.py` | 7-step hierarchy → six recommendation types with explanations |
| `supplier_audit.py`, `run_phase11.py` | Audit trail, scorecard, outputs and SHA-256 manifest |
| `test_workstream_b.py`, `test_workstream_c.py`, `test_phase11.py`, `phase4/test_phase4.py` | Automated tests |
| `outputs/` | Workstream B outputs (+ `run_manifest.json`) |
| `outputs/workstream_c/` | Workstream C outputs (+ `run_manifest_c.json`) |
| `outputs/phase11/` | Phase 11 outputs (+ `run_manifest_p11.json`) |

### Workstream C outputs

| File | Content |
|---|---|
| `scenario_assumptions.csv` | Phase 8 rates, targets, evidence status, workbook cell references |
| `scenario_comparison.csv` | Baseline vs scenario, avoided tCO₂e, % of affected stream and of quantified total, by scope |
| `scenario_monthly.csv` / `scenario_audit_trail.csv` | Monthly results; record-level audit with factor provenance and missing-data flags |
| `financial_assumptions.csv` / `financial_cash_flows.csv` / `financial_comparison.csv` | Phase 9 inputs (with cell refs), year 0–10 cash flows, metrics |
| `operational_feasibility.csv` | Phase 9 feasibility checklist per intervention + summary |
| `financial_reconciliation.csv`, `uncertainty_reconciliation.csv`, `workbook_consistency_checks.csv` | Engine vs workbook checks |
| `uncertainty_cases.csv`, `sensitivity_results.csv`, `switching_values.csv` | Low/base/high, one-way sensitivity, break-even and ranking-tie values |
| `ranking_analysis.csv`, `ranking_reversal_tests.csv`, `decision_robustness.csv` | Ranking per case, reversal scans, robustness |
| `missing_supplier_sensitivity.csv` | Hypothetical Contractor B cases × applicability (sensitivity only) |
| `decision_statements.txt` | Conditional findings generated from the results |

## Calculation rules

* Emissions (t) = quantity × factor (kg/unit) ÷ 1,000; one factor per record; BLOCKED records not calculated.
* Scenario quantity = baseline quantity × Π(1 − rate) over the interventions acting on that record
  (multiplicative, so overlapping interventions cannot be double counted).
* NPV = −CAPEX + Σₜ (gross savings − OPEX) / (1 + r)ᵗ for lead time < t ≤ min(life, horizon); constant real SAR,
  end-of-year cash flows, 5% real, 10 years (Phase 9 workbook).
* Net cost per tonne = −NPV (discounted SAR) ÷ lifetime tonnes avoided (undiscounted). Negative = potential net saving.
* Contractor B sensitivity: avoided = rate × (known freight + applicability × hypothetical Contractor B). The
  hypothetical term is a sensitivity assumption only; the baseline never changes.

## Confidence labels (Workstream B, unchanged)

Criteria C1 activity completeness · C2 factor age · C3 geography · C4 gas coverage · C5 verification ·
C6 boundary fit, each Met / Partial / Not met (C5: a `provisional_proxy` factor counts as unverified = Not met).
NOT QUANTIFIED = no activity data; LOW = ≥ 2 Not met, or 1 Not met + ≥ 2 Partial; HIGH = all Met;
MODERATE = otherwise. All labels are capped "demonstration only".

## Phase 11 rules (summary — see Phase11_Methodology.md)

* Functional unit: tonne-km of the same lane service. Emissions = tonne-km × kgCO₂e/t-km ÷ 1,000.
* Eligibility overrides any weighted score. Missing mandatory inputs give no total and suppress the ranking.
* Default weights carbon 35 / cost 25 / reliability 20 / data quality 15 / improvement 5 — illustrative, editable,
  validated (numeric, non-negative) and normalised.
* Switching NPV = −one-time costs + (current − alternative − recurring cost) × annuity factor. A negative NPV is not
  an automatic rejection; the discounted lifetime cost per tonne is compared with a management willingness to pay.
* The engagement matrix sets engagement priority only; it never triggers replacement. Contractor B stays
  "Unclassified — insufficient evidence"; its hypothetical value is a labelled sensitivity only.
* Combined freight efficiency + switching = adjusted activity × alternative factor on one shared ledger.
