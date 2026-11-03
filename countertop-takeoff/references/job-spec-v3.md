# Job spec — the evidence document (V3 schema, V4 semantics)

`measure.py` is driven by a JSON job spec the AGENT writes after reading
the indexed pack. Every number in the deliverable is either computed from
recorded geometry or quoted from recorded evidence (word boxes, or a
crop-hash-verified bitmap transcription). V4 (P0.1/P0.2) binds every
quantity to that evidence and derives ALL deliverable totals from ONE
resolved model. V2 specs (`"schema": "countertop-takeoff/v2"`, single
source) remain valid. Working examples: `examples/fixture.jobs.json` (v2),
the output of `examples/make_hotel_jobs.py` (full v3).

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
  multiply) AND whose numbers must correspond to the count (the count
  appears as a quoted number token, the boxes are pure integers summing
  to the count, or per-floor `rows[]` whose quoted texts carry each
  value). A quoted "3" never supports a count of 30.
- `evidence.kind = "image"`: `crop_image` + `crop_sha256` + `render_zoom`
  + `crop_bbox` (displayed points) + `headers` + `cells` (transcribed text
  + boxes) + `uncertain_cells`. The audit re-renders the crop and compares
  the hash — proving WHICH pixels were read. Each type ALSO declares
  `count_cells` (row/col of the transcribed cells that prove the count);
  the count VALUE is checked against those cell texts — an edited count
  over verified pixels is caught. A mismatch withholds the counts (blank
  + callout).
- `types[]`: `{"type", "count", "row_text", "rows"?}` — positive INTEGER
  counts; `rows[]` decompose per floor (sum must equal count; mismatches
  are disclosed callouts, not refusals).
- `variants[]`: ADA-style subsets with `included_in_parent_total` (never
  double-counted).
- `stated_totals`: floor/project totals quoted from the page; disagreements
  are disclosed callouts (the quoted per-row counts stay authoritative).
- `room_inventory`: `rooms[]` (deduped plan tags), `per_type_counts`
  (supplied summary), `count_resolutions` (explicit resolutions with
  evidence). V4 derives the plan-derived counts FROM the `rooms[]` tag
  records: a supplied `per_type_counts` contradicting the tags (an edited
  inventory) withholds the type exactly like a schedule-vs-tags mismatch
  (the 3→30 invention trap). NEVER default a missing count to 1.

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
- V4 resolves each assembly's EA INDEPENDENTLY: `enumerated` EA = 1;
  `room_type_count` EA = the schedule count MINUS the counts of included
  variants (an ADA room inside the parent count is subtracted from the
  standard EA, never added again); `room_type_count` + variant EA = that
  variant's own count. Unsupported evidence or a reconciliation conflict
  withholds the EA (blank), never guesses.
- Package exclusion is applied once per assembly in EVERY aggregation
  branch; excluded assemblies are reported separately (`package_excluded`).
- Piece↔assembly membership is bidirectional: orphan pieces, pieces
  claimed by two assemblies, assembly piece-list entries without records,
  and measured regions covered by no piece are flagged (callouts; the
  affected extensions stay blank).
- ALL deliverable totals (project, type rows, both BoQ views, CSV grand
  total) derive from this one resolved model and cannot disagree; the run
  asserts their equality (`dual BoQ reconciliation`).

## `pieces[]`

`{"piece_id", "assembly_id", "route": "geometry"|"stated",
"region_id"? (geometry route), "dims_in"?: {"width","depth","thickness",
"height"}, "finish_tag"?, "edge_runs": [{"profile", "exposure",
"length_in"|null, "source"?}], "splash_runs": [{"height_in", "length_in",
"handing"?, "returns_in"?, "source"?}], "cutouts": [{"kind", "ea",
"source"?}], "source_links": {"length"|"depth"|"thickness"|"material"|
"profile": {"source_id", "page", "kind": plan|elevation|section|spec|
schedule|detail|other, "note"?}}}`

- Unknown lengths/dims keep the affected BoQ fields BLANK with a callout:
  an unknown edge blanks THAT profile's LF (never folded into a known
  length of the same profile); an unknown splash height blanks splash SF
  (never 0); handed splash runs keep `handing`/`returns_in` in the BoQ.
- Piece extensions (SF, edge LF, splash, cutouts) are multiplied by the
  SAME resolved assembly EA; the piece BoQ and the assembly BoQ are two
  views of the same resolved records — never summed with each other.
- V5: pieces may declare LEGITIMATE reuse of one measured region across
  assemblies via the optional spec key `piece_geometry_reuse:
  [{"region_id": ..., "pieces": [...], "reason": ...}]` (validated at
  load; an explicitly DECLARED reuse is a non-defect). An UNDECLARED
  second geometry piece on the same region is a repeated geometry claim:
  it keeps its identity but its extension is withheld blank behind a
  callout.
