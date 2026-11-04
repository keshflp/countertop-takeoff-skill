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
import json
import os
import re
import shutil
import subprocess
import sys
from test_support import build_fixtures, sha256, run_measure as shared_run_measure
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


def run_measure(spec, tag, extra=(), jobs_path=None):
    return shared_run_measure(spec, tag, extra, jobs_path, build=BUILD)


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
         "region_id": "A:vanity", "finish_tag": "PL",
         "edge_runs": [{"profile": "eased", "exposure": "front", "length_in": 60}],
         "cutouts": [{"kind": "sink", "ea": 1}]})
    rc, res, err = run_measure(spec, "v5_geomdup")
    co = callout_text(res)
    check("identity: repeated geometry claim called out and withheld"
          " (total stays 802.00)",
          rc == 0 and abs(res["totals"]["project_sf"] - 802.0) < 0.01
          and "REPEATED GEOMETRY CLAIM" in co,
          f"rc={rc} total={res and res['totals']['project_sf']}")
    pv2 = next(p for p in res["piece_boq"] if p["piece_id"] == "p:v2")
    check("identity: duplicate piece identity remains; SF and extension withheld (5.1)",
          pv2["extension_sf"] is None and pv2.get("sf") is None
          and pv2["edge_lf_ext"] is None and pv2["cutouts_ea_ext"] is None
          and pv2["cutouts_ea"] is None
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


# ------------------------------------- P1.1 uncertainty everywhere
def uncertainty_tests():
    # (1) legitimate derived EA of ZERO: `resolved zero`, not unresolved
    spec = orig_spec()
    spec["schedule"]["variants"] = [{
        "type": "A", "name": "ADA", "count": 3,
        "included_in_parent_total": True,
        "row_text": "TYPE A (ADA) 3 - all units ADA, included in the parent",
        "word_boxes": spec["schedule"]["types"][0]["word_boxes"],
        "rows": []}]
    spec["assemblies"] = [
        {"assembly_id": "a-std", "type": "A", "package": "millwork",
         "quantity_basis": {"mode": "room_type_count", "type": "A"},
         "pieces": ["p:k"],
         "sources": [{"source_id": "plans", "page": 2}]}]
    spec["pieces"] = [
        {"piece_id": "p:k", "assembly_id": "a-std", "route": "geometry",
         "region_id": "A:kitchen", "finish_tag": "PL", "edge_runs": []}]
    rc, res, err = run_measure(spec, "v5_zeroea")
    asm = {a["assembly_id"]: a for a in res["assembly_boq"]}
    check("uncertainty: a derived EA of ZERO is a resolved zero (state"
          " measured), never unresolved",
          rc == 0 and asm["a-std"]["ea"] == 0
          and asm["a-std"]["state"] == "measured"
          and asm["a-std"].get("ea_state") == "resolved",
          f"rc={rc} asm={asm.get('a-std', {})}")
    ledger = json.dumps(res.get("coverage_ledger") or [])
    check("uncertainty: the EA-0 assembly is measured in the ledger with a"
          " resolved-zero marker",
          '"state": "measured"' in ledger
          and "resolved zero" in ledger, ledger[:160])

    # (2) unknown edge length -> null edge LF + named declaration + callout
    spec = messy_spec()
    spec["assemblies"] = [
        {"assembly_id": "a1", "type": "A", "package": "millwork",
         "quantity_basis": {"mode": "room_type_count", "type": "A"},
         "pieces": ["p:k"],
         "sources": [{"source_id": "plans", "page": 5}]}]
    spec["pieces"] = [
        {"piece_id": "p:k", "assembly_id": "a1", "route": "geometry",
         "region_id": "A:kitchen",
         "edge_runs": [{"profile": "eased", "exposure": "front",
                        "length_in": None}]}]
    rc, res, err = run_measure(spec, "v5_edgenull")
    pk = next(p for p in res["piece_boq"] if p["piece_id"] == "p:k")
    co = callout_text(res)
    ledger_txt = json.dumps(res.get("coverage_ledger") or [])
    check("uncertainty: unknown edge length -> NULL edge LF (blank-field"
          " declaration + callout), never a measured number",
          rc == 0 and pk["edge_lf_by_profile"].get("eased") is None
          and any("edge_lf" in b for b in pk.get("blank_fields") or [])
          and "edge_lf" in co
          and "blank: edge_lf" in ledger_txt,
          f"rc={rc} piece={ {k: pk.get(k) for k in ('edge_lf_by_profile',
                                                    'blank_fields')} }")

    # (3) reconciliation compares the SAME known contributions (the strict
    #     pair) - the partial-knowledge totals are reported separately
    rc, res, err = run_measure(json.load(open(HOTEL_JOBS,
                                              encoding="utf-8")),
                               "v5_hotel_dual",
                               jobs_path=os.path.join(BUILD, "hotel",
                                                      "v5_dual.jobs.json"))
    res_hotel_dual = res
    dual = next(i for i in res["audit"]
                if i["check"] == "dual BoQ reconciliation")
    import re as _re
    m = _re.search(r"assembly view ([\d.]+) SF == piece view ([\d.]+) SF",
                   dual["detail"])
    check("uncertainty: the strict pair compares the SAME known"
          " contributions and they agree",
          dual["status"] == "pass" and m
          and abs(float(m.group(1)) - float(m.group(2))) < 0.02,
          dual["detail"][:160])
    check("uncertainty: the full known piece view is reported separately"
          " from the strict pair",
          "full known piece view" in dual["detail"]
          and "partial-knowledge assemblies" in dual["detail"],
          dual["detail"][:200])

    # (4) missing-geometry-page calibration degrades LOCALLY (no stop)
    spec = messy_spec()
    spec["calibrations"].append(
        {"page": 99, "viewport": "ghost", "spans": [
            {"label": "10'-0\"", "word_ids": [41], "seg_ids": [25]},
            {"label": "6'-0\"", "word_ids": [42], "seg_ids": [28]}]})
    rc, res, err = run_measure(spec, "v5_ghostcal")
    co = callout_text(res)
    check("uncertainty: a calibration on a missing-geometry page degrades"
          " locally (exit 0 + callout, other pages still measure)",
          rc == 0 and "not in the geometry" in co
          and abs(res["totals"]["project_sf"] - 990.0) < 0.01,
          f"rc={rc} total={res and res['totals']['project_sf']}")

    # (5) room counts stay DISTINCT from summed assembly EA
    check("uncertainty: totals carry BOTH the schedule unit count and the"
          " summed assembly EA (hotel: 10 room units vs 8 non-excluded"
          " assembly EA)",
          res_hotel_dual["totals"]["unit_count"] == 10
          and res_hotel_dual["totals"]["assembly_ea"] == 8,
          str(res_hotel_dual["totals"]))
    spec_mixed = mixed_v5_spec()
    rc2, res2, _ = run_measure(spec_mixed, "v5_mixed_ea")
    check("uncertainty: mixed job - room schedule units (18) != assembly EA"
          " (28) - different fields, neither overwrites the other",
          rc2 == 0 and res2["totals"]["unit_count"] == 18
          and res2["totals"]["assembly_ea"] == 28,
          str(res2 and res2["totals"]))

    # (6) completeness flags on results/report/CSV
    spec = copy.deepcopy(json.load(open(HOTEL_JOBS, encoding="utf-8")))
    rc, res, err = run_measure(spec, "v5_complete",
                               jobs_path=os.path.join(BUILD, "hotel",
                                                      "v5_complete.jobs.json"))
    t = res["totals"]
    check("uncertainty: hotel totals carry explicit completeness flags"
          " (known subtotal + unknown count)",
          t["project_sf_complete"] is False
          and t["unknown_contribution_count"] >= 1
          and abs(t["known_subtotal_sf"] - t["project_sf"]) < 0.01,
          str(t))
    club_type = next(t2 for t2 in res["types"]
                     if t2["room_type"] == "CLUB")
    check("uncertainty: a partially-known type carries complete=False with"
          " its known subtotal",
          club_type["complete"] is False
          and club_type["extended_sf"] is not None,
          str({k: club_type.get(k) for k in ("complete", "extended_sf")}))

    # (7) an ALL-unknown type shows a BLANK total, never 0.00
    spec = mixed_v5_spec()
    for p in spec["pieces"]:
        if p["piece_id"] == "p:stated":
            p["dims_in"] = {"width": None, "depth": None, "thickness": 2,
                            "height": 36}
    rc, res, err = run_measure(spec, "v5_allunknown",
                               ("--csv",
                                os.path.join(BUILD, "v5_allunknown.csv"),))
    pub_type = next((t2 for t2 in res["types"] if t2["room_type"] == "PUB"),
                    None)
    check("uncertainty: an all-unknown piece shows a BLANK type total"
          " (never 0.00)",
          rc == 0 and pub_type is not None
          and pub_type["extended_sf"] is None,
          str(pub_type and pub_type.get("extended_sf")))
    import csv as _csv
    rows = list(_csv.reader(open(os.path.join(BUILD, "v5_allunknown.csv"),
                                 encoding="utf-8"))) if os.path.exists(
        os.path.join(BUILD, "v5_allunknown.csv")) else []
    pub_row = [r for r in rows if r and r[0] == "type_total"
               and r[1] == "PUB"]
    check("uncertainty: the CSV type_total for an all-unknown type is the"
          " blank marker, never 0.00",
          pub_row and pub_row[0][9] == "__blank__",
          str(pub_row))


