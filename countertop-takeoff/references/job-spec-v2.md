# V2 job spec — the evidence document

`measure.py` is driven by a JSON job spec the AGENT writes after reading the
indexed pack. V2 specs are evidence documents: every number in the deliverable
is either computed from recorded geometry or quoted from recorded text with
word boxes. V1 specs are rejected (`schema` mismatch). A working example:
`examples/fixture.jobs.json`; a full hostile-set example:
`examples/messy.jobs.json`.

## Top level

| key | required | meaning |
|---|---|---|
| `schema` | yes | exactly `"countertop-takeoff/v2"` |
| `source` | yes | `{"pdf": path, "sha256": 64-hex digest of that exact file}` — the approved scope is frozen to this digest; measure re-hashes and refuses on mismatch |
| `geometry` | yes | path to `extract_geometry.py` output (must carry the same source digest) |
| `mode` | yes | `"repeated_types"` (unit schedule multiplies one measured instance per type) or `"individual_rooms"` (each room measured and summed once) — never inferred |
| `policy` | yes | `{"gross_area": "gross" \| "net_of_declared_cutouts", "declarations": [...]}`; `gross_area` may be omitted when a company profile supplies the default. `declarations` records conflicts/omissions/revision decisions for the auditor |
| `profile` | no | path to a company profile (see `references/company-profile.md`) |
| `review` | no | legacy inline field; new independent receipts use `RESULTS.receipt.json`, without modifying results |

## `schedule` (repeated_types only)

| key | meaning |
|---|---|
| `page`, `sheet` | where the schedule lives (citation) |
| `types[]` | `{"type", "count", "row_text", "word_boxes", "rows"?}` — `count` is a positive INTEGER (fractions/negatives refuse; v1 defaulted missing counts to 1 — v2 fails). `row_text` quotes the schedule row; `word_boxes` records the boxes of the words read. `rows[]` optionally decomposes the count per floor (`{"floor", "count", "row_text"}`); the sum must equal `count` |
| `variants[]` | explicit subset allocation: `{"type", "name", "count", "included_in_parent_total", "row_text", "word_boxes", "rows"?}` — `true` = the parent count already contains these units (standard count = count − variant count); `false` = the variant row is additional. ADA-style subsets must not be double-counted |
| `stated_totals` | optional `{"per_floor": {"1": 10, "2": 10}, "project": 20}` — reconciled against the allocated counts; mismatch = hard fail |

## `scope` — the completeness ledger

`pages[]`: ONE entry per source page (any missing page fails):
- `{"page", "disposition": "measured", "expected_regions": [ids...]}` — the
  planned regions for that page; completed results must match exactly
  (missing OR unplanned = fail; an empty list = fail)
- `{"page", "disposition": "intentionally_skipped", "reason"}` — explicit,
  quoted omission (schedule sheets, superseded revisions, unmeasurable
  scans); the reason travels into the report and audit pack
- `{"page", "disposition": "blocked", "reason"}` — unresolved local scope;
  the run completes with callouts and blanks for that page. Run statuses:
  `complete | complete_with_callouts | stopped`.

Measured pages must be class `vector` per the preflight (raster /
searchable_raster / hybrid / text_only pages cannot be measured). Sheets
appearing on several pages with different content (revision conflicts) may
have at most ONE measured page.

## `calibrations[]` — per (page, viewport)

```
{"page": 2, "viewport": "main", "spans": [
  {"label": "10'-0\"", "word_ids": [29], "seg_ids": [14], "real_ft": 10.0?}]}
```

- spans carry the WORDS holding the dimension text and the SEGMENTS of the
  dimension line; code computes every length — the agent never types pt/ft
- `real_ft` optional; parsed from the joined word text otherwise (supports
  split labels like `12'-` + `0"` and fractions like `20'-6` + `1/2"`)
- at least TWO independent spans required; spread ≤2% passes, 2–5% warns,
  >5% hard-fails
- viewports: one sheet can carry two scales (e.g. 18 pt/ft plan + 9 pt/ft
  enlargement); each region calibrates against its own viewport's factor

## `regions[]` — what to measure

| key | meaning |
|---|---|
| `region_id` | unique id, referenced by the scope's `expected_regions` |
| `kind` | `"base"` or `"recheck"` (recheck needs `of`: base region_id; compared within tolerance; never extended) |
| `type`, `variant` | link to the schedule (`variant` must be a declared variant name) |
| `page`, `sheet`, `viewport` | where; viewport defaults to `"main"` and must have a calibration entry |
| `boundary.seg_ids` | the selected boundary segments — must close into EXACTLY one cycle (dangling endpoints/branched nodes refuse, hatch ticks and dimension lines are named in the error) |
| `seed` | `[x, y]` strictly interior point (on-boundary refuses) |
| `expected_sf_range` | `[min, max]` sanity guard; breach = hard fail (this is what catches a wrong calibration) |
| `cutouts` | optional `[{"label", "seg_ids"}]` inner loops; subtracted only under the net policy (each must lie fully inside the boundary) |
| `assembly`, `material` | optional identity (profile groundwork); SF stays the only active quantity |
