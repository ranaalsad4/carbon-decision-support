# Phase 11 — Validation Report

Build environment: Linux, Python 3.13, Streamlit 1.66.1, pytest 9.1.1, pandas, Plotly, openpyxl. Every figure
below was produced by commands that were actually run on the delivered code.

## 1. Test results

Command (run from the project folder `Workstream_BC/`):

```bash
python -m pytest -v -p no:cacheprovider
```

| Suite | Collected | Passed | Failed | Skipped |
|---|---|---|---|---|
| `phase4/test_phase4.py` (Phase 4 / data-quality engine) | 35 | 35 | 0 | 0 |
| `test_workstream_b.py` (Workstream B) | 15 | 15 | 0 | 0 |
| `test_workstream_c.py` (Workstream C) | 25 | 25 | 0 | 0 |
| `test_phase11.py` (Phase 11, new) | 95 | 95 | 0 | 0 |
| **Total** | **170** | **170** | **0** | **0** |

Final line: `170 passed in 14.39s`. `test_phase11.py` has 83 test functions; parametrisation makes 95 collected tests.

**One existing test was changed.** In `test_workstream_c.py::test_dashboard_all_tabs_present_and_no_exceptions`,
the assertion "exactly 8 tabs" became "the original 8 tabs are unchanged and in order, and tab 9 is *Supplier
Decision & Engagement*". All its other assertions are unchanged. This change is required by the ninth tab and is
recorded in the change log.

### Phase 11 tests by brief category

| Category (brief) | Tests | What is checked |
|---|---|---|
| Preservation | 6 | S1 266.155, S2 4,400, S3 193.097, total 4,859.252 · A 121.956, C 71.141, B UNAVAILABLE · 48/60 · inventory identical before/after Phase 11 runs and edits · register and Phase 4 files byte-identical · hypothetical B labelled SENSITIVITY and never in a ledger total |
| Carbon | 10 | tonne-km and emissions · demo 120 → 80, 40 t, 33.33% · negative activity rejected, zero tonne-km gives no division · g/kg unit normalisation, invalid unit rejected · non-numeric/negative parsing · boundary mismatch · different lanes · 40% partial substitution (16 t, SAR 8,000, NPV −91,773.88) · higher-emission alternative · decision vs inventory basis (18.37 t methodology difference) |
| Screening & data quality | 9 | eligibility classes · 14 checks, 3–10 auto · safety gate → Ineligible · capacity shortfall → Ineligible · period mismatch · boundary → conditional, not comparable · verification policy switch · 7 DQ dimensions, B "UNAVAILABLE (not zero)" · equivalence limitations |
| Engagement matrix | 16 | A Q1/Priority 1 (70.53 / 39.29) · C Q4 · B unclassified with default data requests · 8 synthetic quadrant cases including boundaries and missing inputs · editable thresholds · minimum-indicator rule · prospective suppliers excluded · matrix never yields CONSIDER SWITCHING or "replace/terminate" actions at any threshold · action-plan fields, 30/60/90 deadlines labelled as management assumptions |
| Financial | 9 | NPV equals the workbook validation case (−184,434.70) · cost difference, SAR 500/t, break-even 296,114.86, lifetime 597.13 · discount rate 0% · switching cost +30k · horizon 5 y · positive-NPV case and payback · missing cost · zero avoided · willingness-to-pay check |
| Scoring | 12 | default weights normalised · 6 invalid weight sets rejected (negative, non-numeric, boolean, all-zero, missing, unknown) · unnormalised weights give identical scores · L1 D 56.20 rank 1, A 44.96 rank 2, contributions sum to total · eligibility override (E 66.84 not ranked) · missing input → SUPPRESSED · weight change reverses ranking (cost 60% → A) and carbon-weight switch point |
| Recommendations | 12 | default L1 R6 / L2 RETAIN / L3 IMPROVE / L4 DATA · WTP 600 → CONSIDER SWITCHING (R7) · WTP 500 → IMPROVE (R8) · alternative cost 290k → CONSIDER SWITCHING (R5) · non-robust carbon → R5u · incumbent gate failure → INELIGIBLE (R1) · financial-only gain → R9 · ineligible alternative excluded · explanation fields complete, approval flags · six action types · robustness · missing factor / capacity does not crash |
| Uncertainty & integration | 17 | joint cases (10 / 40 / 70 t) · one-way base = deterministic · break-evens · grid zones · no ranking reversal in parameter ranges · ledger inventory basis = Workstream C 28.965 t · no double counting (overlap 6.0 t) · register Validation Cases equal the engine · register loads clean (15 sheets) · duplicate ID / unsupported mode / non-numeric activity reported · user-added supplier (undocumented checks Missing) · edit errors · deletions are session-only · audit fields and no invented verification · scorecard projected vs verified · reproducible output hashes |
| Workstream C unchanged | 1 | fresh `run_workstream_c.py` output hashes equal the committed `run_manifest_c.json` |
| Streamlit smoke | 3 | 9 tabs, no exceptions · objective text and all 8 section headings · recommendations, WTP, invalid-weight error and threshold slider change the display |

