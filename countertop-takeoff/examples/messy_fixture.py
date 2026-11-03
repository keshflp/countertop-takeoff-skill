# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1"]
# ///
"""Generate the MESSY drawing-set fixture (V2): known areas, hostile details.

Called via `uv run examples/make_fixture.py --case messy --out <path>`.
Pages (all coordinates in PDF points; two scales on one sheet on purpose):

  1  A-001  unit schedule: floor columns/totals, TYPE A x5 + TYPE A (ADA) x1
            + TYPE B x4 per floor, PROJECT TOTAL 20; notes state a 25-inch
            counter depth while every plan DRAWS 30 in. (plan/spec conflict)
  2  A-201  TYPE A floor plan, page rotation 90, TWO viewports at different
            scales: unit plan 1/4"=1'-0" (18 pt/ft) with kitchen run + island
            (with a sink loop) and adjacent bedroom/closet linework; bath
            enlargement 1/8"=1'-0" (9 pt/ft) with vanity and floating tile
            hatch
  3  A-202  TYPE A ADA unit plan (18 pt/ft): reduced kitchen + vanity
  4  A-203  TYPE B floor plan (18 pt/ft): L kitchen + peninsula, sink loop,
            vanity; split dimension text (12'- + 0") and a fractional
            dimension (20'-6 1/2")
  5  A-201  REV B duplicate of page 2 with revision marks (sheet-id conflict)
  6  A-204  clubroom amenity plan as a SEARCHABLE RASTER (image + invisible
            OCR text): looks indexable, is unmeasurable

KNOWN TRUTH (gross policy): A 25+18+12 = 55 SF x10, ADA 20+12 = 32 SF x2,
B 35+12 = 47 SF x8 -> project total 990.00 SF (20 units).
Net-of-declared-cutouts variant: B sink 3 SF subtracted -> B 44 SF x8,
total 966.00 SF.
"""

import argparse
import os

import pymupdf

PT_PER_FT_MAIN = 18.0   # 1/4" = 1'-0"
PT_PER_FT_BATH = 9.0    # 1/8" = 1'-0"
FONT = "helv"
INK = (0, 0, 0)


def shoelace(pts):
    s = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return abs(s) / 2.0


def text_centered(page, cx, baseline_y, s, size=9, font=FONT,
                  render_mode=0):
    w = pymupdf.get_text_length(s, fontname=font, fontsize=size)
    page.insert_text((cx - w / 2.0, baseline_y), s, fontname=font,
                     fontsize=size, color=INK, render_mode=render_mode)


def text_left(page, x, baseline_y, s, size=9, font=FONT, render_mode=0):
    page.insert_text((x, baseline_y), s, fontname=font, fontsize=size,
                     color=INK, render_mode=render_mode)


def polygon(page, pts, width=1.0, close=True):
    n = len(pts)
    last = n if close else n - 1
    for i in range(last):
        page.draw_line(pts[i], pts[(i + 1) % n], color=INK, width=width)


def dimension(page, p1, p2, label, text_cx, baseline_y, size=9):
    page.draw_line(p1, p2, color=INK, width=0.75)
    horizontal = abs(p1[1] - p2[1]) < 1e-6
    for p in (p1, p2):
        if horizontal:
            page.draw_line((p[0], p[1] - 4), (p[0], p[1] + 4), color=INK,
                           width=0.75)
        else:
            page.draw_line((p[0] - 3, p[1]), (p[0] + 3, p[1]), color=INK,
                           width=0.75)
    if label is not None:
        text_centered(page, text_cx, baseline_y, label, size)


