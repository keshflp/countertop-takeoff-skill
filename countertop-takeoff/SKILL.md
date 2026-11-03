---
name: countertop-takeoff
description: >-
  Countertop square-footage takeoff from architectural plan/spec PDFs for
  countertop subcontractors bidding apartments and hotels. Indexes the drawing
  set, finds the unit schedule (multiplier table), calibrates drawing scale
  from labeled dimensions, measures countertop polygons from extracted vector
  geometry with scripts, multiplies by the schedule, and emits a cited QA
  report + CSV. Use when the user shares plan PDFs and asks for countertop
  quantities, square footage, SF, or a takeoff.
---

# Countertop Takeoff (V1: square footage only)

You are doing a countertop takeoff on a set of plan/spec PDFs for a countertop
subcontractor. Multifamily/hospitality sets are repetitive: a unit schedule
lists room types (Type A ×24, Type B ×12…) and each type has ONE repeated plan.
V1 scope is **square footage only**. Edge linear feet, backsplash, cutouts,
slab yield, pricing, and invoicing are later phases — see "Extension points".

Every command below runs from THIS skill folder (the folder containing
`SKILL.md`). Scripts are plain Python driven by `uv`:

```console
uv run scripts/index_pdf.py <file.pdf>
```

`uv` auto-provisions Python and the pinned dependencies (`pymupdf`, `shapely`)
on first use — no Python install needed. Fallback for machines without uv:
`pip install -r scripts/requirements.txt`, then run `python` instead of
`uv run`.

## Non-negotiable rules

1. **Vision for recognition, code for measurement.** You may LOOK at rendered
   pages only to decide WHAT to measure (which sheets show kitchens/vanities,
   where the unit schedule is, what a polyline represents). You must NEVER
   produce a quantity by eyeballing an image. Every number in the deliverable
   comes from `measure.py` operating on extracted vector geometry.
