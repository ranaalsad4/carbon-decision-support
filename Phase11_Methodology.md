# Phase 11 — Supplier Decision & Engagement: Methodology

**Objective.** Evaluate freight suppliers using comparable carbon, financial, operational and data-quality evidence;
identify supplier engagement priorities; and support transparent decisions to retain, improve, consider switching
or request additional information.

**Status.** This is a synthetic demonstration for a fictional facility (Riyadh Region, reporting year 2025). Supplier
names, costs, reliability, emission factors and evidence statuses are illustrative assumptions recorded in
`phase11/Phase11_Supplier_Decision_Assumptions_Register.xlsx`. They are not real supplier records, quotations or
verification certificates. The engagement-matrix scores, thresholds and weights and the scoring weights are
**project-designed assumptions, not official UN rules**.

---

## 1. Scope and boundaries

| Item | Treatment |
|---|---|
| Emissions category | GHG Protocol Scope 3 Category 4 (downstream road freight paid by the company), as in Workstream B |
| Boundary | Tank-to-wheel, CO₂e — the inventory convention (Phase 4 factor `FAC-FRT-ROAD-01`, 0.10163 kgCO₂e/t-km) |
| Inventory baseline | Read-only from `calc_engine.py`: Contractor A 121.956 t, Contractor C 71.141 t, Contractor B **UNAVAILABLE** |
| Decision basis | Each lane's own factor (supplier-specific where documented, otherwise the inventory proxy) |
| Prospective suppliers | Offers only. No historical activity is invented, and they are never added to the inventory |

**Two bases, kept apart.** Lane L1 (Contractor A, Riyadh → Dammam, 1.0 million t-km) has a documented but unverified
supplier-specific factor of 0.12 kgCO₂e/t-km. The inventory uses the 0.10163 proxy. The 18.37 t difference is a
**methodology difference, not a reduction**, so the inventory is never restated by Phase 11.

## 2. Data model (register, 15 sheets)

README · Supplier Profiles · Freight Activity · Emission Factors · Service Equivalence · Financial Inputs ·
Screening Evidence · Supplier Maturity · Engagement Matrix Rules · Scoring Weights · Uncertainty Assumptions ·
Engagement Action Plans · Monitoring Indicators · Source Register · Validation Cases.

Each data row carries a data class (Existing synthetic baseline / New synthetic assumption / User-entered /
Calculated output / Missing). Dropdowns restrict statuses. Lanes L1–L3 reproduce the inventory activity: Contractor A
L1 1.0M + L3 0.2M = 1.2M t-km, and Contractor C L2 0.7M t-km. Contractor B's lane L4 has no data.

The loader validates the following and reports each problem as a validation message instead of failing silently:

- duplicate IDs
- unknown references
- unsupported modes
- invalid units, non-numeric values, and negative or zero activity
- percentages above 100
- maturity values above 4
- invalid data-quality labels

## 3. Screening (14 checks) and eligibility

| No. | Check | Type |
|---|---|---|
| 1–2 | Supplier identity · legal and transport safety | Gate (evidence) |
| 3–10 | Capacity · route and specification · mass and distance · reporting period · method · factor source and unit · boundary · cost | **Derived automatically** from offer data |
| 11 | Supporting evidence | Material (evidence) |
| 12 | Third-party verification | Enhancement; becomes mandatory only if the policy switch is on |
| 13–14 | Historical completeness · willingness to improve disclosure | Enhancement |

Eligibility is assigned in this order:

1. A failed gate, capacity or route check makes the offer **Ineligible**.
2. Missing material information (activity, period, method, factor, cost, evidence) makes it **Insufficient evidence**.
3. Otherwise:
   - a boundary mismatch makes it **Conditionally eligible** and not carbon-comparable;
   - missing verification makes it **Conditionally eligible** (or **Insufficient evidence** if verification is mandatory);
   - enhancement gaps make it **Conditionally eligible**.
4. An offer with none of these issues is **Eligible**.

**Eligibility overrides any weighted score.**

## 4. Data quality (7 dimensions)

