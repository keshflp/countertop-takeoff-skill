# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1"]
# ///
"""Generate the HOTEL drawing-set fixture (V3, P0.7): known areas, field-real
traps. Called via `uv run examples/make_fixture.py --case hotel --out <path>`.

Every page carries /Rotate 270 (the real set did). Pages:

  1  A-300  SHEET INDEX (vector): lists A-301..A-305, A-450, A-504 - A-305
            is listed but ABSENT from the delivery (index-gap callout)
  2  A-301  ROOM DISTRIBUTION: VECTOR text headers over a PASTED BITMAP
            table (the real-world trap: text extraction sees the header,
            the whole table is pixels). Table: F1 A3/B0/GR1, F2 A3/B2/GR1,
            project 10 rooms. GR guestroom FF&E excluded from this contract.
  3  A-302  FLOOR 1 PLAN (18 pt/ft): rooms 101/102/103 TYPE A (6'x2.5'
            counters), 104 TYPE GR (4'x2')
  4  A-303  FLOOR 2 PLAN (18 pt/ft): 201/202/203 TYPE A, 204/205 TYPE B
            (8'x2.5'), 206 TYPE GR
  5  A-304  BATH ENLARGEMENT + DETAILS: THREE viewports/scales on one sheet
            (bath 9 pt/ft, edge detail 36, key map 4.5); room 204 enlarged
            (dedupe candidate with the floor-plan tag)
  6  A-450  ELEVATIONS (18 pt/ft): counter runs with LENGTH dims; section
            reference to A-504
  7  A-504  SECTIONS (36 pt/ft): depth 25 1/2 in, thickness 1 1/2 in,
            splash 4 in - the cross-sheet section->length pair
  8  A-301  WRONG DUPLICATE title block: a rendering page mislabeled A-301
            (identity conflict; must be dispositioned, never dropped)
  9  A-306  CLUBROOM: one MEASURABLE decent raster (clubroom counter,
            image-route, 12'x2') and one UNUSABLE low-res raster (blank +
            callout) proving partial completion

KNOWN TRUTH (18 pt/ft rooms): TYPE A counter 6'x2.5' = 15.00 SF; TYPE B
8'x2.5' = 20.00 SF; GR 4'x2' = 8.00 SF; room 204 vanity 4'x2' @9 = 8.00 SF;
clubroom counter (image route) 12'x2' = 24.00 SF. An omitted room (203 in
the canonical spec) stays BLANK with a coverage callout.
"""

import argparse
import os
import sys

import pymupdf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PT_MAIN = 18.0
PT_BATH = 9.0
PT_DETAIL = 36.0
PT_KEY = 4.5
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


def text_centered(page, cx, baseline_y, s, size=9, font=FONT):
    w = pymupdf.get_text_length(s, fontname=font, fontsize=size)
    page.insert_text((cx - w / 2.0, baseline_y), s, fontname=font,
                     fontsize=size, color=INK)


def text_left(page, x, baseline_y, s, size=9, font=FONT):
    page.insert_text((x, baseline_y), s, fontname=font, fontsize=size,
                     color=INK)


def polygon(page, pts, width=1.0):
    n = len(pts)
    for i in range(n):
        page.draw_line(pts[i], pts[(i + 1) % n], color=INK, width=width)


def dimension(page, p1, p2, label, text_cx, baseline_y, size=8):
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


def rotated(page):
    page.set_rotation(270)


# ------------------------------------------------ page 1: A-300 sheet index
def page_index(doc):
    p = doc.new_page(width=612, height=792)
    text_centered(p, 306, 90, "SHEET INDEX - HARBORVIEW HOTEL", size=14)
    text_centered(p, 306, 110, "SHEET A-300", size=10)
    text_centered(p, 306, 128, "PROJECT: HARBORVIEW HOTEL, 2 FLOORS"
                  " (SYNTHETIC HOTEL FIXTURE - NOT A REAL PROJECT)", size=8)
    rows = [
        "A-301   ROOM DISTRIBUTION - FLOORS 1-2",
        "A-302   FLOOR 1 PLAN - GUESTROOMS",
        "A-303   FLOOR 2 PLAN - GUESTROOMS",
        "A-304   BATH ENLARGEMENT AND EDGE DETAILS",
        "A-305   TYPICAL UNIT DETAILS",
        "A-306   CLUBROOM AMENITY",
        "A-450   COUNTER ELEVATIONS",
        "A-504   COUNTER SECTIONS",
        "A-511   FIXTURE SCHEDULES",
    ]
    for i, s in enumerate(rows):
        text_left(p, 120, 160 + i * 18, s, size=10)
    text_left(p, 120, 330, "COUNTERTOP SCOPE: GUESTROOM AND CLUBROOM"
              " COUNTERS. GR GUESTROOM FF&E PACKAGE EXCLUDED - SEE"
              " A-301 NOTES.", size=9)
    rotated(p)
    return p


