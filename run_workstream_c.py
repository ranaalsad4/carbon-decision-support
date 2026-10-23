"""Run Workstream C (Phases 8-10) end to end and write a reproducibility manifest.

    python run_workstream_c.py          # writes outputs/workstream_c/* and run_manifest_c.json

The Workstream B engine (python calc_engine.py) is independent and keeps its own manifest
in outputs/run_manifest.json. Re-running with identical inputs reproduces identical hashes.
"""
import hashlib
import json
import sys
from pathlib import Path

import calc_engine as ce
import financial_engine as fe
import scenario_engine as se
import uncertainty_engine as ue
import workstream_c_inputs as wi

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs" / "workstream_c"


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main(out_dir=None):
    out = Path(out_dir) if out_dir else OUT
    out.mkdir(parents=True, exist_ok=True)
    print("== Phase 8 scenarios")
    se.main(out)
    print("== Phase 9 financial evaluation")
    fin = fe.main(out)
    print("== Phase 10 uncertainty analysis")
    unc = ue.main(out)
    ctx = unc["ctx"]
    se.write_csv(out / "workbook_consistency_checks.csv", ctx["checks"])
    recon = (fe.reconciliation(fin["results"], fin["p9"]) + unc["cases_recon"] + unc["switching_recon"]
             + unc["missing_recon"])
    bad = [r for r in recon if r["status"] != "MATCH"]
    mism = [c for c in ctx["checks"] if c["status"] == "MISMATCH"]
    files = sorted(p for p in out.iterdir() if p.is_file() and p.name != "run_manifest_c.json")
    manifest = {
        "engine_versions": {"scenario": se.ENGINE_VERSION, "financial": fe.ENGINE_VERSION,
                            "uncertainty": ue.ENGINE_VERSION, "workstream_b": ce.ENGINE_VERSION},
        "inputs": {**{p.name: sha256(p) for p in wi.WORKBOOKS.values()},
                   **{f"phase4/data/{n}": sha256(ce.PHASE4 / "data" / n) for n in ce.INPUT_FILES}},
        "outputs": {p.name: sha256(p) for p in files},
        "reconciliation": {"checks": len(recon), "not_matching": len(bad)},
        "workbook_consistency": {"checks": len(ctx["checks"]), "mismatches": len(mism),
                                 "notes": sum(c["status"] == "NOTE" for c in ctx["checks"])},
        "quantified_baseline_tco2e": ctx["quantified_total"],
        "note": "Synthetic demonstration. Re-running with identical inputs must reproduce identical output hashes.",
    }
    (out / "run_manifest_c.json").write_text(json.dumps(manifest, indent=2))
    print(f"== Reconciliation vs workbooks: {len(recon) - len(bad)}/{len(recon)} match; "
          f"consistency mismatches: {len(mism)}")
    print("Outputs written to", out)
    return 0 if not bad and not mism else 1


if __name__ == "__main__":
    sys.exit(main())
