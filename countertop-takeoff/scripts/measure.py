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


def measure_all_regions(spec, pages_by_no, calibrations, snap):
    results = []
    for region in spec["regions"]:
        pno = region["page"]
        if pno not in pages_by_no:
            raise TakeoffError(
                f"region {region['region_id']}: page {pno} is not in the"
                " geometry - re-run extract_geometry.py for it")
        key = (pno, region.get("viewport") or "main")
        cal = calibrations.get(key)
        if cal is None:
            raise TakeoffError(
                f"region {region['region_id']}: no calibration entry for page"
                f" {pno} viewport {key[1]!r} - calibrations are per (page,"
                " viewport), never per page alone")
        results.append(regions_mod.measure_region(
            region, pages_by_no[pno], cal["factor_pt_per_ft"],
            spec["policy"]["gross_area"], snap))
        r = results[-1]
        print(f"measured {r['region_id']}: {r['area_sf']:.2f} SF"
              f" (factor {r['factor_pt_per_ft']:.4f} pt/ft,"
              f" policy {r['gross_area_policy']})")
    return results


def run_pipeline(args):
    base_dir = os.path.dirname(os.path.abspath(args.jobs))
    spec = load_json(args.jobs)
    if isinstance(spec.get("geometry"), str):
        spec["geometry"] = resolve_path(spec["geometry"], base_dir)
    if isinstance(spec.get("source"), dict) and isinstance(
            spec["source"].get("pdf"), str):
        spec["source"]["pdf"] = resolve_path(spec["source"]["pdf"], base_dir)
    parsed = spec_schema.validate_spec(spec)
    geometry = load_json(spec["geometry"])
    print(f"jobs spec  : {args.jobs}")
    print(f"source     : {spec['source']['pdf']}")
    print(f"mode/policy: {spec['mode']} / {spec['policy']['gross_area']}")
    print(f"regions    : {len(spec['regions'])} across"
          f" {len(parsed['scope'])} scope page(s)")

    audit_obj = audit_mod.Audit()
    pages_by_no = audit_mod.audit_scope(spec, geometry, audit_obj)
    calibrations = cal_mod.build_calibrations(
        spec.get("calibrations", []), pages_by_no)
    for key in sorted(calibrations, key=lambda k: (k[0], k[1])):
        cal = calibrations[key]
        print(f"calibration page {key[0]} viewport {key[1]!r}:"
              f" {cal['factor_pt_per_ft']:.4f} pt/ft"
              f" ({len(cal['spans'])} spans, spread"
              f" {cal['spread_pct']:.2f}%, {cal['status']})")
        if cal["status"] != "pass":
            audit_obj.add(
                "calibration spread", "warn",
                f"page {key[0]} viewport {key[1]!r}: spread"
                f" {cal['spread_pct']:.2f}% in the documented 2-5% band -"
                " explain it to the reviewer")
    results = measure_all_regions(spec, pages_by_no, calibrations, args.snap)
    audit_mod.audit_planned_vs_completed(spec, results, pages_by_no,
                                         audit_obj)
    sched = audit_mod.audit_schedule(spec, results, audit_obj)
    unit_total = audit_mod.reconcile_totals(sched, audit_obj)
    audit_mod.audit_region_checks(spec, results, calibrations, audit_obj,
                                  args.recheck_tolerance)
    types, total = audit_mod.aggregate_types(spec, results, audit_obj)
    return finish(spec, geometry, calibrations, types, total, audit_obj,
                  results, unit_total, args)


def finish(spec, geometry, calibrations, types, total, audit_obj, results,
           unit_total, args):
    review_status = REVIEW_PENDING
    settings = {"snap_pt": args.snap,
                "recheck_tolerance_pct": args.recheck_tolerance}
    report = report_out.build_report(spec, calibrations, types, total,
                                     audit_obj, review_status)
    print()
    print(report)
    when = report_out.runtime_versions()["generated_utc"]
    if args.report:
        report_out.write_report(args.report, report)
        print(f"wrote {args.report}")
    if args.json_path:
        payload = report_out.build_results(
            spec, geometry, calibrations, types, total, audit_obj, results,
            review_status, settings, unit_total)
        report_out.write_json(args.json_path, payload)
        print(f"wrote {args.json_path}")
    if audit_obj.failed:
        stale = (report_out.quarantine_stale_export(args.csv_path, when)
                 if args.csv_path else None)
        if stale:
            print(f"quarantined stale export: {stale}")
        raise TakeoffError(
            f"audit FAILED ({len(audit_obj.failed)} item(s)); diagnostics are"
            " in the report/results JSON - fix the job spec and re-run; the"
            " export was NOT written")
    if args.csv_path:
        total_csv = report_out.write_csv(args.csv_path, spec, types, results)
        print(f"wrote {args.csv_path} (extended total {total_csv:.2f} SF)")
    return 0


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("jobs", help="V2 job spec JSON (see module docstring)")
    ap.add_argument("--report", help="write markdown report here")
    ap.add_argument("--csv", dest="csv_path", help="write base-rows CSV here"
                    " (only when no required check failed)")
    ap.add_argument("--json", dest="json_path",
                    help="write full evidence JSON here")
    ap.add_argument("--snap", type=float, default=0.05,
                    help="endpoint snap tolerance in pt (default 0.05)")
    ap.add_argument("--recheck-tolerance", type=float, default=2.0,
                    help="recheck deviation tolerance, percent (default 2.0)")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    return run_pipeline(args)


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except TakeoffError as exc:
        print(f"TAKEOFF STOPPED: {exc}", file=sys.stderr)
        print("Do not guess. Fix the job spec / evidence and re-run.",
              file=sys.stderr)
        sys.exit(2)
