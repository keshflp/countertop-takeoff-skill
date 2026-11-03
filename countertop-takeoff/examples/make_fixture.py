# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1"]
# ///
"""Generate a SYNTHETIC apartment plan PDF with KNOWN countertop areas.

Two cases:
  --case original (default): the clean V1 fixture - unit schedule + two
      per-type plan sheets drawn at 1/4" = 1'-0" (18 pt/ft); total 168.75 SF.
  --case messy: the V2 hostile fixture (see examples/messy_fixture.py):
      floor-column schedule with an ADA subset, a rotated sheet with two
      viewports at different scales, island/peninsula/adjacent-room
      geometry, hatching, a sink loop, split/fractional dimension text, a
      REV B duplicate sheet, and a searchable raster scan page.

Because the coordinates are chosen, the true countertop areas are known
exactly and printed at the end (KNOWN TRUTH). The pipeline must recover them.

Usage:
    uv run examples/make_fixture.py [--case original|messy]
                                    [--out examples/fixture.pdf]
"""

import argparse
import os
import sys

import pymupdf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PT_PER_FT = 18.0  # 1/4" = 1'-0"
FONT = "helv"
INK = (0, 0, 0)

# ---------------------------------------------------------------- geometry ---
# Page 2 / SHEET A-101 - TYPE A
UNIT_A = [(72, 360), (432, 360), (432, 576), (72, 576)]              # 20' x 12'
KITCHEN_A = [  # L-shape: 10' run along top wall + 2.5' leg down left wall
    (72, 360), (252, 360), (252, 405), (117, 405), (117, 450), (72, 450),
]
VANITY_A = [(72, 490), (144, 490), (144, 521.5), (72, 521.5)]        # 4' x 1'9"
# Page 3 / SHEET A-102 - TYPE B
UNIT_B = UNIT_A
KITCHEN_B = [(72, 360), (216, 360), (216, 405), (72, 405)]           # 8' x 2'6"
VANITY_B = list(VANITY_A)


def shoelace(pts):
    s = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return abs(s) / 2.0


def text_centered(page, cx, baseline_y, s, size=9, font=FONT):
    w = pymupdf.get_text_length(s, fontname=font, fontsize=size)
    page.insert_text((cx - w / 2.0, baseline_y), s, fontname=font,
                     fontsize=size, color=INK)


def text_left(page, x, baseline_y, s, size=9, font=FONT):
    page.insert_text((x, baseline_y), s, fontname=font, fontsize=size, color=INK)


def polygon(page, pts, width=1.0):
    n = len(pts)
    for i in range(n):
        page.draw_line(pts[i], pts[(i + 1) % n], color=INK, width=width)


def dimension(page, p1, p2, label, text_cx, baseline_y, size=9):
    """Draw a dimension line with end ticks and a centered text label."""
    page.draw_line(p1, p2, color=INK, width=0.75)
    horizontal = abs(p1[1] - p2[1]) < 1e-6
    for p in (p1, p2):
        if horizontal:
            page.draw_line((p[0], p[1] - 4), (p[0], p[1] + 4), color=INK, width=0.75)
        else:
            page.draw_line((p[0] - 3, p[1]), (p[0] + 3, p[1]), color=INK, width=0.75)
    text_centered(page, text_cx, baseline_y, label, size)


def title_block(page, title, sheet, extra):
    text_centered(page, 306, 90, title, size=14)
    text_centered(page, 306, 110, f"SHEET {sheet}", size=10)
    text_centered(page, 306, 128, extra, size=8)


