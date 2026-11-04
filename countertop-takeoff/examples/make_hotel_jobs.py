# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1"]
# ///
"""Build the canonical V3 job spec for the HOTEL fixture (P0.7).

Every page is /Rotate 270, so all agent selections (seeds, viewport boxes,
word/segment ids) live in DISPLAYED space while the fixture was drawn in
portrait content space. This builder performs the same work the agent does
on a real rotated set:

  1. opens the extracted geometry and maps content-space coordinates to
     displayed space via page.rotation_matrix
  2. locates boundary segment ids + dimension-label word ids by proximity
  3. renders the bitmap schedule crop + clubroom scans and computes their
     hashes (evidence integrity)
  4. assembles the full V3 spec: schedule evidence (image kind), room
     inventory with dedupe, assemblies/pieces with edge/splash/cutout runs
     and cross-sheet source links (A-450 lengths <-> A-504 sections),
     package exclusion (GR FF&E), image-route regions, the intentionally
     omitted room 203 (coverage callout), and the unusable bar scan

Usage:
    uv run examples/make_hotel_jobs.py --pdf build/hotel.pdf \
        --geometry build/hotel.geometry.json --out build/hotel.jobs.json \
        --workdir build/hotel_evidence

The spec intentionally OMITS room 203 (its 15 SF stays blank behind a
coverage callout) and measures everything else; GR rooms are package
excluded and reported separately.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys

import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SKILL, "scripts"))
from preflight_lib import file_sha256 as sha256_file


def render_crop_sha(pdf, page_no, crop_bbox, zoom):
    """Render a displayed-space crop the same way audit.py re-renders it."""
    doc = pymupdf.open(pdf)
    pix = doc[page_no - 1].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom),
                                      clip=pymupdf.Rect(*crop_bbox))
    doc.close()
    return hashlib.sha256(pix.tobytes("png")).hexdigest()


def render_crop_png(pdf, page_no, crop_bbox, zoom, out_png):
    doc = pymupdf.open(pdf)
    pix = doc[page_no - 1].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom),
                                      clip=pymupdf.Rect(*crop_bbox))
    doc.close()
    pix.save(out_png)
    return out_png


class Display:
    """Content-space -> displayed-space mapping per page (rotation)."""

    def __init__(self, pdf):
        doc = pymupdf.open(pdf)
        self.matrices = {}
        for p in doc:
            self.matrices[p.number + 1] = p.rotation_matrix
        doc.close()

    def xy(self, page_no, x, y):
        q = pymupdf.Point(x, y) * self.matrices[page_no]
        return (q.x, q.y)

    def poly(self, page_no, pts):
        return [self.xy(page_no, x, y) for x, y in pts]


def find_boundary_segments(geo_page, content_poly, disp, tol=2.5):
    """Segment ids forming the drawn polygon: endpoints must land on the
    displayed corners."""
    corners = disp.poly(geo_page["page"], content_poly)
    used = []
    seen_pairs = set()
    for s in geo_page["segments"]:
        a = (round(s["x0"], 2), round(s["y0"], 2))
        b = (round(s["x1"], 2), round(s["y1"], 2))
        key = tuple(sorted([a, b]))
        if key in seen_pairs:
            continue  # wall + counter share an edge: one segment only
        ends = [a, b]
        hits = 0
        for e in ends:
            if any(abs(e[0] - c[0]) <= tol and abs(e[1] - c[1]) <= tol
                   for c in corners):
                hits += 1
        if hits == 2:
            used.append((hits, s["id"]))
            seen_pairs.add(key)
    # corner coverage: every corner must be touched; keep exactly the
    # segments that touch corners (counter outlines are 4 segments)
    ids = [sid for hits, sid in sorted(used, reverse=True)]
    return ids


def find_word_ids(geo_page, disp, page_no, x, y, text_prefix=None, tol=12.0):
    """Word ids near a displayed point (dimension labels)."""
    px, py = disp.xy(page_no, x, y)
    out = []
    for w in geo_page["words"]:
        cx, cy = (w["x0"] + w["x1"]) / 2.0, (w["y0"] + w["y1"]) / 2.0
        if abs(cx - px) <= tol and abs(cy - py) <= tol:
            if text_prefix is None or str(w["t"]).startswith(text_prefix):
                out.append(w["id"])
    return sorted(out)


def find_dim_span(geo_page, disp, page_no, x1, y1, x2, y2, words_xy):
    """Calibration span for a dimension line + its label words."""
    a = disp.xy(page_no, x1, y1)
    b = disp.xy(page_no, x2, y2)
    tol = 2.5
    ids = []
    for s in geo_page["segments"]:
        for e in ((s["x0"], s["y0"]), (s["x1"], s["y1"])):
            if (abs(e[0] - a[0]) <= tol and abs(e[1] - a[1]) <= tol) or \
               (abs(e[0] - b[0]) <= tol and abs(e[1] - b[1]) <= tol):
                ids.append(s["id"])
                break
    wids = []
    for (wx, wy, prefix) in words_xy:
        wids.extend(find_word_ids(geo_page, disp, page_no, wx, wy,
                                  text_prefix=prefix))
    return {"word_ids": sorted(set(wids)), "seg_ids": sorted(set(ids)),
            "seg_mid": ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)}


# ---------------------------------------------------------------- geometry
ROOM_W, ROOM_H = 160, 144
CTR_A_W, CTR_B_W, CTR_GR_W, CTR_H = 108, 144, 72, 45
GR_CTR_H = 36

# floor plan room origins (content space), from hotel_fixture.py
ROOMS = {
    "101": (60, 150, "A"), "102": (240, 150, "A"), "103": (60, 340, "A"),
    "104": (240, 340, "GR"),
    "201": (60, 150, "A"), "202": (240, 150, "A"), "203": (420, 150, "A"),
    "204": (60, 340, "B"), "205": (240, 340, "B"), "206": (420, 340, "GR"),
}


def counter_poly(room):
    x0, y0, rtype = ROOMS[room]
    w = {"A": CTR_A_W, "B": CTR_B_W, "GR": CTR_GR_W}[rtype]
    h = GR_CTR_H if rtype == "GR" else CTR_H
    return [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]


def build(pdf, geometry, out, workdir):
    os.makedirs(workdir, exist_ok=True)
    disp = Display(pdf)
    geo = json.load(open(geometry, encoding="utf-8"))
    pages = {p["page"]: p for p in geo["pages"]}
    sha = sha256_file(pdf)

    def ctr_region(room, page_no, region_id, viewport="main"):
        poly = counter_poly(room)
        x0, y0 = ROOMS[room][0], ROOMS[room][1]
        seed_content = (x0 + 6, y0 + 6)
        seed_disp = disp.xy(page_no, *seed_content)
        seg_ids = find_boundary_segments(pages[page_no], poly, disp)
        return {
            "region_id": region_id, "kind": "base", "type": ROOMS[room][2],
            "variant": None, "page": page_no, "source_id": "plans",
            "sheet": {"3": "A-302", "4": "A-303", "5": "A-304"}[str(page_no)],
            "viewport": viewport,
            "boundary": {"seg_ids": seg_ids},
            "seed": [round(seed_disp[0], 3), round(seed_disp[1], 3)],
            "expected_sf_range": [3, 40],
        }

    # ---------------------------------------------------------- regions
    regions = [
        ctr_region("101", 3, "room-101:counter"),
        ctr_region("102", 3, "room-102:counter"),
        ctr_region("103", 3, "room-103:counter"),
        ctr_region("104", 3, "gr-104:counter"),
        ctr_region("201", 4, "room-201:counter"),
        ctr_region("202", 4, "room-202:counter"),
        # room 203 INTENTIONALLY OMITTED -> coverage callout, 15 SF blank
        ctr_region("204", 4, "room-204:counter"),
        ctr_region("205", 4, "room-205:counter"),
        ctr_region("206", 4, "gr-206:counter"),
    ]
    # room 204 vanity on the A-304 bath viewport (9 pt/ft)
    vanity_poly = [(90, 170), (126, 170), (126, 188), (90, 188)]
    vanity_seed = disp.xy(5, 100, 176)
    regions.append({
        "region_id": "room-204:vanity", "kind": "base", "type": "B",
        "variant": None, "page": 5, "source_id": "plans", "sheet": "A-304",
        "viewport": "bath",
        "boundary": {"seg_ids": find_boundary_segments(pages[5],
                                                       vanity_poly, disp)},
        "seed": [round(vanity_seed[0], 3), round(vanity_seed[1], 3)],
        "expected_sf_range": [4, 12],
    })
    return regions, disp, pages, sha


def build_image_routes(pdf, workdir):
    """Render the clubroom scans as crops + agent-style measurements.

    clubroom: legible scan inserted at display rect (40,160)-(380,382);
    the pixmap was rendered at zoom 2 (1224x800 px), so the display scale
    is sx = 340/1224, sy = 222/800 and crop px (zoom 3) follow exactly.
    bar: deliberately unusable low-res blob (zoom 0.15, 91.8x60 px into
    (330,160)-(560,400)) -> ~20 px/ft -> below the usable threshold ->
    BLANK + callout (partial completion proof).

    V4 (P0.2): every measurement records its crop PROVENANCE (source_id,
    page, crop_bbox, render_zoom - the crop binds to source/page/transform)
    and renders its OVERLAY PROOF (mandatory for route acceptance).
    """
    import image_measure

    def placed( rect, pixmap_pt_w, pixmap_pt_h, zoom_img):
        sx = (rect[2] - rect[0]) / (pixmap_pt_w * zoom_img)
        sy = (rect[3] - rect[1]) / (pixmap_pt_h * zoom_img)
        return sx, sy

    # ---- clubroom (legible) ------------------------------------------
    box = [40.0, 160.0, 380.0, 382.0]
    zoom = 3.0
    crop = render_crop_png(pdf, 9, box, zoom,
                           os.path.join(workdir, "clubroom_crop.png"))
    sx, sy = placed(box, 612, 400, 2.0)

    def cpx(x, y):
        """scratch-content pt -> crop px (scratch drawn at 18 pt/ft)."""
        px_x, px_y = x * 2.0, y * 2.0
        return [(px_x * sx) * zoom,
                (px_y * sy) * zoom]

    anchors = [
        {"label": "12'-0\"", "p1": cpx(60, 100), "p2": cpx(276, 100)},
        {"label": "2'-0\"", "p1": cpx(60, 120), "p2": cpx(60, 156)},
    ]
    pts = [{"name": "p1", "px": cpx(60, 120)},
           {"name": "p2", "px": cpx(276, 120)},
           {"name": "p3", "px": cpx(276, 156)},
           {"name": "p4", "px": cpx(60, 156)}]
    club = image_measure.measure_from_points(anchors, pts)
    club["crop"] = crop
    club["crop_sha256"] = hashlib.sha256(open(crop, "rb").read()).hexdigest()
    club["provenance"] = {"source_id": "plans", "page": 9,
                          "crop_bbox": box, "render_zoom": zoom}
    club_overlay = os.path.join(workdir, "clubroom_overlay.png")
    image_measure.render_overlay(crop, club, club_overlay)
    club["overlay"] = club_overlay
    club_path = os.path.join(workdir, "clubroom_measure.json")
    json.dump(club, open(club_path, "w"), indent=1)

    # ---- bar (unusable) ----------------------------------------------
    bbox = [330.0, 160.0, 560.0, 400.0]
    bar_crop = render_crop_png(pdf, 9, bbox, 3.0,
                               os.path.join(workdir, "bar_crop.png"))
    bsx, bsy = placed(bbox, 612, 400, 0.15)

    def bpx(x, y):
        return [x * 0.15 * bsx * 3.0, y * 0.15 * bsy * 3.0]

    bar_anchors = [
        {"label": "5'-0\"", "p1": bpx(60, 100), "p2": bpx(150, 100)},
    ]
    bar_pts = [{"name": "p1", "px": bpx(60, 120)},
               {"name": "p2", "px": bpx(150, 120)},
               {"name": "p3", "px": bpx(150, 156)}]
    bar = image_measure.measure_from_points(bar_anchors, bar_pts)
    bar["crop"] = bar_crop
    bar["crop_sha256"] = hashlib.sha256(open(bar_crop, "rb").read()).hexdigest()
    bar["provenance"] = {"source_id": "plans", "page": 9,
                         "crop_bbox": bbox, "render_zoom": 3.0}
    bar_overlay = os.path.join(workdir, "bar_overlay.png")
    image_measure.render_overlay(bar_crop, bar, bar_overlay)
    bar["overlay"] = bar_overlay
    bar_path = os.path.join(workdir, "bar_measure.json")
    json.dump(bar, open(bar_path, "w"), indent=1)
    return club_path, bar_path


def schedule_evidence(pdf, geo, workdir):
    """Image-kind schedule evidence for the bitmap ROOM DISTRIBUTION table."""
    page2 = next(p for p in geo["pages"] if p["page"] == 2)
    raster = next(r for r in page2.get("content_regions")
                  if r.get("kind") == "raster")
    crop_bbox = raster["bbox"]
    zoom = 3.0
    # Displayed page is rotated 270 degrees. Rotate its clipped render 90
    # degrees clockwise to restore upright table text; boxes are crop pixels.
    rotation = 90
    crop_png = os.path.join(workdir, "schedule_crop.png")
    with pymupdf.open(pdf) as doc:
        matrix = pymupdf.Matrix(zoom, zoom).prerotate(rotation)
        pix = doc[1].get_pixmap(matrix=matrix, clip=pymupdf.Rect(*crop_bbox))
        pix.save(crop_png)
    crop_sha = hashlib.sha256(open(crop_png, "rb").read()).hexdigest()
    # Synthetic ground truth, NOT an OCR/recognition result. Independent
    # transcription is the agent's job. A hash proves pixel identity only.
    columns = ["FLOOR", "TYPE A", "TYPE B", "TYPE GR", "TOTAL"]
    xs = [60, 140, 240, 340, 440, 540]
    values = [["FLOOR 1", "3", "0", "1", "4"],
              ["FLOOR 2", "3", "2", "1", "6"],
              ["TOTAL", "6", "2", "2", "10"]]
    scale = (crop_bbox[3] - crop_bbox[1]) / 612 * zoom
    cells = [{"row": r + 1, "col": col, "text": values[r][c],
              "box": [round(v * scale, 2) for v in
                      (xs[c] + 3, 103 + r * 40, xs[c + 1] - 3, 137 + r * 40)]}
             for r in range(3) for c, col in enumerate(columns)]
    with pymupdf.open() as preview:
        page = preview.new_page(width=pix.width, height=pix.height)
        page.insert_image(page.rect, filename=crop_png)
        for c in cells:
            page.draw_rect(pymupdf.Rect(*c["box"]), color=(1, 0, 0))
        page.get_pixmap().save(os.path.join(workdir, "schedule_cells.png"))
    return {
        "kind": "image",
        "crop_image": os.path.abspath(crop_png),
        "crop_sha256": crop_sha,
        "render_zoom": zoom,
        "render_rotation": rotation,
        "transform": "displayed clip -> zoom 3 -> clockwise 90 -> crop-local pixels",
        "crop_bbox": crop_bbox,
        "headers": ["FLOOR", "TYPE A", "TYPE B", "TYPE GR", "FLOOR TOTAL"],
        "cells": cells,
        "uncertain_cells": [],
        "note": "Synthetic truth supplied by fixture generator, not recognition. "
                "Crop hash proves pixel identity only; transcription is the agent's job. "
                "schedule_cells.png previews boxes on the upright schedule_crop.png.",
    }, crop_png


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--geometry", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--crop-relative-to", default=None,
                    help="directory the evidence crops are referenced from"
                         " (default: the spec's own folder)")
    args = ap.parse_args(argv)
    if not os.path.exists(args.geometry):
        subprocess.run([sys.executable,
                        os.path.join(SKILL, "scripts", "extract_geometry.py"),
                        args.pdf, "--pages", "all",
                        "--out", args.geometry], check=False,
                       cwd=SKILL)
    regions, disp, pages, sha = build(args.pdf, args.geometry, args.out,
                                      args.workdir)
    club_path, bar_path = build_image_routes(args.pdf, args.workdir)
    ev, crop_png = schedule_evidence(args.pdf, geo=json.load(
        open(args.geometry, encoding="utf-8")), workdir=args.workdir)

    base = args.crop_relative_to or os.path.dirname(os.path.abspath(args.out))
    def rel(p):
        return os.path.relpath(p, base)

    spec = empty_spec(args, sha, ev, rel)
    complete_spec(spec, regions, disp, pages, club_path, bar_path, rel)
    json.dump(spec, open(args.out, "w", encoding="utf-8"), indent=1)
    print(f"wrote {args.out}: {len(spec['regions'])} region(s),"
          f" {len(spec['assemblies'])} assembly(ies),"
          f" {len(spec['pieces'])} piece(s)")
    return 0


def empty_spec(args, sha, ev, rel):
    """The evidence document skeleton (schedule + inventory + policy)."""
    return {
        "schema": "countertop-takeoff/v3",
        "sources": [{"source_id": "plans", "path": args.pdf,
                     "sha256": sha, "kind": "pdf"}],
        "geometry": args.geometry,
        "mode": "repeated_types",
        "policy": {"gross_area": "gross", "packages": {"exclude": ["FFE"]},
                   "declarations": [
                       {"kind": "scope_omission",
                        "detail": "room 203 (TYPE A, floor 2) intentionally"
                                  " omitted from this pass - its 15 SF stays"
                                  " blank behind a coverage callout"},
                       {"kind": "do_not_scale",
                        "detail": "sheets say DO NOT SCALE DRAWINGS; piece"
                                  " dims are STATED dimensions from A-450"
                                  " lengths joined to A-504 sections"}]},
        "sheet_index": {"source_id": "plans", "page": 1,
                        "lists": ["A-300", "A-301", "A-302", "A-303",
                                  "A-304", "A-305", "A-306", "A-450",
                                  "A-504", "A-511"]},
        "schedule": {
            "page": 2, "sheet": "A-301", "source_id": "plans",
            "evidence": dict(ev, crop_image=rel(ev["crop_image"])),
            "types": [
                {"type": "A", "count": 6, "row_text": "bitmap TOTAL row:"
                 " TYPE A 6 (floor 1: 3, floor 2: 3)", "word_boxes": [],
                 "count_cells": [{"row": 1, "col": "TYPE A"},
                                 {"row": 2, "col": "TYPE A"}]},
                {"type": "B", "count": 2, "row_text": "bitmap TOTAL row:"
                 " TYPE B 2 (floor 2: 2)", "word_boxes": [],
                 "count_cells": [{"row": 1, "col": "TYPE B"},
                                 {"row": 2, "col": "TYPE B"}]},
                {"type": "GR", "count": 2, "row_text": "bitmap TOTAL row:"
                 " TYPE GR 2 (excluded package, reported separately)",
                 "word_boxes": [],
                 "count_cells": [{"row": 1, "col": "TYPE GR"},
                                 {"row": 2, "col": "TYPE GR"}]}],
            "variants": [],
            "stated_totals": {"per_floor": {"1": 4, "2": 6}, "project": 10},
            "room_inventory": {
                "rooms": [
                    {"room": "101", "type": "A", "page": 3},
                    {"room": "102", "type": "A", "page": 3},
                    {"room": "103", "type": "A", "page": 3},
                    {"room": "104", "type": "GR", "page": 3},
                    {"room": "201", "type": "A", "page": 4},
                    {"room": "202", "type": "A", "page": 4},
                    {"room": "203", "type": "A", "page": 4},
                    {"room": "204", "type": "B", "page": 4},
                    {"room": "205", "type": "B", "page": 4},
                    {"room": "206", "type": "GR", "page": 4}],
                "per_type_counts": {"A": 6, "B": 2, "GR": 2},
                "dedupe_notes": [
                    "room 204 appears on the floor 2 plan AND enlarged on"
                    " A-304 - same room, counted once",
                    "room tags read from word-level TYPE tags on A-302/A-303"],
                "count_resolutions": {}},
        },
    }


def _vp_span(pages, disp, page_no, x1, y1, x2, y2, labels, real_ft=None):
    gp = pages[page_no]
    span = find_dim_span(gp, disp, page_no, x1, y1, x2, y2, labels)
    out = {"word_ids": span["word_ids"], "seg_ids": span["seg_ids"]}
    if real_ft is not None:
        out["real_ft"] = real_ft
    return out


def vp_box(disp, page_no, x0, y0, x1, y1):
    c = disp.poly(page_no, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
    xs = [p[0] for p in c]
    ys = [p[1] for p in c]
    return [round(min(xs), 2), round(min(ys), 2),
            round(max(xs), 2), round(max(ys), 2)]


def complete_spec(spec, regions, disp, pages, club_path, bar_path, rel):
    """Calibrations, image regions, scope, assemblies, pieces."""
    # ------------------------------------------------------- calibrations
    spec["calibrations"] = [
        {"source_id": "plans", "page": 3, "viewport": "main",
         "viewport_box": vp_box(disp, 3, 20, 100, 600, 500),
         "spans": [
             _vp_span(pages, disp, 3, 60, 118, 420, 118, [(240, 109, "20")]),
             _vp_span(pages, disp, 3, 36, 150, 36, 294, [(24, 224, "8")]),
             _vp_span(pages, disp, 3, 60, 470, 168, 470, [(114, 464, "6")])]},
        {"source_id": "plans", "page": 4, "viewport": "main",
         "viewport_box": vp_box(disp, 4, 20, 100, 612, 560),
         "spans": [
             _vp_span(pages, disp, 4, 60, 118, 600, 118, [(330, 109, "30")]),
             _vp_span(pages, disp, 4, 588, 340, 588, 484, [(606, 414, "8")]),
             _vp_span(pages, disp, 4, 60, 524, 168, 524, [(114, 518, "6")])]},
        {"source_id": "plans", "page": 5, "viewport": "bath",
         "viewport_box": vp_box(disp, 5, 60, 130, 230, 260),
         "spans": [
             _vp_span(pages, disp, 5, 90, 152, 126, 152, [(108, 146, "4")]),
             _vp_span(pages, disp, 5, 134, 170, 134, 188, [(150, 182, "2")])]},
        {"source_id": "plans", "page": 5, "viewport": "detail",
         "viewport_box": vp_box(disp, 5, 280, 130, 430, 230),
         "spans": [
             _vp_span(pages, disp, 5, 300, 205, 382, 205, [(341, 199, "2")]),
             _vp_span(pages, disp, 5, 392, 170, 392, 175,
                      [(410, 173, "1")])]},
        {"source_id": "plans", "page": 6, "viewport": "elevations",
         "viewport_box": vp_box(disp, 6, 40, 130, 580, 330),
         "spans": [
             _vp_span(pages, disp, 6, 80, 250, 242, 250, [(161, 244, "6")]),
             _vp_span(pages, disp, 6, 320, 250, 536, 250, [(428, 244, "8")])]},
        {"source_id": "plans", "page": 7, "viewport": "sections",
         "viewport_box": vp_box(disp, 7, 60, 180, 560, 320),
         "spans": [
             _vp_span(pages, disp, 7, 150, 268, 226.5, 268,
                      [(165, 262, "2"), (192, 262, "1/2")]),
             _vp_span(pages, disp, 7, 236, 240, 236, 244.5,
                      [(250, 246, "1")]),
             _vp_span(pages, disp, 7, 142, 228, 142, 240,
                      [(104, 238, "4")])]},
    ]

    # ------------------------------------------------- image-route regions
    regions.append({
        "region_id": "clubroom:counter", "kind": "base", "type": "CLUB",
        "variant": None, "page": 9, "source_id": "plans", "sheet": "A-306",
        "route": "image", "image_measurement": rel(club_path),
        "expected_sf_range": [15, 35]})
    regions.append({
        "region_id": "clubroom:bar", "kind": "base", "type": "CLUB",
        "variant": None, "page": 9, "source_id": "plans", "sheet": "A-306",
        "route": "image", "image_measurement": rel(bar_path),
        "expected_sf_range": [3, 15]})
    spec["regions"] = regions

    # -------------------------------------------------------------- scope
    spec["scope"] = {"pages": [
        {"source_id": "plans", "page": 1, "sheet": "A-300",
         "disposition": "intentionally_skipped",
         "reason": "sheet index page"},
        {"source_id": "plans", "page": 2, "sheet": "A-301",
         "disposition": "intentionally_skipped",
         "reason": "bitmap room distribution - transcribed into schedule"
                   " evidence (crop hash verified), no area scope"},
        {"source_id": "plans", "page": 3, "sheet": "A-302",
         "disposition": "measured",
         "expected_regions": ["room-101:counter", "room-102:counter",
                              "room-103:counter", "gr-104:counter"]},
        {"source_id": "plans", "page": 4, "sheet": "A-303",
         "disposition": "measured",
         "expected_regions": ["room-201:counter", "room-202:counter",
                              "room-204:counter", "room-205:counter",
                              "gr-206:counter"]},
        {"source_id": "plans", "page": 5, "sheet": "A-304",
         "disposition": "measured",
         "expected_regions": ["room-204:vanity"]},
        {"source_id": "plans", "page": 6, "sheet": "A-450",
         "disposition": "intentionally_skipped",
         "reason": "elevations - run LENGTHS feed piece source links (no"
                   " area scope); dims quoted as stated values"},
        {"source_id": "plans", "page": 7, "sheet": "A-504",
         "disposition": "intentionally_skipped",
         "reason": "sections - depth/thickness/splash feed piece source"
                   " links (no area scope)"},
        {"source_id": "plans", "page": 8, "sheet": "A-301",
         "disposition": "superseded",
         "reason": "WRONG duplicate title block: marketing rendering"
                   " mislabeled A-301; no construction scope"},
        {"source_id": "plans", "page": 9, "sheet": "A-306",
         "disposition": "measured",
         "expected_regions": ["clubroom:counter", "clubroom:bar"]},
    ]}

    # --------------------------------------------------------- assemblies
    def ctr_piece(room, finish, cutout=False, splash_len_in=72.0,
                  aid=None):
        aid = aid or f"room-{room}"
        pid = f"{aid}:counter"
        piece = {
            "piece_id": pid, "assembly_id": aid,
            "route": "geometry", "region_id": pid, "finish_tag": finish,
            "edge_runs": [{"profile": "eased", "exposure": "front",
                           "length_in": splash_len_in,
                           "source": {"source_id": "plans", "page": 6,
                                      "kind": "elevation",
                                      "note": "run length per A-450"}}],
            "splash_runs": [{"height_in": 4, "length_in": splash_len_in,
                             "handing": "LH", "returns_in": 6,
                             "source": {"source_id": "plans", "page": 7,
                                        "kind": "section",
                                        "note": "splash 4 in high per"
                                                " A-504"}}],
            "source_links": {
                "length": {"source_id": "plans", "page": 6,
                           "kind": "elevation"},
                "depth": {"source_id": "plans", "page": 7, "kind": "section",
                          "note": "depth 25 1/2 in per A-504"},
                "thickness": {"source_id": "plans", "page": 7,
                              "kind": "section"}},
        }
        if cutout:
            piece["cutouts"] = [{"kind": "sink", "ea": 1,
                                 "source": {"source_id": "plans", "page": 4,
                                            "kind": "plan"}}]
        return piece

    assemblies, pieces = [], []
    # room 203 is deliberately ABSENT here: the room inventory knows it,
    # the assemblies don't cover it -> coverage callout proves the guard
    for room, rtype, finish in (("101", "A", "PL"), ("102", "A", "PL"),
                                ("103", "A", "PL"), ("201", "A", "PL"),
                                ("202", "A", "PL")):
        aid = f"room-{room}"
        pieces.append(ctr_piece(room, finish,
                                splash_len_in=72.0))
        assemblies.append({
            "assembly_id": aid, "room": room, "type": rtype,
            "variant": None, "package": "millwork", "finish_tag": finish,
            "width_in": 72, "depth_in": 25.5, "height_in": 36,
            "handing": None,
            "quantity_basis": {"mode": "enumerated"},
            "pieces": [f"{aid}:counter"],
            "sources": [{"source_id": "plans",
                         "page": 3 if room[0] == "1" else 4}]})
    for room in ("204", "205"):
        aid = f"room-{room}"
        pieces.append(ctr_piece(room, "ST", cutout=True, splash_len_in=96.0))
        assemblies.append({
            "assembly_id": aid, "room": room, "type": "B", "variant": None,
            "package": "millwork", "finish_tag": "ST",
            "width_in": 96, "depth_in": 25.5, "height_in": 36,
            "handing": "RH" if room == "205" else "LH",
            "quantity_basis": {"mode": "enumerated"},
            "pieces": [f"{aid}:counter"],
            "sources": [{"source_id": "plans", "page": 4}]})
    # room 204 vanity piece rides in the 204 assembly
    pieces.append({
        "piece_id": "room-204:vanity", "assembly_id": "room-204",
        "route": "geometry", "region_id": "room-204:vanity",
        "finish_tag": "ST",
        "edge_runs": [{"profile": "eased", "exposure": "front",
                       "length_in": 48}],
        "source_links": {"depth": {"source_id": "plans", "page": 7,
                                   "kind": "section"}}})
    asm204 = next(a for a in assemblies if a["assembly_id"] == "room-204")
    asm204["pieces"].append("room-204:vanity")
    for room in ("104", "206"):
        aid = f"gr-{room}"
        pieces.append(ctr_piece(room, "W", splash_len_in=48.0, aid=aid))
        assemblies.append({
            "assembly_id": aid, "room": room, "type": "GR", "variant": None,
            "package": "FFE", "finish_tag": "W",
            "width_in": 48, "depth_in": 25.5, "height_in": 36,
            "handing": None,
            "quantity_basis": {"mode": "enumerated"},
            "pieces": [f"{aid}:counter"],
            "sources": [{"source_id": "plans",
                         "page": 3 if room == "104" else 4}]})
    # out-of-series clubroom assembly (image-route piece; edge unknown)
    pieces.append({
        "piece_id": "clubroom:counter:piece", "assembly_id": "clubroom",
        "route": "geometry", "region_id": "clubroom:counter",
        "finish_tag": "PL",
        "source_links": {"length": {"source_id": "plans", "page": 9,
                                    "kind": "elevation"}}})
    pieces.append({
        "piece_id": "clubroom:bar:piece", "assembly_id": "clubroom",
        "route": "geometry", "region_id": "clubroom:bar",
        "finish_tag": "PL"})
    assemblies.append({
        "assembly_id": "clubroom", "room": None, "type": "CLUB",
        "variant": None, "package": "public_BOH", "finish_tag": "PL",
        "width_in": None, "depth_in": 24, "height_in": 36, "handing": None,
        "quantity_basis": {"mode": "enumerated"},
        "pieces": ["clubroom:counter:piece", "clubroom:bar:piece"],
        "sources": [{"source_id": "plans", "page": 9}]})
    spec["assemblies"] = assemblies
    spec["pieces"] = pieces


if __name__ == "__main__":
    sys.exit(main() or 0)
