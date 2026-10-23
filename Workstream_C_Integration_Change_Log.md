# Workstream C Integration — Change Log (22 Oct 2026)

**Starting point:** `Workstream_B_Updated.zip`, byte-identical to the Workstream B v1.1 package delivered on 21 Oct 2026.
**Result:** `Workstream_BC_Integrated.zip`, project folder `Workstream_BC/`.

Workstream B and Phase 4 code, data, emission factors, outputs and tests are **unchanged**. Only three existing files were modified, and only to add Workstream C.

## Added

### Engines and dashboard

| File | Purpose |
|---|---|
| `workstream_c_inputs.py` | Reads the Phase 8, 9 and 10 workbooks by row label, returning values with `Sheet!Cell` references. Holds the intervention→record target map. Runs 33 cross-workbook and baseline consistency checks; engines refuse to run on any mismatch. |
| `scenario_engine.py` | Phase 8: record-level scenarios A, B, C and the combined A+B+C, run through the unchanged `calc_engine.run`. Reductions combine multiplicatively, so there is no double counting. Monthly and annual results; audit trail. |
| `financial_engine.py` | Phase 9: cash flows, NPV (loop and closed form), NPC, simple and discounted payback, IRR, cost per tonne (workbook and levelised), additive portfolio, feasibility, reconciliation. |
| `uncertainty_engine.py` | Phase 10 (corrected workbook only): low/base/high cases, one-way sensitivity, break-even and ranking-tie switching values, reversal scans with exact switch points, Contractor B sensitivity, ranking analysis, robustness, conditional statements, reconciliation. |
| `run_workstream_c.py` | Runs Phases 8–10. Writes `outputs/workstream_c/` and `run_manifest_c.json` with SHA-256 hashes of inputs and outputs. |
| `workstream_c_tabs.py` | Dashboard tabs 6–8 (Reduction scenarios, Financial evaluation, Decision intelligence). |
| `test_workstream_c.py` | 25 tests (listed in the verification summary). |

### Data and outputs

| File | Purpose |
|---|---|
| `workbooks/` (3 files) | The uploaded Phase 8, Phase 9 and corrected Phase 10 workbooks, stored unchanged. Their SHA-256 hashes are tested. |
| `outputs/workstream_c/` (20 files) | Scenario outputs: `scenario_assumptions`, `scenario_comparison`, `scenario_monthly`, `scenario_audit_trail`. |
| | Financial outputs: `financial_assumptions`, `financial_cash_flows`, `financial_comparison`, `operational_feasibility`, `financial_reconciliation`. |
| | Uncertainty outputs: `uncertainty_cases`, `sensitivity_results`, `switching_values`, `ranking_analysis`, `ranking_reversal_tests`, `missing_supplier_sensitivity`, `decision_robustness`, `uncertainty_reconciliation`. |
| | Checks and summaries: `workbook_consistency_checks` (all `.csv`), `decision_statements.txt`, `run_manifest_c.json`. |

### Documents

| File | Purpose |
|---|---|
| `Workstream_C_Phases_8_10_Implementation_Report.docx`, `Workstream_C_Integration_Change_Log.md`, `Workstream_C_Verification_Summary.md` | Deliverables, also included in the package. |

## Modified

| File | Change |
|---|---|
| `app.py` | Docstring updated. `import workstream_c_tabs`. Caption shows the Workstream C version. `st.tabs` extended from 5 to 8 tabs, with three `with tabs[5..7]` blocks added at the end. In the existing Hotspots tab, the hotspot `rank` column is cast to text: it mixes numbers with "-", which printed an Arrow conversion traceback in the console; the display is unchanged. Tabs 1–5 are otherwise identical (18 lines added, 4 changed). |
| `requirements.txt` | Added `openpyxl>=3.1` (reads the workbooks). |
| `README.md` | Rewritten for Workstreams B + C, with exact Google Colab steps (upload, extract, install, test, run engines, open dashboard, export). The Workstream B content is kept. |

## Preserved (byte-identical)

- **Workstream B code and tests:** `calc_engine.py`, `confidence.py`, `test_workstream_b.py`, `calculation_test_cases.csv`.
- **Workstream B outputs:** all six files and `run_manifest.json`.
- **Workstream B documents:** report, change log and verification summary.
- **Phase 4:** the entire `phase4/` folder — datasets, emission-factor library (`FAC-ELEC-SEC-01` = 550 kg CO₂e/MWh), validator (DQ-01…DQ-16), tests, outputs and documents.

## Removed

None.

## Notes

- Python bytecode caches (`__pycache__`) are excluded from the ZIP.
- The superseded electricity factor (614.2 kg CO₂/MWh) does not appear in any active register, calculation or Workstream C output. This is tested.