# ------------------------------- page 2: A-301 bitmap schedule under header
def _schedule_table_pixmap():
    scratch = pymupdf.open()
    sp = scratch.new_page(width=612, height=400)
    cols = [60, 140, 240, 340, 440, 540]
    rows = [60, 100, 140, 180, 220]
    header = ["FLOOR", "TYPE A", "TYPE B", "TYPE GR", "FLOOR TOTAL"]
    data = [
        ["FLOOR 1", "3", "0", "1", "4"],
        ["FLOOR 2", "3", "2", "1", "6"],
        ["TOTAL", "6", "2", "2", "10"],
    ]
    for y in rows:
        sp.draw_line((cols[0], y), (cols[-1], y), color=INK, width=1.0)
    for x in cols:
        sp.draw_line((x, rows[0]), (x, rows[-1]), color=INK, width=1.0)
    for i, h in enumerate(header):
        text_centered(sp, (cols[i] + cols[i + 1]) / 2, rows[0] + 22, h,
                      size=10)
    for r, row in enumerate(data):
        for i, cell in enumerate(row):
            text_centered(sp, (cols[i] + cols[i + 1]) / 2, rows[r + 2] - 12,
                          cell, size=10)
    pix = sp.get_pixmap(matrix=pymupdf.Matrix(2, 2))
    scratch.close()
    return pix


def page_schedule(doc):
    p = doc.new_page(width=612, height=792)
    text_centered(p, 306, 90, "ROOM DISTRIBUTION - FLOORS 1-2", size=14)
    text_centered(p, 306, 110, "SHEET A-301", size=10)
    text_centered(p, 306, 128, "PROJECT: HARBORVIEW HOTEL"
                  " (SYNTHETIC HOTEL FIXTURE)", size=8)
    # the table is a PASTED BITMAP: no text objects under the header
    p.insert_image(pymupdf.Rect(150, 150, 462, 430),
                   pixmap=_schedule_table_pixmap())
    notes = [
        "NOTES:",
        "1. GR GUESTROOM FF&E PACKAGE IS EXCLUDED FROM THIS CONTRACT;",
        "   GR ROOM COUNTERTOPS ARE SHOWN FOR COORDINATION ONLY AND ARE",
        "   REPORTED SEPARATELY (SEE FF&E MANUAL).",
        "2. FINISH TAGS: ST = STONE, PL = LAMINATE, W = WOOD.",
        "   BRAND/COLOR TBD - VERIFY IN THE FF&E MANUAL.",
        "3. GUESTROOM COUNTER EXTENTS DIMENSIONED ON A-302 / A-303;",
        "   DEPTH AND SPLASH ON SECTIONS A-504; RUN LENGTHS ON A-450.",
        "4. ROOM 204 BATH ENLARGED ON A-304 (SAME ROOM, NOT AN EXTRA).",
        "5. CLUBROOM COUNTER ON A-306 (OUT-OF-SERIES, MEASURE SEPARATELY).",
    ]
    for i, n in enumerate(notes):
        text_left(p, 90, 470 + i * 14, n, size=9)
    rotated(p)
    return p


# ------------------------------------------------ floor plan helper
ROOM_W = 180   # 10' room width at 18 pt/ft
ROOM_H = 144   # 8' at 18 pt/ft
CTR_A_W = 108  # 6' counter
CTR_B_W = 144  # 8' counter
CTR_GR_W = 72  # 4' counter
CTR_H = 45     # 2.5' counter depth
GR_CTR_H = 36  # GR counter depth (4'x2')


