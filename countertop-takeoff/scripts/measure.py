# /// script
# requires-python = ">=3.9"
# dependencies = ["shapely>=2.0"]
# ///
"""Calibrated countertop measurement (step 3 of the takeoff).

Reads a JSON job spec written by the agent, measures each region's closed
polygon from the vector geometry produced by extract_geometry.py, calibrates
PDF points to real feet using labeled dimensions ON THE SAME SHEET, multiplies
by the unit schedule, and writes a markdown report + CSV + results JSON.

The agent NEVER types a measurement by hand: it only supplies WHERE to measure
(bbox + seed point per region), the schedule counts it read from the indexed
text, and optionally which dimension label to calibrate against.

Job spec schema (JSON):
{
  "pdf": "examples/fixture.pdf",                  # citation only
  "geometry": "build/fixture.geometry.json",      # from extract_geometry.py
  "schedule": {"sheet": "A-001", "counts": {"A": 3, "B": 2}},
  "jobs": [
    {"room_type": "A", "instance": "Unit 101", "page": 2, "sheet": "A-101",
     "regions": [
       {"name": "kitchen", "bbox": [x0, y0, x1, y1], "seed": [x, y],
        "expected_sf_range": [25, 40]}
     ]}
  ]
}

Usage:
    uv run scripts/measure.py jobs.json [--report report.md] [--csv takeoff.csv]
                                        [--json results.json] [--snap 0.05]
                                        [--pad 8] [--spot-tolerance 2.0]
                                        [--spread-fail 5.0]

Exit codes: 0 = pass (warnings possible), 2 = hard failure (do NOT use numbers).
"""

import argparse
import csv
import json
import os
import re
import statistics
import sys
from datetime import datetime, timezone

from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import polygonize, unary_union

# Matches a whole word like 10'-0", 10'0", 10'-6.5", 10'6", 10'
DIM_WORD_RE = re.compile(
    r"^\s*(\d{1,3})\s*'\s*-?\s*(\d{1,2}(?:\.\d+)?)?\s*(?:\"|''|”)?\s*$"
)
SCALE_LINE_RE = re.compile(r"\bscale\b", re.I)


class MeasureError(Exception):
    """Raised when measurement cannot proceed honestly (calibration failed,
    no closed polygon, conflicting dimensions). Never guess around it."""


def resolve_path(path, base_dir):
    """Resolve `path` against cwd first, then against the job file's folder."""
    if os.path.isabs(path) or os.path.exists(path):
        return path
    candidate = os.path.join(base_dir, path)
    if os.path.exists(candidate):
        return candidate
    return path  # let the open() fail with a clear message


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------- calibration

def parse_dim_word(word):
    """Return real length in feet for a word like 10'-0", else None."""
    m = DIM_WORD_RE.match(word)
    if not m:
        return None
    feet = int(m.group(1))
    inches = float(m.group(2)) if m.group(2) else 0.0
    real_ft = feet + inches / 12.0
    return real_ft if real_ft >= 0.5 else None


def group_words_into_lines(words):
    """Cluster words into text lines by vertical midpoint (2 pt tolerance)."""
    lines = []
    for w in sorted(words, key=lambda w: (w["y0"] + w["y1"]) / 2.0):
        mid = (w["y0"] + w["y1"]) / 2.0
        for line in lines:
            if abs(line["mid"] - mid) <= 2.0:
                line["words"].append(w)
                line["mid"] = sum(
                    (x["y0"] + x["y1"]) / 2.0 for x in line["words"]
                ) / len(line["words"])
                break
        else:
            lines.append({"mid": mid, "words": [w]})
    return lines