def plan_page(doc, sheet, title, unit, kitchen, kitchen_label_at, vanity,
              dims, scale_note_at_y=140):
    page = doc.new_page(width=612, height=792)
    title_block(page, title, sheet,
                "PROJECT: RIVERSIDE APARTMENTS, BUILDING 2 "
                "(SYNTHETIC FIXTURE - NOT A REAL PROJECT)")
    text_centered(page, 306, scale_note_at_y, 'COUNTERTOP PLAN. SCALE: 1/4" = 1\'-0"', size=8)
    polygon(page, unit, width=1.5)   # unit outline (walls)
    polygon(page, kitchen, width=1.0)
    polygon(page, vanity, width=1.0)
    text_centered(page, kitchen_label_at[0], kitchen_label_at[1], "KITCHEN", size=8)
    text_centered(page, 108, 545, "BATH", size=8)
    for p1, p2, label, cx, by in dims:
        dimension(page, p1, p2, label, cx, by)
    return page


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", choices=["original", "messy", "hotel"],
                    default="original",
                    help="original = clean V1 fixture; messy = V2 hostile"
                         " fixture; hotel = V3 hotel fixture (rotated pages,"
                         " bitmap schedule, 3 scales on one sheet, wrong"
                         " duplicate title block, GR package exclusion)")
    ap.add_argument("--out", default="examples/fixture.pdf")
    args = ap.parse_args()
    if args.case == "messy":
        import messy_fixture
        messy_fixture.build(args.out)
        return
    if args.case == "hotel":
        import hotel_fixture
        hotel_fixture.build(args.out)
        return

    doc = pymupdf.open()

    # ------------------------------------------------ page 1: UNIT SCHEDULE --
    p1 = doc.new_page(width=612, height=792)
    title_block(p1, "UNIT SCHEDULE", "A-001",
                "PROJECT: RIVERSIDE APARTMENTS, BUILDING 2 "
                "(SYNTHETIC FIXTURE - NOT A REAL PROJECT)")
    cols = [100, 160, 320, 440]
    rows = [210, 238, 266, 294]
    header = ["TYPE", "DESCRIPTION", "UNITS"]
    data = [
        ["A", "1 BED / 1 BATH", "3"],
        ["B", "2 BED / 2 BATH", "2"],
    ]
    for y in rows:
        p1.draw_line((cols[0], y), (cols[-1], y), color=INK, width=1.0)
    for x in cols:
        p1.draw_line((x, rows[0]), (x, rows[-1]), color=INK, width=1.0)
    for i, h in enumerate(header):
        text_centered(p1, (cols[i] + cols[i + 1]) / 2, rows[0] + 18, h, size=9)
    for r, row in enumerate(data):
        for i, cell in enumerate(row):
            text_centered(p1, (cols[i] + cols[i + 1]) / 2, rows[r + 1] - 10,
                          cell, size=9)
    notes = [
        "GENERAL NOTES:",
        '1. KITCHEN COUNTERTOPS: POST-FORMED PLASTIC LAMINATE, 25 IN. DEEP,',
        "   CONTINUOUS ALONG DIMENSIONED RUNS. NO SINK OR RANGE CUTOUTS THIS PHASE.",
        "2. VANITY TOPS: CULTURED MARBLE, 21 IN. DEEP.",
        "3. COUNTERTOP EXTENTS DIMENSIONED ON FLOOR PLANS A-101 AND A-102.",
        "4. UNITS 104 AND 112 (TYPE A) ARE MIRRORED PLANS OF UNIT 101.",
        "5. NO UNIT COUNT CHANGES WITHOUT ADDENDUM.",
    ]
    for i, n in enumerate(notes):
        text_left(p1, 100, 340 + i * 14, n, size=9)

    # --------------------------------------------------- page 2: TYPE A ------
    plan_page(
        doc, "A-101", "TYPE A FLOOR PLAN - 1 BEDROOM", UNIT_A, KITCHEN_A,
        (185, 380), VANITY_A,
        dims=[
            # dim line, label, text center x, baseline y
            ((72, 336), (252, 336), '10\'-0"', 162, 330),
            ((268, 360), (268, 405), '2\'-6"', 288, 384),
            ((72, 596), (432, 596), '20\'-0"', 252, 590),
        ],
    )

    # --------------------------------------------------- page 3: TYPE B ------
    plan_page(
        doc, "A-102", "TYPE B FLOOR PLAN - 2 BEDROOM", UNIT_B, KITCHEN_B,
        (144, 380), VANITY_B,
        dims=[
            ((72, 336), (216, 336), '8\'-0"', 144, 330),
            ((232, 360), (232, 405), '2\'-6"', 252, 384),
            ((72, 596), (432, 596), '20\'-0"', 252, 590),
        ],
    )

    doc.set_metadata({
        "title": "Synthetic countertop takeoff fixture (not a real project)",
        "author": "countertop-takeoff-skill examples/make_fixture.py",
        "producer": "pymupdf",
        "creator": "make_fixture.py",
        "creationDate": "D:20250101000000",
        "modDate": "D:20250101000000",
    })
    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    doc.save(args.out, no_new_id=True)

    # ------------------------------------------------------- KNOWN TRUTH -----
    ka = shoelace(KITCHEN_A) / PT_PER_FT ** 2
    va = shoelace(VANITY_A) / PT_PER_FT ** 2
    kb = shoelace(KITCHEN_B) / PT_PER_FT ** 2
    vb = shoelace(VANITY_B) / PT_PER_FT ** 2
    a_unit, b_unit = ka + va, kb + vb
    print(f"WROTE {args.out}")
    print(f"KNOWN TRUTH (drawn at {PT_PER_FT} pt/ft; areas by shoelace from drawn coordinates):")
    print(f"  A-101 Type A kitchen counter (L-shape) : {ka:8.4f} SF")
    print(f"  A-101 Type A vanity top                : {va:8.4f} SF")
    print(f"  A-101 Type A per-unit total            : {a_unit:8.4f} SF   x3 units = {a_unit*3:.4f} SF")
    print(f"  A-102 Type B kitchen counter (rect)    : {kb:8.4f} SF")
    print(f"  A-102 Type B vanity top                : {vb:8.4f} SF")
    print(f"  A-102 Type B per-unit total            : {b_unit:8.4f} SF   x2 units = {b_unit*2:.4f} SF")
    print(f"  PROJECT TOTAL (A x3 + B x2)            : {a_unit*3 + b_unit*2:8.4f} SF")


if __name__ == "__main__":
    main()