# --------------------------- P1.2 audit pack + estimate PDF repairs
def _fabricated_results(geo_rel=False):
    """A small results JSON over the messy fixture with two regions whose
    ids collide under the old sanitizer: `same:counter` vs `same/counter`."""
    spec = messy_spec()
    jobs = os.path.join(BUILD, "v5_pack_base.jobs.json")
    res_path = os.path.join(BUILD, "v5_pack_base.results.json")
    json.dump(spec, open(jobs, "w", encoding="utf-8"), indent=1)
    if not os.path.exists(res_path):
        measure.main([jobs, "--json", res_path])
    res = json.load(open(res_path, encoding="utf-8"))
    proto = copy.deepcopy(res["regions"][0])
    clones = []
    for rid in ("same:counter", "same/counter"):
        c = copy.deepcopy(proto)
        c["region_id"] = rid
        clones.append(c)
    res["regions"] = clones
    if geo_rel:
        res["geometry"] = "messy.geometry.json"
        for s in res["sources"]:
            s["path"] = "messy.pdf"
        res["source"]["pdf"] = "messy.pdf"
    out = os.path.join(BUILD, "v5_pack_results.json")
    json.dump(res, open(out, "w", encoding="utf-8"))
    return out


def audit_pack_tests():
    # (1) collision-proof, source-qualified proof filenames
    res_path = _fabricated_results()
    pack = os.path.join(BUILD, "v5_pack")
    shutil.rmtree(pack, ignore_errors=True)
    audit_pack.render_pack(json.load(open(res_path, encoding="utf-8")),
                           pack, 2.0)
    pngs = sorted(f for f in os.listdir(pack) if f.endswith(".png"))
    stems = {f.rsplit("_full", 1)[0].rsplit("_closeup", 1)[0]
             for f in pngs}
    index = open(os.path.join(pack, "index.md"), encoding="utf-8").read()
    check("audit-pack: `same:counter` and `same/counter` land on DISTINCT"
          " source-qualified proof filenames", len(stems) == 2, str(stems))
    check("audit-pack: index.md labels carry the source id",
          "(source plans," in index, index[:200])

    # (2) relative paths resolve against the RESULTS FILE's location
    res_rel = _fabricated_results(geo_rel=True)
    pack2 = os.path.join(BUILD, "v5_pack_rel")
    shutil.rmtree(pack2, ignore_errors=True)
    cwd = os.getcwd()
    try:
        os.chdir(os.path.join(SKILL, "examples"))  # NOT the results dir
        audit_pack.render_pack(json.load(open(res_rel, encoding="utf-8")),
                               pack2, 2.0,
                               base_dir=os.path.dirname(res_rel))
    finally:
        os.chdir(cwd)
    pngs2 = [f for f in os.listdir(pack2) if f.endswith(".png")]
    sized2 = [f for f in pngs2
              if os.path.getsize(os.path.join(pack2, f)) > 5000]
    check("audit-pack: relative geometry/source paths resolve against the"
          " results file location (overlays render from another cwd)",
          len(sized2) >= 2, f"{len(sized2)} sized pngs")

    # (3) corrupt geometry recovers per-region instead of aborting
    bad_geo = os.path.join(BUILD, "v5_corrupt.geometry.json")
    open(bad_geo, "w", encoding="utf-8").write("{ this is not json")
    res = json.load(open(res_path, encoding="utf-8"))
    res["geometry"] = bad_geo
    res_path_bad = os.path.join(BUILD, "v5_pack_badgeo_results.json")
    json.dump(res, open(res_path_bad, "w", encoding="utf-8"))
    pack3 = os.path.join(BUILD, "v5_pack_badgeo")
    shutil.rmtree(pack3, ignore_errors=True)
    try:
        audit_pack.render_pack(json.load(open(res_path_bad,
                                              encoding="utf-8")),
                               pack3, 2.0)
        ok = True
        err = ""
    except Exception as exc:  # noqa: BLE001
        ok = False
        err = str(exc)
    index3 = open(os.path.join(pack3, "index.md"),
                  encoding="utf-8").read() if ok else ""
    pngs3 = [f for f in os.listdir(pack3) if f.endswith(".png")] if ok \
        else []
    check("audit-pack: corrupt geometry recovers per-region (pack"
          " completes, geometry note disclosed)",
          ok and len(pngs3) >= 2 and "GEOMETRY NOTE" in index3,
          f"ok={ok} err={err[:100]}")

    # (4) receipt guards: stale/superseded results files
    good = os.path.join(BUILD, "v5_receipt.results.json")
    json.dump({"run_status": "complete"}, open(good, "w",
                                               encoding="utf-8"))
    stale_copy = good + ".stale-20990101T000000"
    shutil.copy(good, stale_copy)
    payload = json.load(open(good, encoding="utf-8"))
    rc = audit_pack.record_receipt(payload, good, "fresh-agent: v5",
                                   "approved", "n", "pack")
    after = json.load(open(good + ".receipt.json", encoding="utf-8"))
    check("audit-pack: the receipt DETECTS superseded sibling results files"
          " and names them",
          rc == 0 and after["superseded_results_files"]
          == [os.path.basename(stale_copy)]
          and "results_sha256" in after, str(rc))
    rc2 = audit_pack.record_receipt({}, stale_copy, "fresh-agent: v5",
                                    "approved", "n", "pack")
    check("audit-pack: a quarantined (*.stale-*) results file REFUSES a"
          " receipt", rc2 == 2, str(rc2))