def find_calibration(page, pad, filter_text=None):
    """Match dimension labels to vector segments on ONE page.

    A label matches the longest segment whose midpoint falls inside the
    label's bbox expanded by `pad` points. Returns per-label scales.
    """
    segments = page["segments"]
    labels, unmatched = [], []
    want = normalize_dim_text(filter_text) if filter_text else None
    for line in group_words_into_lines(page["words"]):
        line_text = " ".join(w["t"] for w in line["words"])
        if SCALE_LINE_RE.search(line_text):
            continue  # skip "SCALE: 1/4\" = 1'-0\"" notes, they are not dimensions
        for w in line["words"]:
            real_ft = parse_dim_word(w["t"])
            if real_ft is None:
                continue
            if want and normalize_dim_text(w["t"]) != want:
                continue
            bx0, by0 = w["x0"] - pad, w["y0"] - pad
            bx1, by1 = w["x1"] + pad, w["y1"] + pad
            cands = []
            for s in segments:
                mx, my = (s["x0"] + s["x1"]) / 2.0, (s["y0"] + s["y1"]) / 2.0
                if bx0 <= mx <= bx1 and by0 <= my <= by1:
                    length = ((s["x1"] - s["x0"]) ** 2 + (s["y1"] - s["y0"]) ** 2) ** 0.5
                    if length >= 3.0:
                        cands.append((length, s))
            if not cands:
                unmatched.append({"label": w["t"], "real_ft": real_ft,
                                  "page": page["page"]})
                continue
            length, seg = max(cands, key=lambda c: c[0])
            labels.append({
                "page": page["page"], "sheet": page.get("sheet"),
                "label": w["t"], "real_ft": real_ft,
                "seg_len_pt": round(length, 4),
                "pt_per_ft": round(length / real_ft, 6),
            })
    return labels, unmatched


def normalize_dim_text(text):
    return text.replace(" ", "").replace("”", '"').replace("''", '"') if text else None


def calibrate_page(page, pad, filter_text=None, spread_fail=5.0):
    """Return the page's pt-per-ft scale plus every label that contributed."""
    labels, unmatched = find_calibration(page, pad, filter_text)
    if not labels:
        raise MeasureError(
            f"CALIBRATION FAILED on page {page['page']}"
            f" (sheet {page.get('sheet') or '?'}): no labeled dimension could be"
            f" matched to a vector segment."
            + (f" Tried label '{filter_text}'." if filter_text else "")
            + " The skill must stop rather than guess - see references/method.md."
        )
    scales = [lb["pt_per_ft"] for lb in labels]
    scale = statistics.median(scales)
    spread = (max(scales) - min(scales)) / scale * 100.0
    if spread > spread_fail:
        raise MeasureError(
            f"CALIBRATION CONFLICT on page {page['page']}: labels disagree by"
            f" {spread:.2f}% (limit {spread_fail}%). Scales: {scales}."
            " Check which dimension belongs to what; do not average blindly."
        )
    return {"scale_pt_per_ft": scale, "labels": labels,
            "unmatched": unmatched, "spread_pct": round(spread, 3)}


# --------------------------------------------- schedule multiplication + QA

def aggregate_types(measured_jobs, schedule, spot_tolerance):
    """Group instances by room type, spot-check them, extend by schedule count."""
    counts = (schedule or {}).get("counts", {})
    types = []
    order = []
    for job in measured_jobs:
        if job["room_type"] not in order:
            order.append(job["room_type"])
    for room_type in order:
        instances = [j for j in measured_jobs if j["room_type"] == room_type]
        base = instances[0]
        base_sf = base["instance_sf"]
        count = counts.get(room_type)
        count_note = None
        if count is None:
            count = 1
            count_note = ("no schedule count found for this type; used 1 -"
                          " VERIFY against the unit schedule")
        spot_checks = []
        for other in instances[1:]:
            dev = (abs(other["instance_sf"] - base_sf) / base_sf * 100.0
                   if base_sf else 0.0)
            spot_checks.append({
                "instance": other["instance"],
                "sf": other["instance_sf"],
                "deviation_pct": round(dev, 3),
                "ok": dev <= spot_tolerance,
            })
        types.append({
            "room_type": room_type,
            "schedule_count": count,
            "schedule_sheet": (schedule or {}).get("sheet"),
            "count_note": count_note,
            "base_instance": base["instance"],
            "sf_per_unit": base_sf,
            "extended_sf": round(base_sf * count, 2),
            "spot_checks": spot_checks,
            "instances": instances,
        })
    return types