# ----------------------------------------------------------- page 1: schedule
def page_schedule(doc):
    p = doc.new_page(width=612, height=792)
    text_centered(p, 306, 90, "UNIT SCHEDULE - FLOORS 1-2", size=14)
    text_centered(p, 306, 110, "SHEET A-001", size=10)
    text_centered(p, 306, 128, "PROJECT: RIVERSIDE EXTENSION, BUILDING 3 "
                  "(SYNTHETIC MESSY FIXTURE - NOT A REAL PROJECT)", size=8)
    cols = [72, 140, 240, 340, 440, 540]
    rows = [200, 230, 260, 290, 320]
    header = ["FLOOR", "TYPE A", "TYPE A (ADA)", "TYPE B", "FLOOR TOTAL"]
    data = [
        ["FLOOR 1", "5", "1", "4", "10"],
        ["FLOOR 2", "5", "1", "4", "10"],
    ]
    for y in rows:
        p.draw_line((cols[0], y), (cols[-1], y), color=INK, width=1.0)
    for x in cols:
        p.draw_line((x, rows[0]), (x, rows[-1]), color=INK, width=1.0)
    for i, h in enumerate(header):
        text_centered(p, (cols[i] + cols[i + 1]) / 2, rows[0] + 18, h, size=8)
    text_centered(p, (cols[0] + cols[1]) / 2, rows[3] - 10, "TOTAL", size=8)
    text_centered(p, (cols[-2] + cols[-1]) / 2, rows[3] - 10, "20", size=8)
    for r, row in enumerate(data):
        for i, cell in enumerate(row):
            text_centered(p, (cols[i] + cols[i + 1]) / 2, rows[r + 1] - 10,
                          cell, size=9)
    notes = [
        "GENERAL NOTES:",
        "1. KITCHEN COUNTERTOPS: PLASTIC LAMINATE, 25 IN. DEEP, ALONG",
        "   DIMENSIONED RUNS. (PLAN SHEETS DIMENSION 30 IN. - SEE ADDENDUM.)",
        "2. VANITY TOPS: CULTURED MARBLE, 21 IN. DEEP.",
        "3. TYPE A (ADA) UNITS ARE MODIFIED TYPE A UNITS WITH A REDUCED",
        "   KITCHEN RUN. THE (ADA) COLUMN IS NOT INCLUDED IN THE TYPE A",
        "   COLUMN. COUNT THEM SEPARATELY.",
        "4. TYPE A UNITS GET AN ISLAND; TYPE B UNITS GET A PENINSULA.",
        "5. CLUBROOM COUNTERTOP SHOWN ON SHEET A-204.",
        "6. NO UNIT COUNT CHANGES WITHOUT ADDENDUM.",
    ]
    for i, n in enumerate(notes):
        text_left(p, 72, 350 + i * 13, n, size=9)
    return p


# --------------------------------------- page 2: TYPE A, rotated, 2 viewports
# Content-space coordinates (portrait); page gets rotation 90 afterwards.
UNIT_WALLS = [(72, 140), (468, 140), (468, 380), (72, 380)]
A_KITCHEN = [(72, 140), (252, 140), (252, 185), (72, 185)]           # 10'x2.5'
A_ISLAND = [(117, 250), (225, 250), (225, 304), (117, 304)]          # 6'x3'
A_SINK = [(148.5, 264), (175.5, 264), (175.5, 300), (148.5, 300)]    # 1.5'x2'
A_BEDWALL_V = [(300, 140), (300, 380)]
A_BEDWALL_H = [(300, 260), (468, 260)]
A_CLOSET = [(390, 140), (420, 140), (420, 200), (390, 200)]
A_VANITY = [(90, 450), (144, 450), (144, 468), (90, 468)]            # 6'x2' @9
HATCH_X = [120, 150, 180, 210]
HATCH_Y = [510, 530, 550]


