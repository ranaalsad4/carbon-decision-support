# Workstream C Verification Summary (executed 22 Oct 2026)

**Environment:** Python 3.13.16 · pytest 9.1.1 · streamlit 1.66.1 · plotly 7.1.0 · pandas 3.0.5 · openpyxl 3.1.5.

**Commands run** (all from the project root):
- `python -m pytest -v`
- `python calc_engine.py`
- `python run_workstream_c.py` (exit code 0)
- `streamlit run app.py`, opened in a headless browser to view all 8 tabs

The same commands were then re-run from a fresh extraction of the final ZIP. Every figure below comes from those runs.

## 1. Tests executed

| Suite | Passed | Failed |
|---|---|---|
| `phase4/test_phase4.py` (Phase 4 data, validator, 16 rules) | 35 | 0 |
| `test_workstream_b.py` (Workstream B, unchanged) | 15 | 0 |
| `test_workstream_c.py` (new) | 25 | 0 |
| **Total** | **75** | **0** |

The previous Workstream B result (15 tests, 50 including Phase 4) is unchanged.

The new tests check:
- **Inputs:** workbooks unchanged (SHA-256); workbooks consistent with each other and with the baseline.
- **Baseline:** unchanged after all Workstream C runs; source records not modified.
- **Scenarios:**
  - default reductions are correct and reconcile with the activity records;
  - existing factor IDs and values are used;
  - Contractor B is never zero;
  - the combined scenario has no double counting, including a forced overlap (1 − 0.9 × 0.9);
  - monthly and annual totals reconcile.
- **Financials:**
  - NPV checked against an independently coded loop;
  - Phase 9 reconciliation;
  - discounting, lead-time and 0% edge cases;
  - cost-per-tonne definition and edge cases.
- **Uncertainty:**
  - Phase 10 reconciliation;
  - switching values (NPV = 0 at the break-even values; the tie gives equal NPVs);
  - sensitivity results reproducible;
  - ranking with all-negative NPVs;
  - reversal detection;
  - Contractor B kept separate and not contaminating the baseline.
- **Outputs:** no superseded factor in any output; output hashes reproducible.
- **Dashboard:** all eight tabs render without exceptions; a slider and a CAPEX input change the displayed values to exactly the engine's results.

**Fault injection:** three deliberate faults were each caught by the suite: additive combination, Contractor B set to zero, and the 614.2 factor value.

## 2. Baseline reconciliation (unchanged)

| Metric | Expected | Engine |
|---|---|---|
| Scope 1 | 266.155 | 266.155 tCO₂e |
| Scope 2 | 4,400.000 | 4,400.000 tCO₂e (8,000 MWh × 550 ÷ 1,000; `FAC-ELEC-SEC-01`, provisional) |
| Scope 3 Cat. 4, known freight (A + C) | 193.097 | 193.097 tCO₂e |
| Quantified total | 4,859.252 | 4,859.252 tCO₂e |
| Record completeness | 48/60 = 80% | 48/60 = 80% |
| Electricity share | ≈ 90.5% | 90.5% |
| Contractor B | unavailable | UNAVAILABLE (12 NULL records, never zero) |

The Workstream B output files are byte-identical to the delivered Workstream B package. The baseline figures typed into the three workbooks equal the engine-computed values (33 consistency checks OK, 0 mismatches).

## 3. Scenario reconciliation (Phase 8)

| Scenario | Avoided (tCO₂e/yr) | Target | Workbook | % of affected stream | % of quantified total |
|---|---|---|---|---|---|
| A Diesel efficiency (10%) | 26.6155 | ≈ 26.616 | 26.6155 | 10.0% | 0.55% |
| B Known freight A + C (15%) | 28.964552 | ≈ 28.965 | 28.96455 | 15.0% | 0.60% |
| C Electricity efficiency (10%) | 440.000 | 440.000 | 440 | 10.0% | 9.05% |
| A + B + C combined | 495.580 | — | — | 10.2% | 10.20% |

- **Derivation:** every result is derived from the 60 activity records through the unchanged engine. Nothing is hard-coded.
- **Freight rounding:** freight differs from the workbook by 0.000002 tCO₂e, because the Phase 4 calculator rounds each monthly record to six decimals.
- **Combined scenario:** equals A + B + C exactly, because the interventions act on different records.
- **Monthly results:** sum to the annual totals.

