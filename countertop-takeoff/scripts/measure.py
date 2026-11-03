# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1", "shapely==2.2.0"]
# ///
"""Calibrated, scope-checked countertop measurement (V2 pipeline).

Runs the V2 flow in one command: validate the job spec against the hashed
source, audit the scope ledger and schedule evidence, calibrate each
(page, viewport) from selected dimension spans, measure every region from
selected boundary segments, run the completeness/reconciliation audit, and
write the evidence package + report + (when safe) the CSV export.

Exit codes:
  0 = required checks passed (status ready or warning; review may still be
      pending - check review_status in the results JSON before delivering)
  2 = hard stop: invalid spec, hash mismatch, non-vector page, failed
      calibration, unclosed boundary, failed audit. Diagnostics (report +
      results JSON) are still written; any previous export is quarantined.

Usage:
    uv run scripts/measure.py <job-spec.json> [--report report.md]
        [--csv takeoff.csv] [--json results.json] [--snap 0.05]
        [--recheck-tolerance 2.0]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit as audit_mod  # noqa: E402
import calibrate as cal_mod  # noqa: E402
import regions as regions_mod  # noqa: E402
import report_out  # noqa: E402
import spec_schema  # noqa: E402
from spec_schema import TakeoffError  # noqa: E402

REVIEW_PENDING = "independent_audit_pending"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_path(path, base_dir):
    if os.path.isabs(path) or os.path.exists(path):
        return path
    candidate = os.path.join(base_dir, path)
    return candidate if os.path.exists(candidate) else path


def load_geometry_map(spec, base_dir):
    """Load one geometry payload per source. spec['geometry'] is a path
    (single source) or a {source_id: path} object (V3 multi-source)."""
    geo_spec = spec["geometry"]
    if isinstance(geo_spec, str):
        path = resolve_path(geo_spec, base_dir)
        return {spec_schema.default_source_id(spec): load_json(path)}
    out = {}
    for sid, path in geo_spec.items():
        out[sid] = load_json(resolve_path(path, base_dir))
    return out


def unresolved_result(region, sid, reason):
    """A region whose SF could not be measured: quantities stay BLANK
    (never zero), the record keeps every identity field, and the reason
    drives the callout."""
    return {
        "region_id": region["region_id"],
        "kind": region.get("kind", "base"),
        "of": region.get("of"),
        "type": region.get("type"),
        "variant": region.get("variant"),
        "page": region["page"],
        "source_id": sid,
        "viewport": region.get("viewport") or "main",
        "sheet": region.get("sheet") or "?",
        "assembly": region.get("assembly"),
        "piece": region.get("piece"),
        "status": "unresolved",
        "unresolved_reason": reason,
        "blank_fields": ["area_sf", "edge_lf", "splash_lf"],
        "area_sf": None,
        "factor_pt_per_ft": None,
        "expected_sf_range": region.get("expected_sf_range"),
    }


def measure_all_regions(spec, pages_by_no, calibrations, snap, audit_obj,
                        base_dir):
    """Measure every region; recoverable failures become UNRESOLVED
    records + callouts at the affected region only (P0.1). The agent's
    alternate routes are the spec's business; code refuses to let one bad
    boundary sink a whole job."""
    results = []
    default_source = spec_schema.default_source_id(spec)
    for region in spec["regions"]:
        sid = region.get("source_id") or default_source
        pno = region["page"]
        rid = region["region_id"]
        if (sid, pno) not in pages_by_no:
            reason = (f"source {sid!r} page {pno} is not in the geometry -"
                      " re-run extract_geometry.py for it")
            results.append(unresolved_result(region, sid, reason))
            print(f"UNRESOLVED {rid}: {reason}")
            continue
        if region.get("route") == "image":
            # P0.6 route 3: the crop anchors ARE the calibration; no vector
            # calibration entry is required for this region.
            r = regions_mod.measure_region_image(region, base_dir)
            results.append(r)
            if r.get("status") == "unresolved":
                print(f"UNRESOLVED {rid} (image route):"
                      f" {r['unresolved_reason'][:100]}")
                if not r.get("_callout_done"):
                    r["_callout_done"] = True
                    audit_obj.add_callout(
                        f"region {rid}", r["unresolved_reason"],
                        blank_fields=r["blank_fields"], pages=[pno],
                        source_id=sid)
            else:
                print(f"measured {rid} (image route): {r['area_sf']:.2f} SF"
                      f" at {r['factor_px_per_ft']} px/ft")
            continue
        key = (sid, pno, region.get("viewport") or "main")
        cal = calibrations.get(key)
        if cal is None:
            reason = (f"no usable calibration for source {sid!r} page {pno}"
                      f" viewport {key[2]!r} - its quantities are excluded"
                      " (blank) while the rest of the job completes")
            results.append(unresolved_result(region, sid, reason))
            print(f"UNRESOLVED {rid}: {reason}")
            continue
        try:
            r = regions_mod.measure_region(
                region, pages_by_no[(sid, pno)], cal["factor_pt_per_ft"],
                spec["policy"]["gross_area"], snap,
                viewport_box=cal.get("viewport_box"))
        except regions_mod.RegionError as exc:
            r = unresolved_result(region, sid, str(exc))
            print(f"UNRESOLVED {rid}: {exc}")
        results.append(r)
        if r.get("status") == "unresolved" and not r.get("_callout_done"):
            r["_callout_done"] = True
            audit_obj.add_callout(
                f"region {rid}", r["unresolved_reason"],
                blank_fields=r["blank_fields"], pages=[pno], source_id=sid)
        else:
            print(f"measured {r['region_id']}: {r['area_sf']:.2f} SF"
                  f" (factor {r['factor_pt_per_ft']:.4f} pt/ft,"
                  f" policy {r['gross_area_policy']})")
    return results


def audit_intake_manifest(spec, audit_obj, base_dir):
    """Step 0 intake (P0.7): when an intake manifest is declared (or found
    beside the job spec), verify it against the declared sources: unavailable
    inputs and expected-count mismatches become disclosed callouts."""
    path = spec.get("intake_manifest")
    if not path:
        candidate = os.path.join(base_dir, "intake_manifest.json")
        if os.path.exists(candidate):
            path = candidate
    if not path:
        return
    path = resolve_path(path, base_dir)
    if not os.path.exists(path):
        audit_obj.add_callout("intake", f"intake manifest not found: {path}",
                              blank_fields=[], pages=[])
        return
    manifest = load_json(path)
    for e in manifest.get("sources") or []:
        if e.get("status") != "resolved":
            audit_obj.add_callout(
                "intake", f"source {e.get('requested')!r} was never resolved"
                " (unavailable at intake) - the job proceeds without it",
                blank_fields=["all quantities from this source"], pages=[])
    verdict = manifest.get("verdict") or ""
    if "mismatch" in verdict:
        audit_obj.add_callout("intake", verdict, blank_fields=[], pages=[])
    audit_obj.add("intake manifest", "pass",
                  f"manifest {os.path.basename(path)}:"
                  f" {len(manifest.get('sources') or [])} source(s)"
                  " requested, disclosed above when not resolved")


def run_pipeline(args):
    base_dir = os.path.dirname(os.path.abspath(args.jobs))
    spec = load_json(args.jobs)
    if isinstance(spec.get("geometry"), str):
        spec["geometry"] = resolve_path(spec["geometry"], base_dir)
    elif isinstance(spec.get("geometry"), dict):
        spec["geometry"] = {k: resolve_path(v, base_dir)
                            for k, v in spec["geometry"].items()}
    if isinstance(spec.get("source"), dict) and isinstance(
            spec["source"].get("pdf"), str):
        spec["source"]["pdf"] = resolve_path(spec["source"]["pdf"], base_dir)
    for s in spec.get("sources", []) or []:
        if isinstance(s.get("path"), str):
            s["path"] = resolve_path(s["path"], base_dir)
    parsed = spec_schema.validate_spec(spec)
    for s in spec["_sources"]:
        if s["kind"] == "pdf":
            s["path"] = resolve_path(s["path"], base_dir)
    profile = spec_schema.validate_profile(spec, base_dir)
    if not spec["policy"].get("gross_area"):
        if profile and profile.get("gross_net_policy"):
            spec["policy"]["gross_area"] = profile["gross_net_policy"]
            print(f"policy     : inherited from profile"
                  f" ({spec['policy']['gross_area']})")
        else:
            raise TakeoffError(
                "no gross-area policy: set policy.gross_area in the job spec"
                " or gross_net_policy in the company profile - never guessed")
    spec_schema.resolve_materials(spec, profile)
    # Package scope rules: company-profile defaults, job policy override.
    spec["_excluded_packages"] = spec_schema.excluded_packages(spec, profile)
    if spec["_excluded_packages"]:
        print(f"packages   : excluded by rule ="
              f" {sorted(spec['_excluded_packages'])} (reported separately)")
    geometry_map = load_geometry_map(spec, base_dir)
    default_source = spec_schema.default_source_id(spec)
    pages_by_no = {}
    for sid, geo in geometry_map.items():
        for p in geo["pages"]:
            pages_by_no[(sid, p["page"])] = p
    print(f"jobs spec  : {args.jobs}")
    print(f"sources    : " + ", ".join(
        f"{s['source_id']}={os.path.basename(s['path'])}"
        for s in spec["_sources"]))
    print(f"mode/policy: {spec['mode']} / {spec['policy']['gross_area']}")
    print(f"regions    : {len(spec['regions'])} across"
          f" {len(parsed['scope'])} scope page(s)")

    audit_obj = audit_mod.Audit()
    audit_intake_manifest(spec, audit_obj, base_dir)
    audit_mod.audit_scope(spec, geometry_map, audit_obj)
    calibrations, cal_errors = cal_mod.build_calibrations(
        spec.get("calibrations", []), pages_by_no, default_source,
        on_error=lambda key, msg: audit_obj.add_callout(
            f"calibration {key[0]!r} p{key[1]} {key[2]!r}", msg,
            blank_fields=["area_sf", "edge_lf", "splash_lf"],
            pages=[key[1]], source_id=key[0]))
    # Verified native-CAD units ARE the calibration for cad sources (P0.6):
    # factor = units_per_ft, computed from $INSUNITS or an explicit
    # operator declaration - never typed per region.
    for s in spec["_sources"]:
        if s["kind"] != "cad":
            continue
        geo = geometry_map.get(s["source_id"]) or {}
        upf = (geo.get("source") or {}).get("units_per_ft")
        if not upf:
            raise TakeoffError(
                f"CAD source {s['source_id']!r} has no verified units -"
                " re-run scripts/cad_input.py (unitless files refuse)")
        for p in geo.get("pages", []):
            key = (s["source_id"], p["page"], "main")
            if key in calibrations:
                continue
            calibrations[key] = {
                "page": p["page"], "viewport": "main",
                "source_id": s["source_id"], "viewport_box": None,
                "spans": [], "factor_pt_per_ft": float(upf),
                "spread_pct": 0.0, "status": "pass",
                "units": (geo.get("source") or {}).get("units"),
                "units_verified": (geo.get("source") or {}).get(
                    "units_verified"),
                "basis": "verified drawing units ($INSUNITS / declared)",
            }
        for c in geo.get("callouts") or []:
            audit_obj.add_callout(c.get("scope", "cad"), c.get("reason",
                                  ""), blank_fields=c.get("blank_fields"),
                                  pages=c.get("source", {}).get("pages"),
                                  source_id=s["source_id"])
    if not calibrations:
        # Catastrophic stop 1: no valid calibration anywhere in the set
        # (a verified-units native-CAD source OR a valid image-route
        # calibration qualifies on its own - P0.3).
        image_cal_ok = any(
            r.get("route") == "image"
            and regions_mod.image_calibration_usable(r, base_dir)
            for r in spec.get("regions") or [])
        if not any(s["kind"] == "cad" for s in spec["_sources"]) \
                and not image_cal_ok:
            raise TakeoffError(
                "STOP: no valid calibration exists anywhere in the set and no"
                " verified-units CAD source or valid image-route calibration"
                " is present - without one agreeing scale no length or area in"
                " this job is measurable")
    for key in sorted(calibrations, key=lambda k: (str(k[0]), k[1], k[2])):
        cal = calibrations[key]
        print(f"calibration source {key[0]!r} page {key[1]} viewport"
              f" {key[2]!r}: {cal['factor_pt_per_ft']:.4f} pt/ft"
              f" ({len(cal['spans'])} spans, spread"
              f" {cal['spread_pct']:.2f}%, {cal['status']})")
        if cal["status"] != "pass":
            audit_obj.add(
                "calibration spread", "warn",
                f"source {key[0]!r} page {key[1]} viewport {key[2]!r}: spread"
                f" {cal['spread_pct']:.2f}% in the documented 2-5% band -"
                " explain it to the reviewer")
        for ov in cal.get("overrides") or []:
            # P0.2: real_ft overrides that contradict readable labels are
            # disclosed, never applied silently
            audit_obj.add_callout(
                f"calibration override {key[0]!r} p{key[1]} {key[2]!r}",
                ov.get("warning", ""), blank_fields=[],
                pages=[key[1]], source_id=key[0])
    results = measure_all_regions(spec, pages_by_no, calibrations, args.snap,
                                  audit_obj, base_dir)
    audit_mod.audit_planned_vs_completed(spec, results, pages_by_no,
                                         audit_obj)
    sched = audit_mod.audit_schedule(spec, results, audit_obj)
    unit_total = audit_mod.reconcile_totals(sched, audit_obj)
    audit_mod.audit_schedule_evidence(spec, geometry_map, audit_obj)
    audit_mod.audit_room_reconciliation(spec, audit_obj)
    audit_mod.audit_room_coverage(spec, audit_obj)
    audit_mod.audit_region_checks(spec, results, calibrations, audit_obj,
                                  args.recheck_tolerance)
    return finish(spec, geometry_map, calibrations, audit_obj, results,
                  unit_total, args, profile)


def finish(spec, geometry_map, calibrations, audit_obj, results, unit_total,
           args, profile):
    """Deliverable assembly (V4): ONE resolved quantity model feeds the
    type rows, project total, both BoQ views, the CSVs and the ledger -
    they cannot disagree (P0.1)."""
    review_status = REVIEW_PENDING
    settings = {"snap_pt": args.snap,
                "recheck_tolerance_pct": args.recheck_tolerance}
    profile_summary = None
    if profile:
        profile_summary = {k: profile.get(k) for k in (
            "profile_version", "company", "gross_net_policy",
            "required_components", "approved_assumptions")}
    results_by_id = {r["region_id"]: r for r in results}
    resolved = audit_mod.resolve_quantities(spec, results, audit_obj,
                                            results_by_id=results_by_id)
    types, total = audit_mod.aggregate_types(spec, results, audit_obj,
                                             resolved=resolved)
    if spec.get("_assemblies"):
        unit_total = sum(a.get("ea") or 0 for a in resolved["assemblies"].values()
                         if a["state"] != "package_excluded")
    ledger = audit_mod.build_coverage_ledger(
        spec, results, audit_obj, results_by_id=results_by_id,
        resolved=resolved)
    assembly_rows = audit_mod.build_assembly_boq(spec, audit_obj, resolved)
    piece_rows = audit_mod.build_piece_boq(spec, audit_obj, resolved)
    audit_mod.audit_dual_boq(assembly_rows, piece_rows, audit_obj,
                             project_total=total)
    # Run status is one of: complete | complete_with_callouts | stopped.
    # Callouts/warnings degrade locally; remaining FAIL items are stops.
    run_status = ("stopped" if audit_obj.failed else
                  ("complete_with_callouts"
                   if (audit_obj.callouts or audit_obj.warned)
                   else "complete"))
    report = report_out.build_report(spec, calibrations, types, total,
                                     audit_obj, review_status, run_status,
                                     ledger, assembly_rows, piece_rows)
    print()
    print(report)
    if args.report:
        report_out.write_report(args.report, report)
        print(f"wrote {args.report}")
    payload = report_out.build_results(
        spec, geometry_map, calibrations, types, total, audit_obj, results,
        review_status, settings, unit_total, coverage_ledger=ledger)
    payload["run_status"] = run_status
    payload["status"] = run_status
    payload["assembly_boq"] = assembly_rows
    payload["piece_boq"] = piece_rows
    payload["totals"]["excluded_package_sf"] = round(
        resolved.get("excluded_total_sf", 0.0), 2)
    payload["totals"]["piece_view_sf"] = round(
        sum(r.get("extension_sf") or 0.0 for r in piece_rows
            if r["state"] != "package_excluded" and not r.get("orphan")), 2)
    payload["totals"]["assembly_view_sf"] = round(
        sum(a.get("extended_sf") or 0.0 for a in assembly_rows
            if a["state"] != "package_excluded"), 2)
    if profile_summary:
        payload["profile"] = profile_summary
    if args.json_path:
        report_out.write_json(args.json_path, payload)
        print(f"wrote {args.json_path}")
    if run_status == "stopped":
        # Diagnostics are published (report + results JSON); exports are NOT.
        raise TakeoffError(
            f"run STOPPED ({len(audit_obj.failed)} required check(s));"
            " diagnostics are in the report/results JSON - resolve the named"
            " stops or exclude the unresolved scope explicitly")
    # Final exports publish only after every internal check has finished.
    if args.csv_path:
        total_csv = report_out.write_csv(
            args.csv_path, spec, types, results,
            resolved=piece_rows if spec.get("_assemblies") else None,
            project_total=total)
        print(f"wrote {args.csv_path} (extended total {total_csv:.2f} SF)")
    if args.piece_csv and piece_rows:
        report_out.write_piece_csv(args.piece_csv, piece_rows)
        print(f"wrote {args.piece_csv} (piece BoQ: {len(piece_rows)} row(s))")
    if args.assembly_csv and assembly_rows:
        report_out.write_assembly_csv(args.assembly_csv, assembly_rows)
        print(f"wrote {args.assembly_csv} (assembly BoQ:"
              f" {len(assembly_rows)} row(s))")
    if args.estimate_profile:
        # P1.1: assembly-EA estimate from the SAME resolved records
        import estimate as estimate_mod
        base = args.report or args.json_path or "build/estimate"
        stem = os.path.splitext(base)[0].replace("report", "estimate")
        payload = estimate_mod.build_estimate(
            args.json_path or args.report, args.estimate_profile,
            out_md=stem + ".md",
            out_json=stem + ".json",
            out_pdf=stem + ".pdf")
        print(f"estimate grand total:"
              + (f" {payload['grand_total']}"
                 if payload["grand_total"] is not None else " BLANK"
                 " (unknown amounts disclosed in the estimate callouts)"))
    return 0


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("jobs", help="V2 job spec JSON (see module docstring)")
    ap.add_argument("--report", help="write markdown report here")
    ap.add_argument("--csv", dest="csv_path", help="write base-rows CSV here"
                    " (only when no required check failed)")
    ap.add_argument("--piece-csv", dest="piece_csv",
                    help="write the PIECE BoQ CSV (dims, SF, edge LF, splash,"
                    " cutouts, extensions)")
    ap.add_argument("--assembly-csv", dest="assembly_csv",
                    help="write the ASSEMBLY BoQ CSV (inch descriptions, EA x"
                    " validated count)")
    ap.add_argument("--json", dest="json_path",
                    help="write full evidence JSON here")
    ap.add_argument("--snap", type=float, default=0.05,
                    help="endpoint snap tolerance in pt (default 0.05)")
    ap.add_argument("--recheck-tolerance", type=float, default=2.0,
                    help="recheck deviation tolerance, percent (default 2.0)")
    ap.add_argument("--estimate-profile", dest="estimate_profile", default=None,
                    help="company profile with rates[] (P1.1): after a"
                         " successful measure, also build the assembly-EA"
                         " estimate next to the report")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    def quarantine_exports():
        # ANY stop must not leave an older export looking current.
        when = report_out.runtime_versions()["generated_utc"]
        for path in (args.csv_path, getattr(args, "piece_csv", None),
                     getattr(args, "assembly_csv", None)):
            if path and os.path.exists(path):
                stale = report_out.quarantine_stale_export(path, when)
                if stale:
                    print(f"quarantined stale export: {stale}", file=sys.stderr)

    try:
        return run_pipeline(args)
    except TakeoffError:
        quarantine_exports()
        raise
    except Exception as exc:  # noqa: BLE001 - quarantine survives ANY crash
        quarantine_exports()
        import traceback
        traceback.print_exc()
        raise TakeoffError(
            f"unexpected pipeline failure (exports quarantined): {exc!r}") \
            from exc


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except TakeoffError as exc:
        print(f"TAKEOFF STOPPED: {exc}", file=sys.stderr)
        print("Do not guess. Fix the job spec / evidence and re-run.",
              file=sys.stderr)
        sys.exit(2)
