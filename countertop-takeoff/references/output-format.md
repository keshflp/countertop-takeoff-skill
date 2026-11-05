# Output format spec (5.1.0)

Contracts for reports, audit packs, estimates, and proposals. Existing v3
results/v5 pricing schema tags are retained.

## 1. Markdown report (`measure.py --report`)

Sections, in order:

1. **Header** — sources + sha256 prefixes, UTC timestamp, mode, gross policy,
   and declarations (conflicts/omissions/revision decisions) for the auditor.
2. **Approved scope** — `page | sheet | disposition | detail` (expected region
   IDs or quoted disposition reason). Every source page appears exactly once.
3. **Schedule evidence** — quoted rows/counts, variants (included vs additional),
   stated totals; or the `individual_rooms` declaration.
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
9. **Audit checklist** — pass/warn/fail items with detail, review status, and
   run status: `complete`, `complete_with_callouts`, or `stopped`.

Input dispositions (`measured | intentionally_skipped | superseded | unresolved`)
describe page plans; coverage-ledger states describe resolved output scope.
An included variant earns `included_scope` only when its construction is
resolved (assembly/pieces, including stated dimensions, or legacy regions).
Repeated assemblies must use the matching schedule type/variant quantity basis;
enumerated assemblies cover distinct rooms in the recorded room inventory.
Missing or unresolved construction makes its type and project incomplete;
package-excluded construction stays excluded. Known SF survives as a subtotal.

## 2. CSV (`--csv`) — completed runs, including callouts

Columns: `row_kind, room_type, variant, region_id, sheet, page, viewport,
region_sf, count_applied, region_extended_sf, pt_per_ft_used, source, notes`

Jobs WITHOUT assemblies keep the V2 shape:
- `base` — one per measured base region; `count_applied` is its unit count;
  `region_extended_sf = region_sf × count_applied`
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

On stops (data stops, spec refusals, crashes), measure.py quarantines superseded
CSVs, reports, results and estimate/proposal outputs as `<name>.stale-<utc>`.
Early cleanup writes current stopped JSON ONLY when `--json` is supplied,
before quarantining dependents: `run_status: "stopped"`, `stopped_early: true`,
and the reason. It does not write a new report. No stopped-run CSVs are written.

Input/output and output/output aliases are rejected before any write or
cleanup, using case-insensitive canonical Windows identity (including links).
This includes JOB -> JOB and every proposal output -> estimate/input alias.
`RESULTS.artifacts.json` records dependent output paths, including proposals
outside the results directory; keep it with the job for stopped-rerun cleanup.
Pricing refusals (`SystemExit`) and unexpected exceptions follow the same
stopped-diagnostic/quarantine path. Invalid alias requests leave inputs intact.

## 3. Results JSON (`--json`) — the evidence package

Schema: `countertop-takeoff/v3 results`. Input-derived selections follow the
[job-spec contract](job-spec-v3.md); output fields include:

| Fields | Contents |
|---|---|
| `source`, `mode`, `policy`, `declarations`, `scope`, `schedule`, `profile` | Source `pdf`/`sha256` and resolved job context |
| `runtime_versions`, `settings` | Python/PyMuPDF/Shapely/platform; `snap_pt` (0.05), `recheck_tolerance_pct` (2.0) |
| `calibrations` | Keyed `<page>:<viewport>`; `spans`, `factor_pt_per_ft`, `spread_pct`, `status` |
| `regions[]` | IDs/kind/type, page/sheet/viewport, `boundary_seg_ids`, seed, `polygon`, `cutout_polygons`; `area_sf`, `gross_area_sf`, `factor_pt_per_ft`, `gross_area_policy`, `curved_boundary`, `expected_sf_range`, `expected_range_ok`, `assembly`, `material_canonical` |
| `types[]` | `room_type`, `schedule_count`, `std_units`, `sf_per_unit`, `extended_sf`, `rows` |
| `totals` | `project_sf`, `unit_count`, `known_subtotal_sf`, `project_sf_complete`, `unknown_contribution_count`, `assembly_ea` |
| `audit[]`, `run_status` | `check`/`status` (`pass|warn|fail`)/`detail`; run statuses from §1 |
| `callouts[]` | `scope`, `reason`, `blank_fields`, `source` |
| `coverage_ledger[]`, `scope_incomplete[]` | `item`, `kind`, `state` (§1); unresolved entries also carry `detail` |
| `assembly_boq[]`, `piece_boq[]` | Resolved quantities (§1/§2) |
| `unavailable_inputs[]` | `item`, `detail`, optional `source` |
| `review_status`, `geometry_page_classes` | Initially `independent_audit_pending`; page-to-class mapping |

Unknown quantity collections are JSON `null` and blank CSV cells. Known
profiles/kinds with unknown amounts remain present as `{"eased": null}` in
both per-instance and extended fields. Explicitly declared empty collections
remain `{}`; verified zero counts remain zero. Markdown labels unknowns
`BLANK` and empty declared collections `none declared`.

