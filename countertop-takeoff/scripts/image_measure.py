# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1"]
# ///
"""Calibrated image-space measurement (V3 measurement route 3).

For DECENT rasters the agent renders a legible crop, SELECTS image points
(anchor endpoints of labeled dimensions + the boundary points of the
countertop outline) and this script computes everything from those
selections. The agent never types a scale factor; two+ agreeing anchors
are required, exactly like PDF calibration.

Rules (P0.6):
  - NO full-plan tracing: the boundary is the agent's selected point list
    (>= 3 points, given in tracing order). The code never infers boundary
    closure and never snaps to pixel edges.
  - quality disclosures are MANDATORY: effective resolution (px per foot),
    anchor spread, and point count travel into the result JSON and become
    callouts in the takeoff report.
  - the crop hash (sha256 of the PNG bytes) is recorded so measure.py can
    prove WHICH pixels were measured.

Usage:
    uv run scripts/image_measure.py --crop build/crop.png \
        --anchors anchors.json --points points.json \
        --out build/img_measure.json [--overlay build/crop_overlay.png]

anchors.json: [{"label": "10'-0\"", "p1": [x, y], "p2": [x, y]}, ...]
  (real_ft parsed from the label; at least 2 anchors, spread <= 5%)
points.json:  [{"name": "p1", "px": [x, y]}, ...]  (>= 3, outline order)
"""

import argparse
import hashlib
import os
import json
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calibrate as cal_mod  # noqa: E402

MIN_ANCHOR_PPI = 25.0     # px per foot below which quality degrades hard
MAX_ANCHOR_SPREAD_PCT = 5.0


def _dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def polygon_area(pts):
    """Shoelace over the agent's point list (order = the outline)."""
    s = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return abs(s) / 2.0