The seven dimensions are:

- completeness
- temporal representativeness
- geographic representativeness
- technological representativeness
- methodological consistency
- evidence and provenance
- verification status

Each is rated High 100 / Medium 60 / Low 20 / Missing 0, and the supplier score is their mean. An unverified but
documented estimate stays usable with its uncertainty. Missing data is never treated as zero.

## 5. Engagement priority matrix

The UN Global Compact approach segments suppliers by impact and maturity into qualitative priorities. Phase 11
makes this numeric using **project-designed, editable** rules:

- **Impact (0–100)** = 0.5 × share of known freight emissions × 100 + 0.3 × share of known tonne-km × 100 + 0.2 ×
  materiality (Critical 100 / Standard 50 / Minor 0).
- **Maturity (0–100)** = mean of the assessed indicators (0–4) ÷ 4 × 100, provided at least 5 of the 7 are assessed.
  The indicators are measurement, data completeness, transparency, targets, reporting, verification and responsiveness.
- **Thresholds** are 50 / 50 and editable. The quadrants are:

| Quadrant | Impact | Maturity | Priority |
|---|---|---|---|
| Q1 | High | Low | Priority 1 — intensive engagement |
| Q2 | High | High | Priority 2 — strategic collaboration |
| Q3 | Low | Low | Priority 3 — basic development |
| Q4 | Low | High | Priority 4 — maintain and monitor |

- If impact or maturity cannot be assessed, the supplier is **Unclassified — insufficient evidence**. Contractor B is
  unclassified. A labelled sensitivity can be switched on that uses a hypothetical 200 tCO₂e/yr from the Phase 10
  workbook. It changes only B's impact score, and B stays unclassified because only 3 of its 7 maturity indicators
  are assessed.
- The matrix sets **engagement priority only and never triggers replacement**.

Results: A 70.5 / 39.3 → Q1 Priority 1 · C 39.5 / 67.9 → Q4 Priority 4 · B Unclassified.

## 6. Carbon comparison

Functional unit: **tonne-km of the same lane service** (same origin, destination, cargo and period). The equations are:

```
emissions_t = tonne_km × EF (kgCO₂e/t-km) ÷ 1,000
avoided_t   = (current EF − alternative EF) × substituted tonne-km ÷ 1,000
reduction % = avoided ÷ current emissions of the substituted service
substituted tonne-km = lane tonne-km × substitution share   (partial substitution, 0 < share ≤ 1)
```

The following make a comparison invalid, and each is shown as a limitation rather than a result:

- different lanes, boundaries, gas coverage or units
- a missing factor
- insufficient capacity or volume

Factors given in g or t per tonne-km are normalised to kg.

## 7. Switching finance (reuses the Phase 9 cash-flow engine)

```
annual cost difference = alternative annual cost + recurring cost − current annual cost   (+ = alternative costs more)
NPV  = −one-time costs + (current − alternative − recurring) × annuity factor(rate, delay, horizon)
annual cost per tCO₂e             = annual cost difference ÷ annual avoided t      (excludes one-time costs)
discounted lifetime cost per tCO₂e = net present cost ÷ (annual avoided t × annuity factor)
break-even alternative annual cost = current − recurring − one-time ÷ annuity factor
```

One-time costs comprise switching, onboarding and incumbent exit. The defaults are 5% real over 10 years
(Phase 9 workbook). **A negative NPV is not an automatic rejection**: it is the price of the reduction, and it is
compared with a management willingness to pay. That value is not set in the register.

Demo (A vs D on L1):

| Metric | Value |
|---|---|
| Emissions, current → alternative | 120 → 80 t |
| Avoided | 40 t (33.33%) |
| Annual cost difference | +SAR 20,000/yr |
| Annual cost per tCO₂e | SAR 500 |
| NPV | −SAR 184,434.70 |
| Discounted lifetime cost | SAR 597.13/tCO₂e |
| Break-even alternative annual cost | SAR 296,114.86 |

The brief quoted an NPV of "≈ −184,443". The exact closed-form value, also given by Excel's PV function in the
register, is **−184,434.70**.

