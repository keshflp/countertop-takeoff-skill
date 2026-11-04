# Output format spec (5.1.0)

Contracts for reports, audit packs, estimates, and proposals. Existing v3
results/v5 pricing schema tags are retained.

## 1. Markdown report (`measure.py --report`)

Sections, in order:

1. **Header** — source PDF(s) + sha256 prefixes, UTC timestamp, mode and
   gross-area policy, declarations (conflicts/omissions/revision decisions)
   recorded for the auditor.
2. **Approved scope** — table `page | sheet | disposition | detail` (detail
   = expected region ids, or the quoted disposition reason). Every source
   page appears exactly once.
3. **Schedule evidence** — the quoted rows, counts, variant flags
   (included in parent total vs additional), stated totals; or the
   `individual_rooms` declaration.
4. **Calibration** — per (source, page, viewport): one row per span
   (`label | seg pt | real ft | pt/ft`), then the factor actually used and
   the spread verdict (OK / WARNING), plus disclosed `real_ft` overrides.
5. **Takeoff by region** — per type: rows with `region | variant |
   assembly/material | sheet (page, viewport) | SF | count | extended SF |
   factor pt/ft` (the ACTUAL per-region factor), type totals (excluded
   package scope shown separately), and the project total.
6. **CALLOUTS** — every degraded-but-disclosed finding: scope, reason,
   blank fields.
7. **Coverage ledger** — every inventoried item (rooms, types, variants,
   regions, pages, assemblies, pieces) in exactly one state:
   `measured | included_scope | package_excluded | superseded | unresolved`.
8. **ASSEMBLY BoQ + PIECE BoQ** — two views of the SAME resolved records
   (never summed); piece extensions ×EA; splash handing/returns preserved.
9. **Audit checklist** — every pass/warn/fail item with detail, the review
   status line, and the overall run status:
   `complete`, `complete_with_callouts`, or `stopped`.

Input dispositions (`measured | intentionally_skipped | superseded | unresolved`)
describe page plans; coverage-ledger states describe resolved output scope.

## 2. CSV (`--csv`) — completed runs, including callouts

Columns: `row_kind, room_type, variant, region_id, sheet, page, viewport,
region_sf, count_applied, region_extended_sf, pt_per_ft_used, source, notes`

