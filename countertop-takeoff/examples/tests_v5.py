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
import time

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


# --------------------------------------------- P0.1 publish safety
def publish_safety_tests(rate_profile):
    # (1) `--json results.json --estimate-profile` must NOT overwrite the
    #     evidence package with the estimate (V5 regression)
    spec = mixed_v5_spec()
    jobs = os.path.join(BUILD, "v5_alias.jobs.json")
    res = os.path.join(BUILD, "v5_alias.json")
    json.dump(spec, open(jobs, "w", encoding="utf-8"), indent=1)
    rc = measure.main([jobs, "--json", res, "--estimate-profile",
                       rate_profile])
    payload = json.load(open(res, encoding="utf-8"))
    est = json.load(open(os.path.join(BUILD, "estimate.json"),
                         encoding="utf-8"))
    check("publish: --json results.json + --estimate-profile keeps the"
          " results intact (estimate on a distinct path)",
          rc == 0 and "run_status" in payload
          and est.get("schema").endswith("estimate"),
          f"rc={rc} results_schema={payload.get('schema')}")
    # (2) estimate.py refuses an explicit alias outright
    try:
        estimate_mod.build_estimate(res, rate_profile, out_json=res)
        refused = False
    except SystemExit as exc:
        refused = "aliases" in str(exc)
    check("publish: estimate.py rejects input/output path aliasing",
          refused, "no refusal")

    # (3) stale-output handling covers results.json + report + estimates;
    #     an early integrity stop writes a CURRENT stopped diagnostic
    csvp = os.path.join(BUILD, "v5_stale.csv")
    repp = os.path.join(BUILD, "v5_stale.report.md")
    estj = os.path.join(BUILD, "v5_stale.estimate.json")
    rc = measure.main([jobs, "--json", res, "--report", repp,
                       "--csv", csvp, "--estimate-profile", rate_profile,
                       "--estimate-json", estj])
    check("publish: good run wrote all artifacts", rc == 0
          and os.path.exists(repp) and os.path.exists(csvp)
          and os.path.exists(estj) and os.path.exists(res))
    t_stop = time.time()
    bad = json.load(open(jobs, encoding="utf-8"))
    if "sources" in bad:
        bad["sources"][0]["sha256"] = "0" * 64
    else:
        bad["source"]["sha256"] = "0" * 64
    json.dump(bad, open(jobs, "w", encoding="utf-8"), indent=1)
    try:
        measure.main([jobs, "--json", res, "--report", repp,
                      "--csv", csvp, "--estimate-profile", rate_profile,
                      "--estimate-json", estj])
        rc2 = 0
    except TakeoffError:
        rc2 = 2
    stale = [f for f in os.listdir(BUILD) if f.startswith("v5_stale")
             and ".stale-" in f]
    diag = json.load(open(res, encoding="utf-8"))
    check("publish: early integrity stop quarantines csv/report/estimate"
          " AND writes a CURRENT stopped diagnostic over results.json",
          rc2 == 2 and not os.path.exists(csvp)
          and not os.path.exists(repp) and not os.path.exists(estj)
          and len(stale) >= 3
          and diag.get("run_status") == "stopped"
          and diag.get("stopped_early") is True
          and os.path.getmtime(res) >= t_stop - 1.0,
          f"rc={rc2} stale={stale} status={diag.get('run_status')}")
    check("publish: the stopped diagnostic names the stop reason",
          "hash mismatch" in (diag.get("stopped_reason") or ""),
          str(diag.get("stopped_reason"))[:120])
    # the quarantined results file carries the superseded marker
    stale_res = [f for f in os.listdir(BUILD)
                 if f.startswith("v5_alias.json.stale-")]
    check("publish: the superseded results file is renamed with a stale"
          " marker (never current-looking)",
          len(stale_res) == 1, str(stale_res))


def mixed_v5_spec():
    """The V4 mixed spec (assemblies + included ADA variant), rebuilt here."""
    import importlib.util
    spec_mod = importlib.util.spec_from_file_location(
        "tv5_mixed", os.path.join(HERE, "tests_v4.py"))
    mod = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(mod)
    return mod.mixed_spec()