def run_audit(types, calibrations, spread_fail):
    """Self-audit checklist. Returns list of {check, status, detail}."""
    items = []

    def add(check, status, detail):
        items.append({"check": check, "status": status, "detail": detail})

    if calibrations:
        worst = max(c["spread_pct"] for c in calibrations.values())
        n = sum(len(c["labels"]) for c in calibrations.values())
        add("calibration", "pass" if worst <= spread_fail else "fail",
            f"{n} dimension label(s) matched on {len(calibrations)} sheet(s);"
            f" worst spread {worst:.2f}% (limit {spread_fail}%)")
    else:
        add("calibration", "fail", "no calibration was performed")

    for t in types:
        for inst in t["instances"]:
            for r in inst["regions"]:
                status = "pass"
                if r["notes"]:
                    status = "warn"
                if r.get("expected_range_ok") is False:
                    status = "fail"
                detail = (f"{t['room_type']}/{inst['instance']}/{r['name']}:",
                          f" {r['area_sf']:.2f} SF in {r['vertices']}-vertex loop;"
                          f" {r['segments_in_bbox']} segs, {r['loops_found']} loops,"
                          f" bbox cap {r['bbox_area_sf']:.2f} SF")
                add("region closure/sanity", status, "".join(detail))

    for t in types:
        for sc in t["spot_checks"]:
            add("spot-check",
                "pass" if sc["ok"] else "fail",
                f"{t['room_type']}: {sc['instance']} = {sc['sf']:.2f} SF vs base"
                f" {t['sf_per_unit']:.2f} SF (dev {sc['deviation_pct']:.2f}%)")

    for t in types:
        status = "warn" if t["count_note"] else "pass"
        add("schedule count", status,
            f"type {t['room_type']}: count {t['schedule_count']}"
            + (f" ({t['count_note']})" if t["count_note"] else
               f" from schedule sheet {t['schedule_sheet']}")
            + " - agent must have READ this from the schedule text")

    total_units = sum(t["schedule_count"] for t in types)
    add("coverage", "pass",
        f"{sum(len(t['instances']) for t in types)} instance(s) measured across"
        f" {len(types)} type(s); schedule total {total_units} units")
    return items


# -------------------------------------------------------------- output