def draw_type_a_content(p, rev_note=None):
    text_centered(p, 306, 90, "TYPE A FLOOR PLAN - FLOORS 1-2", size=14)
    text_centered(p, 306, 110, "SHEET A-201", size=10)
    text_centered(p, 306, 128, "PROJECT: RIVERSIDE EXTENSION, BUILDING 3 "
                  "(SYNTHETIC MESSY FIXTURE)", size=8)
    text_centered(p, 306, 143, 'SCALE: 1/4" = 1\'-0" UNIT PLAN / '
                  '1/8" = 1\'-0" BATH ENLARGEMENT', size=8)
    if rev_note:
        text_left(p, 380, 165, rev_note, size=9)
        polygon(p, [(470, 158), (484, 158), (477, 148)], width=1.0)
    polygon(p, UNIT_WALLS, width=1.5)
    polygon(p, A_KITCHEN, width=1.0)
    polygon(p, A_ISLAND, width=1.0)
    polygon(p, A_SINK, width=0.75)
    text_centered(p, 162, 172, "KITCHEN", size=8)
    text_centered(p, 171, 280, "ISLAND", size=8)
    for seg in (A_BEDWALL_V, A_BEDWALL_H):
        p.draw_line(seg[0], seg[1], color=INK, width=1.5)
    polygon(p, A_CLOSET, width=1.0)
    text_centered(p, 405, 175, "CL", size=8)
    text_centered(p, 384, 300, "BEDROOM", size=8)
    dimension(p, (72, 116), (252, 116), '10\'-0"', 162, 110)
    dimension(p, (117, 328), (225, 328), '6\'-0"', 171, 322)
    dimension(p, (249, 250), (249, 304), '3\'-0"', 262, 280)
    # bath enlargement viewport (9 pt/ft)
    polygon(p, [(72, 450), (270, 450), (270, 576), (72, 576)], width=1.5)
    polygon(p, A_VANITY, width=1.0)
    text_centered(p, 117, 464, "VANITY", size=7)
    text_centered(p, 171, 540, "TILE", size=7)
    for x in HATCH_X:
        p.draw_line((x, 495), (x, 555), color=INK, width=0.5)
    for y in HATCH_Y:
        p.draw_line((105, y), (235, y), color=INK, width=0.5)
    dimension(p, (90, 426), (144, 426), '6\'-0"', 117, 420)
    dimension(p, (162, 450), (162, 468), '2\'-0"', 174, 462)


def page_type_a(doc):
    p = doc.new_page(width=612, height=792)
    draw_type_a_content(p)
    p.set_rotation(90)
    return p


# -------------------------------------------------------- page 3: ADA unit
ADA_KITCHEN = [(72, 140), (216, 140), (216, 185), (72, 185)]         # 8'x2.5'
ADA_VANITY = [(72, 240), (180, 240), (180, 276), (72, 276)]          # 6'x2'


def page_ada(doc):
    p = doc.new_page(width=612, height=792)
    text_centered(p, 306, 90, "TYPE A ADA UNIT PLAN", size=14)
    text_centered(p, 306, 110, "SHEET A-202", size=10)
    text_centered(p, 306, 128, "PROJECT: RIVERSIDE EXTENSION, BUILDING 3 "
                  "(SYNTHETIC MESSY FIXTURE)", size=8)
    text_centered(p, 306, 143, 'SCALE: 1/4" = 1\'-0"', size=8)
    text_centered(p, 306, 163, "ADA KITCHEN: REDUCED 8 FT RUN", size=8)
    polygon(p, UNIT_WALLS, width=1.5)
    polygon(p, ADA_KITCHEN, width=1.0)
    polygon(p, ADA_VANITY, width=1.0)
    text_centered(p, 144, 172, "ADA KITCHEN", size=8)
    text_centered(p, 126, 262, "VAN", size=8)
    dimension(p, (72, 116), (216, 116), '8\'-0"', 144, 110)
    dimension(p, (240, 140), (240, 185), '2\'-6"', 252, 165)
    dimension(p, (72, 216), (180, 216), '6\'-0"', 126, 210)
    dimension(p, (204, 240), (204, 276), '2\'-0"', 216, 262)
    return p


