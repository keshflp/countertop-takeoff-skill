"""Shared runners only; suites own checks, fixtures and result registries."""
import hashlib
import json
import os
import subprocess
import sys

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SKILL, "scripts"))
import measure
from spec_schema import TakeoffError


def sh(*cmd):
    r = subprocess.run([sys.executable, *cmd], capture_output=True,
                       text=True, cwd=SKILL)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd} failed rc={r.returncode}:"
                           f"\n{r.stdout[-800:]}\n{r.stderr[-800:]}")
    return r.stdout


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def run_measure(spec, tag, extra=(), jobs_path=None, *, build, report_csv=False):
    jobs = jobs_path or os.path.join(build, f"{tag}.jobs.json")
    res = os.path.join(build, f"{tag}.results.json")
    with open(jobs, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=1)
    argv = [jobs]
    if report_csv:
        argv += ["--report", os.path.join(build, f"{tag}.report.md"),
                 "--csv", os.path.join(build, f"{tag}.csv")]
    argv += ["--json", res, *extra]
    try:
        rc = measure.main(argv)
        # V2 requires its successful result; later suites permit no payload.
        return (rc or 0), (json.load(open(res, encoding="utf-8"))
                           if report_csv or os.path.exists(res) else None), ""
    except TakeoffError as exc:
        return 2, (json.load(open(res, encoding="utf-8"))
                   if os.path.exists(res) else None), str(exc)
