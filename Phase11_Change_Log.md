# Phase 11 — Change Log

Base: `Workstream_BC_Integrated.zip` (Workstreams B + C, Phases 4–10). Result: `Workstream_BC_Phase11_Integrated.zip`.
Engine version `P11-1.0`.

## Added

| File | Purpose |
|---|---|
| `phase11/Phase11_Supplier_Decision_Assumptions_Register.xlsx` | 15-sheet synthetic assumptions register: data classes, dropdowns, Validation Cases with live formulas |
| `phase11/build_phase11_register.py` | Regenerates the register deterministically |
| `supplier_models.py` | Data classes, number parsing, unit normalisation, validation messages |
| `supplier_data_loader.py` | Register loader with validation; read-only inventory link; session offer edits |
| `supplier_screening_engine.py` | 14 checks (3–10 derived), eligibility, 7 data-quality dimensions, service equivalence |
| `supplier_carbon_engine.py` | Tonne-km comparison, partial substitution, shared activity ledger |
| `supplier_financial_engine.py` | Switching NPV, cost per tonne, break-evens (wraps `financial_engine.py`) |
| `supplier_engagement_engine.py` | Impact, maturity, quadrant, priority, action plans |
| `supplier_scoring_engine.py` | Weight validation and normalisation, scores, ranking status, weight sensitivity |
| `supplier_uncertainty_engine.py` | One-way, joint cases, break-evens, 2-variable grid, ranking reversals |
| `supplier_recommendation_engine.py` | 7-step hierarchy, rules R1–R9, explanations, robustness |
| `supplier_audit.py`, `run_phase11.py` | Audit trail, monitoring scorecard, CSV outputs, SHA-256 manifest |
| `phase11_tab.py` | Dashboard tab 9 with 8 sections (UI only, no calculations) |
| `test_phase11.py` | 95 collected tests |
| `outputs/phase11/` | 20 CSV tables + `run_manifest_p11.json` |

## Modified

| File | Change |
|---|---|
| `app.py` | Imports `phase11_tab`; adds the 9th tab "Supplier Decision & Engagement" after the 8 existing tabs. Docstring updated. Tabs 1–8 are unchanged. |
| `test_workstream_c.py` | The tab test now checks that the original 8 tabs are unchanged and in order, plus the 9th tab (previously "exactly 8 tabs"). |
| `README.md` | Phase 11 overview, commands, file map, rules; test count 75 → 170; ZIP name for Colab. |

## Not modified (verified)

The following files are byte-identical to the uploaded ZIP:

- `calc_engine.py`, `confidence.py`, `scenario_engine.py`, `financial_engine.py`, `uncertainty_engine.py`,
  `workstream_c_inputs.py`, `workstream_c_tabs.py`, `run_workstream_c.py`
- `phase4/`, `workbooks/`
- `outputs/*.csv`, `outputs/run_manifest.json`, `outputs/workstream_c/`
- `requirements.txt` (no new dependencies)

Baseline is preserved: S1 266.155 · S2 4,400 · S3 193.097 · total 4,859.252 · A 121.956 · C 71.141 · B UNAVAILABLE · 48/60.

## Corrections and decisions during implementation

- **NPV target.** The brief's NPV of "≈ −184,443" is −184,434.70 exactly (SAR 8.30 difference). The engine computes
  the exact value; nothing is hard-coded.
- **Uncertainty base values.** Base values come from each offer's own data, not the register base column. User
  edits therefore flow into every sensitivity case.
- **Break-even switching cost.** It is reported as "none" (not 0) when annual savings are not positive.
- **Recommendation engine.** It is guarded against missing capacity, factor or on-time values (no crash, shows
  "not documented").
- **Contractor B under the sensitivity toggle.** B stays unclassified because its maturity evidence (3 of 7
  indicators) is below the project minimum of 5. No maturity value was invented.
- **Two emission bases.** The decision basis (L1 supplier-specific 0.12) and the inventory basis (0.10163 proxy)
  are reported separately. The 18.37 t gap is labelled a methodology difference, not a reduction.
