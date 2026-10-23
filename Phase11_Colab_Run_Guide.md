# Phase 11 — Google Colab Run Guide

Run each block in its own Colab cell, in order. No paid services, API keys or credentials are needed.

## 1. Upload the ZIP

```python
from google.colab import files
uploaded = files.upload()            # choose Workstream_BC_Phase11_Integrated.zip
```

## 2. Extract and enter the project

```python
!unzip -q -o Workstream_BC_Phase11_Integrated.zip -d /content
%cd /content/Workstream_BC
!ls
```

You should see `app.py`, `phase11_tab.py`, the `supplier_*.py` engines, `phase11/`, `workbooks/`, `phase4/` and `outputs/`.

## 3. Install requirements

```python
!pip install -q -r requirements.txt
```

## 4. Run all tests

```python
!python -m pytest -v
```

The expected final line is `170 passed`. To run Phase 11 only: `!python -m pytest -v test_phase11.py` (95 tests).

## 5. Run the engines

```python
!python calc_engine.py               # Workstream B baseline (unchanged)
!python run_workstream_c.py          # Workstream C (unchanged)
!python run_phase11.py               # Phase 11 -> outputs/phase11/
```

`run_phase11.py` prints one recommendation per lane, for example:

```
  L1 OF-A-L1  -> NO DEFENSIBLE RECOMMENDATION YET   [R6] alt=OF-D-L1
  L2 OF-C-L2  -> RETAIN EXISTING SUPPLIER           [R3] alt=None
  L3 OF-A-L3  -> IMPROVE EXISTING SUPPLIER          [R3] alt=None
  L4 OF-B-L4  -> REQUEST BETTER DATA                [R2] alt=None
```

## 6. Open the dashboard

```python
!nohup streamlit run app.py --server.port 8501 --server.headless true > streamlit.log 2>&1 &
import time; time.sleep(8); print(open("streamlit.log").read())
```

**Option A — Colab port proxy:**

```python
from google.colab.output import eval_js
print(eval_js("google.colab.kernel.proxyPort(8501)"))   # click the printed link
```

**Option B — public tunnel (if Option A shows a blank page):**

```python
!curl -s https://ipv4.icanhazip.com        # this IP is the localtunnel "tunnel password"
!npx --yes localtunnel --port 8501         # open the printed https://...loca.lt link
```

Option B makes the dashboard reachable by anyone with the link while the cell runs; stop the cell to close it.

Open the **ninth tab, "Supplier Decision & Engagement"**. Its eight section tabs are Overview · Screening & data
quality · Engagement matrix · Alternatives · Carbon & financial trade-off · Recommendations · Action plans ·
Monitoring & audit.

Things to try:

- **Financial and decision settings** → tick *Management has set a willingness to pay* and enter 600. Lane L1 changes
  to CONSIDER SWITCHING. With 500 it changes to IMPROVE.
- **Engagement matrix** → move the impact threshold to 80. Carrier A moves from Q1 to Q3.
- **Alternatives** → set a weight to a negative number to see the validation error. Open *Edit or add supplier
  offers* to change a cost or add a supplier (session only).
- **Action plans** → change a status. The scorecard in section 8 updates.

## 7. Use your own register (optional)

Download `phase11/Phase11_Supplier_Decision_Assumptions_Register.xlsx`, edit the blue input cells (keep sheet names
and headers), and upload it in the dashboard under *Data source*. Invalid entries appear as validation messages in
section 1. To make the edited register the default, replace the file in `phase11/` and run `!python run_phase11.py`.

## 8. Export results

```python
!zip -q -r results.zip outputs
from google.colab import files
files.download("results.zip")
```

The dashboard also offers a ZIP of all Phase 11 tables (including session edits and a timestamped manifest) in
section 8.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError` | You are not in `/content/Workstream_BC`; re-run `%cd /content/Workstream_BC` |
| Blank page with Option A | Wait 10 s and reload, or use Option B |
| `Address already in use` | `!pkill -f "streamlit run"` in its own cell, then start again |
| Test count differs from 170 | Make sure you extracted the Phase 11 ZIP, not an earlier one |
| Changes to the register not shown | Upload it in *Data source*, or replace the file and restart Streamlit |

These steps were written for Colab but could not be executed from the build environment. The same commands were
run and verified locally (Linux, Python 3.13).
