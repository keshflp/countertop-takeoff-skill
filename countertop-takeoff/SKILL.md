---
name: countertop-takeoff
version: 5.0.0
description: >-
  Countertop takeoffs (SF, edge feet, splash, cutouts) from plan PDFs, DXF,
  and rasters. Preflights the pack, transcribes bitmap schedules with
  crop-hash evidence, cross-validates counts against plan room tags,
  calibrates per viewport from TWO agreeing dimensions, measures
  agent-selected vector boundaries (plus DXF and image routes), and emits
  PIECE + ASSEMBLY BoQs from ONE resolved quantity model - plus an
  optional assembly-EA estimate (rate x EA). Runs to completion;
  unresolvable quantities stay BLANK behind CALLOUTS. Use for countertop
  quantity requests on plan sets.
---

# Countertop Takeoff (V5: safe publishing, evidence identity, complete-scope estimates)

You are doing a countertop takeoff on a drawing set for a countertop
subcontractor. Run to completion, then notify once — no approval gates, no
idle waiting. Unresolvable quantities stay **BLANK** (never zero, and
GENUINELY null — a withheld number never survives as a value in another
field) behind a named CALLOUT; the run finishes `complete`,
`complete_with_callouts`, or `stopped` (exit 0 / 0 / 2). Commands run from
THIS skill folder via uv (`uv run scripts/<name>.py`; uv provisions Python
+ deps). Windows-first: filter JSON with Python one-liners, never grep/sed.

## Non-negotiable rules

1. **Vision for recognition, code for measurement.** Look at renders to
   decide WHAT to measure; never type a scale factor or length — select
   recorded words/segments/points and the code computes. OCR text proves
   nothing about linework; only vector geometry, verified-units CAD, or the
   calibrated image route produces quantities.
2. **Counts are earned, and they correspond.** Every count quotes evidence:
   schedule rows with word boxes, or a bitmap-schedule crop (hash recorded)
   with cell boxes, reconciled against plan room tags. The count VALUE must
   correspond numerically to the quoted evidence (a quoted "3" never
   supports a count of 30; image-evidence counts cite `count_cells`); plan
   room tags are DEDUPED RECORDS, and a supplied summary contradicting them
   withholds the type. Missing counts stay missing — never defaulted to 1.
3. **Graduated degradation.** Bad boundary, missing calibration, unusable
   raster, disagreed count, range breach, overlap, unplanned region,
   failed recheck: try alternate routes, then withhold ONLY the unresolved
   quantities (blank + callout naming room/type, source pages, reason,
   blank fields) and finish the job. Valid EA counts, lengths and finishes
   survive even when SF is impossible.
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
sections/specs). Image-evidence schedule types cite `count_cells` (row/col
of the transcribed cells that prove each count).

### Step 5. Measure
`uv run scripts/measure.py <jobs>.json --report build/report.md --csv
build/takeoff.csv --piece-csv build/pieces.csv --assembly-csv
build/assemblies.csv --json build/results.json`. Exit 0 = deliverable
(callouts in the CALLOUTS section); exit 2 = one of the three stops — read
the named reason. Never edit outputs by hand. Every deliverable derives
from ONE resolved quantity model: project total == assembly BoQ total ==
piece BoQ total == report == CSV grand total (the run asserts this).

### Step 5b. Estimate (when the shop asks for pricing)
Receipt storage is separate from results: `audit_pack.py --record-receipt`
writes `results.json.receipt.json` and NEVER modifies results.json. Its
`results_sha256` hashes the exact immutable results bytes. Pricing/proposal
hashes therefore stay current even if the independent receipt is recorded
later. Receipts travel beside the results; they are not embedded in pricing.
With a rate profile (`examples/example.rate-profile.json` shows the v2
pricing schema — rates[] pin `match.assembly_kind` plus dims/finish, uom
EA, unit_price, includes[]): `uv run scripts/estimate.py
build/results.json --profile <rate-profile.json> --out-md
build/estimate.md --out-json build/estimate.json --out-pdf
build/estimate.pdf` (or add `--estimate-profile` to the measure command;
`--estimate-md/--estimate-json/--estimate-pdf` set EXPLICIT output paths —
an estimate may never overwrite its own evidence package, and paths that
would alias the results/report de-alias automatically). Each in-scope
assembly prices EA × exact rate; unmatched or ambiguous rates and withheld
quantities stay BLANK behind callouts; omitted in-scope scope (a room
covered by NO assembly) is an UNKNOWN amount — priced lines survive, the
grand total stays BLANK, and the callout names what is missing. A
`stopped` run or a results file without `assembly_boq` refuses to be
priced. The .pdf is a PyMuPDF render of estimate.md whose rendered amounts
are re-checked against estimate.json — render a richer PDF from the same
md with the host's document tooling if you have one; the grand total must
agree.

### Step 5c. Proposal-lite (when the shop asks for a customer-facing quote)
`uv run scripts/proposal.py build/results.json --estimate
build/estimate.json --profile <rate-profile.json> --out-md
build/proposal.md --out-json build/proposal.json --out-pdf
build/proposal.pdf` builds a branded proposal/BoQ from the CORRECTED
estimate: fixed layout, short cover note, package summaries grouped FROM
THE DATA, unchanged EA quantities and exact rates, exclusions assembled
from the estimate's exclusions + open items, the profile's SUPPLIED terms,
and blank signature lines. Never invent percentages, tax treatment, or
payable balances. json/md/pdf totals must agree (the script enforces it).

### Steps 6–7. Audit pack, independent audit, deliver
`uv run scripts/audit_pack.py build/results.json --pack build/audit_pack`
renders overlays. Give a FRESH agent (or an independent human, recorded as
such) the pack + raw sources + JSONs to re-verify counts, shells, spans and
omissions; record the receipt with `--record-receipt`. If no independent
auditor is available, deliver with the receipt status disclosed
(`independent_audit_unavailable`) — disclosed, not hidden, not a blocker.
Then deliver report, CSVs (piece BoQ + assembly BoQ — same resolved
records, NEVER summed), results.json, audit pack, receipt, estimate (when
priced), proposal (when quoted), and ONE final summary: totals (with the
known-subtotal + completeness flags), what is BLANK and why (CALLOUTS),
and the coverage ledger (every inventoried item: measured | included_scope
| package_excluded | superseded | unresolved). FF&E-deferred finishes
carry "brand/color TBD" flags.

## Method & output details
Method, calibration bands, boundary closure, curve tolerance:
`references/method.md` · V3/V4 schema: `references/job-spec-v3.md` · output
formats (incl. estimate + proposal): `references/output-format.md` ·
company profile + rate profile (v2 pricing schema, terms):
`references/company-profile.md` · QuickBooks import groundwork (docs only,
no integration): `references/quickbooks-mapping.md` · CAD landscape +
optional CAD-MCP escalation (docs only): `references/cad-context.md`
