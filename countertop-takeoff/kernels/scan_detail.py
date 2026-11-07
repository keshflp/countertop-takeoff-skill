# /// script
# requires-python = ">=3.10"
# dependencies = ["opencv-python-headless==4.12.0.88", "numpy==2.2.6"]
# ///
"""Suggest closed linework from one selected scan crop for human inspection."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

import cv2
import numpy as np

IDENTITY = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
# This matches inspect_input's 144 DPI PDF render (2 preview pixels per page point).
PDF_PREVIEW_ZOOM = 2


def _same_path(left: Path, right: Path) -> bool:
    if os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve())):
        return True
    try:
        return left.samefile(right)
    except OSError:
        return False


def reject_aliases(inputs: dict[str, Path | str | None], outputs: dict[str, Path]) -> None:
    """Refuse outputs that name an input or another output, including symlinks."""
    input_paths = {name: Path(path).resolve() for name, path in inputs.items() if path is not None}
    output_paths = {name: Path(path).resolve() for name, path in outputs.items()}
    for output_name, output in output_paths.items():
        for input_name, source in input_paths.items():
            if _same_path(output, source):
                raise ValueError(f"{output_name} output aliases {input_name} input")
    names = list(output_paths)
    for index, name in enumerate(names):
        for other_name in names[index + 1:]:
            if _same_path(output_paths[name], output_paths[other_name]):
                raise ValueError(f"{name} and {other_name} outputs alias")


def read_image(path: Path) -> tuple[bytes, np.ndarray]:
    """Decode a raster without changing its stored pixels or channel layout."""
    original_bytes = path.read_bytes()
    image = cv2.imdecode(np.frombuffer(original_bytes, np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim not in (2, 3) or min(image.shape[:2]) < 3:
        raise ValueError("crop must be a readable raster at least 3 pixels wide/high")
    if image.ndim == 3 and image.shape[2] not in (3, 4):
        raise ValueError("crop must use grayscale, RGB or RGBA pixels")
    return original_bytes, image


def grayscale(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    conversion = cv2.COLOR_BGRA2GRAY if image.shape[2] == 4 else cv2.COLOR_BGR2GRAY
    return cv2.cvtColor(image, conversion)


def encode_png(image: np.ndarray) -> bytes:
    ok, data = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("could not encode PNG")
    return data.tobytes()


def page_transform(provenance: dict | None, width: int, height: int) -> list[list[float]] | None:
    """Validate the frozen evaluator's declared page-box provenance format."""
    if provenance is None:
        return None
    if not isinstance(provenance, dict):
        raise ValueError("provenance must be a JSON object")
    source_id, page = provenance.get("source_id"), provenance.get("page")
    bbox, zoom = provenance.get("crop_bbox"), provenance.get("render_zoom")

    def number(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    if (not isinstance(source_id, str) or not source_id.strip() or type(page) is not int or page < 1
            or not isinstance(bbox, list) or len(bbox) != 4 or not all(map(number, bbox))
            or not number(zoom) or zoom <= 0 or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]):
        raise ValueError("provenance needs source_id, positive page, ordered crop_bbox and positive render_zoom")
    if any(abs(value * zoom - round(value * zoom)) > 1e-6 for value in bbox):
        raise ValueError("crop_bbox must align to rendered pixels")
    if round((bbox[2] - bbox[0]) * zoom) != width or round((bbox[3] - bbox[1]) * zoom) != height:
        raise ValueError("crop dimensions disagree with crop_bbox and render_zoom")
    return [[1 / zoom, 0, bbox[0]], [0, 1 / zoom, bbox[1]], [0, 0, 1]]


def preview_provenance(
    source: Path, page: int | None, box: tuple[int, int, int, int]
) -> tuple[dict, list[list[float]] | None]:
    """Compute crop-to-page mapping from inspect_input preview pixels."""
    x0, y0, x1, y1 = box
    source_path = source.resolve()
    if source_path.suffix.lower() == ".pdf":
        if type(page) is not int or page < 1:
            raise ValueError("PDF previews require a positive 1-based page number")
        transform = [
            [1 / PDF_PREVIEW_ZOOM, 0, x0 / PDF_PREVIEW_ZOOM],
            [0, 1 / PDF_PREVIEW_ZOOM, y0 / PDF_PREVIEW_ZOOM],
            [0, 0, 1],
        ]
        provenance = {
            "source": str(source_path),
            "source_id": str(source_path),
            "page": page,
            "crop_box_px": [x0, y0, x1, y1],
            "render_zoom": PDF_PREVIEW_ZOOM,
            "source_space": "rendered_page_points",
            "coordinate_note": (
                "Displayed PDF page after /Rotate, with origin at the visible CropBox top-left and y down. "
                "No conversion to unrotated PDF, annotation or OPS coordinates is supported."
            ),
        }
        return provenance, transform
    if page is not None:
        raise ValueError("image previews use image pixels and have no PDF page number")
    provenance = {
        "source": str(source_path),
        "source_id": str(source_path),
        "page": None,
        "crop_box_px": [x0, y0, x1, y1],
        "crop_to_preview": [[1, 0, x0], [0, 1, y0], [0, 0, 1]],
        "source_space": "image_preview_pixels",
    }
    return provenance, None