Jobs WITHOUT assemblies keep the V2 shape:
- `base` — one row per measured base region; `count_applied` = the units
  this region's SF multiplies; `region_extended_sf = region_sf ×
  count_applied`
- `recheck_of_base` — QA recheck rows: `count_applied` 0,
  `region_extended_sf` EMPTY
- `type_total` — exactly one per type with the type's extended SF
- `grand_total` — one row, project total

Jobs WITH assemblies derive every row from the ONE resolved model:
- `base` — one row per PIECE (blank SF/extensions stay blank; notes carry
  the state + the named blanks)
- `type_total` — one per active type; an ALL-unknown type totals as
  `__blank__` (never 0.00)
- `excluded_package_total` — one row with the excluded package SF,
  documented as NEVER added into the grand total
- `grand_total` — equals the full known piece subtotal and project/report.
  BoQ equality compares the SAME fully resolved assembly subset separately.
  Hotel: 123.00 SF resolved subset vs 146.98 SF full known subtotal; unknown
  contributions keep completeness false. Neither number asserts complete scope.

## 2b. Stale-output handling + stopped diagnostics

On ANY stop (the three data stops, spec refusals, unexpected crashes),
measure.py quarantines EVERY superseded artifact — CSVs, the report,
results.json, and estimate/proposal outputs — as `<name>.stale-<utc>`, and
writes a CURRENT stopped diagnostic results JSON
(`run_status: "stopped"`, `stopped_early: true`, the stop reason) over the
results path before quarantining dependent outputs. No CSV exports are written
for stopped runs; old artifacts cannot look current. Receipt rules are below.

Input/output and output/output aliases are rejected before any write or
cleanup, using case-insensitive canonical Windows identity (including links).
This includes JOB -> JOB and every proposal output -> estimate/input alias.
`RESULTS.artifacts.json` records dependent output paths, including proposals
outside the results directory; keep it with the job for stopped-rerun cleanup.
Pricing refusals (`SystemExit`) and unexpected exceptions follow the same
stopped-diagnostic/quarantine path. Invalid alias requests leave inputs intact.

## 3. Results JSON (`--json`) — the evidence package

```json
{
  "schema": "countertop-takeoff/v3 results",
  "source": {"pdf": "...", "sha256": "..."},
  "mode": "repeated_types", "policy": {...}, "declarations": [...],
  "runtime_versions": {"python": "...", "pymupdf": "2.1",
                       "shapely": "2.2.0", "platform": "...", ...},
  "settings": {"snap_pt": 0.05, "recheck_tolerance_pct": 2.0},
  "scope": {...}, "schedule": {...}, "profile": {...},
  "calibrations": {"<page>:<viewport>": {"spans": [...],
                  "factor_pt_per_ft": 18.0, "spread_pct": 0.0,
                  "status": "pass"}},
  "regions": [{"region_id": "A:kitchen", "kind": "base", "type": "A",
               "page": 2, "viewport": "main", "sheet": "A-101",
               "boundary_seg_ids": [4,5,6,7,8,9], "seed": [160, 390],
               "polygon": [[x, y], ...], "cutout_polygons": [...],
               "area_sf": 31.25, "gross_area_sf": 31.25,
               "factor_pt_per_ft": 18.0, "gross_area_policy": "gross",
               "curved_boundary": false, "expected_sf_range": [25, 40],
               "expected_range_ok": true, "assembly": null,
               "material_canonical": null}],
  "types": [{"room_type": "A", "schedule_count": 3, "std_units": 3,
             "sf_per_unit": 38.25, "extended_sf": 114.75, "rows": [...]}],
  "totals": {"project_sf": 168.75, "unit_count": 5,
             "known_subtotal_sf": 168.75, "project_sf_complete": true,
             "unknown_contribution_count": 0, "assembly_ea": null},
  "audit": [{"check": "...", "status": "pass|warn|fail", "detail": "..."}],
  "run_status": "complete | complete_with_callouts | stopped",
  "callouts": [{"scope", "reason", "blank_fields", "source"}],
  "coverage_ledger": [{"item", "kind", "state":
                       "measured|included_scope|package_excluded|superseded|unresolved"}],
  "assembly_boq": [...],
  "piece_boq": [...],
  "scope_incomplete": [{"item", "kind", "state": "unresolved", "detail"}],
  "unavailable_inputs": [{"item", "detail", "source"?}],
  "review_status": "independent_audit_pending",
  "geometry_page_classes": {"1": "text_only", "2": "vector"}
}
```

After an independent audit, `audit_pack.py --record-receipt` writes
`results.json.receipt.json` without modifying results.json:

```json
{"status": "independent_audit_recorded", "reviewer": "...",
           "verdict": "approved|rejected", "notes": "...",
           "pack_dir": "...", "results_sha256": "...",
           "superseded_results_files": [...],
 "recorded_utc": "...", "review_status": "independent_audit_approved"}