def room_with_counter(p, x0, y0, tag, ctag, ctr_w, ctr_h=CTR_H,
                      ctr_label=None):
    """One guestroom box (ROOM_W x ROOM_H) with its counter strip along the
    top wall, a room-number + TYPE tag, and a counter width dim."""
    walls = [(x0, y0), (x0 + ROOM_W, y0), (x0 + ROOM_W, y0 + ROOM_H),
             (x0, y0 + ROOM_H)]
    polygon(p, walls, width=1.5)
    ctr = [(x0, y0), (x0 + ctr_w, y0), (x0 + ctr_w, y0 + ctr_h),
           (x0, y0 + ctr_h)]
    polygon(p, ctr, width=1.0)
    text_centered(p, x0 + ROOM_W / 2, y0 + ROOM_H / 2 + 3, tag, size=9)
    text_centered(p, x0 + ROOM_W / 2, y0 + ROOM_H / 2 + 16, ctag, size=7)
    if ctr_label:
        text_centered(p, x0 + ctr_w / 2, y0 + ctr_h / 2 + 3, ctr_label,
                      size=7)
    return ctr


# ------------------------------------------------ page 3: A-302 floor 1
def page_floor1(doc):
    p = doc.new_page(width=612, height=792)
    text_centered(p, 306, 90, "FLOOR 1 PLAN - GUESTROOMS", size=14)
    text_centered(p, 306, 110, "SHEET A-302", size=10)
    text_centered(p, 306, 128, "PROJECT: HARBORVIEW HOTEL"
                  " (SYNTHETIC HOTEL FIXTURE)", size=8)
    text_centered(p, 306, 143, 'SCALE: 1/4" = 1\'-0"', size=8)
    # row 1: rooms 101, 102 (contiguous party walls: 60..380)
    ctr101 = room_with_counter(p, 60, 150, "101", "TYPE A", CTR_A_W,
                               ctr_label="COUNTER")
    ctr102 = room_with_counter(p, 240, 150, "102", "TYPE A", CTR_A_W,
                               ctr_label="COUNTER")
    # row 2: rooms 103, 104 (104 = GR)
    ctr103 = room_with_counter(p, 60, 340, "103", "TYPE A", CTR_A_W,
                               ctr_label="COUNTER")
    ctr104 = room_with_counter(p, 240, 340, "104", "TYPE GR", CTR_GR_W,
                               ctr_h=GR_CTR_H,
                               ctr_label="GR CTR")
    # dimensions: three UNIQUE lengths calibrate this sheet
    dimension(p, (60, 118), (420, 118), '20\'-0"', 240, 112)      # 360 pt
    dimension(p, (36, 150), (36, 294), '8\'-0"', 30, 224)         # 144 pt
    dimension(p, (60, 470), (168, 470), '6\'-0"', 114, 464)       # 108 pt
    rotated(p)
    return p, ctr101, ctr102, ctr103, ctr104


# ------------------------------------------------ page 4: A-303 floor 2
def page_floor2(doc):
    p = doc.new_page(width=612, height=792)
    text_centered(p, 306, 90, "FLOOR 2 PLAN - GUESTROOMS", size=14)
    text_centered(p, 306, 110, "SHEET A-303", size=10)
    text_centered(p, 306, 128, "PROJECT: HARBORVIEW HOTEL"
                  " (SYNTHETIC HOTEL FIXTURE)", size=8)
    text_centered(p, 306, 143, 'SCALE: 1/4" = 1\'-0"', size=8)
    # row 1: rooms 201, 202, 203 (A) - contiguous 60..540
    ctr201 = room_with_counter(p, 60, 150, "201", "TYPE A", CTR_A_W,
                               ctr_label="COUNTER")
    ctr202 = room_with_counter(p, 240, 150, "202", "TYPE A", CTR_A_W,
                               ctr_label="COUNTER")
    ctr203 = room_with_counter(p, 420, 150, "203", "TYPE A", CTR_A_W,
                               ctr_label="COUNTER")
    # row 2: 204, 205 (B), 206 (GR)
    ctr204 = room_with_counter(p, 60, 340, "204", "TYPE B", CTR_B_W,
                               ctr_label="COUNTER")
    ctr205 = room_with_counter(p, 240, 340, "205", "TYPE B", CTR_B_W,
                               ctr_label="COUNTER")
    ctr206 = room_with_counter(p, 420, 340, "206", "TYPE GR", CTR_GR_W,
                               ctr_h=GR_CTR_H,
                               ctr_label="GR CTR")
    # dimensions: three UNIQUE lengths
    dimension(p, (60, 118), (600, 118), '30\'-0"', 330, 112)      # 540 pt
    dimension(p, (588, 340), (588, 484), '8\'-0"', 596, 414)      # 144 pt
    dimension(p, (60, 524), (168, 524), '6\'-0"', 114, 518)       # 108 pt
    rotated(p)
    return p, ctr201, ctr202, ctr203, ctr204, ctr205, ctr206