2. **Mandatory scale calibration.** Never convert PDF points to feet without a
   calibration factor recovered from a labeled dimension ON THE SAME SHEET
   (e.g. a "10'-0"" string whose endpoints exist in the vector data). If
   calibration fails, STOP and tell the user. Never assume a scale from the
   title block note (1/4"=1'-0" is often wrong on half-size or non-standard
   prints) — you may use it only as a sanity band around the measured factor.
3. **Multiplication is earned, never assumed.** The unit/room-type schedule is
   the multiplier table. Find it, read its counts from page TEXT, verify them
   at the check-in gate, and only then multiply. No schedule + no repetition =
   fallback mode (step 10).
4. **Check-in gate.** Pause for user approval after indexing (step 7 in the
   flow below) — before any extraction work.
5. **Cite everything.** Every number cites sheet + page. Deliver the QA table.
6. **Self-audit.** Run the step-9 checklist before presenting results. If any
   item fails, fix or disclose — never silently ship.

## Workflow

### 1) Intake & page inventory

- Ask for / locate the PDF(s). If plans are only available on a planroom,
  the USER downloads them manually (respect the vendor's terms — this skill
  never scrapes planrooms).
- Run `uv run scripts/index_pdf.py <file.pdf>` for each PDF. It writes
  `<pdf>.index.json` (full per-page TEXT + flags) and prints a table:
  sheet numbers, unit-schedule/plan/spec flags, countertop keyword hits,
  dimension-label counts, type tags.
- Skim the JSON text of flagged pages. Note: scanned (raster-only) pages have
  no text and no vectors — if `dim_count` is 0 everywhere and text is empty,
  the set needs OCR/vector treatment that V1 does not do. Say so and stop.

### 2) Find the unit schedule (the multiplier table)

- Candidates are pages flagged `unit_schedule` (or "schedule" + qty/type tags).
  READ their text. Build the table: `type -> count`, and note the source sheet
  (e.g. A-001). Room types may also appear as unit types (1BR/2BR), room
  numbers with repeated tags, or hospitality keys (King run, Queen run, ADA).
- Cross-check counts against anything else in the set that states totals
  (cover sheet stats, parking count × bedrooms). Discrepancies go to the
  check-in gate, not to silent judgment calls.
- If there is NO schedule and plans show each room individually → jump to
  step 10 (fallback mode).

### 3) Identify countertop-bearing sheets per type

- From the index: plan sheets with `counter_terms` (counter/countertop/vanity/
  kitchen) — usually one plan per TYPE, not per unit. Elevations/details give
  construction info, not area; ignore them for V1.
- Extract vector geometry for ONLY those pages:
  `uv run scripts/extract_geometry.py <file.pdf> --pages 2,3 --out build/<name>.geometry.json`
  (1-based page numbers, exactly as index_pdf prints them).
- If you have page images or a rendering surface, you may view pages to locate
  countertops; then express each location as a bbox + interior seed point in
  PDF page coordinates (the geometry JSON tells you the page size; segment
  coordinates cluster around the linework you identified). This is the ONLY
  vision-to-code handoff: coordinates for WHERE, never numbers for HOW MUCH.
- You can find seed points without images too: `words` in the geometry JSON
  give label positions (e.g. the word "KITCHEN"), and `segments` cluster by
  room. Grep the JSON: `grep -o '"t": *"KITCHEN"[^}]*' build/*.geometry.json`.

### 4) Calibration

- `measure.py` calibrates automatically: it finds dimension-like words
  (`10'-0"`, `2'-6"`, `8'`…) in the page's text layer, matches each to the
  longest vector segment whose midpoint sits inside the label's bbox (+pad),
  and computes `pt_per_ft = segment_length / real_length`. Multiple labels are
  cross-checked (median; >5% spread = hard stop).
- You do not need to do anything — but you DO need to verify the printed
  calibration table in the report: labels matched, scales, spread. If a sheet
  has no usable dimension strings (common on scanned sheets), measure.py exits
  with `CALIBRATION FAILED`. Do NOT proceed by assuming a scale; ask the user
  for a known dimension (e.g. a door width) and pass it explicitly via the job
  spec: `"calibration": {"text": "3'-0\""}` — only if such a label truly exists
  on that sheet.
- Sanity band: the measured factor should roughly match the title-block scale
  (1/4"=1'-0" ⇒ ~18 pt/ft at full size; half-size prints halve it). A wild
  mismatch means the wrong sheet region or a scaled photocopy — investigate.

### 5) Measure one instance per type (scripts, exact geometry)

- Write a job spec JSON (schema in `scripts/measure.py` docstring;
  working example: `examples/fixture.jobs.json`). Per TYPE, measure ONE
  instance: one entry with `page`, `sheet`, and `regions` — each region =
  `{"name": "kitchen", "bbox": [x0,y0,x1,y1], "seed": [x,y],
  "expected_sf_range": [min,max]}`.
- bbox rules: big enough to contain the ENTIRE countertop outline with margin,
  small enough to EXCLUDE neighboring linework (dimension lines/ticks, wall
  lines not part of the counter, adjacent counters). Seed = any point strictly
  inside the counter outline. Add `expected_sf_range` from gut sense — it is a
  QA guard, NOT the measurement (range breach = audit fail).
- Run: `uv run scripts/measure.py <jobs>.json --report build/report.md --csv build/takeoff.csv --json build/results.json`
- How it measures: segments inside bbox → endpoints snapped → linework noded
  and closed into loops (shapely `polygonize`) → smallest loop containing the
  seed = the countertop → shoelace area ÷ scale² = SF. The report also lists
  edge LF per region as INFORMATIONAL ONLY (phase-2 scope).
- Typical real-world bboxes are generous; when a bbox catches extra closed
  loops (walls), the tool takes the smallest loop containing the seed and
  notes it. Verify such notes.

### 6) Spot-check + exception hunt

- Spot-check: measure a SECOND instance of the same type (another sheet showing
  the same type, or the same region with an independently chosen bbox) as a
  second job entry. `measure.py` compares instances per type; >2% deviation =
  audit FAIL. Resolve before shipping (different revisions? different unit?).
- Exception hunt — look for units whose SF differs from their type and must be
  measured separately (add them as their own room_type/instance entries):
  - **Mirrored units**: same SF; verify ONE mirrored instance matches its type.
  - **Corner / end units**, **ADA-modified units**, **ground/penthouse
    variants**: usually their own plan sheet — measure separately, get their
    true count from the schedule or key plan.
  - **Amenity spaces** (lobby, clubroom, pool bath): no type letter — measure
    each individually with `schedule_count` 1 or their own count.
  - **Missing/mismatched tags**: any counter on a plan whose type you cannot
    name goes to the check-in gate as an open question.

### 7) Check-in gate with the user (MANDATORY PAUSE)

After indexing and BEFORE extraction/measurement, present and wait for
approval:

1. Sheets found (page → sheet → title, candidate role).
2. Room/unit types found and counts as read from the schedule (quote them).
3. The exact item list you intend to take off (type → sheet → regions).
4. Anything ambiguous (unclear counts, exceptions, suspected revisions).

Only after explicit approval continue. If the user corrects a count, fix the
job spec and re-run. Do not skip the gate even if the user said "just do it"
— summarize and give them a clear one-line approve/fix choice.

### 8) Extended takeoff table + QA table

`measure.py` emits both. Deliver them (report.md text + takeoff.csv) and keep
the CSV undamaged — it feeds the shop's quoting workflow later:

- **Totals**: per type — SF/unit (from ONE measured instance), schedule count,
  extended SF; project total.
- **QA table**: room type | instance measured | SF | schedule count |
  extended SF | source (pdf, page, sheet). Every number traces to a sheet.
- CSV columns: `room_type, instance, region, sheet, page, region_sf,
  edge_lf_info, instance_sf, schedule_count, extended_sf, source, notes`.

### 9) Self-audit checklist (run before presenting results)

Every item prints in the report's Self-audit section; re-verify the human ones:

- [ ] Calibration factor reported per sheet, labels matched, spread within
      limit (script enforces; you read the table).
- [ ] Counts match the schedule YOU read — and you showed them to the user at
      the gate.
- [ ] Per-type SF within sane ranges (script checks `expected_sf_range`;
      sanity bands: apartment kitchen counters ~15–45 SF, vanities ~4–15 SF;
      hotels vary more — use judgment, flag surprises).
- [ ] No unexplained room tags: every measured region answered "which type,
      how many"; every schedule type answered "where measured".
- [ ] Spot-check deviations within tolerance (script enforces; you explain any
      warn).
- [ ] No region's SF exceeds its bbox cap (script enforces).
- [ ] Citations: every row carries pdf + page + sheet (script generates).

If anything FAILs: fix the job spec and re-run, or disclose the failure.
`measure.py` exits non-zero on fail — never edit its output by hand.

### 10) No-pattern fallback mode

If the set has NO unit schedule AND rooms do not repeat (custom homes, clubs,
restaurants): declare **"no repetition pattern found"** to the user, then:

- list EVERY countertop-bearing room as its own "type" with count 1,
- measure each room's instance individually (steps 4–5 per room),
- expect the check-in gate to be longer: confirm the full room list before
  measuring,
- totals = plain sum; QA table shows count 1 everywhere — that is correct here,
  not a bug.

Never invent repetition ("these two bathrooms look the same") without user
confirmation at the gate.

## Extension points (future phases — do NOT implement now)

- **Edge linear feet**: `edge_lf_info` per region is already computed and
  reported (informational). Phase 2 promotes front-edge vs backsplash edges by
  identifying which polygon edges face open floor.
- **Backsplash height / SF**: needs section/elevation data (edge heights).
- **Cutouts**: sinks/ranges are inner loops; V1 picks the outer face only.
  Phase 3 subtracts inner loops contained in the face.
- **Slab yield / seam planning**: polygon layout vs standard slab sizes.
- **Pricing + QuickBooks invoices**: SF × unit price matrix per material.
- **Shop-drawing PDFs**: counter elevations from the measured polygons.

## Smoke test (2 minutes, no real project needed)

Prove the toolchain works on any machine:

```console
uv run examples/make_fixture.py --out build/smoke.pdf
uv run scripts/index_pdf.py build/smoke.pdf
uv run scripts/extract_geometry.py build/smoke.pdf --pages 2,3 --out build/smoke.geometry.json
uv run scripts/measure.py examples/fixture.jobs.json --report build/smoke_report.md --csv build/smoke.csv
```

Expected: total **168.75 SF** (Type A 38.25 ×3 + Type B 27.00 ×2), calibration
18.0000 pt/ft, self-audit PASS. Full walkthrough with verified output:
`examples/run_example.md`.

## Method & output details

- Measuring method, calibration math, geometry extraction, exception rules:
  `references/method.md`.
- Exact output formats (report, CSV, results JSON, exit codes):
  `references/output-format.md`.
