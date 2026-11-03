# Measuring method

How this skill turns PDF linework into trustworthy square footage. Written for
the agent doing the takeoff and for the human auditing it.

## 0. Why this design

Plan PDFs are vector drawings: every wall, counter edge, and dimension string
is stored as coordinates in PDF points (1/72 inch), not pixels. That means
quantities can be COMPUTED rather than estimated. The failure mode this skill
guards against is an AI eyeballing a rendered page and quoting a number —
plausible, unfalsifiable, and wrong often enough to lose bids. So:

- The model recognizes (which sheets, which outlines, which labels).
- Scripts measure (calibration, polygon area, multiplication).
- Every number is reproducible from the geometry JSON.

## 1. Page inventory (`index_pdf.py`)

Reads only the text layer of each page and flags:

- **Sheet number**: `SHEET A-101` patterns in the text.
- **Unit schedule**: "unit schedule" phrases, or schedule + qty/type words.
- **Plans with countertop terms**: counter/countertop/vanity/kitchen/cabinet.
- **Dimension labels**: words like `10'-0"` (with or without the hyphen,
  e.g. `10'6"`, `10'`), used later for calibration.

It writes `<pdf>.index.json` with full per-page text — this is where the agent
READS the unit schedule counts. Text is vector data; reading text is not
"eyeballing".

Limitation: scanned (raster) pages have no text layer and no vectors. V1
requires vector PDFs (native CAD exports or vector-faithful prints).

## 2. Geometry extraction (`extract_geometry.py`)

Uses PyMuPDF `page.get_drawings()` and flattens every drawing item into
straight segments:

- `l` line items → one segment each
- `c` béziers → 8 chords each
- `re` rectangles / `qu` quads → 4 edges each

Output JSON per page: `segments: [{x0,y0,x1,y1,w}]` in page points (origin
top-left, y grows downward — consistent throughout, so lengths and areas are
unaffected) plus `words: [{t,x0,y0,x1,y1}]` for calibration. Rotated pages are
not normalized in V1; if a sheet prints rotated, extract-and-measure in its
stored orientation (areas are rotation-invariant; only your bbox/seed bookkeeping
must match the stored coordinates).

## 3. Scale calibration

**Rule: no measurement without calibration, on the same sheet.**

1. Find dimension-like words (`10'-0"` → 10.0 ft, `2'-6"` → 2.5 ft) in the
   page's words, skipping any line that reads like a scale note
   (`SCALE: 1/4" = 1'-0"` is a statement about the drawing, not a dimension).
2. For each label, take the longest vector segment whose midpoint falls inside
   the label's bbox expanded by a pad (default 12 pt). Dimension strings in CAD
   exports sit exactly on their dimension line, which makes this match
   reliable; picking the longest candidate rejects tick marks.
3. `pt_per_ft = segment_length_pt / real_length_ft`.
4. Cross-check: the sheet's labels must agree (median is used; spread > 5% is
   a hard stop; 2–5% is a warning you must explain). CAD dimensions are exact,
   so disagreement means wrong segment matched — investigate, don't average.

Sanity band: compare against the title block (1/4"=1'-0" full-size ⇒ 18 pt/ft;
a half-size print ⇒ 9 pt/ft; 1/8" ⇒ 36 pt/ft …). The title block is a CHECK,
never the source. If a sheet has no dimension strings, the skill stops — the
user must supply a known dimension that actually exists as a labeled string on
that sheet (job spec `"calibration": {"text": "..."}`) or the set cannot be
measured honestly.

## 4. Region selection and polygon assembly

The agent gives each countertop a **bbox** (window) and a **seed** (point
inside the counter). `measure.py` then:

1. Keeps segments whose BOTH endpoints lie inside the bbox — this is why the
   bbox must exclude dimension lines, ticks, and non-counter walls.
2. Snaps endpoints to a grid (`--snap`, default 0.05 pt) to heal float noise,
   nodes the linework (`unary_union`) and closes it into faces
   (`shapely.ops.polygonize`).
3. Picks the **smallest face containing the seed**. Smallest, because room
   walls may also form a closed loop around the counter; the counter face is
   strictly inside it. (In the fixture the counter shares an edge with the
   unit outline; noding splits the shared edge and the two faces stay distinct
   — unit ~96 SF vs counter 31.25 SF, so "smallest containing seed" is
   unambiguous.)
4. Area by shoelace over the face vertices → `SF = area_pt² / pt_per_ft²`.

If the seed is not inside any closed loop the tool refuses to guess (exit 2)
with the distance to the nearest loop in the message — usually a bbox too
tight or a seed on a line.

`edge_lf_info` (face perimeter ÷ scale) is reported per region as
INFORMATIONAL ONLY: V1 cannot yet tell countertop front edge from wall edge.

## 5. Repetition and multiplication

- The **unit schedule** (read from page text by the agent, confirmed by the
  user at the gate) is the only multiplier source.
- Measure ONE instance per type; `measure.py` multiplies:
  `extended_sf = sf_per_unit × schedule_count`.
- **Spot-check**: a second instance of the same type must agree within 2%
  (configurable `--spot-tolerance`). These sets are nominally identical, so a
  real deviation means revision mismatch or a modified unit — stop and look.
- Counts the agent cannot find default to 1 WITH A WARNING in the report
  ("VERIFY") — a warning is not license to ship.

### Exception rules (measure separately, do not fold into a type)

| Exception | Why | Handling |
|---|---|---|
| Mirrored units | Same SF by definition | Verify ONE; if it matches, type holds |
| Corner/end units | Extra counter run | Own plan sheet → own instance + own count |
| ADA-modified units | Lowered/shorter runs, different appliances | Own instance + own count |
| Ground / penthouse variants | Upgraded or reduced counter packages | Own instance + own count |
| Amenity spaces (lobby, club, pool bath) | No type letter | Measure individually, count 1 unless schedule says otherwise |
| Unlabeled counters | Unknown multiplier | Open question at the gate — never guess |

## 6. Known limitations (V1, by design)

- **Raster/scanned PDFs**: no vectors → no measurement. Reject clearly.
- **Cutouts**: sink/range inner loops are ignored (outer face wins). Phase 3.
- **Curved counters**: béziers are flattened to 8 chords (error well under a
  square inch at typical scales); fine for V1.
- **Rotated sheets**: areas are fine; bbox/seed must use stored coordinates.
- **Text-as-curves exports**: labels have no text layer → calibration
  impossible → the skill stops rather than assume.
- **3D/BIM exports with smart hatching**: hatch fills add segments inside the
  bbox; the smallest-face rule usually shrugs them off, but watch the
  `loops_found` notes in the report.

## 7. Worked example

`examples/run_example.md` is a full verified run against the synthetic fixture:
known areas are recovered exactly (total 168.75 SF; Type A 38.25 ×3; Type B
27.00 ×2; calibration 18.0000 pt/ft from six labels, spread 0.00%).