def measure_from_points(anchors, points):
    """Core computation shared with the measure.py route acceptance.

    anchors: [{"label", "p1", "p2", "real_ft"?}] ; points: [{"name", "px"}]
    Returns the result dict (area_sf blank on any refusal-quality problem,
    with the reason in warnings - callers decide stop vs callout).

    V4 (P0.2): anchors must be INDEPENDENT - duplicate endpoints or the
    same real_ft quoted twice collapse to one measurement (duplicating a
    span never satisfies the two-anchor rule); an explicit real_ft that
    contradicts its readable label is disclosed as a warning. The raw
    selections are recorded so measure.py can RECOMPUTE the area from
    them (an edited result number over unchanged pixels is rejected).
    """
    warnings = []
    if len(anchors) < 2:
        warnings.append("fewer than 2 anchors - one label agreeing with"
                        " itself is not a calibration")
    if len(points) < 3:
        warnings.append("fewer than 3 boundary points - no polygon")
    scales = []
    seen_endpoints = {}
    seen_fts = {}
    for i, a in enumerate(anchors):
        real_ft = a.get("real_ft")
        parsed = cal_mod.parse_dim_text(a.get("label") or "")
        if parsed is not None and parsed <= 0:
            warnings.append(f"anchor {i} label {a.get('label')!r}:"
                            " parsed dimension must be positive")
            continue
        if real_ft is None:
            real_ft = parsed
        if not real_ft or real_ft <= 0:
            warnings.append(f"anchor {i} label {a.get('label')!r} is not a"
                            " parseable dimension")
            continue
        # P0.2: a real_ft override contradicting the readable label is
        # disclosed, never applied silently
        if a.get("real_ft") is not None and parsed is not None \
                and abs(a["real_ft"] - parsed) / parsed > 0.01:
            warnings.append(
                f"anchor {i} real_ft override {a['real_ft']} contradicts the"
                f" readable label {a.get('label')!r} (= {parsed:.4f} ft) -"
                " confirm the override or fix the selection")
        key = (round(float(a["p1"][0]), 1), round(float(a["p1"][1]), 1),
               round(float(a["p2"][0]), 1), round(float(a["p2"][1]), 1))
        if key in seen_endpoints:
            warnings.append(
                f"anchors {seen_endpoints[key]} and {i} share the SAME"
                " endpoints - duplicate anchors are NOT independent"
                " evidence; pick a different labeled dimension")
            continue
        if round(float(real_ft), 4) in seen_fts:
            warnings.append(
                f"anchors {seen_fts[round(float(real_ft), 4)]} and {i} both"
                f" measure {real_ft} ft - same-length anchors do not"
                " cross-check a scale; pick a different labeled dimension")
            continue
        seen_endpoints[key] = i
        seen_fts[round(float(real_ft), 4)] = i
        length_px = _dist(a["p1"], a["p2"])
        if length_px < 8:
            warnings.append(f"anchor {i} is only {length_px:.1f} px - too"
                            " short to calibrate")
            continue
        scales.append({"label": a.get("label"), "real_ft": real_ft,
                       "length_px": round(length_px, 3),
                       "px_per_ft": round(length_px / real_ft, 4),
                       "p1": list(a["p1"]), "p2": list(a["p2"])})
    px_per_ft = None
    spread = None
    if len(scales) >= 2:
        vals = [s["px_per_ft"] for s in scales]
        px_per_ft = sorted(vals)[len(vals) // 2]
        spread = (max(vals) - min(vals)) / px_per_ft * 100.0
        if spread > MAX_ANCHOR_SPREAD_PCT:
            warnings.append(f"anchor scales disagree by {spread:.2f}%"
                            f" (limit {MAX_ANCHOR_SPREAD_PCT}%) - wrong"
                            " endpoints picked? do not average")
    elif scales:
        px_per_ft = scales[0]["px_per_ft"]
        warnings.append("only ONE usable anchor - a single labeled dimension"
                        " is not independent calibration evidence")
    if px_per_ft and px_per_ft < MIN_ANCHOR_PPI:
        warnings.append(f"effective resolution {px_per_ft:.1f} px/ft is"
                        " below the usable-raster threshold"
                        f" ({MIN_ANCHOR_PPI:.0f}) - re-render a larger crop"
                        " or treat this region as unusable")
    area_sf = None
    poly = [p["px"] for p in points]
    if len(poly) >= 3 and px_per_ft:
        area_sf = round(polygon_area(poly) / px_per_ft ** 2, 4)
    return {
        "anchors": scales,
        "selections": {"anchors": anchors, "points": points},
        "anchor_independence": {"usable_anchors": len(scales),
                                "declared_anchors": len(anchors)},
        "px_per_ft": px_per_ft,
        "anchor_spread_pct": round(spread, 3) if spread is not None else None,
        "polygon_px": poly,
        "area_sf": area_sf,
        "warnings": warnings,
        "quality": {
            "usable": bool(area_sf) and not warnings,
            "route": "image",
            "note": "agent-selected image points; code computed the scale"
                    " and area; overlay proof is mandatory",
        },
    }


def render_overlay(crop_path, result, overlay_path):
    """Overlay proof: anchors (orange) + measured outline (blue) on the
    crop. Mandatory output of this route."""
    import pymupdf
    img = pymupdf.Pixmap(crop_path)
    w, h = img.width, img.height
    doc = pymupdf.open()
    page = doc.new_page(width=w, height=h)
    page.insert_image(pymupdf.Rect(0, 0, w, h), pixmap=img)
    poly = result.get("polygon_px") or []
    if len(poly) >= 3:
        page.draw_polyline(poly + [poly[0]], color=(0.05, 0.45, 0.95),
                           width=1.5)
    for a in result.get("anchors") or []:
        page.draw_line(a["p1"], a["p2"], color=(0.95, 0.35, 0.05), width=1.5)
        page.insert_text((a["p1"][0], a["p1"][1] - 4),
                         f"{a['label']} {a['px_per_ft']:.1f}px/ft",
                         fontname="helv", fontsize=9,
                         color=(0.95, 0.35, 0.05))
    page.insert_text((6, 14),
                     f"image route: {result.get('area_sf')} SF  "
                     f"{result.get('px_per_ft')} px/ft",
                     fontname="helv", fontsize=11, color=(0, 0, 0))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(1, 1))
    pix.save(overlay_path)
    doc.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--crop", required=True, help="rendered crop PNG")
    ap.add_argument("--anchors", required=True, help="anchors JSON")
    ap.add_argument("--points", required=True, help="boundary points JSON")
    ap.add_argument("--out", required=True, help="result JSON")
    ap.add_argument("--overlay", default=None, help="overlay proof PNG"
                    " (REQUIRED for route acceptance in measure.py)")
    ap.add_argument("--source-id", default=None,
                    help="source_id the crop was rendered from (P0.2 crop"
                         " binding: source, page, transform)")
    ap.add_argument("--page", type=int, default=None,
                    help="1-based page the crop was rendered from")
    ap.add_argument("--crop-bbox", default=None,
                    help="crop bbox in displayed points: x0,y0,x1,y1")
    ap.add_argument("--render-zoom", type=float, default=None,
                    help="zoom used to render the crop (transform record)")
    args = ap.parse_args(argv)
    if not os.path.exists(args.crop):
        print(f"ERROR: crop {args.crop} not found", file=sys.stderr)
        return 2
    anchors = json.load(open(args.anchors, encoding="utf-8"))
    points = json.load(open(args.points, encoding="utf-8"))
    result = measure_from_points(anchors, points)
    result["crop"] = args.crop
    result["crop_sha256"] = hashlib.sha256(
        open(args.crop, "rb").read()).hexdigest()
    # P0.2: the crop binds to (source, page, transform) - recorded here and
    # verified by measure.py before any image-route area is accepted
    provenance = {"source_id": args.source_id, "page": args.page,
                  "crop_bbox": ([float(v) for v in
                                 args.crop_bbox.split(",")]
                                if args.crop_bbox else None),
                  "render_zoom": args.render_zoom}
    result["provenance"] = provenance
    if args.overlay:
        render_overlay(args.crop, result, args.overlay)
        result["overlay"] = args.overlay
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    print(f"# image measurement -> {args.out}")
    print(f"  px/ft: {result['px_per_ft']}  spread:"
          f" {result['anchor_spread_pct']}%  area: {result['area_sf']} SF")
    for w in result["warnings"]:
        print(f"  WARNING: {w}")
    if result["warnings"]:
        print("  (warnings travel into the takeoff report as callouts;"
              " unusable rasters stay BLANK, never guessed)")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
