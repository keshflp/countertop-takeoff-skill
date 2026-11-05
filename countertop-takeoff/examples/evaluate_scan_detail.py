# /// script
# requires-python = ">=3.10"
# dependencies = ["opencv-python-headless==4.12.0.88", "numpy==2.2.6", "pymupdf==2.1", "shapely==2.2.0"]
# ///
"""Frozen synthetic scan-detail workload; no real-plan accuracy claim.

From the skill folder:
  uv run examples/evaluate_scan_detail.py --prepare --baseline --tag baseline
  uv run examples/evaluate_scan_detail.py --tag candidate1
Preparation runs once. Later evaluations reuse identical PNGs and oracle.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from shapely.geometry import Polygon

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
BUILD = SKILL / "build" / "scan-detail"
MATCH_IOU = 0.90  # Matching rule for these synthetic outlines, not bid accuracy.
SIZE = (800, 520)
RECT = [(140, 180), (620, 180), (620, 280), (140, 280)]
ELL = [(140, 160), (620, 160), (620, 260), (340, 260), (340, 380), (140, 380)]
NOTCH = [(140, 180), (620, 180), (620, 320), (420, 320), (420, 260), (340, 260), (340, 320), (140, 320)]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fixture_image(poly, *, outline=True, labeled=True, distractions=False):
    """Render with PyMuPDF, independently of the OpenCV contour algorithm."""
    doc = pymupdf.open()
    page = doc.new_page(width=SIZE[0], height=SIZE[1])
    if outline:
        page.draw_polyline(poly + [poly[0]], color=(0.08,) * 3, width=2)
    # Two visible, distinct dimension labels. 40 px/ft; neither is inferred.
    for a, b, text, at in [((140, 95), (620, 95), "12'-0\"", (340, 85)),
                            ((680, 180), (680, 280), "2'-6\"", (690, 235))]:
        if labeled:
            page.draw_line(a, b, color=(0.12,) * 3, width=1)
            for x, y in (a, b):
                page.draw_line((x - 5, y - 5), (x + 5, y + 5), color=(0.12,) * 3)
            page.insert_text(at, text, fontsize=14)
    if distractions:
        # Sink rim and a larger enclosing cabinet/wall loop are deliberately
        # plausible non-counter contours. Geometry cannot identify their role.
        page.draw_rect((430, 195, 535, 260), color=(0.1,) * 3, width=2)
        page.draw_rect((85, 135, 655, 425), color=(0.2,) * 3, width=2)
    page.insert_text((140, 460), "GENERATED DETAIL - NOT A CUSTOMER PLAN", fontsize=12)
    pix = page.get_pixmap(colorspace=pymupdf.csGRAY, alpha=False)
    image = np.frombuffer(pix.samples, np.uint8).reshape(SIZE[1], SIZE[0]).copy()
    doc.close()
    return image


def prepare(root):
    if (root / "truth.json").exists():
        raise ValueError("workload already exists; reuse it, do not replace it during comparison")
    root.mkdir(parents=True, exist_ok=True)
    cases = []
    scans = pymupdf.open()
    definitions = [
        ("rectangle", RECT, "clean", True),
        ("ell", ELL, "clean", True),
        ("notch", NOTCH, "clean", True),
        ("speckle", RECT, "speckle", True),
        ("gradient", RECT, "gradient", True),
        ("gradient-ell", ELL, "gradient", True),
        ("skew", RECT, "skew", True),
        ("distractions", RECT, "distractions", True),
        ("broken", RECT, "broken", False),
        ("no-outline", RECT, "empty", False),
        ("unreadable", RECT, "unreadable", False),
        ("cabinet-only", RECT, "cabinet", False),
    ]
    rng = np.random.default_rng(20261104)
    for name, poly, effect, eligible in definitions:
        image = fixture_image(poly, outline=effect != "empty",
                              labeled=effect != "cabinet", distractions=effect == "distractions")
        reference = image.copy()
        truth_poly = np.array(poly, dtype=np.float64)
        if effect == "speckle":
            image[rng.random(image.shape) < 0.006] = 0
        elif effect == "gradient":
            # Multiplicative shadow, same underlying strokes and dimensions.
            illumination = np.linspace(0.27, 1.0, SIZE[0])[None, :]
            image = np.clip(image * illumination, 0, 255).astype(np.uint8)
        elif effect == "skew":
            matrix = cv2.getRotationMatrix2D((400, 260), 3.0, 1.0)
            image = cv2.warpAffine(image, matrix, SIZE, borderValue=255)
            reference = image.copy()
            truth_poly = cv2.transform(truth_poly[None], matrix)[0]
        elif effect == "broken":
            image[174:187, 360:383] = 255
        elif effect == "unreadable":
            image = cv2.resize(cv2.resize(image, (80, 52), interpolation=cv2.INTER_AREA),
                               SIZE, interpolation=cv2.INTER_LINEAR)
        page = scans.new_page(width=880, height=640)
        ok, png = cv2.imencode(".png", image)
        assert ok
        page.insert_image((40, 60, 840, 580), stream=png.tobytes())
        crop = root / f"{name}.png"
        page.get_pixmap(clip=pymupdf.Rect(40, 60, 840, 580),
                        colorspace=pymupdf.csGRAY, alpha=False).save(str(crop))
        reference_path = root / f"{name}.reference.png"
        assert cv2.imwrite(str(reference_path), reference)
        anchors = [{"label": "12'-0\"", "p1": [140, 95], "p2": [620, 95]},
                   {"label": "2'-6\"", "p1": [680, 180], "p2": [680, 280]}]
        if effect == "skew":
            for anchor in anchors:
                for key in ("p1", "p2"):
                    anchor[key] = cv2.transform(np.array([[anchor[key]]], np.float64), matrix)[0, 0].tolist()
        cases.append({"name": name, "crop": crop.name, "crop_sha256": digest(crop),
                      "reference": reference_path.name, "reference_sha256": digest(reference_path),
                      "page": len(cases) + 1, "crop_bbox": [40, 60, 840, 580], "render_zoom": 1,
                      "eligible": eligible, "outline": truth_poly.tolist() if eligible else None,
                      "anchors": anchors if eligible else None,
                      "reason": ("visible labeled dimensions and closed counter" if eligible else
                                 "no supported closed countertop or no readable calibration")})
    scans.save(str(root / "scans.pdf"))
    scans.close()
    (root / "truth.json").write_text(json.dumps({"seed": 20261104, "match_iou": MATCH_IOU,
        "source_sha256": digest(root / "scans.pdf"), "cases": cases}, indent=2), encoding="utf-8")


def evaluate(root, tag, baseline):
    truth_path = root / "truth.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    assert truth["match_iou"] == MATCH_IOU
    assert digest(root / "scans.pdf") == truth["source_sha256"]
    rows = []
    for case in truth["cases"]:
        crop = root / case["crop"]
        assert digest(crop) == case["crop_sha256"]
        reference_path = root / case["reference"]
        assert digest(reference_path) == case["reference_sha256"]
        reference = cv2.imread(str(reference_path), cv2.IMREAD_GRAYSCALE)
        original = cv2.imread(str(crop), cv2.IMREAD_GRAYSCALE)
        mapping_error = 0.0
        if baseline:
            proposals = []  # Existing measurement helper proposes no outlines.
            cleaned = original
        else:
            from scan_detail import suggest_detail
            provenance = {k: case[k] for k in ("page", "crop_bbox", "render_zoom")}
            provenance["source_id"] = "generated-scans"
            result = suggest_detail(crop, root / tag / case["name"], provenance)
            proposals = result["suggestions"]
            cleaned = cv2.imread(result["cleaned"], cv2.IMREAD_GRAYSCALE)
            assert cleaned.shape == original.shape
            assert result["suggestion_space"] == "original_crop_pixels"
            assert not {"area_sf", "px_per_ft", "quality", "selections"}.intersection(result)
            test_points = [[0, 0], [800, 0], [800, 520], [0, 520]]
            test_points += [p["px"] for s in proposals for p in s["points"]]
            points = np.column_stack([test_points, np.ones(len(test_points))])
            inverse = np.array(result["cleaned_to_original"])
            mapped = points @ inverse.T
            mapping_error = float(np.max(np.abs(mapped - points)))
            page_mapped = points @ np.array(result["original_to_page"]).T
            expected_page = points.copy()
            expected_page[:, :2] += [40, 60]
            mapping_error = max(mapping_error, float(np.max(np.abs(page_mapped - expected_page))))
            assert mapping_error <= 1e-9
            assert all(s["status"] == "requires_inspection" for s in proposals)
        polygons = [Polygon([p["px"] for p in s["points"]]) for s in proposals]
        expected = Polygon(case["outline"]) if case["eligible"] else None
        ious = [p.intersection(expected).area / p.union(expected).area for p in polygons] if expected else []
        matches = [i for i, iou in enumerate(ious) if iou >= MATCH_IOU]
        best = max(range(len(ious)), key=ious.__getitem__) if ious else None
        ink = reference < 128
        background = cv2.dilate((reference < 245).astype(np.uint8), np.ones((7, 7), np.uint8)) == 0
        row = {"case": case["name"], "eligible": case["eligible"], "proposals": len(proposals),
               "ink_retained_pct": round(float(np.mean(cleaned[ink] < 128) * 100), 4),
               "background_darkness_pct": round(float(np.mean(255 - cleaned[background]) / 255 * 100), 4),
               "mapping_error_px_or_pt": mapping_error,
               "missed": int(case["eligible"] and not matches),
               "spurious": len(polygons) - int(bool(matches)),
               "best_iou": round(ious[best], 6) if best is not None else None,
               "boundary_error_px": round(polygons[best].hausdorff_distance(expected), 4) if best is not None else None,
               "area_error_pct": round((polygons[best].area / expected.area - 1) * 100, 4) if best is not None else None}
        rows.append(row)
        assert digest(crop) == case["crop_sha256"], "source crop changed"
    result = {"tag": tag, "workload_sha256": digest(truth_path),
              "evaluator_sha256": digest(__file__), "baseline": baseline,
              "helper_sha256": None if baseline else digest(SKILL / "scripts" / "scan_detail.py"),
              "opencv": cv2.__version__, "numpy": np.__version__,
              "eligible_details": sum(c["eligible"] for c in truth["cases"]),
              "missed": sum(r["missed"] for r in rows), "spurious": sum(r["spurious"] for r in rows),
              "cases": rows,
              "limits": "Generated crops only. Oracle selections are not blind recognition. No real checked plans supplied."}
    (root / f"{tag}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    if not args.tag.replace("-", "").isalnum():
        ap.error("tag must contain only letters, digits or hyphens")
    if args.prepare:
        prepare(BUILD)
    evaluate(BUILD, args.tag, args.baseline)


if __name__ == "__main__":
    main()