def estimate_pdf_tests():
    # exact rate precision: 3 EA x 55.555 must show 55.555 (not 55.56)
    import pymupdf
    spec = orig_spec()
    spec["assemblies"] = [
        {"assembly_id": "a-std", "type": "A", "package": "millwork",
         "quantity_basis": {"mode": "room_type_count", "type": "A"},
         "pieces": ["p:k", "p:v"],
         "sources": [{"source_id": "plans", "page": 2}]}]
    spec["pieces"] = [
        {"piece_id": "p:k", "assembly_id": "a-std", "route": "geometry",
         "region_id": "A:kitchen", "edge_runs": []},
        {"piece_id": "p:v", "assembly_id": "a-std", "route": "geometry",
         "region_id": "A:vanity", "edge_runs": []}]
    jobs = os.path.join(BUILD, "v5_pdf.jobs.json")
    res = os.path.join(BUILD, "v5_pdf.results.json")
    json.dump(spec, open(jobs, "w", encoding="utf-8"), indent=1)
    rc = measure.main([jobs, "--json", res])
    prof = {"profile_version": "2", "company": "Precision Shop",
            "currency": "USD",
            "rates": [{"item_code": "P-A",
                       "match": {"assembly_kind": "A"},
                       "uom": "EA", "unit_price": 55.555,
                       "currency": "USD"}]}
    pp = os.path.join(BUILD, "v5_pdf_profile.json")
    json.dump(prof, open(pp, "w", encoding="utf-8"))
    payload = estimate_mod.build_estimate(
        res, pp, out_md=os.path.join(BUILD, "v5_pdf.md"),
        out_json=os.path.join(BUILD, "v5_pdf.json"),
        out_pdf=os.path.join(BUILD, "v5_pdf.pdf"))
    line = payload["lines"][0]
    check("estimate-pdf: the line total is Decimal-exact ROUND_HALF_UP"
          " (3 x 55.555 -> 166.67)",
          line["qty_ea"] == 3 and line["line_total"] == 166.67,
          str(line))
    doc = pymupdf.open(os.path.join(BUILD, "v5_pdf.pdf"))
    txt = "\n".join(pg.get_text() for pg in doc)
    n_pages = doc.page_count
    doc.close()
    check("estimate-pdf: the EXACT rate 55.555 is visible (never silently"
          " 55.56)",
          "55.555" in txt and "3 EA x 55.555 = 166.67" in txt
          and "55.56" not in txt.replace("55.555", ""), txt[:120])
    first = next(ln for ln in txt.split("\n") if ln.strip())
    check("estimate-pdf: the first text line is the title, below the page"
          " top (extractable, not clipped)",
          first.strip().startswith("Countertop Estimate"), repr(first))
    check("estimate-pdf: every rendered line total agrees with"
          " estimate.json",
          all(f"{l['line_total']:,.2f}" in txt
              for l in payload["lines"] if l["line_total"] is not None)
          and (f"{payload['grand_total']:,.2f}" in txt if payload["grand_total"] is not None
               else "GRAND TOTAL: BLANK" in txt), txt[:200])

    # long descriptions wrap; many lines paginate
    spec = mixed_v5_spec()
    for i in range(30):
        aid = f"pad{i}"
        spec["assemblies"].append(
            {"assembly_id": aid, "type": "PUB-RECEPTION-VANITY-RUN-WITH-A-"
             "VERY-LONG-DESCRIPTIVE-TYPE-NAME-FOR-WRAPPING", "package":
             "public_BOH", "quantity_basis": {"mode": "enumerated"},
             "pieces": [f"pp:{i}"],
             "sources": [{"source_id": "plans", "page": 5}]})
        spec["pieces"].append(
            {"piece_id": f"pp:{i}", "assembly_id": aid, "route": "stated",
             "dims_in": {"width": 24, "depth": 30, "thickness": 2,
                         "height": 36}, "edge_runs": []})
    jobs = os.path.join(BUILD, "v5_pdf_many.jobs.json")
    res = os.path.join(BUILD, "v5_pdf_many.results.json")
    json.dump(spec, open(jobs, "w", encoding="utf-8"), indent=1)
    rc = measure.main([jobs, "--json", res])
    prof2 = {"profile_version": "2", "company": "Many Lines",
             "currency": "USD",
             "rates": [{"item_code": "M-P",
                        "match": {"assembly_kind": "PUB-RECEPTION-VANITY-"
                                  "RUN-WITH-A-VERY-LONG-DESCRIPTIVE-TYPE-"
                                  "NAME-FOR-WRAPPING"},
                        "uom": "EA", "unit_price": 10.0,
                        "currency": "USD"}]}
    pp2 = os.path.join(BUILD, "v5_pdf_many_profile.json")
    json.dump(prof2, open(pp2, "w", encoding="utf-8"))
    payload2 = estimate_mod.build_estimate(
        res, pp2, out_md=os.path.join(BUILD, "v5_pdf_many.md"),
        out_json=os.path.join(BUILD, "v5_pdf_many.json"),
        out_pdf=os.path.join(BUILD, "v5_pdf_many.pdf"))
    doc = pymupdf.open(os.path.join(BUILD, "v5_pdf_many.pdf"))
    txt2 = "\n".join(pg.get_text() for pg in doc)
    n_pages2 = doc.page_count
    last_page_txt = doc[-1].get_text()
    doc.close()
    check("estimate-pdf: long descriptions wrap fully (last description"
          " chunk extractable)",
          "NAME-FOR-WRAPPING" in txt2.replace("\n", "").replace(" ", "")
          or "WRAPPING" in txt2, txt2[:120])
    check("estimate-pdf: many-line estimates paginate (2+ pages, grand"
          " total on the LAST page)",
          n_pages2 >= 2 and "GRAND TOTAL" in last_page_txt,
          f"pages={n_pages2} last_has_grand={'GRAND TOTAL' in last_page_txt}")
    check("estimate-pdf: every line total of the paginated estimate agrees"
          " with estimate.json",
          all(f"{l['line_total']:,.2f}" in txt2
              for l in payload2["lines"] if l["line_total"] is not None),
          f"n_lines={len(payload2['lines'])}")


