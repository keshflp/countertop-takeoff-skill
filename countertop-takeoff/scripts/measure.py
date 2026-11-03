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


def run_pipeline(args):
    base_dir = os.path.dirname(os.path.abspath(args.jobs))
    spec = load_json(args.jobs)
    geometry = load_json(resolve_path(spec["geometry"], base_dir))
    pages = {p["page"]: p for p in geometry["pages"]}
    jobs = spec["jobs"]
    print(f"jobs spec : {args.jobs}")
    print(f"geometry  : {spec['geometry']}  ({len(pages)} pages loaded)")
    print(f"jobs      : {len(jobs)} instance(s) to measure")
    # STUB: calibration, region measurement and report land in the next commits.
    raise MeasureError("pipeline not implemented yet")


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