def clean_scan(gray: np.ndarray) -> np.ndarray:
    """Boost local contrast and remove isolated specks without resampling."""
    mask = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY_INV, 51, 12)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = np.ones(count, np.uint8)
    keep[0] = 0
    keep[stats[:, cv2.CC_STAT_AREA] <= 2] = 0
    return 255 - keep[labels] * 255


def stroke_middle(inner: np.ndarray, outer: np.ndarray) -> np.ndarray:
    """Suggest a stroke midpoint when corresponding corners are unambiguous."""
    if len(inner) != len(outer):
        return inner
    alternatives = [np.roll(order, offset, axis=0)
                    for order in (outer, outer[::-1]) for offset in range(len(outer))]
    paired = min(alternatives, key=lambda points: float(np.sum((points - inner) ** 2)))
    if np.max(np.linalg.norm(paired - inner, axis=1)) > 6:
        return inner
    return (inner + paired) / 2


def closed_outlines(cleaned: np.ndarray) -> list[dict]:
    """Find enclosed linework; geometry cannot identify a countertop."""
    height, width = cleaned.shape
    contours, hierarchy = cv2.findContours(255 - cleaned, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return []
    proposals = []
    for index, contour in enumerate(contours):
        parent, depth = hierarchy[0, index, 3], 0
        while parent >= 0:
            depth += 1
            parent = hierarchy[0, parent, 3]
        if depth % 2 != 1:
            continue
        area = cv2.contourArea(contour)
        if not 0.005 * width * height <= area <= 0.80 * width * height:
            continue
        polygon = cv2.approxPolyDP(contour, 1.5, True).reshape(-1, 2)
        if not 3 <= len(polygon) <= 12:
            continue
        outer = cv2.approxPolyDP(contours[hierarchy[0, index, 3]], 1.5, True).reshape(-1, 2)
        polygon = stroke_middle(polygon, outer)
        if ((polygon <= 1).any() or (polygon[:, 0] >= width - 2).any()
                or (polygon[:, 1] >= height - 2).any()):
            continue
        proposals.append(polygon.tolist())
    proposals.sort(key=lambda polygon: (min(y for x, y in polygon), min(x for x, y in polygon)))
    return [
        {"id": f"outline-{index + 1}", "status": "requires_inspection",
         "points": [{"name": f"p{point_index + 1}", "px": point}
                    for point_index, point in enumerate(polygon)]}
        for index, polygon in enumerate(proposals)
    ]


def _paths(output_dir: Path, include_crop: bool) -> dict[str, Path]:
    paths = {
        "cleaned": output_dir / "cleaned.png",
        "overlay": output_dir / "suggestions.png",
        "suggestions": output_dir / "suggestions.json",
    }
    if include_crop:
        paths["crop"] = output_dir / "crop.png"
    return paths


def _write_result(
    original_crop: Path,
    original_bytes: bytes,
    gray: np.ndarray,
    output_dir: Path,
    provenance: dict | None,
    transform: list[list[float]] | None,
    inputs: dict[str, Path | str | None],
    crop_copy: bool = False,
) -> dict:
    paths = _paths(output_dir, crop_copy)
    reject_aliases(inputs, paths)
    cleaned = clean_scan(gray)
    suggestions = closed_outlines(cleaned)
    overlay = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    for suggestion in suggestions:
        points = np.array([point["px"] for point in suggestion["points"]], np.int32)
        cv2.polylines(overlay, [points], True, (0, 100, 230), 2)
        x, y = points[0]
        cv2.putText(overlay, suggestion["id"], (int(x), max(14, int(y) - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 60, 200), 1, cv2.LINE_AA)
    cv2.putText(overlay, "UNREVIEWED LINEWORK - inspect ORIGINAL; not measurement proof",
                (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 200), 1, cv2.LINE_AA)
    result = {
        "kind": "scan_detail_suggestions",
        "status": "requires_inspection",
        "review_required": True,
        "original_crop": {
            "path": str(paths.get("crop", original_crop).resolve()),
            "sha256": hashlib.sha256(original_bytes).hexdigest(),
            "size_px": [gray.shape[1], gray.shape[0]],
        },
        "provenance": provenance,
        "provenance_verified": False,
        "suggestion_space": "original_crop_pixels",
        "cleaned_to_original": IDENTITY,
        "original_to_page": transform,
        "cleaned": str(paths["cleaned"].resolve()),
        "overlay": str(paths["overlay"].resolve()),
        "suggestions": suggestions,
        "limitations": [
            "Closed linework can be a cabinet, wall or sink, not a countertop.",
            "Cleanup can erase labels; it cannot restore missing scan detail.",
            "No area, scale, counts or completeness are inferred.",
            "Adopt or edit points explicitly; use written dimensions or ask Dad.",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    if crop_copy:
        paths["crop"].write_bytes(original_bytes)
    paths["cleaned"].write_bytes(encode_png(cleaned))
    paths["overlay"].write_bytes(encode_png(overlay))
    paths["suggestions"].write_text(json.dumps(result, indent=2), encoding="utf-8")
    if not crop_copy and original_crop.read_bytes() != original_bytes:
        raise ValueError("original crop changed while writing suggestions")
    return result


def suggest_detail(crop: str | Path, output_dir: str | Path, provenance: dict | None = None) -> dict:
    """Run the frozen candidate on a crop; provenance is only for offline evaluation."""
    crop_path, output_path = Path(crop).resolve(), Path(output_dir).resolve()
    if not crop_path.is_file():
        raise ValueError("crop must be a readable file")
    original_bytes, image = read_image(crop_path)
    gray = grayscale(image)
    transform = page_transform(provenance, gray.shape[1], gray.shape[0])
    inputs: dict[str, Path | str | None] = {"original crop": crop_path}
    if provenance and isinstance(provenance.get("source"), str):
        inputs["source"] = provenance["source"]
    return _write_result(crop_path, original_bytes, gray, output_path,
                         provenance, transform, inputs)


def validate_box(box: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    if (not isinstance(box, (tuple, list)) or len(box) != 4
            or any(type(value) is not int for value in box)):
        raise ValueError("crop box needs four integer pixel coordinates")
    x0, y0, x1, y1 = box
    if x0 < 0 or y0 < 0 or x1 <= x0 or y1 <= y0 or x1 > width or y1 > height:
        raise ValueError("crop box must be a non-empty rectangle inside the preview")
    return x0, y0, x1, y1


def suggest_preview(
    preview: str | Path,
    source: str | Path,
    output_dir: str | Path,
    box: tuple[int, int, int, int],
    page: int | None = None,
) -> dict:
    """Crop an inspect_input PNG exactly, then map its pixels from its source type."""
    preview_path, source_path = Path(preview).resolve(), Path(source).resolve()
    output_path = Path(output_dir).resolve()
    if not preview_path.is_file() or not source_path.is_file():
        raise ValueError("preview and original source must be readable files")
    if preview_path.suffix.lower() != ".png":
        raise ValueError("use the PNG preview created by inspect_input")
    preview_bytes, image = read_image(preview_path)
    height, width = image.shape[:2]
    x0, y0, x1, y1 = validate_box(box, width, height)
    provenance, transform = preview_provenance(source_path, page, (x0, y0, x1, y1))
    preview_page = page if source_path.suffix.lower() == ".pdf" else 1
    expected_preview = source_path.parent / "previews" / source_path.name / f"page-{preview_page}.png"
    if not _same_path(preview_path, expected_preview):
        raise ValueError("preview must be inspect_input's page preview for the selected source and page")
    crop_bytes = encode_png(image[y0:y1, x0:x1])
    crop_path = output_path / "crop.png"
    result = _write_result(
        crop_path, crop_bytes, grayscale(image[y0:y1, x0:x1]), output_path,
        provenance, transform,
        {"preview": preview_path, "source": source_path}, crop_copy=True,
    )
    if preview_path.read_bytes() != preview_bytes:
        raise ValueError("preview changed while writing suggestions")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crop", help="existing crop PNG; provenance is evaluation-only")
    parser.add_argument("--preview", help="inspect_input preview PNG to crop exactly")
    parser.add_argument("--source", help="original image or PDF for preview provenance")
    parser.add_argument("--page", type=int, help="1-based PDF page; image previews have no page")
    parser.add_argument("--box", nargs=4, type=int, metavar=("X0", "Y0", "X1", "Y1"),
                        help="integer preview-pixel bounds, with exclusive X1 and Y1")
    parser.add_argument("--out-dir", help="separate output directory")
    parser.add_argument("--selfcheck", action="store_true")
    args = parser.parse_args(argv)
    if args.selfcheck:
        print('{"ok":true}')
        return 0
    if not args.out_dir or bool(args.crop) == bool(args.preview):
        parser.error("choose exactly one of --crop or --preview and provide --out-dir")
    try:
        if args.preview:
            if not args.source or args.box is None:
                parser.error("--preview requires --source and --box; it computes provenance")
            result = suggest_preview(args.preview, args.source, args.out_dir, tuple(args.box), args.page)
        else:
            if args.source or args.page is not None or args.box:
                parser.error("--source, --page and --box belong with --preview")
            result = suggest_detail(args.crop, args.out_dir)
    except (OSError, ValueError, cv2.error) as exc:
        parser.exit(2, f"scan detail refused: {exc}\n")
    print(f"{len(result['suggestions'])} unreviewed suggestions; inspect {result['overlay']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