# --------------------------------- P0.2 evidence + quantity identity
def identity_tests():
    # (1) 3 -> 30 with an EDITED row_text over the real '3' box: caught
    spec = orig_spec()
    spec["schedule"]["types"][0]["count"] = 30
    spec["schedule"]["types"][0]["row_text"] = \
        "A | 1 BED / 1 BATH | 30 units total (edited quote)"
    rc, res, err = run_measure(spec, "v5_p30_text")
    co = callout_text(res)
    check("identity: 3->30 with EDITED row_text over the real '3' box is"
          " caught (row_text is descriptive only)",
          rc == 0 and "numeric correspondence" in co
          and "descriptive only" in co
          and res["totals"]["project_sf"] < 100.0,
          f"rc={rc} total={res and res['totals']['project_sf']}")

    # (2) repeated geometry claim: a second piece on the same region must
    #     NOT inflate the total; declared reuse is a non-defect
    spec = mixed_v5_spec()
    spec["assemblies"].append(
        {"assembly_id": "van-enum2", "type": "A", "package": "public_BOH",
         "quantity_basis": {"mode": "enumerated"}, "pieces": ["p:v2"],
         "sources": [{"source_id": "plans", "page": 5}]})
    spec["pieces"].append(
        {"piece_id": "p:v2", "assembly_id": "van-enum2", "route": "geometry",
         "region_id": "A:vanity", "finish_tag": "PL", "edge_runs": []})
    rc, res, err = run_measure(spec, "v5_geomdup")
    co = callout_text(res)
    check("identity: repeated geometry claim called out and withheld"
          " (total stays 802.00)",
          rc == 0 and abs(res["totals"]["project_sf"] - 802.0) < 0.01
          and "REPEATED GEOMETRY CLAIM" in co,
          f"rc={rc} total={res and res['totals']['project_sf']}")
    pv2 = next(p for p in res["piece_boq"] if p["piece_id"] == "p:v2")
    check("identity: the duplicate piece keeps identity but its extension is"
          " blank",
          pv2["extension_sf"] is None and pv2.get("sf") is not None
          and "extension_sf" in (pv2.get("blank_fields") or []), str(pv2))
    # declared reuse: same shape, now with an explicit declaration
    spec["piece_geometry_reuse"] = [{
        "region_id": "A:vanity", "pieces": ["p:v", "p:v2"],
        "reason": "the vanity geometry genuinely serves two enumerated"
                  " assemblies (declared by the operator)"}]
    rc, res, err = run_measure(spec, "v5_geomdup_ok")
    co = callout_text(res)
    check("identity: explicitly declared piece reuse is a NON-defect"
          " (802 + 12 = 814.00, no claim callout)",
          rc == 0 and abs(res["totals"]["project_sf"] - 814.0) < 0.01
          and "REPEATED GEOMETRY CLAIM" not in co,
          f"rc={rc} total={res and res['totals']['project_sf']}"
          f" callouts={co[:140]}")

    # (3) uncertain included-variant evidence withholds the dependent
    #     standard EA (never restores the parent count)
    spec = mixed_v5_spec()
    for v in spec["schedule"]["variants"]:
        if v["name"] == "ADA":
            v["word_boxes"] = [{"t": "zzz-not-a-word", "x0": 1, "y0": 1,
                                "x1": 2, "y1": 2}]
    rc, res, err = run_measure(spec, "v5_ada_bad")
    co = callout_text(res)
    asm = {a["assembly_id"]: a for a in res["assembly_boq"]}
    check("identity: uncertain included-variant evidence withholds the"
          " dependent standard EA (never 8->10)",
          rc == 0 and asm["fl1-a"]["ea"] is None
          and asm["aada"]["ea"] is None
          and res["totals"]["project_sf"] != 824.0,
          f"rc={rc} eas={{k: v['ea'] for k, v in asm.items()}}")
    check("identity: the withholding names the parent-count restoration"
          " refusal",
          "never restored to the full parent count" in co
          or "cannot be split reliably" in co,
          co[:200])
    check("identity: additional-scope pricing survives (partial knowledge)",
          res["totals"]["project_sf"] > 300.0,
          str(res["totals"]["project_sf"]))


