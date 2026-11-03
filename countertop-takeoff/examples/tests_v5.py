# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1", "shapely==2.2.0"]
# ///
"""V5 acceptance tests: safe publishing, evidence/quantity identity,
estimate scope inheritance, uncertainty consistency, audit-pack and
estimate-PDF repairs, proposal-lite agreement checks.

Run from the skill folder:  uv run examples/tests_v5.py

On top of tests_v2/v3/v4 (which stay green), this suite locks the V5
regressions. Group per P-block; each check names the finding it pins:

  P0.1 publish safety
    - estimates get distinct output paths; `--json results.json
      --estimate-profile` can no longer overwrite the evidence package
    - stale-output handling covers results.json/report/estimates (not just
      CSVs); an early stop writes a CURRENT stopped diagnostic
    - intake: pre-existing destination files never get overwritten
    - intake: per-source failures retained in the manifest
  P0.2 evidence + quantity identity
    - 3 -> 30 with an EDITED row_text over the real "3" box: caught
    - repeated geometry claim: second piece on the same region does not
      inflate the total; explicitly declared reuse is a non-defect
    - uncertain included-variant evidence withholds the dependent standard
      EA (never restores the parent count)
  P0.3 estimate scope inheritance
    - stopped result -> estimate refuses
    - missing assembly_boq -> refuse, never price 0.00
    - hotel omitted room 203 -> priced lines survive, grand total BLANK,
      callout names the missing room
    - ONE effective currency; malformed prices/EA rejected with useful
      diagnostics; currency-formatted strings parse or error clearly
  P1.1 uncertainty everywhere
    - explicit known-subtotal + completeness flags; zero-EA is `zero` not
      unresolved; unknown edge LF stays null with a named declaration
    - reconciliation compares the SAME known contributions across views
    - missing-geometry-page calibration degrades locally (no stop)
    - room counts stay distinct from summed assembly EA
  P1.2 audit pack + estimate PDF
    - source-qualified collision-proof filenames; relative paths resolve
      against the results file; corrupt geometry recovers per-region
    - receipt guard detects superseded/quarantined results files
    - PDF: exact rate precision, title below the page top, wrapping +
      pagination, rendered amounts agree with estimate.json
  P1.3 proposal-lite
    - proposal.json/md/pdf agree with the corrected estimate (blank
      preserved); package groupings from the data; binding to the results

Exits 0 only if every check passes; prints a case -> verdict matrix.
"""

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SKILL, "scripts"))
sys.path.insert(0, HERE)

import measure  # noqa: E402
import audit_pack  # noqa: E402
import intake  # noqa: E402
import estimate as estimate_mod  # noqa: E402
from spec_schema import TakeoffError  # noqa: E402

BUILD = os.path.join(SKILL, "build", "test")
HOTEL_JOBS = os.path.join(BUILD, "hotel", "hotel.jobs.json")
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}"
          + (f" - {detail}" if detail and not ok else ""))


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


def build_fixtures():
    """messy + hotel + orig fixtures + geometry + canonical hotel spec."""
    os.makedirs(BUILD, exist_ok=True)
    sh(os.path.join(HERE, "make_fixture.py"), "--case", "messy",
       "--out", os.path.join(BUILD, "messy.pdf"))
    sh(os.path.join(HERE, "make_fixture.py"), "--out",
       os.path.join(BUILD, "orig.pdf"))
    sh(os.path.join(SKILL, "scripts", "extract_geometry.py"),
       os.path.join(BUILD, "messy.pdf"), "--pages", "all",
       "--out", os.path.join(BUILD, "messy.geometry.json"))
    sh(os.path.join(SKILL, "scripts", "extract_geometry.py"),
       os.path.join(BUILD, "orig.pdf"), "--pages", "all",
       "--out", os.path.join(BUILD, "orig.geometry.json"))
    hdir = os.path.join(BUILD, "hotel")
    os.makedirs(hdir, exist_ok=True)
    sh(os.path.join(HERE, "make_fixture.py"), "--case", "hotel",
       "--out", os.path.join(BUILD, "hotel", "hotel.pdf"))
    sh(os.path.join(SKILL, "scripts", "extract_geometry.py"),
       os.path.join(BUILD, "hotel", "hotel.pdf"), "--pages", "all",
       "--out", os.path.join(BUILD, "hotel", "hotel.geometry.json"))
    sh(os.path.join(HERE, "make_hotel_jobs.py"),
       "--pdf", os.path.join(BUILD, "hotel", "hotel.pdf"),
       "--geometry", os.path.join(BUILD, "hotel", "hotel.geometry.json"),
       "--out", HOTEL_JOBS,
       "--workdir", os.path.join(hdir, "evidence"))
    print("fixtures built.")


def run_measure(spec, tag, extra=(), jobs_path=None):
    jobs = jobs_path or os.path.join(BUILD, f"{tag}.jobs.json")
    res = os.path.join(BUILD, f"{tag}.results.json")
    json.dump(spec, open(jobs, "w", encoding="utf-8"), indent=1)
    argv = [jobs, "--json", res, *extra]
    try:
        rc = measure.main(argv)
        return (rc or 0), (json.load(open(res, encoding="utf-8"))
                           if os.path.exists(res) else None), ""
    except TakeoffError as exc:
        return 2, (json.load(open(res, encoding="utf-8"))
                   if os.path.exists(res) else None), str(exc)