## 8. Weighted scoring (supporting evidence only)

Default weights are carbon 35 / lifecycle cost 25 / reliability 20 / data quality 15 / improvement 5. They are
illustrative and user-adjustable. They must be numeric and non-negative, and are normalised to 100%. The criteria
are:

- **Carbon** = 100 × (0.15 − EF) ÷ (0.15 − 0.05).
- **Cost** = 50 + 50 × (incumbent − offer annualised cost) ÷ (20% × incumbent). One-time costs are annualised.
- **Reliability** = 100 × (on-time − 90) ÷ 10.
- **Data quality** = the section 4 score.
- **Improvement** = (targets + responsiveness) ÷ 8 × 100.

All criteria are clamped to 0–100. A missing mandatory input gives **no total** (never zero) and **suppresses** the
definitive ranking. Ineligible and insufficient-evidence offers are shown for transparency but never ranked.

Lane L1 results:

| Offer | Score | Status |
|---|---|---|
| D | 56.20 | Rank 1 |
| A | 44.96 | Rank 2 |
| E | 66.84 | Ineligible (safety gate failed), not ranked |

Weight sensitivity: below a carbon weight of 10% the top offer becomes A. A cost weight of 60% also puts A first.

## 9. Recommendation hierarchy (project-designed)

The hierarchy applies these steps in order:

1. Legal and safety
2. Evidence sufficiency
3. Service equivalence and alternative eligibility
4. Comparable carbon and cost
5. Operational risk
6. Uncertainty
7. Conditional recommendation

| Rule | Condition | Action |
|---|---|---|
| R1 | Incumbent fails a gate | INELIGIBLE / ESCALATE |
| R2 | Incumbent evidence insufficient | REQUEST BETTER DATA |
| R3 / R4 | No viable or lower-emission alternative | IMPROVE (Priority 1/3 or unclassified) or RETAIN |
| R5 | Lower emissions and NPV ≥ 0, robust carbon benefit | CONSIDER SWITCHING |
| R5u / R7u | As R5 / R7 but carbon benefit not robust across joint cases | NO DEFENSIBLE RECOMMENDATION YET |
| R6 | Lower emissions, NPV < 0, no willingness to pay set | NO DEFENSIBLE RECOMMENDATION YET |
| R7 | Lower emissions, NPV < 0, lifetime cost per tonne ≤ willingness to pay | CONSIDER SWITCHING |
| R8 | Lower emissions, cost per tonne > willingness to pay | IMPROVE / RETAIN |
| R9 | Higher emissions but NPV > 0 (financial-only gain) | NO DEFENSIBLE RECOMMENDATION YET |

Each recommendation carries:

- supporting evidence and material assumptions
- carbon, financial and operational implications
- data-quality limitations and excluded alternatives
- sensitivity and robustness
- next steps
- a human-approval flag

CONSIDER SWITCHING, ESCALATE and NO DEFENSIBLE always require human approval. **No recommendation awards a contract
or certifies a supplier as sustainable.**

Default results:

| Lane | Recommendation | Rule |
|---|---|---|
| L1 | NO DEFENSIBLE RECOMMENDATION YET | R6 |
| L2 | RETAIN | R3 |
| L3 | IMPROVE | R3 |
| L4 | REQUEST BETTER DATA | R2 |

With a willingness to pay of SAR 600/t, L1 becomes CONSIDER SWITCHING (R7). With SAR 500/t it becomes IMPROVE (R8).

## 10. Uncertainty (stress values, not probabilities)

The register gives low / base / high values for these variables:

| Variable | Low / base / high |
|---|---|
| Alternative EF | 0.06 / 0.08 / 0.10 |
| Current EF | 0.11 / 0.12 / 0.13 |
| Demand | 0.9 / 1.0 / 1.1 M t-km |
| Alternative cost | 290 / 320 / 350 k |
| Switching cost | 15 / 30 / 60 k |
| Monitoring cost | 0 / 0 / 10 k |
| Delay | 0 / 0 / 1 year |
| Alternative on-time | 95 / 97 / 98% |