def build_report(spec, calibrations, types, audit):
    lines = []
    lines.append("# Countertop Takeoff Report")
    lines.append("")
    lines.append(f"- source PDF: `{spec['pdf']}`")
    lines.append(f"- generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append(f"- schedule counts from sheet {(spec.get('schedule') or {}).get('sheet', '?')}"
                 " (agent-read from indexed page text)")
    lines.append("")
    lines.append("## Calibration")
    lines.append("")
    lines.append("| page | sheet | label | segment pt | real ft | pt/ft |")
    lines.append("|-----:|-------|-------|-----------:|--------:|------:|")
    for page_no in sorted(calibrations):
        c = calibrations[page_no]
        for lb in c["labels"]:
            lines.append(f"| {lb['page']} | {lb['sheet'] or '?'} | {lb['label']}"
                         f" | {lb['seg_len_pt']:.2f} | {lb['real_ft']:.4f}"
                         f" | {lb['pt_per_ft']:.4f} |")
        lines.append("")
        lines.append(f"Scale used on page {page_no}: **{c['scale_pt_per_ft']:.4f} pt/ft**"
                     f" (median of {len(c['labels'])} labels,"
                     f" spread {c['spread_pct']:.2f}%)")
        lines.append("")
    lines.append("## Takeoff by type")
    for t in types:
        lines.append("")
        lines.append(f"### Type {t['room_type']} - schedule count {t['schedule_count']}")
        lines.append("")
        lines.append("| instance | sheet (page) | region | SF | edge LF (info) |")
        lines.append("|----------|--------------|--------|---:|---------------:|")
        for inst in t["instances"]:
            for r in inst["regions"]:
                lines.append(f"| {inst['instance']} | {inst['sheet']} ({inst['page']})"
                             f" | {r['name']} | {r['area_sf']:.2f}"
                             f" | {r['edge_lf_info']:.2f} |")
        lines.append("")
        lines.append(f"Per-unit total: **{t['sf_per_unit']:.2f} SF**"
                     f" -> x{t['schedule_count']} units = **{t['extended_sf']:.2f} SF**")
        for sc in t["spot_checks"]:
            verdict = "PASS" if sc["ok"] else "FAIL"
            lines.append(f"Spot-check {sc['instance']}: {sc['sf']:.2f} SF vs base"
                         f" {t['sf_per_unit']:.2f} SF"
                         f" (dev {sc['deviation_pct']:.2f}%) {verdict}")
        if t["count_note"]:
            lines.append(f"WARNING: {t['count_note']}")
    lines.append("")
    lines.append("## Totals")
    lines.append("")
    lines.append("| type | SF/unit | units | extended SF |")
    lines.append("|------|--------:|------:|------------:|")
    total_ext = 0.0
    total_units = 0
    for t in types:
        total_ext += t["extended_sf"]
        total_units += t["schedule_count"]
        lines.append(f"| {t['room_type']} | {t['sf_per_unit']:.2f}"
                     f" | {t['schedule_count']} | {t['extended_sf']:.2f} |")
    lines.append(f"| **total** |  | {total_units} | **{total_ext:.2f}** |")
    lines.append("")
    lines.append("## QA table")
    lines.append("")
    lines.append("| room type | instance measured | SF | schedule count | extended SF | source |")
    lines.append("|-----------|-------------------|---:|---------------:|------------:|--------|")
    for t in types:
        for inst in t["instances"]:
            if inst["instance"] == t["base_instance"] or True:
                lines.append(
                    f"| {t['room_type']} | {inst['instance']}"
                    f" | {inst['instance_sf']:.2f} | {t['schedule_count']}"
                    f" | {t['extended_sf']:.2f}"
                    f" | {spec['pdf']} p.{inst['page']} ({inst['sheet']}) |")
    lines.append("")
    lines.append("## Self-audit")
    lines.append("")
    mark = {"pass": "x", "warn": " ", "fail": "!!"}
    for item in audit:
        lines.append(f"- [{mark[item['status']]}] {item['check']}:"
                     f" {item['status'].upper()} - {item['detail']}")
    failed = [i for i in audit if i["status"] == "fail"]
    warned = [i for i in audit if i["status"] == "warn"]
    lines.append("")
    overall = "FAIL" if failed else ("PASS (with warnings)" if warned else "PASS")
    lines.append(f"**Overall: {overall}**"
                 f" ({len(failed)} fail, {len(warned)} warn)")
    return "\n".join(lines) + "\n"


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("jobs", help="job spec JSON (see module docstring)")
    ap.add_argument("--report", help="write markdown report here")
    ap.add_argument("--csv", dest="csv_path", help="write takeoff CSV here")
    ap.add_argument("--json", dest="json_path", help="write full results JSON here")
    ap.add_argument("--snap", type=float, default=0.05,
                    help="endpoint snap tolerance in pt (default 0.05)")
    ap.add_argument("--pad", type=float, default=12.0,
                    help="calibration search pad around a label bbox, pt (default 12)")
    ap.add_argument("--spot-tolerance", type=float, default=2.0,
                    help="spot-check deviation tolerance, percent (default 2.0)")
    ap.add_argument("--spread-fail", type=float, default=5.0,
                    help="calibration label spread that hard-fails, percent (default 5)")
    return ap.parse_args(argv)


# ------------------------------------------------- region polygon assembly

def snap(value, snap_tol):
    return round(value / snap_tol) * snap_tol if snap_tol > 0 else value


def segments_in_bbox(segments, bbox):
    """Keep segments whose BOTH endpoints lie inside the bbox (small eps)."""
    x0, y0, x1, y1 = bbox
    eps = 1e-6
    out = []
    for s in segments:
        if (x0 - eps <= s["x0"] <= x1 + eps and x0 - eps <= s["x1"] <= x1 + eps
                and y0 - eps <= s["y0"] <= y1 + eps
                and y0 - eps <= s["y1"] <= y1 + eps):
            out.append(s)
    return out