# ------------------------------------------------------- page 4: TYPE B plan
B_KITCHEN_L = [(72, 120), (288, 120), (288, 165), (306, 165),
               (306, 201), (261, 201), (261, 165), (72, 165)]  # 30+5 SF
B_SINK = [(100, 124), (136, 124), (136, 151), (100, 151)]      # 2'x1.5' = 3 SF
B_VANITY = [(72, 240), (180, 240), (180, 276), (72, 276)]      # 6'x2' = 12 SF


def page_type_b(doc):
    p = doc.new_page(width=612, height=792)
    text_centered(p, 306, 90, "TYPE B FLOOR PLAN", size=14)
    text_centered(p, 306, 110, "SHEET A-203", size=10)
    text_centered(p, 306, 128, "PROJECT: RIVERSIDE EXTENSION, BUILDING 3 "
                  "(SYNTHETIC MESSY FIXTURE)", size=8)
    text_centered(p, 306, 143, 'SCALE: 1/4" = 1\'-0"', size=8)
    polygon(p, UNIT_WALLS, width=1.5)
    polygon(p, B_KITCHEN_L, width=1.0)
    polygon(p, B_SINK, width=0.75)
    polygon(p, B_VANITY, width=1.0)
    text_centered(p, 170, 145, "KITCHEN", size=8)
    text_centered(p, 283, 190, "PEN", size=7)
    text_centered(p, 126, 262, "VAN", size=8)
    # split dimension text: two separate text runs over one 12'-0" dim line
    dimension(p, (72, 96), (288, 96), None, 0, 0)
    text_left(p, 150, 90, "12'-", size=9)
    text_left(p, 185, 90, '0"', size=9)
    dimension(p, (312, 120), (312, 165), '2\'-6"', 324, 146)
    # fractional dimension: 20'-6 1/2" drawn EXACTLY at 18 pt/ft
    # (20.5416667 ft x 18 = 369.75 pt of line length: 72 -> 441.75)
    dimension(p, (72, 596), (441.75, 596), None, 0, 0)
    text_left(p, 180, 590, "20'-6", size=9)
    text_left(p, 215, 590, '1/2"', size=9)
    dimension(p, (72, 216), (180, 216), '6\'-0"', 126, 210)
    dimension(p, (204, 240), (204, 276), '2\'-0"', 216, 262)
    return p


# --------------------------------------- page 5: REV B duplicate of page 2
def page_rev_b(doc):
    p = doc.new_page(width=612, height=792)
    draw_type_a_content(p, rev_note="REV B - CHECK PRINT, SUPERSEDES "
                        "2025-01-01 ISSUE")
    p.set_rotation(90)
    return p