The analysis includes:

- **One-way tests.**
- **Joint cases**, with every variable set in its unfavourable or favourable direction:

| Case | Avoided (t/yr) | NPV (SAR) |
|---|---|---|
| Unfavourable | 10 | −523,304 |
| Base | 40 | −184,435 |
| Favourable | 70 | +62,217 |

- **Break-evens:**
  - financial: alternative cost SAR 296,115
  - carbon: alternative EF 0.12
  - willingness to pay needed: SAR 597.13/t
- **A two-variable grid** of EF × cost.
- **Ranking reversals.**
- **Recommendation robustness.** The L1 recommendation is not robust: at an alternative cost of SAR 290,000 it
  becomes CONSIDER SWITCHING.

## 11. Double-counting control (shared activity ledger)

Workstream C's freight optimisation (15%, Phase 8) and supplier switching act on the same tonne-km. The ledger
applies both to each incumbent row jointly:

```
combined emissions = activity × (1 − efficiency) × [(1 − share) × current EF + share × alternative EF] ÷ 1,000
```

Rules:

- The baseline is never rewritten.
- Contractor B's row is UNAVAILABLE and is excluded from every total.
- The Scope 3 Category 4 boundary is unchanged.

| Basis | Baseline | Efficiency | Switching | Combined | Overlap removed |
|---|---|---|---|---|---|
| Inventory (proxy) | 193.097 | 28.965 (= Workstream C) | 21.630 | 47.350 | 3.244 |
| Decision (lane factors) | 211.467 | 31.720 | 40.000 | 65.720 | 6.000 |

## 12. Engagement actions, monitoring and audit

Action plans are generated from register templates by quadrant. Further templates are triggered by a verification
gap, an ineligible offer, or an unclassified supplier (B: 5 default data requests). Each action has:

- a responsible role
- a deadline of 30 / 60 / 90 days — an **editable management assumption, not a UN requirement**
- required evidence
- a success indicator
- a status, editable in the session without changing the inventory
- a follow-up date (+14 days)
- a verification method

The monitoring scorecard separates **projected** reductions from **verified actual** reductions. The verified values
are "none — no post-implementation data".

Each audit record contains:

- input version (register SHA-256)
- engine version
- supplier and offer IDs
- source, period and method
- emission factor and its verification status, exactly as recorded
- assumptions
- the rule triggered and the lane action
- evidence status

No verification certificates or audit findings are invented.

## 13. Sources (register sheet "Source Register")

| ID | Source | Used for | Does NOT establish | Access |
|---|---|---|---|---|
| S1 | UN Global Compact, *Sustainable Procurement Implementation Framework* | Procurement cycle; impact × maturity segmentation into Priorities 1–4 | Numeric weights, thresholds or scores | Page opened 2026-10-23 |
| S2 | UN Global Compact, *GHG Emissions Data Management* | Data requests, data-quality progression, verification, scorecards | Project thresholds or deadlines | Page opened 2026-10-23 |
| S3 | UN Global Compact, *GHG Emissions Reduction* | Selection criteria, capacity building, audits, corrective action plans | Switching rules or carbon prices | Page opened 2026-10-23 |
| S4 | GHG Protocol, *Scope 3 Standard* (2011) | Scope 3 boundary; Category 4 classification | Supplier selection decisions | Landing page opened |
| S5 | GHG Protocol, *Technical Guidance for Calculating Scope 3 Emissions* | Category 4 fuel/distance/spend methods (cited in Phase 3) | The supplier-specific factors used here | Landing page; method chapter via Phase 3 |
| S6 | Phase 4 emission-factor library (`FAC-FRT-ROAD-01`, DESNZ 2025 UK proxy) | Proxy factor for lanes without supplier data | Saudi supplier-specific performance | In package |
| S7 | Phase 9 workbook | 5% real discount rate, 10-year horizon | A Saudi corporate hurdle rate | In package |

No other standard (for example GLEC or ISO 14083) was consulted for Phase 11, so none is cited.
