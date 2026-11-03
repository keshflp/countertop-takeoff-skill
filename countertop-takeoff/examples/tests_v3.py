# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1", "shapely==2.2.0", "ezdxf==1.4.2"]
# ///
"""V3 acceptance tests: hotel field traps, degradation, dual BoQ, routes.

Run from the skill folder:  uv run examples/tests_v3.py

Covers the V3 regressions on top of tests_v2.py (which keeps 168.75 / 990 /
936 exact):

  hotel fixture (canonical spec from examples/make_hotel_jobs.py)
    - partial completion: room 203 omitted -> coverage callout, 15 SF blank;
      clubroom bar scan unusable -> blank + callout; everything else measured
      (expected ~147 SF measured; GR 16 SF package_excluded separately)
    - identity: wrong duplicate A-301 -> conflict callout; A-305/A-511
      listed in the drawing index but absent -> gap callouts
    - dual-BoQ reconciliation: piece view == assembly view, never summed
    - image schedule evidence: crop hash verified by re-render
  schedule-count invention: 3 -> 30 without resolution is caught by
    plan-tag reconciliation (callout; extension withheld in the
    multiplication path)
  GR package toggle: exclude on/off flips package_excluded <-> measured
  DXF route: unitless refuses (exit 2); --units declares operator-verified
    with warning callout; verified units measure exactly
  individual_rooms: no KeyError crash; grouped rows render
  intake manifest: requested vs resolved, hashes, page counts, mismatch
    verdict; unavailable sources become callouts in measure
  quarantine survives unexpected exceptions; exit codes 0 / 0 / 2

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
from spec_schema import TakeoffError  # noqa: E402

BUILD = os.path.join(SKILL, "build", "test")
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


def run_measure(spec, tag, extra=(), jobs_path=None):
    jobs = jobs_path or os.path.join(BUILD, f"{tag}.jobs.json")
    res = os.path.join(BUILD, f"{tag}.results.json")
    with open(jobs, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=1)
    argv = [jobs, "--json", res, *extra]
    try:
        rc = measure.main(argv)
        return (rc or 0), (json.load(open(res, encoding="utf-8"))
                           if os.path.exists(res) else None), ""
    except TakeoffError as exc:
        return 2, (json.load(open(res, encoding="utf-8"))
                   if os.path.exists(res) else None), str(exc)


def build_hotel():
    """Fixture + geometry + canonical spec, all under BUILD/hotel/."""
    hdir = os.path.join(BUILD, "hotel")
    os.makedirs(hdir, exist_ok=True)
    pdf = os.path.join(hdir, "hotel.pdf")
    geo = os.path.join(hdir, "hotel.geometry.json")
    spec = os.path.join(hdir, "hotel.jobs.json")
    work = os.path.join(hdir, "evidence")
    sh(os.path.join(HERE, "make_fixture.py"), "--case", "hotel",
       "--out", pdf)
    sh(os.path.join(SKILL, "scripts", "extract_geometry.py"), pdf,
       "--pages", "all", "--out", geo)
    sh(os.path.join(HERE, "make_hotel_jobs.py"), "--pdf", pdf,
       "--geometry", geo, "--out", spec, "--workdir", work)
    return json.load(open(spec, encoding="utf-8")), spec


HOTEL_JOBS = os.path.join(BUILD, "hotel", "hotel.jobs.json")


def hotel_tests():
    spec, _ = build_hotel()
    piece_csv = os.path.join(BUILD, "hotel_pieces.csv")
    asm_csv = os.path.join(BUILD, "hotel_asm.csv")
    rc, res, err = run_measure(spec, "hotel", (
        "--piece-csv", piece_csv, "--assembly-csv", asm_csv),
        jobs_path=HOTEL_JOBS)
    check("hotel: exit 0 (complete_with_callouts)", rc == 0, err[:160])
    check("hotel: run status", bool(res) and
          res.get("run_status") == "complete_with_callouts",
          str(res and res.get("run_status")))
    total = res["totals"]["project_sf"]
    check("hotel: measured total ~147 SF (omitted room + bar blank)",
          abs(total - 147.0) < 0.5, str(total))
    callouts = " | ".join(c["scope"] + ": " + c["reason"]
                          for c in res.get("callouts") or [])
    check("hotel: omitted-room 203 callout",
          "room coverage" in callouts and "'203'" in callouts,
          callouts[:200])
    check("hotel: unusable bar scan blank + callout",
          "clubroom:bar" in callouts,
          callouts[:120])
    check("hotel: A-301 wrong duplicate -> conflict callout",
          "identity/conflict" in callouts and "A-301" in callouts)
    check("hotel: missing indexed sheets A-305 + A-511 callouts",
          callouts.count("A-305") >= 1 and callouts.count("A-511") >= 1)
    bar = next(r for r in res["regions"] if r["region_id"] == "clubroom:bar")
    check("hotel: bar quantities BLANK (never zero)",
          bar.get("area_sf") is None and
          bar.get("status") == "unresolved", str(bar.get("area_sf")))
    club = next(r for r in res["regions"]
                if r["region_id"] == "clubroom:counter")
    check("hotel: clubroom image route ~24 SF at 30 px/ft",
          club.get("route") == "image" and club.get("area_sf") is not None
          and abs(club["area_sf"] - 24.0) < 0.5,
          str((club.get("route"), club.get("area_sf"))))
    states = {a["assembly_id"]: a["state"] for a in res["assembly_boq"]}
    check("hotel: GR assemblies package_excluded, others measured",
          states.get("gr-104") == "package_excluded"
          and states.get("gr-206") == "package_excluded"
          and states.get("room-101") == "measured", str(states))
    dual = [i for i in res["audit"]
            if i["check"] == "dual BoQ reconciliation"]
    check("hotel: dual-BoQ reconciliation pass (never summed)",
          dual and dual[0]["status"] == "pass", str(dual[:1]))
    check("hotel: piece + assembly CSVs written",
          os.path.exists(piece_csv) and os.path.exists(asm_csv))
    ledger = json.dumps(res.get("coverage_ledger") or [])
    check("hotel: ledger has package_excluded + unresolved states",
          '"package_excluded"' in ledger and '"unresolved"' in ledger)
    img_ev = res.get("schedule", {}).get("evidence", {})
    check("hotel: image schedule evidence verified (crop hash)",
          img_ev.get("kind") == "image" and bool(img_ev.get("crop_sha256"))
          and any(i["status"] == "pass" and "crop hash verified" in i["detail"]
                  for i in res["audit"]))
    return spec


def invention_tests(hotel_spec):
    """3 -> 30 schedule-count invention: caught by plan-tag reconciliation."""
    # (a) hotel (enumerated): mismatch -> callout + ledger unresolved
    spec = copy.deepcopy(hotel_spec)
    spec["schedule"]["types"][0]["count"] = 30
    rc, res, err = run_measure(spec, "inv_hotel", jobs_path=HOTEL_JOBS)
    callouts = " | ".join(c["reason"] for c in res.get("callouts") or [])
    check("invention 3->30 (hotel): plan-tag mismatch callout",
          rc == 0 and "disagrees with the plan-derived" in callouts,
          callouts[:180])
    ledger = json.dumps(res.get("coverage_ledger") or [])
    check("invention 3->30 (hotel): type A ledger unresolved",
          '"state": "unresolved"' in ledger and "type A x30" in ledger)

    # (b) messy (multiplication path): add a plan-tag inventory of 3 vs the
    # schedule's 10 -> the x10 extension is withheld (blank), total drops
    sys.path.insert(0, HERE)
    import importlib.util
    spec_mod = importlib.util.spec_from_file_location(
        "tv2", os.path.join(HERE, "tests_v2.py"))
    tv2 = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(tv2)
    pdfs = {"messy": os.path.join(BUILD, "messy.pdf")}
    geo = {"messy": os.path.join(BUILD, "messy.geometry.json")}
    base = tv2.spec_messy(pdfs, geo)
    base["schedule"]["room_inventory"] = {
        "rooms": [{"room": f"10{i}", "type": "A", "page": 2}
                  for i in (1, 2, 3)],
        "per_type_counts": {"A": 3, "B": 8},
        "dedupe_notes": ["tags on the type plan"],
        "count_resolutions": {}}
    rc, res, err = run_measure(base, "inv_messy")
    callouts = " | ".join(c["reason"] for c in res.get("callouts") or [])
    check("invention 10-vs-3 (messy): extension withheld with callout",
          rc == 0 and "disagrees with the plan-derived" in callouts
          and abs(res["totals"]["project_sf"] - 440.0) < 1e-9,
          f"rc={rc} total={res and res['totals']['project_sf']}"
          f" callouts={callouts[:160]}")
    # the invented count WITHOUT any inventory still must not pass silently:
    # messy has no tags, so the absence of plan evidence is itself disclosed
    rc, res, err = run_measure(tv2.spec_messy(pdfs, geo), "inv_none")
    items = " | ".join(i["check"] + ": " + i["detail"]
                       for i in res.get("audit", [])
                       if i["check"].startswith("room reconciliation"))
    check("invention guard (messy): unarmed guard disclosed in the audit",
          rc == 0 and "invention" in items
          and "WITHOUT cross-validation" in items,
          f"rc={rc} items={items[:150]}")


def dxf_tests():
    """DXF route: unitless refusal + operator-verified declaration + exact
    measurement from verified units."""
    import ezdxf  # noqa: F401
    dxf_path = os.path.join(BUILD, "cad_smoke.dxf")
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 0  # unitless on purpose
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (120, 0), (120, 30), (0, 30)], close=True)
    doc.saveas(dxf_path)
    import cad_input
    import io
    import contextlib
    err = io.StringIO()
    rc1 = None
    try:
        with contextlib.redirect_stderr(err):
            rc1 = cad_input.main([dxf_path, "--out",
                                  os.path.join(BUILD, "cad.cad.json")])
    except SystemExit as e:
        rc1 = e.code if isinstance(e.code, int) else 1
    check("dxf: unitless refusal exits 2 with guidance",
          rc1 == 2 and "UNITLESS" in err.getvalue(), err.getvalue()[:160])
    rc2 = cad_input.main([dxf_path, "--out",
                          os.path.join(BUILD, "cad.cad.json"),
                          "--units", "in"])
    cad = json.load(open(os.path.join(BUILD, "cad.cad.json"),
                         encoding="utf-8"))
    check("dxf: --units declares operator-verified + warning callout",
          rc2 == 0
          and cad["source"]["units_verified"] is False
          and any("UNITLESS" in c["reason"] for c in cad["callouts"]),
          str(cad["source"]))
    # verified units measure exactly: 120x30 in / 144 = 25.00 SF
    spec = {
        "schema": "countertop-takeoff/v3",
        "sources": [{"source_id": "cad", "path": dxf_path,
                     "sha256": sha256(dxf_path), "kind": "cad"}],
        "geometry": os.path.join(BUILD, "cad.cad.json"),
        "mode": "individual_rooms",
        "policy": {"gross_area": "gross"},
        "scope": {"pages": [{"source_id": "cad", "page": 1,
                             "disposition": "measured",
                             "expected_regions": ["slab:a"]}]},
        "calibrations": [],
        "regions": [{"region_id": "slab:a", "kind": "base", "type": "A",
                     "page": 1, "source_id": "cad", "viewport": "main",
                     "boundary": {"seg_ids": [0, 1, 2, 3]},
                     "seed": [60.0, 15.0],
                     "expected_sf_range": [20, 30]}],
        "_assemblies": [], "_pieces": [],
    }
    rc, res, err = run_measure(spec, "cad_exact")
    got = next((r2 for r2 in (res or {}).get("regions", [])
                if r2["region_id"] == "slab:a"), {})
    area = (got or {}).get("area_sf")
    check("dxf: verified units measure 25.00 SF exactly",
          rc == 0 and area is not None and abs(area - 25.0) < 1e-9,
          f"rc={rc} area={area} err={err[:120]}")
    check("dxf: unitless warning travels into the job callouts",
          any("UNITLESS" in c["reason"] for c in (res or {}).get("callouts", [])),
          str([c["scope"] for c in (res or {}).get("callouts", [])]))


def toggle_and_misc_tests(hotel_spec):
    """GR package toggle: excluded by rule <-> included when the job
    overrides the profile default."""
    spec = copy.deepcopy(hotel_spec)
    spec["policy"]["packages"] = {"exclude": []}
    rc, res, err = run_measure(spec, "hotel_gr_on", jobs_path=HOTEL_JOBS)
    total_on = res["totals"]["project_sf"]
    states = {a["assembly_id"]: a["state"] for a in res["assembly_boq"]}
    check("GR toggle ON: gr measured and counted (+16 SF)",
          rc == 0 and states.get("gr-104") == "measured"
          and abs(total_on - 163.0) < 0.5, f"total={total_on}")
    rc, res, err = run_measure(hotel_spec, "hotel_gr_off",
                               jobs_path=HOTEL_JOBS)
    total_off = res["totals"]["project_sf"]
    states = {a["assembly_id"]: a["state"] for a in res["assembly_boq"]}
    check("GR toggle OFF: gr package_excluded and excluded from totals",
          states.get("gr-104") == "package_excluded"
          and abs(total_off - 147.0) < 0.5, f"total={total_off}")


def individual_rooms_tests():
    """V2 crashed with KeyError 'rows' in reporting; must now complete."""
    sha = sha256(os.path.join(BUILD, "messy.pdf"))
    spec = {
        "schema": "countertop-takeoff/v2",
        "source": {"pdf": os.path.join(BUILD, "messy.pdf"), "sha256": sha},
        "geometry": os.path.join(BUILD, "messy.geometry.json"),
        "mode": "individual_rooms",
        "policy": {"gross_area": "gross"},
        "scope": {"pages": [
            {"page": 1, "disposition": "intentionally_skipped",
             "reason": "schedule sheet"},
            {"page": 2, "disposition": "intentionally_skipped",
             "reason": "superseded"},
            {"page": 5, "disposition": "measured",
             "expected_regions": ["room:kitchen"]},
            {"page": 3, "disposition": "intentionally_skipped",
             "reason": "not in scope"},
            {"page": 4, "disposition": "intentionally_skipped",
             "reason": "not in scope"},
            {"page": 6, "disposition": "intentionally_skipped",
             "reason": "raster"}]},
        "calibrations": [{"page": 5, "viewport": "unit-plan", "spans": [
            {"label": "10'-0\"", "word_ids": [41], "seg_ids": [25]},
            {"label": "6'-0\"", "word_ids": [42], "seg_ids": [28]},
            {"label": "3'-0\"", "word_ids": [43], "seg_ids": [31]}]}],
        "regions": [{"region_id": "room:kitchen", "kind": "base",
                     "type": "ROOM 201", "variant": None, "page": 5,
                     "sheet": "A-201", "viewport": "unit-plan",
                     "boundary": {"seg_ids": [7, 8, 9, 10]},
                     "seed": [630, 160],
                     "expected_sf_range": [20, 30]}]}
    rc, res, err = run_measure(spec, "v3_ir")
    check("individual_rooms: completes with grouped rows (V2 KeyError fix)",
          rc == 0 and res["types"][0]["rows"][0]["region_id"] == "room:kitchen"
          and abs(res["totals"]["project_sf"] - 25.0) < 1e-9,
          f"rc={rc} err={err[:120]}")


def intake_tests():
    """Intake manifest: requested vs resolved, hashes, page counts,
    expected-count verdict; unavailable inputs disclosed downstream."""
    jobdir = os.path.join(BUILD, "intake")
    shutil.rmtree(jobdir, ignore_errors=True)
    src_pdf = os.path.join(BUILD, "hotel", "hotel.pdf")
    r = subprocess.run([sys.executable,
                        os.path.join(SKILL, "scripts", "intake.py"),
                        "--job-dir", jobdir, "--expect", "2",
                        "--source", src_pdf, "--cloud-id", "drvH1",
                        "--cloud-rev", "2",
                        "--source", "drive://plans-latest.pdf"],
                       capture_output=True, text=True, cwd=SKILL)
    manifest = json.load(open(os.path.join(jobdir, "intake_manifest.json"),
                              encoding="utf-8"))
    resolved = [e for e in manifest["sources"]
                if e["status"] == "resolved"]
    unavailable = [e for e in manifest["sources"]
                   if e["status"] == "unavailable"]
    copied = resolved[0]["resolved_path"]
    check("intake: manifest written; source copied into the job dir",
          os.path.isfile(copied) and copied.startswith(
              os.path.abspath(jobdir)))
    check("intake: hash + size + page count recorded",
          len(resolved[0]["sha256"]) == 64
          and resolved[0]["size_bytes"] > 0
          and resolved[0]["page_count"] == 9,
          str({k: resolved[0][k] for k in
               ("size_bytes", "page_count", "cloud_id", "cloud_revision")}))
    check("intake: cloud id/revision recorded",
          resolved[0]["cloud_id"] == "drvH1"
          and resolved[0]["cloud_revision"] == "2")
    check("intake: unfetched Drive name recorded unavailable",
          len(unavailable) == 1 and "fetch" in unavailable[0]["note"])
    check("intake: expected-count mismatch verdict",
          "expected_count_mismatch" in manifest["verdict"])
    # downstream: measure discloses the unavailable source via callouts
    sys.path.insert(0, HERE)
    import importlib.util
    spec_mod = importlib.util.spec_from_file_location(
        "tv2", os.path.join(HERE, "tests_v2.py"))
    tv2 = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(tv2)
    spec = tv2.spec_messy(
        {"messy": os.path.join(BUILD, "messy.pdf")},
        {"messy": os.path.join(BUILD, "messy.geometry.json")})
    shutil.copy(os.path.join(jobdir, "intake_manifest.json"),
                os.path.join(BUILD, "intake_manifest.json"))
    rc, res, err = run_measure(spec, "intake_downstream")
    callouts = " | ".join(c["scope"] + ": " + c["reason"]
                          for c in res.get("callouts") or [])
    check("intake: measure discloses unavailable source + mismatch",
          rc == 0 and "never resolved" in callouts
          and "expected_count_mismatch" in callouts, callouts[:200])
    os.remove(os.path.join(BUILD, "intake_manifest.json"))


def quarantine_and_exit_tests(hotel_spec):
    """Quarantine must survive UNEXPECTED exceptions; exit codes 0/0/2."""
    # a good run first, so a CSV exists
    rc, res, err = run_measure(hotel_spec, "q_survive",
                               ("--csv", os.path.join(BUILD,
                                                      "q_survive.csv")),
                               jobs_path=HOTEL_JOBS)
    good_csv = os.path.join(BUILD, "q_survive.csv")
    check("quarantine: good run wrote the csv", os.path.exists(good_csv))
    # now force an unexpected exception mid-pipeline
    jobs = HOTEL_JOBS
    orig = measure.report_out.build_report

    def boom(*a, **k):
        raise RuntimeError("simulated unexpected crash")
    measure.report_out.build_report = boom
    try:
        rc2, res2, err2 = run_measure(json.load(open(jobs,
                                                    encoding="utf-8")),
                                      "q_survive",
                                      ("--csv", good_csv))
    finally:
        measure.report_out.build_report = orig
    stale = [f for f in os.listdir(BUILD)
             if f.startswith("q_survive.csv.stale-")]
    check("quarantine: unexpected exception -> exit 2 + stale csv renamed",
          rc2 == 2 and not os.path.exists(good_csv) and len(stale) == 1,
          f"rc={rc2} stale={stale} err={err2[:120]}")
    # exit codes through the subprocess contract
    jobs_good = HOTEL_JOBS
    r0 = subprocess.run([sys.executable,
                         os.path.join(SKILL, "scripts", "measure.py"),
                         jobs_good], capture_output=True, text=True,
                        cwd=SKILL)
    bad = copy.deepcopy(json.load(open(jobs_good, encoding="utf-8")))
    bad["sources"][0]["sha256"] = "0" * 64
    jobs_bad = os.path.join(BUILD, "exit2.jobs.json")
    json.dump(bad, open(jobs_bad, "w", encoding="utf-8"))
    r2 = subprocess.run([sys.executable,
                         os.path.join(SKILL, "scripts", "measure.py"),
                         jobs_bad], capture_output=True, text=True,
                        cwd=SKILL)
    check("exit codes: 0 complete_with_callouts, 2 stopped (integrity)",
          r0.returncode == 0 and r2.returncode == 2,
          f"rc0={r0.returncode} rc2={r2.returncode}")


def main():
    shutil.rmtree(BUILD, ignore_errors=True)
    os.makedirs(BUILD, exist_ok=True)
    sh(os.path.join(HERE, "make_fixture.py"), "--case", "messy",
       "--out", os.path.join(BUILD, "messy.pdf"))
    sh(os.path.join(SKILL, "scripts", "extract_geometry.py"),
       os.path.join(BUILD, "messy.pdf"), "--pages", "all",
       "--out", os.path.join(BUILD, "messy.geometry.json"))
    print("messy fixture built.")
    hotel_spec = hotel_tests()
    invention_tests(hotel_spec)
    toggle_and_misc_tests(hotel_spec)
    individual_rooms_tests()
    dxf_tests()
    intake_tests()
    quarantine_and_exit_tests(hotel_spec)
    print()
    failed = [r for r in RESULTS if not r[1]]
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}"
              + (f"  [{detail}]" if detail and not ok else ""))
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
