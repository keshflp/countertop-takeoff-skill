---
name: countertop-takeoff
version: 3.0.0
description: >-
  Countertop takeoffs (SF, edge feet, splash, cutouts) from plan PDFs, DXF,
  and rasters. Preflights the pack, transcribes bitmap schedules with
  crop-hash evidence, cross-validates counts against plan room tags,
  calibrates per viewport from TWO agreeing dimensions, measures
  agent-selected vector boundaries (plus DXF and image routes), and emits
  PIECE + ASSEMBLY BoQs from one evidence model. Runs to completion;
  unresolvable quantities stay BLANK behind CALLOUTS. Use for countertop
  quantity requests on plan sets.
---

# Countertop Takeoff (V3: measure everything measurable, disclose the rest)

You are doing a countertop takeoff on a drawing set for a countertop
subcontractor. Run to completion, then notify once — no approval gates, no
idle waiting. Unresolvable quantities stay **BLANK** (never zero) behind a
named CALLOUT; the run finishes `complete`, `complete_with_callouts`, or
`stopped` (exit 0 / 0 / 2). Commands run from THIS skill folder via uv
(`uv run scripts/<name>.py`; uv provisions Python + deps). Windows-first:
filter JSON with Python one-liners, never grep/sed.

## Non-negotiable rules

1. **Vision for recognition, code for measurement.** Look at renders to
   decide WHAT to measure; never type a scale factor or length — select
   recorded words/segments/points and the code computes. OCR text proves
   nothing about linework; only vector geometry, verified-units CAD, or the
   calibrated image route produces quantities.
2. **Counts are earned.** Every count quotes evidence: schedule rows with
   word boxes, or a bitmap-schedule crop (hash recorded) with cell boxes,
   reconciled against plan room tags. Missing counts stay missing — never
   defaulted to 1.
3. **Graduated degradation.** Bad boundary, missing calibration, unusable
   raster, disagreed count: try alternate routes, then exclude ONLY the
   unresolved quantities (blank + callout naming room/type, source pages,
   reason, blank fields). Valid EA counts, lengths and finishes survive
   even when SF is impossible.
4. **Exactly three stops** (exit 2; everything else degrades): (a) no valid
   calibration anywhere (verified native-CAD units qualify); (b) no unit
   schedule AND no repeatable pattern after reading images and plan tags;
   (c) source-file integrity mismatch.
5. **Cite everything.** Every number carries source id, page, viewport,
   selection ids, and the actual calibration factor.

## Workflow — in this order, to completion

### Step 0. Intake
Resolve every requested input into ONE job directory on this machine:
local paths and chat attachments directly; Drive/OneDrive files fetched by
their apps into the job dir. Then `uv run scripts/intake.py --job-dir
jobs/<name> --source <path>... [--expect N] [--cloud-id ...]` writes the
intake manifest (requested vs resolved, sizes, hashes, page counts,
expected-count verdict). Unavailable inputs are disclosed callouts.

### Step 1. Preflight + inventory
`uv run scripts/index_pdf.py <file.pdf>` → page table + `<pdf>.index.json`:
content classes and REGIONS (a pasted bitmap schedule under a vector header
is flagged for vision reading), duplicate pages, sheet-alias candidates,
drawing-index gaps, revision marks. Disposition EVERY page (measured /
intentionally_skipped / superseded) keyed by (source_id, page). For CAD:
`uv run scripts/cad_input.py <file.dxf> --out ...` (DWG: convert via the
free ODA File Converter first; unitless files refuse without `--units`).

### Step 2. Schedule evidence + room tags
Text schedules: quote rows with word boxes. Bitmap schedules (flagged in
step 1): render a legible crop, read it with vision, record the crop hash +
cell boxes + uncertain cells. Independently inventory room/type tags across
plans (dedupe rooms shown on both overall and enlarged plans), then
reconcile schedule cells ↔ floor subtotals ↔ project total ↔ plan-derived
counts. A count disagreeing with plan tags without recorded resolution
evidence is withheld (blank + callout) — the invented-count guard.

### Step 3. Measure — routes in order
1. **Vector PDF**: calibrate each (page, viewport) from TWO+ agreeing
   labeled dimension spans (unique lengths, unique segments — duplicating
   one span never counts twice); select closed boundary segments per region
   with a strictly interior seed and an honest expected_sf_range; extract
   with `uv run scripts/extract_geometry.py`. 2. **Supplied DXF**: verified
   units ARE the calibration (step 1). 3. **Decent rasters**: `uv run
   scripts/image_measure.py --crop ... --anchors ... --points ...` — anchor
   endpoints of labeled dimensions plus boundary points; code computes
   scale + area; overlay proof mandatory; unusable rasters stay blank; no
   full-plan tracing. Stated dimensions beat scaling: DO NOT SCALE DRAWINGS
   sheets get stated values from sections/elevations joined to plan lengths.

### Step 4. Build the job spec
`references/job-spec-v3.md` is the schema; `examples/fixture.jobs.json` and
the output of `examples/make_hotel_jobs.py` are working examples. You write
selections + evidence; code computes everything. Model the job as
assemblies (room/type, package millwork|FFE|public_BOH, finish tag ST/PL/W,
inch dims, handing, quantity basis) and pieces (geometry or stated dims,
edge runs by profile+exposure, splash runs with LH/RH returns, cutouts EA,
source links: length from plan/elevation, depth/thickness/material from
sections/specs).

### Step 5. Measure
`uv run scripts/measure.py <jobs>.json --report build/report.md --csv
build/takeoff.csv --piece-csv build/pieces.csv --assembly-csv
build/assemblies.csv --json build/results.json`. Exit 0 = deliverable
(callouts in the CALLOUTS section); exit 2 = one of the three stops — read
the named reason. Never edit outputs by hand.

### Steps 6–7. Audit pack, independent audit, deliver
`uv run scripts/audit_pack.py build/results.json --pack build/audit_pack`
renders overlays. Give a FRESH agent (or an independent human, recorded as
such) the pack + raw sources + JSONs to re-verify counts, shells, spans and
omissions; record the receipt with `--record-receipt`. If no independent
auditor is available, deliver with the receipt status disclosed
(`independent_audit_unavailable`) — disclosed, not hidden, not a blocker.
Then deliver report, CSVs (piece BoQ + assembly BoQ — same records, NEVER
summed), results.json, audit pack, receipt, and ONE final summary: totals,
what is BLANK and why (CALLOUTS), and the coverage ledger (every
inventoried item: measured | package_excluded | superseded | unresolved).
FF&E-deferred finishes carry "brand/color TBD" flags.

## Method & output details
Method, calibration bands, boundary closure, curve tolerance:
`references/method.md` · V3 schema: `references/job-spec-v3.md` · output
formats: `references/output-format.md` · company profile:
`references/company-profile.md` · CAD landscape + optional CAD-MCP
escalation (docs only): `references/cad-context.md`