```

The receipt hashes the exact immutable results bytes. Recording it cannot
stale pricing/proposal hashes. Empty `{}`, noncompleted or quarantined results
are refused. Superseded siblings match the real `results.json.stale-*` names.
Normal sequence: intake -> inventory/evidence -> selections/spec -> measurement
-> audit/receipt -> pricing/proposal -> delivery. Audit unavailability is
disclosed, with no gate; the separate receipt can be recorded later safely.

## 4. Audit pack (`audit_pack.py --pack DIR`)

- `<source>__<region>-<digest>_full.png` / `..._closeup.png` per measured
  region (collision-resistant, source-qualified filenames): base page render
  (recorded rotation applied) + translucent measured shell, region id,
  area, ACTUAL factor, policy, seed marker, calibration span highlights,
  declared cutouts. Relative paths resolve against the RESULTS file's own
  location; a corrupt geometry payload degrades per-source with a
  disclosed GEOMETRY NOTE instead of aborting the pack
- `index.md`: run summary (run status, review status, totals), the CALLOUTS
  the reviewer must confirm, plus what to check: raw sheets, schedule
  evidence, omissions, overlays. Unresolved regions render a marker page
  naming the blank; image-route regions point at the route's own overlay

## 5. Exit codes

| code | meaning |
|---|---|
| 0 | `complete` (deliverable) or `complete_with_callouts` (deliver with the CALLOUTS list: blank fields named, never zeros); CSVs written |
| 2 | `stopped` — one of the three catastrophic cases: no valid calibration anywhere (verified-units CAD OR a valid image-route calibration qualifies), no schedule and no repeatable pattern, or source integrity mismatch (ALL source kinds are re-hashed before measuring); also spec malformation. Diagnostics (report + results JSON) are still written; no exports; stale exports quarantined — even when the pipeline itself crashes. A `stopped` run can never receive an approved audit receipt |

## 5b. Estimate (`estimate.py` / `measure.py --estimate-profile`)

One computation over the assembly BoQ + rate profile produces:

- `estimate.json` — schema `countertop-takeoff/v5 estimate`; scope_complete
  flag, unknown_scope (omitted in-scope items), currency,
  sha256 of the results JSON + rate profile, `lines[]` (item_code,
  description with inch dims, assembly_ids, room, qty_ea, unit_price_exact,
  line_total, rate_reference {item_code, includes, uom},
  quantity_evidence, callout_references, arithmetic string),
  `priced_subtotal`, `grand_total` (null while any in-scope amount is
  unknown), `unknown_amounts`, `exclusions` (package-excluded assemblies,
  never priced), `callouts`, and the arithmetic block (Decimal exact,
  ROUND_HALF_UP to whole cents per line, single-currency rule)
  (`unit_price` remains a legacy approximate numeric field; documents and
  arithmetic use the authoritative exact decimal string)
- `estimate.md` — header (company, timestamp, currency, scope-completeness
  flag, provenance); table `Item code | Description | QTY EA | Unit price |
  Total` (long descriptions wrap into continuation rows — amounts never
  split); priced subtotal; exclusions; CALLOUTS (incl. omitted in-scope
  scope as UNKNOWN amounts); grand total — BLANK while any in-scope amount
  is unknown; per-line arithmetic with EXACT rate precision (55.555 stays
  55.555, never 55.56)
- `estimate.pdf` — PyMuPDF render of estimate.md: first line below the
  page top, wrapped + paginated (grand total on the last page), and every
  rendered amount RE-READ from the PDF and checked against estimate.json
  before the file ships. Markdown syntax is removed: PDFs show plain BLANK,
  clean headings and exact rates, with readable assembly/room identifiers.
  Host tooling may render richer PDFs from the same Markdown; totals must agree.
- `proposal.json` / `proposal.md` / `proposal.pdf` (`scripts/proposal.py`,
  ) — proposal-lite built FROM the corrected estimate: schema
  `countertop-takeoff/v5 proposal`; provenance binds the estimate sha256
  AND the results sha256 (mismatch refuses); package summaries grouped
  from the data; UNCHANGED EA quantities and exact rates; exclusions from
  the estimate + open items; supplied terms; blank signature lines; totals
  carried verbatim (blank preserved) — never invented percentages, tax,
  or payable balances; json/md/pdf agreement enforced like estimates
  Each line's EA x exact rate must reproduce its amount; missing provenance
  hashes refuse. Package amounts are line sums, labeled known subtotals when
  omissions exist; unresolved regions/rooms/inputs/ledger entries propagate
  their reasons and blank the grand total even when all surviving lines price.

## 6. Side files (regenerable, gitignored)

- `<pdf>.index.json` — `{pdf, generated_utc, source:{sha256}, page_count,
  pages:[{page, sheet, title, width, height, dim_labels, dim_count, flags,
  identity{rotation, mediabox, cropbox, displayed_*}, word_count,
  preflight{op_counts, segment_count, segment_bounds, images, image_cover_pct,
  class, class_reasons, fingerprint, revision_marks}, text}],
  findings{duplicate_pages, sheet_id_conflicts, pages_needing_disposition}}`
- `<pdf>.geometry.json` — `{pdf, generated_utc, source:{sha256, page_count},
  pages:[{page, sheet, identity, coordinate_space:"displayed", segment_count,
  word_count, segments:[{id, path, op, x0, y0, x1, y1, w}], words:[{id, t,
  x0, y0, x1, y1}], preflight{...}, text_chars}]}`