HOTEL_ALLMATCH_PROFILE = {
    "profile_version": "2", "company": "V5 Shop", "currency": "USD",
    "terms": ["Net 30 from invoice date.",
              "Prices valid for 30 days."],
    "rates": [
        {"item_code": "V5-A", "match": {"assembly_kind": "A",
                                        "finish_tag": "PL",
                                        "width_in": 72, "depth_in": 25.5},
         "uom": "EA", "unit_price": 485.00, "currency": "USD"},
        {"item_code": "V5-B", "match": {"assembly_kind": "B",
                                        "finish_tag": "ST",
                                        "width_in": 96, "depth_in": 25.5},
         "uom": "EA", "unit_price": 918.335, "currency": "USD"},
        {"item_code": "V5-CLUB", "match": {"assembly_kind": "CLUB",
                                           "package": "public_BOH"},
         "uom": "EA", "unit_price": 742.10, "currency": "USD"},
    ],
}


# -------------------------------- P0.3 estimates inherit completeness
def estimate_scope_tests():
    prof_path = os.path.join(BUILD, "v5_hotel_rates.json")
    json.dump(HOTEL_ALLMATCH_PROFILE, open(prof_path, "w",
                                           encoding="utf-8"), indent=1)
    hotel_res = os.path.join(BUILD, "v5_hotel.results.json")
    rc, res, err = run_measure(json.load(open(HOTEL_JOBS,
                                              encoding="utf-8")),
                               "v5_hotel",
                               jobs_path=os.path.join(BUILD, "hotel",
                                                      "v5_base.jobs.json"))
    check("estimate-scope: hotel run completes with callouts",
          rc == 0 and res.get("run_status") == "complete_with_callouts",
          f"rc={rc} err={err[:120]}")

    # (1) the hotel omitted-room case: room 203 has NO assembly -> priced
    #     lines + subtotal survive, grand total BLANK, callout names 203
    payload = estimate_mod.build_estimate(
        hotel_res, prof_path,
        out_md=os.path.join(BUILD, "v5_est_203.md"),
        out_json=os.path.join(BUILD, "v5_est_203.json"),
        out_pdf=os.path.join(BUILD, "v5_est_203.pdf"))
    check("estimate-scope: hotel omitted room 203 -> grand total BLANK with"
          " priced lines surviving",
          payload["grand_total"] is None
          and payload["priced_subtotal"] > 0
          and all(l["line_total"] is not None for l in payload["lines"]),
          f"grand={payload['grand_total']}"
          f" subtotal={payload['priced_subtotal']}")
    check("estimate-scope: the callout NAMES the omitted room",
          any("203" in c["scope"] + " " + c["reason"]
              and "UNKNOWN" in c["reason"]
              for c in payload["callouts"])
          and any("203" in (u.get("item") or "")
                  for u in payload["unknown_scope"]),
          str(payload["callouts"][-1]))
    check("estimate-scope: scope_complete flag is False on the payload",
          payload["scope_complete"] is False)

    # (2) a stopped result refuses to be priced
    stopped = json.load(open(hotel_res, encoding="utf-8"))
    stopped["run_status"] = "stopped"
    spath = os.path.join(BUILD, "v5_stopped_results.json")
    json.dump(stopped, open(spath, "w", encoding="utf-8"))
    try:
        estimate_mod.build_estimate(spath, prof_path,
                                    out_json=os.path.join(
                                        BUILD, "v5_no.json"))
        refused = "no SystemExit"
    except SystemExit as exc:
        refused = str(exc)
    check("estimate-scope: a stopped result NEVER gets priced",
          "stopped" in str(refused) and not os.path.exists(
              os.path.join(BUILD, "v5_no.json")), str(refused)[:110])

    # (3) missing assembly_boq refuses - never silently prices 0.00
    noboq = json.load(open(hotel_res, encoding="utf-8"))
    del noboq["assembly_boq"]
    np = os.path.join(BUILD, "v5_noboq_results.json")
    json.dump(noboq, open(np, "w", encoding="utf-8"))
    try:
        estimate_mod.build_estimate(np, prof_path,
                                    out_json=os.path.join(
                                        BUILD, "v5_no2.json"))
        refused2 = "no SystemExit"
    except SystemExit as exc:
        refused2 = str(exc)
    check("estimate-scope: missing assembly_boq refuses (never prices"
          " 0.00)",
          "assembly_boq" in str(refused2)
          and not os.path.exists(os.path.join(BUILD, "v5_no2.json")),
          str(refused2)[:110])
    empty = json.load(open(hotel_res, encoding="utf-8"))
    empty["assembly_boq"] = []
    ep = os.path.join(BUILD, "v5_emptyboq_results.json")
    json.dump(empty, open(ep, "w", encoding="utf-8"))
    try:
        estimate_mod.build_estimate(ep, prof_path)
        refused3 = False
    except SystemExit as exc:
        refused3 = True
    check("estimate-scope: an EMPTY assembly_boq refuses too",
          refused3 is True, str(refused3))

    # (4) malformed numeric input: fractional + negative EA refuse with
    #     useful diagnostics
    for bad_ea, label in ((2.5, "fractional"), (-2, "negative")):
        bad = json.load(open(hotel_res, encoding="utf-8"))
        bad["assembly_boq"][0]["ea"] = bad_ea
        bp = os.path.join(BUILD, f"v5_badea_{label}.json")
        json.dump(bad, open(bp, "w", encoding="utf-8"))
        try:
            estimate_mod.build_estimate(bp, prof_path)
            got = False
        except SystemExit as exc:
            got = "malformed EA" in str(exc) and label in str(exc)
        check(f"estimate-scope: {label} EA refuses with a diagnostic",
              got, label)

    # (5) ONE effective currency: profile currency absent + USD/EUR mix
    mixed_prof = {"profile_version": "2", "company": "Mix",
                  "rates": [
                      {"item_code": "U", "match": {"assembly_kind": "A"},
                       "uom": "EA", "unit_price": 1, "currency": "USD"},
                      {"item_code": "E", "match": {"assembly_kind": "B"},
                       "uom": "EA", "unit_price": 1, "currency": "EUR"}]}
    mp = os.path.join(BUILD, "v5_mixcur.json")
    json.dump(mixed_prof, open(mp, "w", encoding="utf-8"))
    try:
        estimate_mod.load_profile(mp)
        refused_cur = False
    except SystemExit as exc:
        refused_cur = "mixed currencies" in str(exc) \
            and "USD" in str(exc) and "EUR" in str(exc)
    check("estimate-scope: USD+EUR mixing refuses even without a profile"
          " currency",
          refused_cur is True, "no refusal")
    ok_prof = {"profile_version": "2", "company": "Eu",
               "rates": [
                   {"item_code": "E1", "match": {"assembly_kind": "A"},
                    "uom": "EA", "unit_price": 1, "currency": "EUR"},
                   {"item_code": "E2", "match": {"assembly_kind": "B"},
                    "uom": "EA", "unit_price": 2, "currency": "EUR"}]}
    op = os.path.join(BUILD, "v5_eur.json")
    json.dump(ok_prof, open(op, "w", encoding="utf-8"))
    _, _, cur = estimate_mod.load_profile(op)
    check("estimate-scope: a consistent rate-declared currency resolves"
          " (EUR without profile currency)",
          cur == "EUR", str(cur))

    # (6) '$1,234.56' rates parse exactly; garbage refuses clearly
    cur_prof = {"profile_version": "2", "company": "Cur",
                "currency": "USD",
                "rates": [{"item_code": "C1",
                           "match": {"assembly_kind": "CLUB"},
                           "uom": "EA", "unit_price": "$1,234.56",
                           "currency": "USD"}]}
    cp = os.path.join(BUILD, "v5_curstr.json")
    json.dump(cur_prof, open(cp, "w", encoding="utf-8"))
    _, rates_c, _ = estimate_mod.load_profile(cp)
    from decimal import Decimal
    got = estimate_mod.rate_amount(rates_c[0], "unit_price")
    check("estimate-scope: '$1,234.56' parses to exactly 1234.56",
          got == Decimal("1234.56"), str(got))
    try:
        estimate_mod.parse_money("twelve"); parse_ok = False
    except SystemExit as exc:
        parse_ok = "not a parseable amount" in str(exc) \
            and "Decimal" not in str(exc)
    check("estimate-scope: unparseable amount -> clear error, no raw"
          " Decimal traceback", parse_ok)


def main():
    global ORIG_PDFS, ORIG_GEO
    shutil.rmtree(BUILD, ignore_errors=True)
    os.makedirs(BUILD, exist_ok=True)
    build_fixtures()
    ORIG_PDFS = {"orig": os.path.join(BUILD, "orig.pdf")}
    ORIG_GEO = {"orig": os.path.join(BUILD, "orig.geometry.json")}
    rate_profile = os.path.join(HERE, "example.rate-profile.json")
    intake_tests_v5()
    publish_safety_tests(rate_profile)
    identity_tests()
    estimate_scope_tests()
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
