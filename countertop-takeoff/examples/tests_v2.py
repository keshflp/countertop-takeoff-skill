# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1", "shapely==2.2.0"]
# ///
"""V2 acceptance tests: exact numbers, safe exports, refusal behavior.

Run from the skill folder:  uv run examples/tests_v2.py

Builds both fixtures into build/test/, measures them with dynamically-built
V2 job specs (source digest computed at runtime), and asserts:

  positive
    - original fixture: 168.75 SF exactly, factor 18, status complete, exit 0
    - messy gross:      990.00 SF exactly (per-viewport factors 18 / 9),
                        ADA variant allocated without double-counting,
                        CSV grand total 990.00, exit 0
    - messy net:        declared B sink cutout subtracted -> 966.00, exit 0
    - CSV shape: base rows carry the extension; recheck rows never extended;
                 one totals row per type + grand total
    - audit pack: PNG overlays exist for every passing case; receipt records
  degradation (V3 graduated degradation replaces V2 whole-job refusals;
  each case exits 0 with status complete_with_callouts, blanks the affected
  quantities, and names them in CALLOUTS - replacements listed inline)
    - unresolved scan page, unresolved revision, single-span calibration,
      hatch contamination, open boundary, seed on boundary, missing type,
      missing region, wrong calibration (range breach), stated-total
      mismatch
  refusal (structural / catastrophic stops - still exit 2)
    - duplicate region, invalid count, negative count, empty measured page,
      source-hash mismatch (integrity stop)

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


# ------------------------------------------------------------ spec builders
def spec_original(pdfs, geo):
    sha = sha256(pdfs["orig"])
    return {
        "schema": "countertop-takeoff/v2",
        "source": {"pdf": pdfs["orig"], "sha256": sha},
        "geometry": geo["orig"],
        "mode": "repeated_types",
        "policy": {"gross_area": "gross", "declarations": [
            {"kind": "plan_spec_conflict",
             "detail": "notes say 25 in. deep; plans dimension 30 in."}]},
        "schedule": {"page": 1, "sheet": "A-001",
            "types": [
                {"type": "A", "count": 3, "row_text": "A | 1 BED / 1 BATH | 3",
                 "word_boxes": [{"t": "3", "x0": 377.498, "y0": 218.325,
                                 "x1": 382.502, "y1": 230.691}]},
                {"type": "B", "count": 2, "row_text": "B | 2 BED / 2 BATH | 2",
                 "word_boxes": [{"t": "2", "x0": 377.498, "y0": 246.325,
                                 "x1": 382.502, "y1": 258.691}]}],
            "variants": [],
            "stated_totals": {"project": 5}},
        "scope": {"pages": [
            {"page": 1, "sheet": "A-001", "disposition": "intentionally_skipped",
             "reason": "schedule sheet"},
            {"page": 2, "sheet": "A-101", "disposition": "measured",
             "expected_regions": ["A:kitchen", "A:vanity"]},
            {"page": 3, "sheet": "A-102", "disposition": "measured",
             "expected_regions": ["B:kitchen", "B:vanity"]}]},
        "calibrations": [
            {"page": 2, "viewport": "main", "spans": [
                {"label": "10'-0\"", "word_ids": [29], "seg_ids": [14]},
                {"label": "2'-6\"", "word_ids": [30], "seg_ids": [17]},
                {"label": "20'-0\"", "word_ids": [31], "seg_ids": [20]}]},
            {"page": 3, "viewport": "main", "spans": [
                {"label": "8'-0\"", "word_ids": [29], "seg_ids": [12]},
                {"label": "2'-6\"", "word_ids": [30], "seg_ids": [15]},
                {"label": "20'-0\"", "word_ids": [31], "seg_ids": [18]}]}],
        "regions": [
            {"region_id": "A:kitchen", "kind": "base", "type": "A",
             "variant": None, "page": 2, "sheet": "A-101", "viewport": "main",
             "boundary": {"seg_ids": [4, 5, 6, 7, 8, 9]}, "seed": [160, 390],
             "expected_sf_range": [25, 40]},
            {"region_id": "A:vanity", "kind": "base", "type": "A",
             "variant": None, "page": 2, "sheet": "A-101", "viewport": "main",
             "boundary": {"seg_ids": [10, 11, 12, 13]}, "seed": [100, 505],
             "expected_sf_range": [5, 10]},
            {"region_id": "A:kitchen@recheck", "kind": "recheck",
             "of": "A:kitchen", "type": "A", "variant": None, "page": 2,
             "sheet": "A-101", "viewport": "main",
             "boundary": {"seg_ids": [4, 5, 6, 7, 8, 9]}, "seed": [200, 380],
             "expected_sf_range": [25, 40]},
            {"region_id": "B:kitchen", "kind": "base", "type": "B",
             "variant": None, "page": 3, "sheet": "A-102", "viewport": "main",
             "boundary": {"seg_ids": [4, 5, 6, 7]}, "seed": [140, 382],
             "expected_sf_range": [15, 30]},
            {"region_id": "B:vanity", "kind": "base", "type": "B",
             "variant": None, "page": 3, "sheet": "A-102", "viewport": "main",
             "boundary": {"seg_ids": [8, 9, 10, 11]}, "seed": [100, 505],
             "expected_sf_range": [5, 10]}]}


# IDs below were read from the extracted messy geometry (deterministic).
# page 2 = superseded A-201; page 5 = REV B (measured); offsets +3 vs page 2.
def spec_messy(pdfs, geo, policy="gross"):
    sha = sha256(pdfs["messy"])
    spec = {
        "schema": "countertop-takeoff/v2",
        "source": {"pdf": pdfs["messy"], "sha256": sha},
        "geometry": geo["messy"],
        "mode": "repeated_types",
        "policy": {"gross_area": policy, "declarations": [
            {"kind": "plan_spec_conflict",
             "detail": "notes 25 in.; plans dimension 30 in."},
            {"kind": "scope_omission",
             "detail": "clubroom counter on A-204 is a searchable raster -"
                       " skipped, manual takeoff required"},
            {"kind": "revision_disposition",
             "detail": "A-201 on pages 2 and 5; page 5 (REV B) measured"}]},
        "schedule": {"page": 1, "sheet": "A-001",
            "types": [
                {"type": "A", "count": 10,
                 "row_text": "FLOOR 1: TYPE A 5 | FLOOR 2: TYPE A 5",
                 "word_boxes": [{"t": "5", "x0": 187.5, "y0": 210.3,
                                 "x1": 192.5, "y1": 222.7}],
                 "rows": [{"floor": "1", "count": 5, "row_text": "F1 A 5"},
                          {"floor": "2", "count": 5, "row_text": "F2 A 5"}]},
                {"type": "B", "count": 8,
                 "row_text": "FLOOR 1: TYPE B 4 | FLOOR 2: TYPE B 4",
                 "word_boxes": [{"t": "4", "x0": 387.5, "y0": 210.3,
                                 "x1": 392.5, "y1": 222.7}],
                 "rows": [{"floor": "1", "count": 4, "row_text": "F1 B 4"},
                          {"floor": "2", "count": 4, "row_text": "F2 B 4"}]}],
            "variants": [
                {"type": "A", "name": "ADA", "count": 2,
                 "included_in_parent_total": False,
                 "row_text": "TYPE A (ADA) 1 per floor - separate column",
                 "word_boxes": [{"t": "1", "x0": 287.5, "y0": 210.3,
                                 "x1": 292.5, "y1": 222.7}],
                 "rows": [{"floor": "1", "count": 1, "row_text": "F1 ADA 1"},
                          {"floor": "2", "count": 1, "row_text": "F2 ADA 1"}]}],
            "stated_totals": {"per_floor": {"1": 10, "2": 10},
                              "project": 20}},
        "scope": {"pages": [
            {"page": 1, "disposition": "intentionally_skipped",
             "reason": "schedule sheet"},
            {"page": 2, "sheet": "A-201", "disposition": "intentionally_skipped",
             "reason": "superseded by REV B page 5"},
            {"page": 5, "sheet": "A-201", "disposition": "measured",
             "expected_regions": ["A:kitchen", "A:island", "A:vanity"]},
            {"page": 3, "sheet": "A-202", "disposition": "measured",
             "expected_regions": ["AADA:kitchen", "AADA:vanity"]},
            {"page": 4, "sheet": "A-203", "disposition": "measured",
             "expected_regions": ["B:kitchen", "B:vanity"]},
            {"page": 6, "sheet": "A-204", "disposition": "intentionally_skipped",
             "reason": "searchable raster scan - unmeasurable, manual"
                       " takeoff pending"}]},
        "calibrations": [
            {"page": 5, "viewport": "unit-plan", "spans": [
                {"label": "10'-0\"", "word_ids": [41], "seg_ids": [25]},
                {"label": "6'-0\"", "word_ids": [42], "seg_ids": [28]},
                {"label": "3'-0\"", "word_ids": [43], "seg_ids": [31]}]},
            {"page": 5, "viewport": "bath-enlargement", "spans": [
                {"label": "6'-0\"", "word_ids": [46], "seg_ids": [49]},
                {"label": "2'-0\"", "word_ids": [47], "seg_ids": [52]}]},
            {"page": 3, "viewport": "main", "spans": [
                {"label": "8'-0\"", "word_ids": [28], "seg_ids": [12]},
                {"label": "2'-6\"", "word_ids": [29], "seg_ids": [15]},
                {"label": "6'-0\"", "word_ids": [30], "seg_ids": [18]}]},
            {"page": 4, "viewport": "main", "spans": [
                {"label": "12'-0\" split", "word_ids": [21, 22],
                 "seg_ids": [20]},
                {"label": "20'-6 1/2\" fractional", "word_ids": [24, 25],
                 "seg_ids": [26]},
                {"label": "6'-0\"", "word_ids": [26], "seg_ids": [29]}]}],
        "regions": []}
    spec["regions"] = [
        {"region_id": "A:kitchen", "kind": "base", "type": "A",
         "variant": None, "page": 5, "sheet": "A-201", "viewport": "unit-plan",
         "boundary": {"seg_ids": [7, 8, 9, 10]}, "seed": [630, 160],
         "expected_sf_range": [20, 30]},
        {"region_id": "A:island", "kind": "base", "type": "A",
         "variant": None, "page": 5, "sheet": "A-201", "viewport": "unit-plan",
         "boundary": {"seg_ids": [11, 12, 13, 14]}, "seed": [500, 130],
         "expected_sf_range": [14, 22]},
        {"region_id": "A:vanity", "kind": "base", "type": "A",
         "variant": None, "page": 5, "sheet": "A-201",
         "viewport": "bath-enlargement",
         "boundary": {"seg_ids": [38, 39, 40, 41]}, "seed": [333, 120],
         "expected_sf_range": [8, 16]},
        {"region_id": "A:kitchen@recheck", "kind": "recheck",
         "of": "A:kitchen", "type": "A", "variant": None, "page": 5,
         "sheet": "A-201", "viewport": "unit-plan",
         "boundary": {"seg_ids": [7, 8, 9, 10]}, "seed": [645, 200],
         "expected_sf_range": [20, 30]},
        {"region_id": "AADA:kitchen", "kind": "base", "type": "A",
         "variant": "ADA", "page": 3, "sheet": "A-202", "viewport": "main",
         "boundary": {"seg_ids": [4, 5, 6, 7]}, "seed": [140, 160],
         "expected_sf_range": [16, 24]},
        {"region_id": "AADA:vanity", "kind": "base", "type": "A",
         "variant": "ADA", "page": 3, "sheet": "A-202", "viewport": "main",
         "boundary": {"seg_ids": [8, 9, 10, 11]}, "seed": [120, 255],
         "expected_sf_range": [8, 16]},
        {"region_id": "B:kitchen", "kind": "base", "type": "B",
         "variant": None, "page": 4, "sheet": "A-203", "viewport": "main",
         "boundary": {"seg_ids": [4, 5, 6, 7, 8, 9, 10, 11]},
         "seed": [200, 140], "expected_sf_range": [30, 40]},
        {"region_id": "B:vanity", "kind": "base", "type": "B",
         "variant": None, "page": 4, "sheet": "A-203", "viewport": "main",
         "boundary": {"seg_ids": [16, 17, 18, 19]}, "seed": [120, 255],
         "expected_sf_range": [8, 16]}]
    return spec


# ------------------------------------------------------------------ runners
def run_measure(spec, tag):
    """Run measure.main in-process. Returns (rc, results_json or None,
    error_text). rc 2 = TakeoffError (refusal)."""
    jobs = os.path.join(BUILD, f"{tag}.jobs.json")
    report = os.path.join(BUILD, f"{tag}.report.md")
    csv_path = os.path.join(BUILD, f"{tag}.csv")
    res = os.path.join(BUILD, f"{tag}.results.json")
    with open(jobs, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=1)
    argv = [jobs, "--report", report, "--csv", csv_path, "--json", res]
    try:
        rc = measure.main(argv)
        payload = json.load(open(res, encoding="utf-8"))
        return (rc or 0), payload, ""
    except TakeoffError as exc:
        return 2, (json.load(open(res, encoding="utf-8"))
                   if os.path.exists(res) else None), str(exc)


def read_csv_rows(tag):
    import csv as _csv
    path = os.path.join(BUILD, f"{tag}.csv")
    if not os.path.exists(path):
        return None
    with open(path, newline="", encoding="utf-8") as f:
        return list(_csv.reader(f))


def main():
    shutil.rmtree(BUILD, ignore_errors=True)
    os.makedirs(BUILD, exist_ok=True)
    pdfs = {"orig": os.path.join(BUILD, "orig.pdf"),
            "messy": os.path.join(BUILD, "messy.pdf")}
    sh(os.path.join(HERE, "make_fixture.py"), "--out", pdfs["orig"])
    sh(os.path.join(HERE, "make_fixture.py"), "--case", "messy",
       "--out", pdfs["messy"])
    sh(os.path.join(SKILL, "scripts", "index_pdf.py"), pdfs["orig"],
       "--out", os.path.join(BUILD, "orig.index.json"))
    sh(os.path.join(SKILL, "scripts", "index_pdf.py"), pdfs["messy"],
       "--out", os.path.join(BUILD, "messy.index.json"))
    sh(os.path.join(SKILL, "scripts", "extract_geometry.py"), pdfs["orig"],
       "--pages", "all", "--out", os.path.join(BUILD, "orig.geometry.json"))
    sh(os.path.join(SKILL, "scripts", "extract_geometry.py"), pdfs["messy"],
       "--pages", "all", "--out", os.path.join(BUILD, "messy.geometry.json"))
    print("fixtures built and extracted.")
    geo = {"orig": os.path.join(BUILD, "orig.geometry.json"),
           "messy": os.path.join(BUILD, "messy.geometry.json")}
    positives(pdfs, geo)
    profile_tests(pdfs, geo)
    negative_tests(pdfs, geo)
    print()
    failed = [r for r in RESULTS if not r[1]]
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}"
              + (f"  [{detail}]" if detail and not ok else ""))
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


# ---------------------------------------------------------------- positive
def positives(pdfs, geo):
    # 1) original fixture: exact numbers, unchanged
    rc, res, err = run_measure(spec_original(pdfs, geo), "t_orig")
    check("original: exit 0", rc == 0, err[:120])
    check("original: 168.75 SF total",
          res and abs(res["totals"]["project_sf"] - 168.75) < 1e-9,
          str(res and res["totals"]))
    check("original: status complete (V3: ready -> complete superseded)",
          res and res["status"] == "complete", str(res and res["status"]))
    factors = {r["region_id"]: r["factor_pt_per_ft"] for r in res["regions"]}
    check("original: factor 18 everywhere",
          all(abs(v - 18.0) < 1e-9 for v in factors.values()), str(factors))

    # 2) messy gross: exact per-region + total, per-viewport factors
    rc, res, err = run_measure(spec_messy(pdfs, geo), "t_messy")
    check("messy gross: exit 0", rc == 0, err[:120])
    want = {"A:kitchen": 25.0, "A:island": 18.0, "A:vanity": 12.0,
            "AADA:kitchen": 20.0, "AADA:vanity": 12.0, "B:kitchen": 35.0,
            "B:vanity": 12.0}
    got = {r["region_id"]: r["area_sf"] for r in res["regions"]
           if r["kind"] == "base"}
    check("messy gross: all regions exact", got == want, str(got))
    check("messy gross: 990.00 total",
          abs(res["totals"]["project_sf"] - 990.0) < 1e-9,
          str(res["totals"]))
    by_id = {r["region_id"]: r for r in res["regions"]}
    check("messy gross: bath viewport factor 9",
          abs(by_id["A:vanity"]["factor_pt_per_ft"] - 9.0) < 1e-9,
          str(by_id["A:vanity"]["factor_pt_per_ft"]))
    check("messy gross: unit viewport factor 18",
          abs(by_id["A:kitchen"]["factor_pt_per_ft"] - 18.0) < 1e-9)
    check("messy gross: ADA not double-counted",
          res["totals"]["unit_count"] == 20
          and any(r["variant"] == "ADA" for r in res["regions"]),
          str(res["totals"]))
    check("messy gross: status complete_with_callouts"
          " (V3: the A-201 rev conflict is a disclosed callout)",
          res["status"] == "complete_with_callouts", str(res["status"]))

    # 3) CSV shape: base rows extended, rechecks separate, totals rows
    rows = read_csv_rows("t_messy")
    header, data = rows[0], rows[1:]
    kinds = [r[0] for r in data]
    base_rows = [r for r in data if r[0] == "base"]
    recheck_rows = [r for r in data if r[0] == "recheck_of_base"]
    type_rows = [r for r in data if r[0] == "type_total"]
    grand = [r for r in data if r[0] == "grand_total"]
    check("csv: header has region_extended_sf + factor",
          "region_extended_sf" in header and "pt_per_ft_used" in header)
    check("csv: base rows carry region_sf x count",
          all(abs(float(r[8]) * float(r[7]) - float(r[9])) < 0.01
              for r in base_rows))
    check("csv: recheck rows never extended",
          all(r[8] == "0" and r[9] == "" for r in recheck_rows),
          str(recheck_rows))
    check("csv: one totals row per type + grand total",
          len(type_rows) == 2 and len(grand) == 1
          and abs(float(grand[0][9]) - 990.0) < 1e-9,
          str([r[1] + ":" + r[9] for r in type_rows + grand]))
    check("csv: grand total equals base extension sum",
          abs(sum(float(r[9]) for r in base_rows)
              - float(grand[0][9])) < 0.01)

    # 4) messy net: declared sink cutouts subtracted (island sink + B sink)
    net_spec = spec_messy(pdfs, geo, policy="net_of_declared_cutouts")
    for r in net_spec["regions"]:
        if r["region_id"] == "B:kitchen":
            r["cutouts"] = [{"label": "sink", "seg_ids": [12, 13, 14, 15]}]
        if r["region_id"] == "A:island":
            r["cutouts"] = [{"label": "sink", "seg_ids": [15, 16, 17, 18]}]
    rc, res, err = run_measure(net_spec, "t_messy_net")
    check("messy net: exit 0", rc == 0, err[:120])
    bk = next(r for r in res["regions"] if r["region_id"] == "B:kitchen")
    isl = next(r for r in res["regions"] if r["region_id"] == "A:island")
    check("messy net: B kitchen 32.00 (35 - 3 sink)",
          abs(bk["area_sf"] - 32.0) < 1e-9, str(bk["area_sf"]))
    check("messy net: island 15.00 (18 - 3 sink)",
          abs(isl["area_sf"] - 15.0) < 1e-9, str(isl["area_sf"]))
    check("messy net: total 936.00",
          abs(res["totals"]["project_sf"] - 936.0) < 1e-9,
          str(res["totals"]))

    # 5) audit pack renders overlays; receipt records
    for tag in ("t_orig", "t_messy"):
        res_path = os.path.join(BUILD, f"{tag}.results.json")
        pack = os.path.join(BUILD, f"{tag}_pack")
        audit_pack.render_pack(json.load(open(res_path, encoding="utf-8")),
                               pack, 2.0)
        pngs = [f for f in os.listdir(pack) if f.endswith(".png")]
        sized = [f for f in pngs
                 if os.path.getsize(os.path.join(pack, f)) > 5000]
        check(f"audit pack {tag}: png overlays exist",
              len(sized) >= 8, f"{len(sized)} sized pngs")
    res_path = os.path.join(BUILD, "t_messy.results.json")
    payload = json.load(open(res_path, encoding="utf-8"))
    audit_pack.record_receipt(payload, res_path, "fresh-agent: test",
                              "approved", "matrix run", "pack")
    after = json.load(open(res_path + ".receipt.json", encoding="utf-8"))
    check("receipt: sidecar recorded + review status (5.1 immutable results)",
          after["review_status"] == "independent_audit_approved"
          and after["reviewer"] == "fresh-agent: test"
          and json.load(open(res_path, encoding="utf-8")) == payload)


def profile_tests(pdfs, geo):
    """P1 groundwork: company profile validation + material identity."""
    prof_path = os.path.join(BUILD, "profile.json")
    with open(prof_path, "w", encoding="utf-8") as f:
        json.dump({"profile_version": "1", "company": "Test Shop",
                   "material_aliases": {"laminate": "postformed-laminate"},
                   "gross_net_policy": "gross",
                   "required_components": ["counter", "vanity"],
                   "approved_assumptions": ["drawn geometry is truth"]}, f)
    spec = spec_original(pdfs, geo)
    spec["profile"] = prof_path
    spec["regions"][0]["material"] = "laminate"
    spec["regions"][0]["assembly"] = "kitchen-run"
    rc, res, err = run_measure(spec, "t_prof")
    check("profile: valid profile passes", rc == 0, err[:120])
    rk = next(r for r in res["regions"] if r["region_id"] == "A:kitchen")
    check("profile: material resolved to canonical",
          rk.get("material_canonical") == "postformed-laminate",
          str(rk.get("material_canonical")))
    check("profile: profile summary in results",
          res.get("profile", {}).get("company") == "Test Shop")
    # policy inherited from profile
    spec2 = spec_original(pdfs, geo)
    del spec2["policy"]["gross_area"]
    spec2["profile"] = prof_path
    rc2, res2, err2 = run_measure(spec2, "t_prof2")
    check("profile: gross policy inherited", rc2 == 0, err2[:120])
    # unresolved material refuses
    spec3 = spec_original(pdfs, geo)
    spec3["profile"] = prof_path
    spec3["regions"][0]["material"] = "mystery-stone"
    rc3, _, err3 = run_measure(spec3, "t_prof3")
    check("profile: unresolved material refuses",
          rc3 == 2 and "mystery-stone" in err3, err3[:140])
    # unknown profile key refuses
    with open(prof_path, "w", encoding="utf-8") as f:
        json.dump({"profile_version": "1", "pricing": True}, f)
    spec4 = spec_original(pdfs, geo)
    spec4["profile"] = prof_path
    rc4, _, err4 = run_measure(spec4, "t_prof4")
    check("profile: unknown key refuses", rc4 == 2 and "pricing" in err4,
          err4[:140])


# ---------------------------------------------------------------- negative
# V3 split the old refusal matrix in two:
#   degradation - recoverable findings at the affected region/viewport/count:
#                 exit 0, run_status complete_with_callouts, affected fields
#                 BLANK, named in CALLOUTS (each case lists its V2->V3
#                 supersession)
#   refusal     - structural malformation or a catastrophic stop: exit 2
def expect_degradation(pdfs, geo, name, mutate, callout_part, blank_ids,
                       want_total=None, ledger_part=None):
    spec = spec_messy(pdfs, geo)
    mutate(spec)
    rc, res, err = run_measure(spec, f"n_{name}")
    csv_path = os.path.join(BUILD, f"n_{name}.csv")
    ok_rc = rc == 0
    ok_status = bool(res) and res.get("run_status") == "complete_with_callouts"
    callouts = " | ".join(
        c["scope"] + ": " + c["reason"]
        for c in ((res.get("callouts") or []) if res else []))
    ok_reason = callout_part.lower() in callouts.lower()
    blanks = {r["region_id"] for r in ((res.get("regions") or []) if res else [])
              if r.get("status") == "unresolved"}
    ok_blank = all(bid in blanks for bid in blank_ids)
    ok_csv = os.path.exists(csv_path)  # degraded runs still deliver the rest
    ok_total = want_total is None or (
        res and abs(res["totals"]["project_sf"] - want_total) < 1e-9)
    ledger_txt = json.dumps(res.get("coverage_ledger") or []) if res else ""
    ok_ledger = ledger_part is None or ledger_part.lower() in ledger_txt.lower()
    check(f"degrade {name} (V3 replaces V2 refuse-{name})",
          ok_rc and ok_status and ok_reason and ok_blank and ok_csv
          and ok_total and ok_ledger,
          f"rc={rc} status={ok_status} reason_ok={ok_reason}"
          f" blanks={sorted(blanks)} want_blank={blank_ids}"
          f" csv={ok_csv} total_ok={ok_total} ledger_ok={ok_ledger}"
          f" err={err[:160]}"
          f" callouts={callouts[:220]}")


def expect_refusal(pdfs, geo, name, mutate, reason_part):
    """Structural/catastrophic cases that STILL refuse (exit 2, no csv)."""
    spec = spec_messy(pdfs, geo)
    mutate(spec)
    rc, res, err = run_measure(spec, f"n_{name}")
    csv_path = os.path.join(BUILD, f"n_{name}.csv")
    details = err
    if res and res.get("audit"):
        details += " | " + " | ".join(
            i["check"] + ": " + i["detail"]
            for i in res["audit"] if i["status"] == "fail")
    ok_rc = rc == 2
    ok_reason = reason_part.lower() in details.lower()
    ok_no_csv = not os.path.exists(csv_path)
    check(f"refuse {name}", ok_rc and ok_reason and ok_no_csv,
          f"rc={rc} reason_ok={ok_reason} csv_absent={ok_no_csv}"
          f" err={details[:200]}")


def negative_tests(pdfs, geo):
    def drop_regions(pred):
        def m(s):
            s["regions"] = [r for r in s["regions"] if not pred(r)]
        return m

    # --- degradation (V3 graduated degradation; each case supersedes a V2
    #     whole-job refusal; supersessions listed in the final summary) ---
    # V2 refuse missing_type -> V3: type B count has no region; SF blank
    expect_degradation(pdfs, geo, "missing_type", drop_regions(
        lambda r: r["type"] == "B" and r["kind"] == "base"),
        "no standard region measured", [],
        want_total=614.0,  # A(55x10) + ADA(32x2); B excluded blank
        ledger_part='"type B x8"')

    # V2 refuse missing_region -> V3: planned region with no record =
    # unresolved callout, the rest delivers
    expect_degradation(pdfs, geo, "missing_region", drop_regions(
        lambda r: r["region_id"] == "A:vanity"),
        "produced no measurement record", [], want_total=870.0)

    def dup(s):
        src = next(r for r in s["regions"] if r["region_id"] == "B:kitchen")
        clone = copy.deepcopy(src)
        clone["region_id"] = "B:kitchen@copy"
        s["regions"].append(clone)
    # V4 SUPERSEDES refuse-duplicate_region (P0.3: overlap/unplanned-scope
    # failures degrade LOCALLY; nothing stops the job). The unplanned
    # duplicate record is withheld blank behind a callout; the PLANNED
    # original keeps its measurement (only one instance survives). The
    # planned-pair overlap case (BOTH records withheld) is the tests_v4
    # regression "overlap: duplicated pair withheld, job completes".
    expect_degradation(pdfs, geo, "duplicate_region_withheld", dup,
                       "UNPLANNED region", ["B:kitchen@copy"],
                       want_total=990.0)

    def bad_count(s):
        s["schedule"]["types"][1]["count"] = 4.5
    expect_refusal(pdfs, geo, "invalid_count", bad_count, "positive integer")

    def neg_count(s):
        s["schedule"]["variants"][0]["count"] = -1
    expect_refusal(pdfs, geo, "negative_count", neg_count, "positive integer")

    # V2 refuse unresolved_scan -> V3: the raster page's planned region
    # cannot produce a record; disclosed unresolved, job completes
    def scan_measured(s):
        for e in s["scope"]["pages"]:
            if e["page"] == 6:
                e["disposition"] = "measured"
                e["expected_regions"] = ["clubroom:counter"]
    expect_degradation(pdfs, geo, "unresolved_scan", scan_measured,
                       "produced no measurement record", [],
                       want_total=990.0)

    # V2 refuse unresolved_revision -> V3: missing dispositions become a
    # coverage callout (never a silent drop)
    def no_revision_disposition(s):
        s["scope"]["pages"] = [e for e in s["scope"]["pages"]
                               if e["page"] not in (2, 5)]
    expect_degradation(pdfs, geo, "unresolved_revision",
                       no_revision_disposition, "no scope disposition", [],
                       want_total=990.0)

    def wrong_calibration(s):
        for c in s["calibrations"]:
            if c["page"] == 5 and c["viewport"] == "unit-plan":
                c["spans"] = [
                    {"label": "6'-0\"", "word_ids": [46], "seg_ids": [49]},
                    {"label": "2'-0\"", "word_ids": [47], "seg_ids": [52]}]
    # V2 refuse wrong_calibration -> V3: range breach withholds the number
    expect_degradation(pdfs, geo, "wrong_calibration", wrong_calibration,
                       "outside expected",
                       ["A:kitchen", "A:island", "A:kitchen@recheck"],
                       want_total=560.0)  # A:vanity 120 + ADA 64 + B 376

    def single_span(s):
        for c in s["calibrations"]:
            if c["page"] == 5 and c["viewport"] == "unit-plan":
                c["spans"] = c["spans"][:1]
    # V2 refuse single_span -> V3: that viewport degrades; others deliver
    expect_degradation(pdfs, geo, "single_span", single_span,
                       "calibration", ["A:kitchen", "A:island"],
                       want_total=560.0)

    def hatch(s):
        r = next(r for r in s["regions"] if r["region_id"] == "A:vanity")
        r["boundary"]["seg_ids"].append(42)
    # V2 refuse hatch_contamination -> V3: region unresolved + callout
    expect_degradation(pdfs, geo, "hatch_contamination", hatch,
                       "not a single closed", ["A:vanity"], want_total=870.0)

    def open_shell(s):
        r = next(r for r in s["regions"] if r["region_id"] == "A:kitchen")
        r["boundary"]["seg_ids"] = [7, 8, 9]
    expect_degradation(pdfs, geo, "open_boundary", open_shell,
                       "not a single closed", ["A:kitchen"], want_total=740.0)

    def seed_on_edge(s):
        r = next(r for r in s["regions"] if r["region_id"] == "A:kitchen")
        r["seed"] = [652.0, 160.0]
    expect_degradation(pdfs, geo, "seed_on_boundary", seed_on_edge,
                       "strictly interior", ["A:kitchen"], want_total=740.0)

    def empty_page(s):
        for e in s["scope"]["pages"]:
            if e["page"] == 5:
                e["expected_regions"] = []
    # an empty measured page is spec malformation (the v1 hole) - still refuses
    expect_refusal(pdfs, geo, "empty_measured_page", empty_page,
                   "expected_regions")

    def bad_total(s):
        s["schedule"]["stated_totals"]["project"] = 21
    # V2 refuse stated_total_mismatch -> V3: evidence conflict disclosed as
    # a callout; the quoted per-row counts stay authoritative
    expect_degradation(pdfs, geo, "stated_total_mismatch", bad_total,
                       "stated project total", [], want_total=990.0)

    def bad_hash(s):
        s["source"]["sha256"] = "0" * 64
    expect_refusal(pdfs, geo, "source_hash_mismatch", bad_hash, "hash mismatch")

    # stale-export quarantine: a later failing run must quarantine the old csv
    run_measure(spec_messy(pdfs, geo), "q_good")
    good_csv = os.path.join(BUILD, "q_good.csv")
    check("quarantine: good run wrote csv", os.path.exists(good_csv))
    bad = spec_messy(pdfs, geo)
    bad["source"]["sha256"] = "0" * 64
    run_measure(bad, "q_good")
    quarantined = [f for f in os.listdir(BUILD)
                   if f.startswith("q_good.csv.stale-")]
    check("quarantine: stale export renamed on failure",
          not os.path.exists(good_csv) and len(quarantined) == 1,
          str(quarantined))

    # subprocess exit-code fidelity (the contract other tools rely on)
    jobs = os.path.join(BUILD, "sub.jobs.json")
    json.dump(spec_messy(pdfs, geo), open(jobs, "w", encoding="utf-8"))
    r0 = subprocess.run([sys.executable, os.path.join(SKILL, "scripts",
                        "measure.py"), jobs], capture_output=True,
                        text=True, cwd=SKILL)
    json.dump(bad, open(jobs, "w", encoding="utf-8"))
    r2 = subprocess.run([sys.executable, os.path.join(SKILL, "scripts",
                        "measure.py"), jobs], capture_output=True,
                        text=True, cwd=SKILL)
    check("subprocess: exit 0 on ready, exit 2 on refusal",
          r0.returncode == 0 and r2.returncode == 2,
          f"rc0={r0.returncode} rc2={r2.returncode}")


if __name__ == "__main__":
    sys.exit(main())
