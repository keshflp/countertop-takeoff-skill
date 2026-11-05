---
name: countertop-takeoff
description: >-
  Countertop takeoffs (SF, edge feet, splash, cutouts) from plan PDFs, DXF,
  and rasters. Preflights inputs; reads bitmap schedules with crop-hash evidence;
  reconciles plan tags; calibrates viewports from TWO agreeing dimensions;
  measures selected vector boundaries, DXF, or images; emits PIECE + ASSEMBLY
  BoQs from ONE resolved model and optional assembly-EA pricing (rate x EA).
  Runs to completion with unresolvable quantities BLANK behind CALLOUTS.
---

# Countertop Takeoff

Do a countertop subcontractor's takeoff. Run to completion, then notify once:
no approval gates or idle waiting. Unresolved quantities stay **BLANK**, never
zero, GENUINELY null in every usable field, behind a named CALLOUT. Status:
`complete`, `complete_with_callouts`, `stopped` (exit 0/0/2). Run from THIS skill
folder via `uv run scripts/<name>.py` (uv provisions Python + deps).
Windows-first: filter JSON with Python one-liners, never grep/sed.

## Non-negotiable rules

1. **Vision for recognition, code for measurement.** Look at renders to
   decide WHAT to measure; never type a scale factor or length — select
   recorded words/segments/points and code computes. OCR proves no linework;
   quantities require vectors, verified CAD units, or calibrated images.
2. **Counts are earned, and they correspond.** Every count quotes evidence:
   schedule rows with word boxes, or a bitmap-schedule crop (hash recorded)
   with cell boxes, reconciled against plan room tags. The count VALUE must
   correspond numerically to the quoted evidence (a quoted "3" never
   supports a count of 30; image-evidence types AND variants cite `count_cells`);
   uncertain/unsupported referenced cells withhold the count and dependent
   standard allocation. Hashes prove pixels only; the agent transcribes.
   Plan room tags are DEDUPED RECORDS; a contradictory summary
   withholds the type. Missing counts stay missing — never defaulted to 1.
3. **Graduated degradation.** Bad boundary, missing calibration, unusable
   raster, disagreed count, range breach, overlap, unplanned region,
   failed recheck: try alternate routes, then withhold ONLY the unresolved
   quantities (blank + callout naming room/type, source pages, reason,
   blank fields) and finish the job. Valid EA counts, lengths and finishes
   survive ordinary geometry failure even when SF is impossible. Identity
   conflicts withhold affected SF/extended LF/cutouts and assembly pricing.