## 2. Brief targets reconciled

| Brief item | Brief value | Engine value | Status |
|---|---|---|---|
| Avoided emissions | 40 t | 40.000 t | ✓ |
| Reduction | 33.33% | 33.333% | ✓ |
| Annual cost difference | +SAR 20,000 | +SAR 20,000 | ✓ |
| Annual cost per tonne | SAR 500 | SAR 500 | ✓ |
| Switching NPV | ≈ −184,443 | **−184,434.70** | Differs by SAR 8.30: the brief figure appears rounded or mistyped. The closed form −30,000 − 20,000 × 7.721735 = −184,434.70, and Excel's PV function in the register gives the same. |
| Break-even alternative cost | ≈ 296,115 | 296,114.86 | ✓ |
| Contractor A baseline | 121.956 | 121.956 (unchanged) | ✓ |
| Contractor B | UNAVAILABLE | UNAVAILABLE, unclassified | ✓ |
| Workstream C freight reduction | 28.965 | 28.96455 on the shared ledger (inventory basis) | ✓ no double counting |

The ledger and Workstream C differ by 2 × 10⁻⁶ t (2 g). Workstream C sums rounded record-level emissions, while the
ledger multiplies the annual tonne-km. The test tolerance is 1 × 10⁻⁵ t, and the reason is documented in the test.

## 3. Fault injection (do the tests catch real errors?)

Each fault was applied to a temporary copy of the project, and `test_phase11.py` was then run on that copy.

| Injected fault | Result |
|---|---|
| Missing Contractor B impact scored as 0 instead of UNCLASSIFIED | 1 failed — detected |
| Ineligible offers allowed into the ranking | 1 failed — detected |
| No-willingness-to-pay rule (R6) removed | 2 failed — detected |
| Ledger adds efficiency and switching separately (double counting) | 1 failed — detected |
| Lifetime cost per tonne computed without the annuity factor | 6 failed — detected |

## 4. Other verification performed

- **End-to-end run.** `python run_phase11.py` writes 20 CSV tables and `run_manifest_p11.json` (SHA-256 of inputs
  and outputs). Two runs give identical hashes.
- **Existing outputs untouched.** `outputs/*.csv` (Workstream B) and `outputs/workstream_c/*` are byte-identical to
  the uploaded ZIP (`diff -rq`). Only `outputs/phase11/` is new.
- **Register.** It was recalculated with LibreOffice: 32 formulas, 0 errors. Its cached Validation Cases values equal
  the engine to 1e-9.
- **Dashboard.**
  - Streamlit AppTest runs with no exceptions or Arrow conversion warnings.
  - Interactive checks:

    | Control | Result |
    |---|---|
    | Willingness to pay SAR 600/t | L1 → CONSIDER SWITCHING |
    | Willingness to pay SAR 500/t | L1 → IMPROVE |
    | Negative weight | Error shown, defaults used |
    | Impact threshold 80 | A moves to Q3 |
    | B sensitivity | Impact 50.6 labelled SENSITIVITY; B stays unclassified (3 of 7 maturity indicators) |
    | Edited offer (D at SAR 290,000) | L1 → CONSIDER SWITCHING |
    | Invalid entries (`"abc"`, −5) | Reported as validation errors, treated as missing |

  - Screenshots of all eight sections were taken with Playwright/Chromium at 1500 px width and reviewed.
- **Static check.** `pyflakes` is clean on all Phase 11 modules and tests.

## 5. Limitations (exact)

1. **Synthetic data.** All supplier, cost, reliability, factor and evidence values are synthetic. The recommendations
   demonstrate the method, not real procurement decisions.
2. **Plotly click selection.** Clicking a point in the engagement matrix uses Streamlit's `on_select`. AppTest
   cannot simulate a Plotly click, so this was verified only by code path; the selection box beside the chart
   always works.
3. **No willingness to pay set.** The register leaves willingness to pay blank by design. L1 therefore stays at
   NO DEFENSIBLE RECOMMENDATION YET until management enters a value.
4. **Session-only edits.** Action-plan statuses and offer edits last for the session only. Persistent storage
   across sessions was not implemented (the dashboard has no database). Results can be downloaded as CSV/ZIP.
5. **Untested Colab steps.** The Colab steps (port proxy or localtunnel) were written for Colab but could not be
   executed from the build environment.
6. **No change-over-time indicators.** Monitoring "change" indicators (intensity, activity, maturity) show "n/a —
   first reporting year" because no later period exists.