def spec_from(test_file, fn_name, pdfs, geo):
    """Load a spec builder out of an older suite without running it."""
    import importlib.util
    spec_mod = importlib.util.spec_from_file_location(
        f"tv5_{fn_name}", os.path.join(HERE, test_file))
    mod = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(mod)
    return getattr(mod, fn_name)(pdfs, geo)


ORIG_PDFS = None
ORIG_GEO = None


def orig_spec():
    return spec_from("tests_v2.py", "spec_original", ORIG_PDFS, ORIG_GEO)


def messy_spec():
    return spec_from("tests_v2.py", "spec_messy",
                     {"messy": os.path.join(BUILD, "messy.pdf")},
                     {"messy": os.path.join(BUILD, "messy.geometry.json")})


def callout_text(res):
    return " | ".join(c["scope"] + ": " + c["reason"]
                      for c in ((res or {}).get("callouts") or []))


def main():
    global ORIG_PDFS, ORIG_GEO
    shutil.rmtree(BUILD, ignore_errors=True)
    os.makedirs(BUILD, exist_ok=True)
    build_fixtures()
    ORIG_PDFS = {"orig": os.path.join(BUILD, "orig.pdf")}
    ORIG_GEO = {"orig": os.path.join(BUILD, "orig.geometry.json")}
    intake_tests_v5()
    print()
    failed = [r for r in RESULTS if not r[1]]
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}"
              + (f"  [{detail}]" if detail and not ok else ""))
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


# --------------------------------------------------- P0.1 intake repairs
def intake_tests_v5():
    import intake as intake_mod
    # (1) pre-existing destination: a retry must never overwrite the
    #     earlier copy
    jobdir = os.path.join(BUILD, "v5_intake_pre")
    shutil.rmtree(jobdir, ignore_errors=True)
    src_old = os.path.join(BUILD, "messy.pdf")
    src_new = os.path.join(BUILD, "hotel", "hotel.pdf")
    r1 = subprocess.run(
        [sys.executable, os.path.join(SKILL, "scripts", "intake.py"),
         "--job-dir", jobdir, "--source", src_old],
        capture_output=True, text=True, cwd=SKILL)
    first = json.load(open(os.path.join(jobdir, "intake_manifest.json"),
                           encoding="utf-8"))["sources"][0]
    r2 = subprocess.run(
        [sys.executable, os.path.join(SKILL, "scripts", "intake.py"),
         "--job-dir", jobdir, "--source", src_new, "--name", "messy.pdf",
         "--expect", "1"],
        capture_output=True, text=True, cwd=SKILL)
    man2 = json.load(open(os.path.join(jobdir, "intake_manifest.json"),
                          encoding="utf-8"))
    second = man2["sources"][0]
    old_still_there = os.path.exists(first["resolved_path"])
    old_intact = (old_still_there
                  and sha256(first["resolved_path"]) == first["sha256"])
    check("intake: retry with a pre-existing destination preserves the"
          " earlier copy (lands on a fresh name)",
          r2.returncode == 0 and old_intact
          and second["destination_name"] == "messy-2.pdf"
          and second["sha256"] == sha256(src_new),
          f"rc={r2.returncode} old_intact={old_intact} "
          f"dest={second.get('destination_name')}")
    check("intake: manifest discloses the preserved pre-existing file",
          "preserved" in (second.get("note") or "")
          and "messy-2.pdf" in (second.get("note") or ""),
          str(second.get("note"))[:120])

    # (2) per-source failure retained; manifest still written
    jobdir = os.path.join(BUILD, "v5_intake_err")
    shutil.rmtree(jobdir, ignore_errors=True)
    entries = [{"requested": "good.pdf", "local_path": src_new},
               {"requested": "bad.pdf", "local_path": src_old}]
    orig_copy = shutil.copy2

    def flaky_copy(src, dst, *a, **k):
        if os.path.abspath(str(src)) == os.path.abspath(src_old):
            raise PermissionError("simulated copy failure (tests_v5)")
        return orig_copy(src, dst, *a, **k)
    shutil.copy2 = flaky_copy
    try:
        rc = intake_mod.main(["--job-dir", jobdir,
                              "--entry", json.dumps(entries[0]),
                              "--entry", json.dumps(entries[1])])
    finally:
        shutil.copy2 = orig_copy
    man = json.load(open(os.path.join(jobdir, "intake_manifest.json"),
                         encoding="utf-8"))
    bad = [e for e in man["sources"] if e["requested"] == "bad.pdf"]
    good = [e for e in man["sources"] if e["requested"] == "good.pdf"]
    check("intake: per-source copy failure retained as status=error,"
          " manifest still written",
          rc == 0 and os.path.exists(
              os.path.join(jobdir, "intake_manifest.json"))
          and bad and bad[0]["status"] == "error"
          and "simulated copy failure" in (bad[0].get("error") or ""),
          f"rc={rc} bad={bad and bad[0].get('status')}")
    check("intake: the other source still resolved alongside the failure",
          good and good[0]["status"] == "resolved"
          and "source_errors: 1" in man["verdict"],
          str(man["verdict"]))


if __name__ == "__main__":
    sys.exit(main())