## 4. Financial reconciliation (Phase 9)

| Intervention | NPV engine (SAR) | NPV workbook | Target | Simple payback | IRR | SAR/tCO₂e |
|---|---|---|---|---|---|---|
| A Diesel | 17,217.35 | 17,217.35 | ≈ 17,217 | 6.00 y | 10.6% | −64.69 |
| B Known freight | 96,208.58 | 96,208.58 | ≈ 96,209 | 4.29 y | 19.4% | −332.16 |
| C Electricity | 619,651.56 | 619,651.56 | ≈ 619,652 | 3.45 y | 26.2% | −140.83 |

- **Agreement:** 123 of 123 Phase 9 checks match (metrics plus year 0–10 net cash flow, discount factor and PV for each intervention). The largest difference is 2.3e-5 SAR/tCO₂e (freight rounding).
- **Inputs used:** horizon 10 years and real discount rate 5%, read from `Assumptions!B18:B19`.
- **Cost per tonne:** discounted SAR ÷ undiscounted lifetime tonnes, as in the workbook. Negative values are potential net savings, not verified savings.

## 5. Uncertainty and switching validation (Phase 10, corrected workbook)

- **Cases:** 81 of 81 checks match.

  | Case | Diesel (SAR) | Freight (SAR) | Electricity (SAR) |
  |---|---|---|---|
  | Low | −67,576 | −115,847 | −183,607 |
  | Base | 17,217 | 96,209 | 619,652 |
  | High | 78,042 | 253,377 | 1,224,844 |

  All three are negative in the low case. Diesel is ranked first there only as the least negative, and it is not recommended.
- **Switching values:** 12 of 12 match.
  - Electricity–freight tie at **SAR 92,211.74/yr** of electricity gross savings, reproduced independently (target ≈ 92,212).
  - Electricity CAPEX would have to reach SAR 1,023,443, or freight savings SAR 107,788/yr, for freight to tie with electricity.
  - Break-even gross savings: SAR 12,770 (diesel), 27,541 (freight), 79,752 (electricity).
- **Ranking reversals:** within the tested 0.5×–1.5× range, the only reversal is electricity savings or effectiveness below **0.576×** of base. There is no reversal for CAPEX, OPEX, the shared discount rate (0–15%) or lead time (0–3 years); each reversal test also reports its exact switch point.
- **Contractor B:** 12 of 12 match.
  - The hypothetical Contractor B emissions (50, 200 and 600 t) are sensitivity assumptions only. Applicability multiplies only the hypothetical-B term; the baseline is unchanged; no financial savings are assigned to Contractor B.
  - Freight abatement in the base case is 28.96 t (known data) plus 30.00 t (hypothetical B) = 58.96 t, matching `Cases!H8`.
- **Total reconciliation:** 228 of 228 engine-versus-workbook checks match. Two clean runs give identical SHA-256 hashes for all 19 Workstream C result files; `run_manifest_c.json` is the 20th file and records those hashes.

## 6. Unresolved issues and disclosures

1. **Hypothetical Contractor B in the workbook's base case.** The corrected Phase 10 workbook's base case includes 200 tCO₂e/yr of hypothetical Contractor B in freight abatement (58.96 vs 28.96 tCO₂e/yr). This is reproduced exactly, but reported as a separate, labelled sensitivity. The known-data figure is primary.
2. **Workbook formula edge cases.**
   - Phase 9 returns 0 for payback and cost per tonne when they are undefined.
   - Phase 10's NPV formula returns −CAPEX at a 0% discount rate.
   - The engines handle these correctly. Results are identical at all workbook inputs.
3. **Unused input.** Phase 10 `Inputs` row 11 (eligible share for Contractor B = 0) is not used by any workbook formula. Applicability is taken from `Inputs!B28` = 1.
4. **Colab not tested.** The Colab instructions were written for Colab but could not be executed in Colab. The same commands were run locally, including from a fresh extraction of the ZIP.
5. **Assumptions behind the analysis.** All inputs remain synthetic. The SEC electricity factor is provisional. No feasibility check is validated. The portfolio NPV assumes no interactions between interventions. No result is an investment recommendation.
