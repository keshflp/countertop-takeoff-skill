# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Deliberately wasteful baseline: safe rectangular strips, one piece per slab."""

from __future__ import annotations

import json
import math
import sys


def run(data: dict) -> dict:
    settings, slab = data["settings"], data["slab"]
    width = slab["lengthIn"] - 2 * settings["slabTrimIn"]
    height = slab["widthIn"] - 2 * settings["slabTrimIn"]
    if width <= 0 or height <= 0:
        raise ValueError("The trim leaves no usable slab.")
    pieces, placements, rectangles, warnings = [], [], [], []
    clearance = max(settings["minSeamToCutoutIn"], settings["minMaterialBesideCutoutIn"])
    for installation in data["installations"]:
        poly, rects = installation["outline"], []
        ys = sorted({y for _, y in poly})
        # Scan horizontal bands; merge identical spans across adjacent bands.
        for y0, y1 in zip(ys, ys[1:]):
            middle = (y0 + y1) / 2
            xs = sorted(x for (x, y), (nx, ny) in zip(poly, poly[1:] + poly[:1])
                        if x == nx and min(y, ny) < middle < max(y, ny))
            for x0, x1 in zip(xs[::2], xs[1::2]):
                prior = next((r for r in rects if r[0] == x0 and r[2] == x1 and r[3] == y0), None)
                if prior is None:
                    rects.append([x0, y0, x1, y1])
                else:
                    prior[3] = y1
        pending = list(rects)
        while pending:
            x0, y0, x1, y1 = pending.pop(0)
            w, h = x1 - x0, y1 - y0
            fits = w <= width and h <= height
            rotates = settings["allowRotate"] and h <= width and w <= height
            if not fits and not rotates:
                # Split only an oversized dimension. Search the 1/16 grid nearest its midpoint.
                vertical = w > width or (settings["allowRotate"] and w > height and w >= h)
                lo, hi = (x0, x1) if vertical else (y0, y1)
                candidates = sorted(range(round(lo * 16) + 1, round(hi * 16)), key=lambda c: (abs(c / 16 - (lo + hi) / 2), c))
                split = None
                for candidate in candidates:
                    c = candidate / 16
                    a = (c, y0, c, y1) if vertical else (x0, c, x1, c)
                    safe = True
                    for cutout in installation["cutouts"]:
                        dx = max(a[0] - cutout["x"] - cutout["w"], cutout["x"] - a[2], 0)
                        dy = max(a[1] - cutout["y"] - cutout["h"], cutout["y"] - a[3], 0)
                        safe &= dx * dx + dy * dy >= clearance * clearance and dx * dx + dy * dy > 0
                    if safe:
                        split = c
                        break
                if split is None:
                    raise ValueError("No safe seam fits beside the cutout.")
                if vertical:
                    pending[:0] = [[x0, y0, split, y1], [split, y0, x1, y1]]
                else:
                    pending[:0] = [[x0, y0, x1, split], [x0, split, x1, y1]]
                continue
            identifier = f"p{len(pieces) + 1}"
            pieces.append({"id": identifier, "installationId": installation["id"],
                           "outline": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]})
            rectangles.append((installation["id"], x0, y0, x1, y1))
            placements.append({"index": len(placements) + 1, "placements": [
                {"pieceId": identifier, "x": 0, "y": 0, "rotated": not fits}]})
        for cutout in installation["cutouts"]:
            for (x, y), (nx, ny) in zip(poly, poly[1:] + poly[:1]):
                dx = max(min(x, nx) - cutout["x"] - cutout["w"], cutout["x"] - max(x, nx), 0)
                dy = max(min(y, ny) - cutout["y"] - cutout["h"], cutout["y"] - max(y, ny), 0)
                if dx * dx + dy * dy < settings["minMaterialBesideCutoutIn"] ** 2:
                    warnings.append(f"{installation['id']}: the cutout leaves little material beside an original edge; confirm with Dad.")
                    break
    seams = []
    for i, (identifier, x, y, right, bottom) in enumerate(rectangles):
        for other, ox, oy, oright, obottom in rectangles[i + 1:]:
            if identifier != other:
                continue
            if right == ox or oright == x:
                a, b = max(y, oy), min(bottom, obottom)
                if a < b:
                    seams.append({"installationId": identifier, "x0": max(x, ox), "y0": a, "x1": max(x, ox), "y1": b})
            if bottom == oy or obottom == y:
                a, b = max(x, ox), min(right, oright)
                if a < b:
                    seams.append({"installationId": identifier, "x0": a, "y0": max(y, oy), "x1": b, "y1": max(y, oy)})
    # Corner seams must obey the same cutout rules as seams introduced by length.
    for seam in seams:
        installation = next(i for i in data["installations"] if i["id"] == seam["installationId"])
        for cutout in installation["cutouts"]:
            dx = max(seam["x0"] - cutout["x"] - cutout["w"], cutout["x"] - seam["x1"], 0)
            dy = max(seam["y0"] - cutout["y"] - cutout["h"], cutout["y"] - seam["y1"], 0)
            if dx * dx + dy * dy < clearance * clearance or dx == dy == 0:
                raise ValueError("The simple corner seam is too close to a cutout.")
    total = sum((r - x) * (b - y) for _, x, y, r, b in rectangles)
    lower = math.ceil(total / (width * height))
    return {"ok": True, "pieces": pieces, "seams": seams, "slabs": placements, "slabCount": len(placements),
            "lowerBound": lower, "provenOptimal": len(placements) == lower, "warnings": warnings}


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        print(json.dumps({"ok": True}))
    else:
        try:
            print(json.dumps(run(json.load(sys.stdin))))
        except (ValueError, KeyError, TypeError) as error:
            print(json.dumps({"ok": False, "error": {"tag": "NaiveLayout", "message": str(error)}}))
