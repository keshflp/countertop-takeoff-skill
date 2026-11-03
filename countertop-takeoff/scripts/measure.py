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

# Matches a whole word like 10'-0", 10'0", 10'6.5", 10', 2'-6"
DIM_WORD_RE = re.compile(
    r"^\s*(\d{1,3})\s*'\s*(\d{1,2}(?:\.\d+)?)?\s*(?:\"|''|”)?\s*$"
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


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("jobs", help="job spec JSON (see module docstring)")
    ap.add_argument("--report", help="write markdown report here")
    ap.add_argument("--csv", dest="csv_path", help="write takeoff CSV here")
    ap.add_argument("--json", dest="json_path", help="write full results JSON here")
    ap.add_argument("--snap", type=float, default=0.05,
                    help="endpoint snap tolerance in pt (default 0.05)")
    ap.add_argument("--pad", type=float, default=8.0,
                    help="calibration search pad around a label bbox, pt (default 8)")
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
    raise MeasureError("STUB: aggregation and report land in the next commits")


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