# ------------------- page 5: A-304 enlargement + details, 3 scales 1 sheet
def page_enlargement(doc):
    p = doc.new_page(width=612, height=792)
    text_centered(p, 306, 90, "BATH ENLARGEMENT AND EDGE DETAILS", size=14)
    text_centered(p, 306, 110, "SHEET A-304", size=10)
    text_centered(p, 306, 128, "PROJECT: HARBORVIEW HOTEL"
                  " (SYNTHETIC HOTEL FIXTURE)", size=8)
    text_centered(p, 306, 143, 'SCALE: 1/8" BATH PLAN / 3" EDGE DETAIL /'
                  ' 1/96" KEY MAP', size=8)
    # --- bath viewport (9 pt/ft): room 204 vanity 4'x2'
    bath = [(72, 160), (180, 160), (180, 244), (72, 244)]     # 12'x9.3' room
    polygon(p, bath, width=1.5)
    vanity = [(90, 170), (126, 170), (126, 188), (90, 188)]   # 4'x2' @9
    polygon(p, vanity, width=1.0)
    text_centered(p, 108, 182, "VANITY", size=7)
    text_centered(p, 126, 236, "204 (ENLARGED)", size=8)
    dimension(p, (90, 152), (126, 152), '4\'-0"', 108, 146)   # 36 pt @9
    dimension(p, (134, 170), (134, 188), '2\'-0"', 142, 182)  # 18 pt @9
    # --- edge detail viewport (36 pt/ft): slab thickness 1.5" + splash 4"
    slab = [(300, 170), (381, 170), (381, 174.5), (300, 174.5)]  # 81x4.5 pt
    polygon(p, slab, width=1.0)
    splash = [(300, 158), (303.5, 158), (303.5, 170), (300, 170)]
    polygon(p, splash, width=1.0)                             # 3.5x12 pt
    text_centered(p, 341, 190, "EDGE DETAIL", size=8)
    dimension(p, (300, 205), (381, 205), '2\'-3"', 340, 199)  # 81 pt @36
    dimension(p, (392, 170), (392, 174.5), None, 0, 0)
    text_left(p, 398, 175, '1 1/2"', size=8)
    # --- key map viewport (4.5 pt/ft): 10'x10' floor blob
    key = [(460, 160), (505, 160), (505, 205), (460, 205)]    # 45 pt @4.5
    polygon(p, key, width=1.0)
    text_centered(p, 482, 220, "KEY MAP", size=7)
    dimension(p, (460, 150), (505, 150), '10\'-0"', 482, 144)  # 45 pt @4.5
    rotated(p)
    return p, vanity


# --------------------------------------- page 6: A-450 counter elevations
def page_elevations(doc):
    p = doc.new_page(width=612, height=792)
    text_centered(p, 306, 90, "COUNTER ELEVATIONS", size=14)
    text_centered(p, 306, 110, "SHEET A-450", size=10)
    text_centered(p, 306, 128, "PROJECT: HARBORVIEW HOTEL"
                  " (SYNTHETIC HOTEL FIXTURE)", size=8)
    text_centered(p, 306, 143, 'SCALE: 1-1/2" = 1\'-0"', size=8)
    # TYPE A counter elevation: 6' wide x 36" high at 27 pt/ft (1-1/2"=1')
    elev_a = [(80, 170), (242, 170), (242, 224), (80, 224)]   # 162 x 54
    polygon(p, elev_a, width=1.0)
    splash_a = [(80, 164), (86, 164), (86, 170), (80, 170)]   # 6" splash @27
    polygon(p, splash_a, width=1.0)
    text_centered(p, 161, 240, "TYPE A COUNTER ELEVATION - RUN LENGTH"
                  " PER FLOOR PLAN", size=8)
    dimension(p, (80, 250), (242, 250), '6\'-0"', 161, 244)   # 162 pt @27
    # TYPE B counter elevation: 8' wide x 36" high
    elev_b = [(320, 170), (536, 170), (536, 224), (320, 224)]  # 216 x 54
    polygon(p, elev_b, width=1.0)
    splash_b = [(320, 164), (326, 164), (326, 170), (320, 170)]
    polygon(p, splash_b, width=1.0)
    text_centered(p, 428, 240, "TYPE B COUNTER ELEVATION", size=8)
    dimension(p, (320, 250), (536, 250), '8\'-0"', 428, 244)   # 216 pt @27
    text_left(p, 80, 300, "COUNTER DEPTH, THICKNESS AND SPLASH HEIGHT: SEE"
              " SECTIONS A-504.", size=9)
    text_left(p, 80, 316, "DO NOT SCALE DRAWINGS. USE STATED DIMENSIONS.",
              size=9)
    rotated(p)
    return p


