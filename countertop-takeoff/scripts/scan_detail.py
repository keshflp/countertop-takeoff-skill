# /// script
# requires-python = ">=3.10"
# dependencies = ["opencv-python-headless==4.12.0.88", "numpy==2.2.6"]
# ///
"""Clean a selected scan crop and propose CLOSED LINEWORK for inspection.

This does not recognize countertops or produce measurements. Inspect the
original and overlay, explicitly choose/edit points, then use image_measure.py
on the ORIGINAL crop with two independently readable labeled dimensions.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np
from publish_safety import reject_aliases

IDENTITY = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]


def read_gray(path):
    image = cv2.imdecode(np.frombuffer(Path(path).read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None or min(image.shape) < 3:
        raise ValueError("crop must be a readable raster at least 3 pixels wide/high")
    return image


def save_png(path, image):
    ok, data = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("could not encode PNG")
    Path(path).write_bytes(data.tobytes())


def page_transform(provenance, width, height):
    if provenance is None:
        return None
    if not isinstance(provenance, dict):
        raise ValueError("provenance must be a JSON object")
    sid, page = provenance.get("source_id"), provenance.get("page")
    bbox, zoom = provenance.get("crop_bbox"), provenance.get("render_zoom")
    number = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    if not isinstance(sid, str) or not sid.strip() or type(page) is not int or page < 1 \
            or not isinstance(bbox, list) or len(bbox) != 4 or not all(map(number, bbox)) \
            or not number(zoom) or zoom <= 0 or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        raise ValueError("provenance needs source_id, positive page, ordered crop_bbox and positive render_zoom")
    if any(abs(v * zoom - round(v * zoom)) > 1e-6 for v in bbox):
        raise ValueError("use a pixel-aligned crop bbox; fractional raster origins are unsupported by the measurement route")
    if round((bbox[2] - bbox[0]) * zoom) != width \
            or round((bbox[3] - bbox[1]) * zoom) != height:
        raise ValueError("crop dimensions disagree with bbox/zoom; use the original untransformed crop")
    return [[1 / zoom, 0, bbox[0]], [0, 1 / zoom, bbox[1]], [0, 0, 1]]


def clean_scan(gray):
    """Local contrast tolerates shadows; never resample or repair gaps."""
    mask = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY_INV, 51, 12)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = np.ones(count, np.uint8)
    keep[0] = 0
    keep[stats[:, cv2.CC_STAT_AREA] <= 2] = 0
    mask = keep[labels] * 255
    return 255 - mask


def stroke_middle(inner, outer):
    """Midpoint of corresponding corners of a thin, closed ink stroke.

    Fall back to the inner face if paired corners are ambiguous or more
    than six pixels apart. This suggests points, never asserts a true edge.
    """
    if len(inner) != len(outer):
        return inner
    alternatives = [np.roll(order, offset, axis=0)
                    for order in (outer, outer[::-1]) for offset in range(len(outer))]
    paired = min(alternatives, key=lambda a: float(np.sum((a - inner) ** 2)))
    if np.max(np.linalg.norm(paired - inner, axis=1)) > 6:
        return inner
    return (inner + paired) / 2


def closed_outlines(cleaned):
    """Suggest holes enclosed by ink, without joining broken boundaries.

    These size/vertex filters only reduce review clutter. They do not prove
    object identity, calibration, readable labels or usable scan resolution.
    """
    height, width = cleaned.shape
    contours, hierarchy = cv2.findContours(255 - cleaned, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return []
    proposals = []
    for i, contour in enumerate(contours):
        parent, depth = hierarchy[0, i, 3], 0
        while parent >= 0:
            depth += 1
            parent = hierarchy[0, parent, 3]
        if depth % 2 != 1:  # A hole, not the outline of an open ink stroke.
            continue
        area = cv2.contourArea(contour)
        if not 0.005 * width * height <= area <= 0.80 * width * height:
            continue
        polygon = cv2.approxPolyDP(contour, 1.5, True).reshape(-1, 2)
        if not 3 <= len(polygon) <= 12:
            continue
        outer = cv2.approxPolyDP(contours[hierarchy[0, i, 3]], 1.5, True).reshape(-1, 2)
        polygon = stroke_middle(polygon, outer)
        if (polygon <= 1).any() or (polygon[:, 0] >= width - 2).any() \
                or (polygon[:, 1] >= height - 2).any():
            continue
        proposals.append(polygon.tolist())
    # Stable display IDs, not a confidence rank or a recommended measurement.
    proposals.sort(key=lambda p: (min(y for x, y in p), min(x for x, y in p)))
    return [{"id": f"outline-{i + 1}", "status": "requires_inspection",
             "points": [{"name": f"p{j + 1}", "px": p} for j, p in enumerate(poly)]}
            for i, poly in enumerate(proposals)]


def suggest_detail(crop, output_dir, provenance=None):
    crop, output_dir = Path(crop).resolve(), Path(output_dir).resolve()
    cleaned_path, overlay_path, result_path = [output_dir / name for name in
                                             ("cleaned.png", "suggestions.png", "suggestions.json")]
    reject_aliases({"original crop": str(crop)},
                   {"cleaned": str(cleaned_path), "overlay": str(overlay_path), "suggestions": str(result_path)})
    original_bytes = crop.read_bytes()
    gray = read_gray(crop)
    height, width = gray.shape
    transform = page_transform(provenance, width, height)
    cleaned = clean_scan(gray)
    suggestions = closed_outlines(cleaned)
    overlay = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    for suggestion in suggestions:
        pts = np.array([p["px"] for p in suggestion["points"]], np.int32)
        cv2.polylines(overlay, [pts], True, (0, 100, 230), 2)
        x, y = pts[0]
        cv2.putText(overlay, suggestion["id"], (int(x), max(14, int(y) - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 60, 200), 1, cv2.LINE_AA)
    cv2.putText(overlay, "UNREVIEWED LINEWORK - inspect ORIGINAL; not measurement proof",
                (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 200), 1, cv2.LINE_AA)
    result = {"kind": "scan_detail_suggestions", "review_required": True,
              "original_crop": {"path": str(crop), "sha256": hashlib.sha256(original_bytes).hexdigest(),
                                "size_px": [width, height]},
              "provenance": provenance, "provenance_verified": False,
              "suggestion_space": "original_crop_pixels", "cleaned_to_original": IDENTITY,
              "original_to_page": transform,
              "cleaned": str(cleaned_path), "overlay": str(overlay_path),
              "suggestions": suggestions,
              "limitations": ["Closed linework can be a cabinet, wall or sink, not a countertop.",
                              "Cleanup can erase labels; it cannot restore missing scan detail.",
                              "No area, scale, counts or completeness are inferred.",
                              "Adopt/edit points explicitly; measure the original crop with independent labeled anchors."]}
    output_dir.mkdir(parents=True, exist_ok=True)
    save_png(cleaned_path, cleaned)
    save_png(overlay_path, overlay)
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    assert crop.read_bytes() == original_bytes
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--crop", required=True, help="original selected crop PNG")
    ap.add_argument("--out-dir", required=True, help="separate output directory")
    ap.add_argument("--provenance", help="optional JSON with source_id/page/crop_bbox/render_zoom; declared, not verified here")
    args = ap.parse_args(argv)
    try:
        reject_aliases({"crop": args.crop, "provenance": args.provenance},
                       {name: str(Path(args.out_dir) / name) for name in
                        ("cleaned.png", "suggestions.png", "suggestions.json")})
        provenance = json.loads(Path(args.provenance).read_text(encoding="utf-8")) if args.provenance else None
        if provenance is not None and not isinstance(provenance, dict):
            raise ValueError("provenance must be a JSON object")
        result = suggest_detail(args.crop, args.out_dir, provenance)
    except (OSError, ValueError, cv2.error) as exc:
        ap.exit(2, f"scan detail refused: {exc}\n")
    print(f"{len(result['suggestions'])} unreviewed closed-linework suggestions; inspect {result['overlay']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
