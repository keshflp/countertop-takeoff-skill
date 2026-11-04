# Measuring method

The agent recognizes scope and selects evidence; code computes quantities.
Plan PDFs can contain vectors, rasters, or both. Text/OCR alone never proves
measurable linework. Follow the workflow order in [SKILL.md](../SKILL.md).

## 1. Intake and preflight

Collect every requested input into one job directory with an intake manifest:
requested/resolved files, byte sizes, SHA-256, page counts, expected-count
verdict, and unavailable inputs. Cloud downloads happen through the agent.

`index_pdf.py` inventories each PDF's sheet identity, rotation/crop metadata,
vector operations/bounds, image coverage, dimension labels, and type tags.
Page classes are `vector`, `text_only`, `searchable_raster`, `raster`,
`hybrid`, or `uncertain`. Inspect content REGIONS too: a bitmap schedule under
a vector header needs image reading without disqualifying other linework.
Coverage thresholds are percentages (20/60); raster fingerprints hash pixels.

Record duplicate pages, conflicting revisions, sheet aliases, drawing-index
gaps, and revision decisions. Disposition each `(source_id, page)` as
`measured` (expected region IDs), `intentionally_skipped` (reason),
`superseded` (reason), or `unresolved` (reason). These are INPUT dispositions,
not the output coverage-ledger states listed below. No `blocked` disposition.

## 2. Schedule and room evidence

Quote text rows with selected word IDs/boxes. For bitmap schedules, render a
legible crop, record source/page/bbox/zoom and crop SHA-256, transcribe cells
with boxes, and mark uncertainty. Image-evidence types AND variants cite
`count_cells`; uncertain or unsupported cells withhold their counts and
any dependent standard allocation. Hashes prove pixel identity, not reading.

Counts must correspond NUMERICALLY to cited evidence: a quoted 3 cannot
support 30. `row_text` is descriptive only. Independently inventory room tags
and deduplicate rooms appearing on overall/enlarged plans. Reconcile those
records with schedule cells, floor subtotals, and project totals; a conflicting
summary cannot override tags. Unsupported counts stay blank, never default 1.

Included variants are subtracted from parent counts only when supported;
unknown included counts withhold the dependent parent allocation. Enumerated
rooms use declared `individual_rooms` mode, not a fallback count.

## 3. Measurement routes, in order

1. Selected vector PDF boundaries with per-viewport calibration.
2. Supplied DXF with verified native units (convert DWG first).
3. Calibrated image-space measurement for legible rasters.

Try available alternate routes before withholding affected quantities. Raster
or hybrid classification alone is not a blanket exclusion; unusable imagery
stays blank with a named callout. Automatic full-plan tracing is out of scope.
Stated section/elevation dimensions take priority on DO NOT SCALE DRAWINGS
sheets; preserve provenance when joining depth/thickness/material to lengths.

### Vector extraction and calibration

`extract_geometry.py` emits stable word/segment IDs, source-path/operator
identity (`l`, `c`, `re`, `qu`), source SHA-256, and preflight metadata.
Coordinates are DISPLAYED page space: rotation is applied consistently to
selections, seeds, and overlays. Measurement verifies the source binding.

Calibration belongs to `(source, page, viewport)` and needs TWO or more
agreeing independent dimensions: unique segment selections AND parsed lengths.
Viewport boxes constrain spans and seeds; duplicate calibration keys refuse.
The parser accepts total inches, decimal feet, inch-only values, fractions,
and split labels. Code joins selected words, sums selected segment lengths,
and computes `pt_per_ft = length_pt / real_ft`; no typed scale factors.
Explicit `real_ft` values must not contradict readable labels.

Use the median factor: spread <=2% passes, 2-5% warns, >5% fails that local
calibration. Record the actual factor on every region. The title block is a
sanity check only (1/4 inch per foot gives 18 pt/ft full size); never borrow
another viewport's scale. A failed viewport does not invalidate healthy ones.

### Boundaries and geometry

The agent selects shell segment IDs, a strictly interior seed, and an honest
`expected_sf_range`. Code snaps to a 0.05 pt grid, nodes the graph, requires
every node degree 2 and exactly one closed cycle. Dangling, branched, or
ambiguous selections are withheld; there is no nearest-face repair fallback.
The seed must satisfy `Polygon.contains` and boundary distance >0.01 pt.
Area is shoelace area in pt squared divided by the actual factor squared.

`gross` subtracts nothing; `net_of_declared_cutouts` subtracts only selected
closed cutout loops verified inside the shell. Undeclared sink rims are not
automatically deductions. Repeated geometry, overlaps, unplanned regions,
range breaches, and failed rechecks produce local callouts and named blanks.
Rechecks use independent selections, default 2% tolerance, and never extend.

PDF beziers flatten to 8 chords; curved boundaries carry `curved_boundary`.
An 8-chord quarter circle loses approximately 0.02*r^2 pt squared: a 3-ft
radius loses about 0.18 SF (26 square inches). Disclose this tolerance.
Explicit edge runs distinguish profile/exposure; perimeter alone does not.

### CAD and image evidence

DXF `$INSUNITS` supplies scale; unitless files refuse without explicit
`--units in|ft|mm|cm|m`, recorded as operator-verified. Metres convert by
1/0.3048 ft/m; unit 8 is microinches. MINSERT arrays expand row x column;
layer-0 children inherit the insert layer before filtering. Bulges use
chord counts for <=0.5% area error per curve. Unsupported OCS extrusions
are named exclusions. See [CAD routes](cad-context.md).

The image route needs crop hash, source/page/bbox/zoom binding, two agreeing
labeled anchors, selected boundary points, and mandatory overlay proof.
Measurement recomputes area from selections; changing a result number while
retaining pixels fails evidence validation. CAD/image bytes are re-hashed.

## 4. Resolved quantities and audit

One resolved quantity model feeds every deliverable. For jobs declaring
assemblies, the run ASSERTS the PIECE and ASSEMBLY BoQs agree over the SAME
fully resolved assembly subset; project/report/CSV equal the full known piece
subtotal, including valid parts of incomplete assemblies. Hotel: **123.00 SF**
resolved subset vs **146.98 SF** full known subtotal. Carry completeness flags
and omission reasons; neither subtotal proves complete scope. Never sum BoQs.
Package exclusions apply once per assembly and are reported separately.

Coverage ledger OUTPUT states are `measured`, `included_scope`,
`package_excluded`, `superseded`, `unresolved`: every inventoried room, type,
variant, region, page, assembly, and piece must be accounted for. Validate
planned/completed IDs, evidence identity, reciprocal piece/assembly membership,
and declared geometry reuse. Identity conflicts withhold affected extensions.

Local failures yield genuinely null fields with callouts naming scope, source,
reason, and blanks; valid EA/length/finish facts survive ordinary SF failure.
`measured_area_sf` may retain diagnostics, never a disguised usable quantity.
Run statuses: `complete`, `complete_with_callouts`, `stopped`. Exactly three DATA stops:
no valid calibration anywhere (verified CAD/image calibration qualifies),
no schedule AND no repeatable pattern, or source integrity mismatch.
Malformed specs refuse separately before measurement. Stopped runs quarantine
exports; see [output formats](output-format.md) for paths, diagnostics, receipts,
and downstream EA pricing/proposal rules. No fourth data stop or approval gate.

Measure -> audit pack/independent receipt -> requested pricing/proposal ->
delivery. If independent audit is unavailable, disclose it and continue.
Use the [first-run checklist](first-run-checklist.md) and [synthetic walkthrough](../examples/run_example.md);
fixtures verify known geometry, not autonomous recognition on unseen plans.