# ---------------------------------- page 7: A-504 sections (36 pt/ft)
def page_sections(doc):
    p = doc.new_page(width=612, height=792)
    text_centered(p, 306, 90, "COUNTER SECTIONS", size=14)
    text_centered(p, 306, 110, "SHEET A-504", size=10)
    text_centered(p, 306, 128, "PROJECT: HARBORVIEW HOTEL"
                  " (SYNTHETIC HOTEL FIXTURE)", size=8)
    text_centered(p, 306, 143, 'SCALE: 3" = 1\'-0"', size=8)
    # section at 36 pt/ft: depth 25 1/2" horizontal (76.5 pt),
    # thickness 1 1/2" (4.5 pt), splash 4" (12 pt)
    slab = [(150, 240), (226.5, 240), (226.5, 244.5), (150, 244.5)]
    polygon(p, slab, width=1.0)
    splash = [(150, 228), (154.5, 228), (154.5, 240), (150, 240)]
    polygon(p, splash, width=1.0)
    text_centered(p, 188, 262, "TYPICAL GUESTROOM COUNTER SECTION", size=8)
    dimension(p, (150, 268), (226.5, 268), None, 0, 0)
    text_left(p, 165, 262, '2\'-1 1/2"', size=8)          # 25 1/2 in depth
    dimension(p, (236, 240), (236, 244.5), None, 0, 0)
    text_left(p, 242, 246, '1 1/2"', size=8)              # thickness
    dimension(p, (142, 228), (142, 240), None, 0, 0)
    text_left(p, 96, 238, '4" SPLASH', size=8)            # splash height
    text_left(p, 150, 300, "RUN LENGTHS: SEE ELEVATIONS A-450. FLOOR PLAN"
              " EXTENTS: A-302 / A-303.", size=8)
    text_left(p, 150, 316, "DO NOT SCALE DRAWINGS.", size=8)
    rotated(p)
    return p


# ------------------ page 8: A-301 WRONG DUPLICATE title block (rendering)
def page_wrong_duplicate(doc):
    p = doc.new_page(width=612, height=792)
    text_centered(p, 306, 90, "LOBBY PERSPECTIVE - PRESENTATION", size=14)
    text_centered(p, 306, 110, "SHEET A-301", size=10)   # WRONG duplicate
    text_centered(p, 306, 128, "PROJECT: HARBORVIEW HOTEL"
                  " (SYNTHETIC HOTEL FIXTURE)", size=8)
    # a "rendering": decorative rectangles, no countertop linework
    polygon(p, [(120, 200), (500, 200), (500, 480), (120, 480)], width=1.0)
    polygon(p, [(160, 260), (340, 260), (340, 420), (160, 420)], width=0.5)
    text_centered(p, 306, 500, "MARKETING RENDERING - NOT CONSTRUCTION"
                  " DOCUMENTATION", size=9)
    rotated(p)
    return p


# -------- page 9: A-306 clubroom: decent raster + unusable raster
def _clubroom_scan_pixmap():
    """A legible scan: clubroom counter elevation 12'x2' at 18 pt/ft."""
    scratch = pymupdf.open()
    sp = scratch.new_page(width=612, height=400)
    ctr = [(60, 120), (276, 120), (276, 156), (60, 156)]      # 12'x2' @18
    polygon(sp, ctr, width=1.0)
    dimension(sp, (60, 100), (276, 100), '12\'-0"', 168, 94)  # 216 pt
    text_centered(sp, 168, 180, "CLUBROOM COUNTER", size=9)
    pix = sp.get_pixmap(matrix=pymupdf.Matrix(2, 2))
    scratch.close()
    return pix