def assemble_faces(segments, snap_tol):
    """Node the linework and return closed faces (polygons) it encloses."""
    lines = []
    for s in segments:
        p0 = (snap(s["x0"], snap_tol), snap(s["y0"], snap_tol))
        p1 = (snap(s["x1"], snap_tol), snap(s["y1"], snap_tol))
        if p0 != p1:
            lines.append(LineString([p0, p1]))
    if not lines:
        return []
    merged = unary_union(MultiLineString(lines))
    return list(polygonize(merged))


def measure_region(page, region, scale_pt_per_ft, snap_tol):
    """Measure one region: closed polygon inside bbox containing the seed.

    Returns region dict with area_sf. Raises MeasureError when the region
    cannot be measured honestly.
    """
    name = region["name"]
    bbox, seed = region["bbox"], region["seed"]
    segs = segments_in_bbox(page["segments"], bbox)
    if not segs:
        raise MeasureError(
            f"region '{name}' on page {page['page']}: bbox {bbox} contains no"
            " vector segments. Re-draw the bbox around the countertop linework.")
    faces = assemble_faces(segs, snap_tol)
    point = Point(seed)
    containing = [f for f in faces if f.covers(point)]
    if not containing:
        nearest = min((f.distance(point) for f in faces), default=None)
        raise MeasureError(
            f"region '{name}' on page {page['page']}: seed {seed} is not inside"
            f" any closed loop ({len(faces)} loops found, nearest "
            f"{nearest:.1f} pt away). Move the seed INSIDE the countertop outline"
            " or widen the bbox so the outline closes.")
    face = min(containing, key=lambda f: (f.area, f.length))
    area_sf = face.area / (scale_pt_per_ft ** 2)
    edge_lf = face.length / scale_pt_per_ft  # informational, phase-2 scope
    bbox_area_sf = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) / (scale_pt_per_ft ** 2)
    notes = []
    if len(containing) > 1:
        notes.append(f"{len(containing)} nested loops contain seed; took smallest")
    if area_sf > bbox_area_sf * 1.001:
        raise MeasureError(
            f"region '{name}': measured {area_sf:.2f} SF exceeds its bbox"
            f" ({bbox_area_sf:.2f} SF) - wrong scale or wrong bbox. Stopping.")
    result = {
        "name": name,
        "bbox": bbox,
        "seed": seed,
        "segments_in_bbox": len(segs),
        "loops_found": len(faces),
        "vertices": len(face.exterior.coords) - 1,
        "area_pt2": round(face.area, 4),
        "area_sf": round(area_sf, 2),
        "edge_lf_info": round(edge_lf, 2),
        "bbox_area_sf": round(bbox_area_sf, 2),
    }
    expected = region.get("expected_sf_range")
    if expected:
        ok = expected[0] <= area_sf <= expected[1]
        result["expected_sf_range"] = expected
        result["expected_range_ok"] = ok
        if not ok:
            notes.append(f"SF {area_sf:.2f} outside expected range {expected}")
    result["notes"] = notes
    return result


