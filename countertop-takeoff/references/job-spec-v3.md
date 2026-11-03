# V3 job spec — the evidence document

`measure.py` is driven by a JSON job spec the AGENT writes after reading
the indexed pack. Every number in the deliverable is either computed from
recorded geometry or quoted from recorded evidence (word boxes, or a
crop-hash-verified bitmap transcription). V2 specs
(`"schema": "countertop-takeoff/v2"`) remain valid single-source specs.
Working examples: `examples/fixture.jobs.json` (v2), the output of
`examples/make_hotel_jobs.py` (full v3).

## Top level

| key | required | meaning |
|---|---|---|
| `schema` | yes | `"countertop-takeoff/v3"` (or the v2 tag for legacy specs) |
| `sources` | v3 | `[{"source_id", "path", "sha256", "kind": "pdf"\|"cad"\|"image"}]` — pages are keyed (source_id, page_number); v2's single `source` object is accepted and normalized |
| `geometry` | yes | path to `extract_geometry.py`/`cad_input.py` output, or `{source_id: path}` for multi-source jobs |
| `mode` | yes | `"repeated_types"` (schedule multiplies one measured prototype per type) or `"individual_rooms"` (each room measured once) |
| `policy` | yes | `{"gross_area": "gross"\|"net_of_declared_cutouts", "declarations": [...], "packages": {"exclude": ["FFE"...]}}`; package exclusion overrides the company-profile default |
| `sheet_index` | no | `{"source_id", "page", "lists": [...]}` — sheets listed on the drawing index; gaps become callouts |
| `intake_manifest` | no | path to the step-0 manifest; unavailable sources and count mismatches become callouts |
| `calibrations` | yes* | per (source_id, page, viewport): TWO+ agreeing, independent spans; `viewport_box` bounds the viewport in displayed points; for CAD sources the verified units act as the calibration and no entry is needed |
| `regions` | yes | what to measure (see below) |
| `assemblies` | v3 | one record per room-instance prototype |
| `pieces` | v3 | construction records with runs + provenance |
| `profile` | no | company profile path (`references/company-profile.md`) |

## `schedule` — counts with evidence

- `evidence.kind = "text"`: each type carries `row_text` + `word_boxes`
  that must reference ACTUAL extracted words (fabricated quotes refuse to
  multiply).
- `evidence.kind = "image"`: `crop_image` + `crop_sha256` + `render_zoom` +
  `crop_bbox` (displayed points) + `headers` + `cells` (transcribed text +
  boxes) + `uncertain_cells`. The audit re-renders the crop and compares
  the hash — proving WHICH pixels were read. A mismatch withholds the
  counts (blank + callout).
- `types[]`: `{"type", "count", "row_text", "rows"?}` — positive INTEGER
  counts; `rows[]` decompose per floor (sum must equal count; mismatches
  are disclosed callouts, not refusals).
- `variants[]`: ADA-style subsets with `included_in_parent_total` (never
  double-counted).
- `stated_totals`: floor/project totals quoted from the page; disagreements
  are disclosed callouts (the quoted per-row counts stay authoritative).
- `room_inventory`: `rooms[]` (deduped plan tags), `per_type_counts`
  (plan-derived), `count_resolutions` (explicit resolutions with evidence).
  An unexplained schedule-vs-plan mismatch (the 3→30 invention trap)
  withholds the affected extension. NEVER default a missing count to 1.

## `scope` — the completeness ledger input

One entry per (source_id, page): `measured` (with `expected_regions`),
`intentionally_skipped` (reason), or `superseded` (reason). Pages with no
disposition are recorded unresolved + callout — never silently dropped.
Sheet-label conflicts, unlabeled measured pages, and drawing-index gaps
are tolerant-identity CALLOUTS.

## `regions[]`

| key | meaning |
|---|---|
| `region_id`, `kind` | unique id; `"base"` or `"recheck"` (`of`: base id) |
| `type`, `variant` | link to the schedule (or to a declared piece for out-of-series scope) |
| `page`, `sheet`, `viewport`, `source_id` | where; the viewport must have a calibration entry (image route excepted) |
| `boundary.seg_ids` | selected boundary segments — must close into EXACTLY one cycle; dangling/branched nodes refuse with coordinates |
| `seed` | `[x, y]` strictly interior, inside the viewport box |
| `expected_sf_range` | sanity guard; a breach WITHHOLDS the quantity (blank + callout) instead of shipping it |
| `cutouts` | inner loops; subtracted only under the net policy |
| `route: "image"` | image-route region: `image_measurement` points at an `image_measure.py` result; the crop hash is re-verified |

## `assemblies[]`

`{"assembly_id", "room"?, "type", "variant"?, "package":
millwork|FFE|public_BOH, "finish_tag"?: "ST"|"PL"|"W"|..., "width_in"?,
"depth_in"?, "height_in"?, "handing"?: "LH"|"RH", "quantity_basis":
{"mode": "room_type_count", "type", "variant"?} | {"mode": "enumerated"},
"pieces": [piece_id...], "sources": [{"source_id", "page"}]}`

- Unknown dims stay `null` (blank), never 0.
- `room_type_count` EA = the validated schedule count for the type/variant
  (withheld when the count is unsupported); `enumerated` EA = 1.
- When ALL assemblies are enumerated, each measured instance counts ONCE
  (no schedule multiplication); package-excluded assemblies are reported
  separately as `package_excluded`.

## `pieces[]`

`{"piece_id", "assembly_id", "route": "geometry"|"stated",
"region_id"? (geometry route), "dims_in"?: {"width","depth","thickness",
"height"}, "finish_tag"?, "edge_runs": [{"profile", "exposure",
"length_in"|null, "source"?}], "splash_runs": [{"height_in", "length_in",
"handing"?, "returns_in"?, "source"?}], "cutouts": [{"kind", "ea",
"source"?}], "source_links": {"length"|"depth"|"thickness"|"material"|
"profile": {"source_id", "page", "kind": plan|elevation|section|spec|
schedule|detail|other, "note"?}}}`

- Unknown lengths/dims keep the affected BoQ fields BLANK with a callout.
- Piece BoQ extensions use the SAME validated assembly counts as the
  assembly BoQ — the two views are never summed with each other; their
  consistency is checked and both totals reported.