# ----------------------------------------------- P1.3 proposal-lite
def proposal_tests():
    import proposal as proposal_mod
    import pymupdf
    prof_path = os.path.join(BUILD, "v5_hotel_rates.json")  # has terms[]
    hotel_res = os.path.join(BUILD, "v5_hotel.results.json")

    # (1) BLANK-case proposal (hotel room 203 unresolved): totals blank
    est_blank = os.path.join(BUILD, "v5_est_203.json")
    payload = proposal_mod.build_proposal(
        hotel_res, est_blank, prof_path,
        out_md=os.path.join(BUILD, "v5_proposal_blank.md"),
        out_json=os.path.join(BUILD, "v5_proposal_blank.json"),
        out_pdf=os.path.join(BUILD, "v5_proposal_blank.pdf"))
    check("proposal: built from the corrected BLANK estimate - grand"
          " preserved blank",
          payload["schema"].endswith("proposal")
          and payload["grand_total"] is None
          and payload["scope_complete"] is False
          and len(payload["packages"]) >= 2, str(payload["grand_total"]))
    mdb = open(os.path.join(BUILD, "v5_proposal_blank.md"),
               encoding="utf-8").read()
    jsb = json.load(open(os.path.join(BUILD, "v5_proposal_blank.json"),
                         encoding="utf-8"))
    doc = pymupdf.open(os.path.join(BUILD, "v5_proposal_blank.pdf"))
    txtb = "\n".join(pg.get_text() for pg in doc)
    doc.close()
    check("proposal: json/md/pdf agree on the BLANK total",
          "ESTIMATE TOTAL: __blank__" in mdb
          and jsb["grand_total"] is None
          and "ESTIMATE TOTAL: BLANK" in txtb,
          mdb[-400:])
    check("proposal: signature lines are blank and the terms section carries"
          " the SUPPLIED terms",
          "________________________________________" in mdb
          and "Net 30 from invoice date" in mdb
          and "Prices valid for 30 days" in mdb
          and jsb["terms"], mdb[-600:])
    check("proposal: package summaries come from the data (millwork +"
          " public_BOH priced, FFE shown once as excluded), EA totals"
          " unchanged",
          {g["package"] for g in payload["packages"]}
          == {"millwork", "public_BOH", "FFE"}
          and sum(g["ea_total"] for g in payload["packages"])
          == sum(l["qty_ea"] or 0 for l in payload["lines"])
          and sum(1 for g in payload["packages"] if g["package"] == "FFE")
          == 1,
          str([(g["package"], g["ea_total"]) for g in payload["packages"]]))
    check("proposal: no invented percentages/tax/payable language",
          "tax" not in mdb.lower() or "invents no" in mdb.lower()
          and "payable" not in mdb.lower().replace("payable balances", ""),
          "")

    # (2) Genuinely complete scope; never erase omissions to fabricate it.
    spec = orig_spec()
    spec["assemblies"], spec["pieces"] = [], []
    for typ, finish, width in (("A", "PL", 72), ("B", "ST", 96)):
        pids = [typ + ":kitchen", typ + ":vanity"]
        spec["assemblies"].append({"assembly_id": typ, "type": typ,
            "package": "millwork", "finish_tag": finish, "width_in": width,
            "depth_in": 25.5, "pieces": pids,
            "quantity_basis": {"mode": "room_type_count", "type": typ},
            "sources": [{"source_id": "plans", "page": 2}]})
        spec["pieces"].extend({"piece_id": pid, "assembly_id": typ,
            "route": "geometry", "region_id": pid, "edge_runs": []} for pid in pids)
    run_measure(spec, "v5_priced_complete")
    priced_res = os.path.join(BUILD, "v5_priced_complete.results.json")
    est_p = os.path.join(BUILD, "v5_est_priced.json")
    est2 = estimate_mod.build_estimate(priced_res, prof_path, out_json=est_p)
    payload = proposal_mod.build_proposal(
        priced_res, est_p, prof_path,
        out_md=os.path.join(BUILD, "v5_proposal.md"),
        out_json=os.path.join(BUILD, "v5_proposal.json"),
        out_pdf=os.path.join(BUILD, "v5_proposal.pdf"))
    grand = payload["grand_total"]
    check("proposal: priced case carries the estimate total unchanged",
          grand == est2["priced_subtotal"] and payload["scope_complete"],
          str(grand))
    mdp = open(os.path.join(BUILD, "v5_proposal.md"),
               encoding="utf-8").read()
    doc = pymupdf.open(os.path.join(BUILD, "v5_proposal.pdf"))
    txtp = "\n".join(pg.get_text() for pg in doc)
    doc.close()
    grand_s = f"{grand:,.2f}"
    check("proposal: json/md/pdf agree on the priced total",
          f"ESTIMATE TOTAL: {grand_s} USD" in mdp
          and grand_s in txtp and grand_s in mdp,
          mdp[-300:])
    # package subtotal agreement: each fully-priced package's amount equals
    # the sum of its lines' totals
    from collections import defaultdict
    sums = defaultdict(float)
    for l in payload["lines"]:
        if l.get("line_total") is not None:
            sums[l.get("package")] += l["line_total"]
    check("proposal: every package amount equals the sum of its lines",
          all(abs(g["known_amount"] - sums.get(g["package"], 0.0)) < 0.01
              for g in payload["packages"] if g["lines"]),
          str([(g["package"], g["known_amount"], sums.get(g["package"]))
               for g in payload["packages"]]))

    # (3) binding: an estimate from a DIFFERENT results file refuses
    other = os.path.join(BUILD, "v5_proposal_other.json")
    json.dump({"schema": "countertop-takeoff/v3 results"},
              open(other, "w", encoding="utf-8"))
    try:
        proposal_mod.build_proposal(other, est_blank, prof_path)
        refused = False
    except SystemExit as exc:
        refused = "DIFFERENT results file" in str(exc)
    check("proposal: refuses an estimate not bound to the same results"
          " file", refused, "no refusal")
    # (4) an inconsistent estimate (tampered subtotal) refuses
    tampered = json.load(open(est_p, encoding="utf-8"))
    tampered["priced_subtotal"] = 1.23
    tp = os.path.join(BUILD, "v5_est_tampered.json")
    json.dump(tampered, open(tp, "w", encoding="utf-8"))
    try:
        proposal_mod.build_proposal(priced_res, tp, prof_path)
        refused2 = False
    except SystemExit as exc:
        refused2 = "disagrees with its own lines" in str(exc)
    check("proposal: refuses an internally inconsistent estimate",
          refused2, "no refusal")