def run_pipeline(args):
    base_dir = os.path.dirname(os.path.abspath(args.jobs))
    spec = load_json(args.jobs)
    geometry = load_json(resolve_path(spec["geometry"], base_dir))
    pages = {p["page"]: p for p in geometry["pages"]}
    jobs = spec["jobs"]
    print(f"jobs spec : {args.jobs}")
    print(f"geometry  : {spec['geometry']}  ({len(pages)} pages loaded)")
    print(f"jobs      : {len(jobs)} instance(s) to measure")
    # STUB: region measurement + report land in the next commits.
    calibrations = {}
    for page_no in sorted({j["page"] for j in jobs}):
        if page_no not in pages:
            raise MeasureError(
                f"page {page_no} is not in the geometry file; re-run"
                f" extract_geometry.py with --pages {page_no}")
        calib = calibrate_page(pages[page_no], args.pad,
                               spread_fail=args.spread_fail)
        print(f"calibration page {page_no}: {calib['scale_pt_per_ft']:.4f} pt/ft"
              f"  ({len(calib['labels'])} labels, spread {calib['spread_pct']:.2f}%)")
        calibrations[page_no] = calib
    measured_jobs = []
    for job in jobs:
        page = pages[job["page"]]
        scale = calibrations[job["page"]]["scale_pt_per_ft"]
        calib_text = (job.get("calibration") or {}).get("text")
        if calib_text:
            scale = calibrate_page(page, args.pad, filter_text=calib_text,
                                   spread_fail=args.spread_fail)["scale_pt_per_ft"]
        regions = [measure_region(page, region, scale, args.snap)
                   for region in job["regions"]]
        measured_jobs.append({
            "room_type": str(job["room_type"]),
            "instance": job["instance"],
            "page": job["page"],
            "sheet": job.get("sheet") or page.get("sheet") or "?",
            "instance_sf": round(sum(r["area_sf"] for r in regions), 2),
            "regions": regions,
        })
        print(f"measured {job['room_type']}/{job['instance']}:"
              f" {measured_jobs[-1]['instance_sf']:.2f} SF"
              f"  ({', '.join(r['name'] + ' ' + format(r['area_sf'], '.2f') + ' SF' for r in regions)})")
    types = aggregate_types(measured_jobs, spec.get("schedule"),
                            args.spot_tolerance)
    audit = run_audit(types, calibrations, args.spread_fail)
    report = build_report(spec, calibrations, types, audit)
    print()
    print(report)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"wrote {args.report}")
    if args.csv_path:
        write_csv(args.csv_path, spec, types)
        print(f"wrote {args.csv_path}")
    if args.json_path:
        write_results_json(args.json_path, spec, calibrations, types, audit, args)
        print(f"wrote {args.json_path}")
    failed = [i for i in audit if i["status"] == "fail"]
    if failed:
        raise MeasureError(
            f"self-audit FAILED ({len(failed)} item(s)); numbers above must not"
            " be quoted until fixed")
    return 0


def write_csv(path, spec, types):
    cols = ["room_type", "instance", "region", "sheet", "page", "region_sf",
            "edge_lf_info", "instance_sf", "schedule_count", "extended_sf",
            "source", "notes"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(cols)
        for t in types:
            for inst in t["instances"]:
                for r in inst["regions"]:
                    notes = "; ".join(r["notes"]) if r["notes"] else ""
                    if inst["instance"] != t["base_instance"]:
                        notes = (notes + "; " if notes else "") + "spot-check instance"
                    writer.writerow([
                        t["room_type"], inst["instance"], r["name"],
                        inst["sheet"], inst["page"], f"{r['area_sf']:.2f}",
                        f"{r['edge_lf_info']:.2f}", f"{inst['instance_sf']:.2f}",
                        t["schedule_count"], f"{t['extended_sf']:.2f}",
                        f"{spec['pdf']} p.{inst['page']} ({inst['sheet']})",
                        notes,
                    ])


def write_results_json(path, spec, calibrations, types, audit, args):
    payload = {
        "pdf": spec["pdf"],
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "settings": {"snap_pt": args.snap, "pad_pt": args.pad,
                     "spot_tolerance_pct": args.spot_tolerance,
                     "spread_fail_pct": args.spread_fail},
        "calibrations": {str(k): v for k, v in calibrations.items()},
        "types": [
            {k: v for k, v in t.items() if k != "instances"} for t in types
        ],
        "jobs": spec["jobs"],
        "audit": audit,
        "status": ("FAIL" if any(i["status"] == "fail" for i in audit)
                   else "PASS"),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)


def main(argv=None):
    args = parse_args(argv)
    return run_pipeline(args)


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except MeasureError as exc:
        print(f"MEASUREMENT STOPPED: {exc}", file=sys.stderr)
        print("Do not guess. Fix the job spec / geometry and re-run.", file=sys.stderr)
        sys.exit(2)