4. **Exactly three stops** (exit 2; everything else degrades): (a) no valid
   calibration anywhere (verified native-CAD units qualify); (b) no unit
   schedule AND no repeatable pattern after reading images and plan tags;
   (c) source-file integrity mismatch.
   Schema malformation refuses before measurement; it is not a fourth data stop.
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
intentionally_skipped / superseded / unresolved) keyed by (source_id, page). For CAD:
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

   For a selected scan detail, optional `scripts/scan_detail.py` cleans a
   separate copy and suggests closed linework. Inspect the ORIGINAL and
   suggestion overlay; explicitly adopt/edit an outline before supplying
   points to `image_measure.py`. Suggestions are not countertop recognition,
   calibration, measurement proof or completeness. See the
   [scan assistance procedure](references/method.md#selected-scan-detail-assistance).

### Step 4. Build the job spec
`references/job-spec-v3.md` is the schema; `examples/fixture.jobs.json` and
the output of `examples/make_hotel_jobs.py` are working examples. You write
selections + evidence; code computes everything. Model the job as
assemblies (room/type, package millwork|FFE|public_BOH, finish tag ST/PL/W,
inch dims, handing, quantity basis) and pieces (geometry or stated dims,
edge runs by profile+exposure, splash runs with LH/RH returns, cutouts EA,
source links: length from plan/elevation, depth/thickness/material from
sections/specs). Image-evidence schedule types and variants cite `count_cells` (row/col
of the transcribed cells that prove each count).

### Step 5. Measure
`uv run scripts/measure.py <jobs>.json --report build/report.md --csv
build/takeoff.csv --piece-csv build/pieces.csv --assembly-csv
build/assemblies.csv --json build/results.json`. Exit 0 = deliverable
(callouts in the CALLOUTS section); exit 2 = one of the three stops — read
the named reason. Never edit outputs by hand. Every deliverable derives
from ONE resolved quantity model. Project/report/CSV equal the full known
piece subtotal. Assembly/piece BoQ equality compares the SAME fully resolved
subset; partial assembly pieces remain in the full known subtotal. The hotel
case is 123.00 SF resolved subset vs 146.98 SF full known subtotal. Carry
completeness flags and omission reasons with both; never claim equal scopes.

### Step 6. Audit pack and independent receipt
`uv run scripts/audit_pack.py build/results.json --pack build/audit_pack`
renders overlays. Give a FRESH agent (or an independent human, recorded as
such) the pack + raw sources + JSONs to re-verify counts, shells, spans and
omissions. The pack's `index.md` links assembly/type/variant applications,
earned EA, schedule/tag evidence and original-pixel proofs; unassigned rooms
and unresolved scope stay visible. Record the receipt with `--record-receipt`.
If no independent auditor is available, disclose `independent_audit_unavailable`
and continue.
Use `references/first-run-checklist.md` for supervision/blind exercise; no gate.

### Step 7. Estimate (when the shop asks for pricing)
Receipt storage writes `results.json.receipt.json` and NEVER modifies results.json.
See `references/output-format.md` for immutable hash/receipt and pricing contracts.
With a rate profile (`examples/example.rate-profile.json`): `uv run scripts/estimate.py
build/results.json --profile <rate-profile.json> --out-md
build/estimate.md --out-json build/estimate.json --out-pdf
build/estimate.pdf`. Alternatively use measure's `--estimate-profile` and
`--estimate-md/--estimate-json/--estimate-pdf`; explicit paths must be distinct
from evidence and other outputs. Each assembly prices EA × exact rate.
Unmatched/ambiguous rates, withheld quantities, or omitted in-scope scope
leave unknown amounts BLANK with callouts; priced lines survive, grand total
stays BLANK. Stopped runs or results without `assembly_boq` refuse pricing.
When supplied, per-rate `rate_basis` source/date/quote reference and inclusions
appear on estimates and proposals. Missing metadata stays BLANK; dates do not
imply rate expiry. See `references/company-profile.md`.

### Step 7b. Proposal-lite (when the shop asks for a customer-facing quote)
`uv run scripts/proposal.py build/results.json --estimate
build/estimate.json --profile <rate-profile.json> --out-md
build/proposal.md --out-json build/proposal.json --out-pdf
build/proposal.pdf` builds a branded proposal/BoQ from the corrected estimate:
unchanged EA/rates, package summaries, exclusions/open items, supplied terms,
and blank signature lines. Never invent percentages, tax treatment, or payable
balances. JSON/Markdown/PDF totals must agree.

### Step 8. Deliver
Then deliver report, CSVs (piece BoQ + assembly BoQ — same resolved
records, NEVER summed), results.json, audit pack, receipt, estimate (when
priced), proposal (when quoted), and ONE final summary: totals (with the
known-subtotal + completeness flags), what is BLANK and why (CALLOUTS),
and the coverage ledger (every inventoried item: measured | included_scope
| package_excluded | superseded | unresolved). FF&E-deferred finishes
carry "brand/color TBD" flags.

## Method & output details
Method/tolerances: `references/method.md` · schema: `references/job-spec-v3.md` ·
outputs/pricing/receipts: `references/output-format.md` · profiles: `references/company-profile.md` ·
QuickBooks groundwork (no integration): `references/quickbooks-mapping.md` · CAD: `references/cad-context.md`