# ------------------------------------------------ P1.4 docs alignment
def install_docs_ok(text):
    """Accept either the transfer placeholder or any published GitHub owner."""
    clone = re.search(r"git clone\s+(\S+)", text)
    if not clone or "--ff-only" not in text:
        return False
    url = clone[1].strip("\"'")
    return url == "ORG-URL-PLACEHOLDER" or bool(re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:)[A-Za-z0-9_.-]+/countertop-takeoff-skill(?:\.git)?", url))


def docs_tests():
    root = os.path.dirname(SKILL)                       # repo root
    sk = os.path.join(root, "countertop-takeoff")       # skill folder
    readme = open(os.path.join(root, "README.md"),
                  encoding="utf-8").read()
    qb_path = os.path.join(sk, "references", "quickbooks-mapping.md")
    qb = open(qb_path, encoding="utf-8").read() if os.path.exists(qb_path) \
        else ""
    check("docs: quickbooks-mapping.md exists with the US importer"
          " constraints and the no-integration statement",
          bool(qb) and "1000 rows" in qb and "100 invoices" in qb
          and "real account" in qb
          and "NO QuickBooks API/MCP integration" in qb
          and "sales-tax" in qb,
          f"exists={os.path.exists(qb_path)}")
    check("docs: README supports a placeholder or any published owner/org URL",
          install_docs_ok(readme),
          "")
    check("docs: README explains clone-update vs separately-copied-skill",
          "Separately-copied skill folder" in readme
          and "does NOT update itself" in readme, "")
    check("docs: README roadmap promises no shop drawings and marks V6"
          " exploratory",
          "not promised" in readme and "Exploratory" in readme
          and "Shop-drawing PDFs generated" not in readme, "")
    check("docs: README qualifies the three DATA stops + spec refusal and"
          " scopes the equal-total claim to assembly jobs",
          "three kinds of DATA failure" in readme
          and "spec validation" in readme
          and "for jobs that declare" in readme, "")
    cp = open(os.path.join(sk, "references", "company-profile.md"),
              encoding="utf-8").read()
    check("docs: company-profile.md aligns required_components with the"
          " implementation (recorded, NOT enforced)",
          "NOT enforced" in cp and "Recorded + echoed" in cp, "")
    method = open(os.path.join(sk, "references", "method.md"),
                  encoding="utf-8").read()
    check("docs: method.md scopes the three-stop + equal-total claims"
          " correctly",
          "three DATA stops" in method and "ASSERTS the" in method, "")
    check("docs: job-spec-v3.md documents piece_geometry_reuse",
          "piece_geometry_reuse" in open(os.path.join(
              sk, "references", "job-spec-v3.md"),
              encoding="utf-8").read(), "")


def main():
    global ORIG_PDFS, ORIG_GEO
    shutil.rmtree(BUILD, ignore_errors=True)
    os.makedirs(BUILD, exist_ok=True)
    build_fixtures(BUILD)
    ORIG_PDFS = {"orig": os.path.join(BUILD, "orig.pdf")}
    ORIG_GEO = {"orig": os.path.join(BUILD, "orig.geometry.json")}
    rate_profile = os.path.join(HERE, "example.rate-profile.json")
    intake_tests_v5()
    publish_safety_tests(rate_profile)
    identity_tests()
    estimate_scope_tests()
    uncertainty_tests()
    audit_pack_tests()
    estimate_pdf_tests()
    proposal_tests()
    docs_tests()
    import tests_v51
    tests_v51.run(sys.modules[__name__])
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
