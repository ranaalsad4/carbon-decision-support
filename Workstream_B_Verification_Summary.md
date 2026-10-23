# Workstream B Verification Summary (v1.1, executed 21 Oct 2026)

Python 3.13.16 · pytest 9.1.1 · streamlit 1.66.1 · plotly 7.1.0 · pandas 3.0.5. Commands run: `python phase4/validate_phase4.py` (exit 0), `python calc_engine.py` (exit 0), `python -m pytest -v`. The dashboard was also launched with `streamlit run app.py` and checked visually. Every number below comes from the generated outputs.

## Emissions (clean data, all tCO2e)

| Rank | Source | Activity | Emissions | Share of quantified total |
|---|---|---|---|---|
| 1 | Grid electricity (Scope 2) | 8,000 MWh | **4,400.000** | 90.5% |
| 2 | Diesel generators (Scope 1) | 100,000 L | 266.155 | 5.5% |
| 3 | Freight, Contractor A (S3 Cat. 4) | 1,200,000 t-km | 121.956 | 2.5% |
| 4 | Freight, Contractor C (S3 Cat. 4) | 700,000 t-km | 71.141 | 1.5% |
| – | Freight, Contractor B (S3 Cat. 4) | missing (12 × NULL) | **UNAVAILABLE** (not 0) | — |
| | Scope 3 Cat. 4 known-data subtotal | 1,900,000 t-km | 193.097 | 4.0% |
| | **Quantified total (indicative, incomplete)** | | **4,859.252** | 100% |

- **Scope totals:** Scope 1 266.155, Scope 2 4,400.000, Scope 3 Cat. 4 193.097 (INCOMPLETE). They sum to 4,859.252, which equals the sum of the source-level outputs.
- **Monthly electricity:** 291.5 tCO2e (Dec) to 442.75 tCO2e (Jul–Aug).
- **Rounding:** shares are shown to 1 decimal, as in the v1.0 engine. Phase 4's summary uses 2 decimals (90.55 / 5.48 / 2.51 / 1.46).

## Mandatory consistency checks

| # | Check | Result |
|---|---|---|
| 1 | Same electricity factor in Phase 3, Phase 4 and Workstream B | ✓ `FAC-ELEC-SEC-01`, 550 kg CO2e/MWh, SEC 2024, location-based, `provisional_proxy`; `phase4/` byte-identical to the Phase 4 v1.1 package |
| 2 | 8,000 MWh → 4,400 tCO2e | ✓ (12 monthly records summed) |
| 3 | Scope 2 recalculated | ✓ 4,400.000 tCO2e |
| 4 | Total recalculated from source-level outputs | ✓ 4,859.252 tCO2e |
| 5 | Percentages reconcile | ✓ 90.5 + 5.5 + 2.5 + 1.5 = 100.0 |
| 6 | Contractor B unquantified | ✓ UNAVAILABLE at record, monthly and source level; never 0 |
| 7 | Scope 1 and 3 activity records unchanged | ✓ quantities identical; diesel and freight results identical to v1.0 |
| 8 | 16 rules operational | ✓ all 16 fire on seeded test data; 22/22 seeded cases PASS |
| 9 | Audit trail preserves factor provenance | ✓ 40 fields, including ID, value, unit, source, title, version, reference year, boundary, scope, method and verification status |
| 10 | Confidence labels follow the criteria | ✓ tested against the unchanged rule |
| 11 | Dashboard and report match outputs | ✓ dashboard renders 4,400.0 / 4,859.3 tCO2e; report tables and Figure 1 are generated from the output CSVs |
| 12 | No old electricity results in active outputs | ✓ no `FAC-ELE-GRID-01`, `614.2` or `4913.6` in `outputs/` (tested) |
| 13 | Python tests rerun | ✓ **50/50 passed** (15 Workstream B + 35 Phase 4); previously 43 |
| 14 | Reproducibility rerun | ✓ two clean runs gave identical SHA-256 output hashes; input hashes match the Phase 4 files |
| 15 | Failures or warnings disclosed | No failures. Expected warnings are listed below. |

## Data-quality validation (Phase 5 engine = Phase 4 validator, issue-level output in `phase4/validation_report.csv`)

- **Clean data (60 records):** 0 BLOCK, 72 WARN, all expected.
  - 12 × DQ-01: Contractor B missing.
  - 60 × DQ-13: factor warnings. The 12 electricity warnings give reference year 2024 vs 2025 and `provisional_proxy`; the 48 others are UK proxies and EF1/EF3 verification status.
- **Test data (63 records):** 18 BLOCK, 79 WARN. All 16 rules fire, and all 22 seeded cases are detected with the expected severity.
- **Factor checks:** availability (DQ-08), unit compatibility (DQ-09), activity matching, boundary and attributes (DQ-13), and register checks for source, year, scope and method all pass for the clean data.

## Confidence labels

| Source | C1 | C2 | C3 | C4 | C5 | C6 | Label |
|---|---|---|---|---|---|---|---|
| Diesel generators | Met | Met | Partial | Met | Partial | Met | MODERATE |
| Grid electricity | Met | **Partial** (2024) | Met | Met | **Not met** (provisional) | Met | **MODERATE** (was LOW) |
| Freight A / C | Met | Met | Partial | Met | Not met | Partial | LOW |
| Freight B | Not met | Met | Partial | Met | Not met | Partial | NOT QUANTIFIED |

- **Coverage:** record completeness is 48/60 = 80%. Emissions coverage is 4/5 sources and 2/3 carriers; the share of the true total is unknown.

## Unresolved limitations and disclosures

1. **The SEC factor is unverified.** The published value, unit, MWh basis and national-grid representativeness have not been confirmed against the primary SEC 2024 report, so it remains `provisional_proxy`.
2. **Year mismatch:** the 2024 factor is applied to 2025 activity.
3. **UK proxies:** the diesel and freight factors still need checking against the DESNZ workbook. The freight factor is direct (tank-to-wheel) only.
4. **Incomplete total:** Contractor B is missing, so Scope 3 Cat. 4 and the total are incomplete.
5. **Synthetic data:** all activity data is synthetic.
6. **Package rebuilt from loose files.** The original Workstream B ZIP was not supplied, so the package was rebuilt from the individual files provided, using the README layout. The v1.0 `outputs/` folder was not available for comparison, so v1.0 values are taken from the v1.0 report.
7. **Phase 5 naming:** Phase 5 has no separate module. As in v1.0, the data-quality engine is the Phase 4 validator, which `calc_engine.py` reuses.