def _lowres_blob_pixmap():
    """Deliberately unusable: a 5' counter rendered at tiny zoom."""
    scratch = pymupdf.open()
    sp = scratch.new_page(width=612, height=400)
    polygon(sp, [(60, 120), (150, 120), (150, 156), (60, 156)], width=1.0)
    dimension(sp, (60, 100), (150, 100), '5\'-0"', 105, 94)
    pix = sp.get_pixmap(matrix=pymupdf.Matrix(0.15, 0.15))
    scratch.close()
    return pix


def page_clubroom(doc):
    p = doc.new_page(width=612, height=792)
    text_centered(p, 306, 90, "CLUBROOM AMENITY", size=14)
    text_centered(p, 306, 110, "SHEET A-306", size=10)
    text_centered(p, 306, 128, "PROJECT: HARBORVIEW HOTEL"
                  " (SYNTHETIC HOTEL FIXTURE)", size=8)
    text_centered(p, 306, 143, "SCANS - NOT VECTOR LINWORK", size=8)
    p.insert_image(pymupdf.Rect(40, 160, 380, 382),
                   pixmap=_clubroom_scan_pixmap())
    text_centered(p, 210, 418, "CLUBROOM COUNTER ELEVATION (LEGIBLE SCAN)", size=8)
    p.insert_image(pymupdf.Rect(330, 160, 560, 400),
                   pixmap=_lowres_blob_pixmap())
    text_centered(p, 445, 418, "BAR COUNTER (LOW-RES SCAN - UNUSABLE)", size=8)
    rotated(p)
    return p


def build(out_path):
    doc = pymupdf.open()
    page_index(doc)
    page_schedule(doc)
    page_floor1(doc)
    page_floor2(doc)
    page_enlargement(doc)
    page_elevations(doc)
    page_sections(doc)
    page_wrong_duplicate(doc)
    page_clubroom(doc)
    doc.set_metadata({
        "title": "Synthetic HOTEL countertop takeoff fixture (not real)",
        "author": "countertop-takeoff-skill examples/hotel_fixture.py",
        "producer": "pymupdf", "creator": "hotel_fixture.py",
        "creationDate": "D:20250303000000", "modDate": "D:20250303000000",
    })
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    doc.save(out_path, no_new_id=True)
    doc.close()

    a_sf = shoelace([(0, 0), (CTR_A_W, 0), (CTR_A_W, CTR_H), (0, CTR_H)]) \
        / PT_MAIN ** 2
    b_sf = shoelace([(0, 0), (CTR_B_W, 0), (CTR_B_W, CTR_H), (0, CTR_H)]) \
        / PT_MAIN ** 2
    gr_sf = shoelace([(0, 0), (CTR_GR_W, 0), (CTR_GR_W, 36), (0, 36)]) \
        / PT_MAIN ** 2
    vanity_sf = shoelace([(0, 0), (36, 0), (36, 18), (0, 18)]) / PT_BATH ** 2
    club_sf = shoelace([(0, 0), (216, 0), (216, 36), (0, 36)]) / PT_MAIN ** 2
    print(f"WROTE {out_path}")
    print("KNOWN TRUTH (shoelace from drawn coordinates):")
    print(f"  TYPE A counter 6'x2.5'        : {a_sf:8.4f} SF (x5 measured"
          " rooms in the canonical spec; room 203 omitted -> callout)")
    print(f"  TYPE B counter 8'x2.5'        : {b_sf:8.4f} SF (x2)")
    print(f"  TYPE GR counter 4'x2'         : {gr_sf:8.4f} SF (x2,"
          " package_excluded - reported separately)")
    print(f"  room 204 vanity 4'x2' @9      : {vanity_sf:8.4f} SF")
    print(f"  clubroom counter (image route): {club_sf:8.4f} SF")
    measured = 5 * a_sf + 2 * b_sf + vanity_sf + club_sf
    excluded = 2 * gr_sf
    print(f"  CANONICAL SPEC measured total : {measured:8.4f} SF"
          f" (+ {excluded:.2f} SF GR excluded; room 203 blank + callout;"


          f" unusable bar scan blank + callout)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="build/hotel.pdf")
    args = ap.parse_args()
    build(args.out)