`sf_state` distinguishes area/extension resolution from `quantity_complete`
(all modeled SF/edge/splash/cutout fields resolved). `property_gaps[]` records
piece-level named blank fields and source links. `totals.quantity_complete`
also requires complete scope. An area-resolved piece may retain unknown
cutouts without losing its gross SF; EA pricing still uses the independent
validated assembly count.
Legacy area-only jobs without an assembly/piece property model report
`totals.quantity_complete: null` (not assessed). Their area completeness
remains independently recorded by `project_sf_complete`.

For assembly jobs, `types[].sf_per_unit` is a single prototype's known area,
or the active assembly-EA-weighted mean across multiple assemblies of that
type. Unknown areas/weights prevent computing that mean. The explicit
`sf_per_unit_basis` identifies the denominator; assembly EA is not necessarily
guestroom count. Unit areas are never summed across enumerated rooms.
Edge/splash/cutout run sources, including word/segment selections, are retained
in piece `source_links` under scoped keys such as `splash_runs[0]`, and on the
run details themselves.

The coverage ledger includes exactly one `page` entry per inventoried
`(source_id, page)`, including pages absent from extracted geometry or from
the job's dispositions. Intentionally skipped pages are `included_scope`
with the original disposition/reason, superseded pages stay `superseded`,
and unresolved/missing pages stay `unresolved`. Missing indexed sheets have
separate named `sheet` entries with index provenance and blank fields; these
propagate into `scope_incomplete[]` and downstream pricing completeness.

Stated-dimension pieces retain a primary source/page/sheet and every property
source link, including selection IDs, across JSON, CSV and report views.

Active aggregate counts and SF per unit stay `null` if any contribution is
unknown; reports and CSVs show blank markers. Genuine zero stays zero, and
excluded assemblies do not affect active aggregates. `unit_count` uses counts
validated by schedule evidence and room reconciliation, independently of summed
`assembly_ea`. An unknown included-variant split can leave the parent room count
known while assembly EA is withheld.

`audit_pack.py --record-receipt` writes `results.json.receipt.json` without
modifying results: `status: independent_audit_recorded`, `reviewer`, `verdict`
(`approved|rejected`), `notes`, `pack_dir`, `results_sha256`,
`superseded_results_files`, `recorded_utc`, and `review_status`
(e.g. `independent_audit_approved`).

Receipts hash immutable results bytes without staling pricing/proposals.
Empty `{}`, noncompleted or quarantined results refuse; superseded siblings
match `results.json.stale-*`. Follow [workflow](../SKILL.md); audit unavailability
is disclosed without a gate, and the receipt can safely be recorded later.

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
| 2 | `stopped` — the [three data stops](method.md#4-resolved-quantities-and-audit), spec refusal, or crash. Stale artifacts are quarantined; early cleanup writes stopped JSON only with `--json`, without a new report (§2b). No exports or approved receipt |

## 5b. Estimate (`estimate.py` / `measure.py --estimate-profile`)

One computation over the assembly BoQ + rate profile produces:

- `estimate.json` — schema `countertop-takeoff/v5 estimate`; scope_complete,
  unknown_scope (omitted in-scope items), currency, results/profile hashes, `lines[]` (item_code,
  description with inch dims, assembly_ids, room, qty_ea, unit_price_exact,
  line_total, rate_reference {item_code, includes, uom},
  quantity_evidence, callout_references, arithmetic string),
  `priced_subtotal`, `grand_total` (null while any in-scope amount is
  unknown), `unknown_amounts`, `exclusions` (package-excluded assemblies,
  never priced), `callouts`, and the arithmetic block (Decimal exact,
  ROUND_HALF_UP to whole cents per line, single-currency rule)
  (`unit_price` is legacy approximate; documents/math use the exact decimal string)
- `estimate.md` — company, timestamp, currency, scope-completeness, provenance;
  table `Item code | Description | QTY EA | Unit price | Total` (descriptions
  wrap, amounts never split); priced subtotal; exclusions; CALLOUTS including
  omitted scope as UNKNOWN amounts; grand total BLANK while any amount is unknown;
  per-line arithmetic with EXACT rates (55.555 stays 55.555, never 55.56).
- `estimate.pdf` — PyMuPDF render of estimate.md: first line below the
  page top, wrapped + paginated (grand total on the last page), and every
  rendered amount RE-READ from the PDF and checked against estimate.json
  before the file ships. Markdown syntax is removed: PDFs show plain BLANK,
  clean headings and exact rates, with readable assembly/room identifiers.
  Host tooling may render richer PDFs from the same Markdown; totals must agree.
- `proposal.json/.md/.pdf` (`scripts/proposal.py`) — proposal-lite from the
  corrected estimate; schema `countertop-takeoff/v5 proposal`. Provenance binds
  estimate AND results sha256 (missing/mismatched hashes refuse). Package
  summaries group data; EA/exact rates stay unchanged. Include exclusions/open
  items, supplied terms, blank signatures, verbatim totals preserving blanks;
  never invent percentages, tax, or payable balances. Enforce json/md/pdf
  agreement and EA x exact rate per line. Package amounts sum lines (known
  subtotals with omissions); unresolved regions/rooms/inputs/ledger entries
  carry reasons and blank the grand total even if every surviving line prices.

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