# --------------------------------- page 6: searchable raster (OCR-style)
def page_scan(doc):
    """Raster page with an invisible OCR text layer: text is present, the
    linework is pixels - unmeasurable by design."""
    scratch = pymupdf.open()
    sp = scratch.new_page(width=612, height=792)
    polygon(sp, [(60, 80), (550, 80), (550, 700), (60, 700)], width=1.5)
    polygon(sp, [(90, 120), (330, 120), (330, 165), (90, 165)], width=1.0)
    dimension(sp, (90, 100), (330, 100), '12\'-0"', 210, 94)
    text_centered(sp, 210, 180, "CLUBROOM COUNTER", size=8)
    text_centered(sp, 306, 60, "SHEET A-204 - CLUBROOM AMENITY PLAN", size=12)
    pix = sp.get_pixmap(matrix=pymupdf.Matrix(2, 2))
    scratch.close()
    p = doc.new_page(width=612, height=792)
    p.insert_image(pymupdf.Rect(0, 0, 612, 792), pixmap=pix)
    ocr = ["SHEET A-204", "CLUBROOM AMENITY PLAN", "CLUBROOM COUNTER",
           '12\'-0"', "COUNTERTOP", "SCALE 1/4 IN = 1 FT",
           "CLUB ROOM AMENITY FINISH PLAN, LEVEL 1",
           "COUNTERTOP: PLASTIC LAMINATE, 30 IN. DEEP",
           "GENERAL NOTES: VERIFY ALL DIMENSIONS ON SITE",
           "GYP BOARD CEILING", "PAINTED WALLS AT COUNTER",
           "SEALED CONCRETE FLOOR", "GLASS STOREFRONT", "DOOR TYPE C",
           "RECEPTION DESK COUNTER", "TRASH ENCLOSURE", "ELECTRICAL OUTLET"]
    for i, w in enumerate(ocr):
        text_left(p, 80 + (i % 3) * 40, 300 + (i // 3) * 16, w, size=8,
                  render_mode=3)
    return p


def build(out_path):
    doc = pymupdf.open()
    page_schedule(doc)
    page_type_a(doc)
    page_ada(doc)
    page_type_b(doc)
    page_rev_b(doc)
    page_scan(doc)
    doc.set_metadata({
        "title": "Synthetic MESSY countertop takeoff fixture (not real)",
        "author": "countertop-takeoff-skill examples/messy_fixture.py",
        "producer": "pymupdf", "creator": "messy_fixture.py",
        "creationDate": "D:20250202000000", "modDate": "D:20250202000000",
    })
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    doc.save(out_path, no_new_id=True)
    doc.close()
    ka = shoelace(A_KITCHEN) / PT_PER_FT_MAIN ** 2
    isl = shoelace(A_ISLAND) / PT_PER_FT_MAIN ** 2
    av = shoelace(A_VANITY) / PT_PER_FT_BATH ** 2
    ada_k = shoelace(ADA_KITCHEN) / PT_PER_FT_MAIN ** 2
    ada_v = shoelace(ADA_VANITY) / PT_PER_FT_MAIN ** 2
    bk = shoelace(B_KITCHEN_L) / PT_PER_FT_MAIN ** 2
    bvn = shoelace(B_VANITY) / PT_PER_FT_MAIN ** 2
    sink = shoelace(B_SINK) / PT_PER_FT_MAIN ** 2
    a_unit = ka + isl + av
    ada_unit = ada_k + ada_v
    b_unit = bk + bvn
    print(f"WROTE {out_path}")
    print("KNOWN TRUTH (gross policy; shoelace from drawn coordinates):")
    print(f"  A kitchen 10'x2.5'        : {ka:8.4f} SF")
    print(f"  A island 6'x3' (sink gross): {isl:8.4f} SF")
    print(f"  A vanity 6'x2' @9pt/ft    : {av:8.4f} SF")
    print(f"  Type A per-unit           : {a_unit:8.4f} SF  x10 = "
          f"{a_unit*10:.4f} SF")
    print(f"  ADA kitchen 8'x2.5'       : {ada_k:8.4f} SF")
    print(f"  ADA vanity 6'x2'          : {ada_v:8.4f} SF")
    print(f"  ADA per-unit              : {ada_unit:8.4f} SF  x2 = "
          f"{ada_unit*2:.4f} SF")
    print(f"  B kitchen L (gross)       : {bk:8.4f} SF  (sink {sink:.2f} SF"
          " subtractable under net policy)")
    print(f"  B vanity 6'x2'            : {bvn:8.4f} SF")
    print(f"  Type B per-unit           : {b_unit:8.4f} SF  x8 = "
          f"{b_unit*8:.4f} SF")
    gross = a_unit * 10 + ada_unit * 2 + b_unit * 8
    net = (ka + isl + av) * 10 + ada_unit * 2 + (bk - sink + bvn) * 8
    print(f"  PROJECT TOTAL gross       : {gross:8.4f} SF")
    print(f"  PROJECT TOTAL net (B sink): {net:8.4f} SF")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="build/messy.pdf")
    args = ap.parse_args()
    build(args.out)
