# Measuring method (V4)

How this skill turns drawing sets (vector PDFs, DXF, rasters) into
trustworthy, auditable quantities. Written for the agent doing the takeoff
and for the human auditing it.

## V4 deltas over V3 (this section is current; the rest describes the
shared method)

- ONE RESOLVED QUANTITY MODEL: every deliverable total (project, type
  rows, assembly BoQ, piece BoQ, CSV grand total) derives from the same
  resolved records; for jobs that declare assemblies the run ASSERTS the
  views agree — it reconciles them against each other over the SAME known
  contributions (not by regrouping extensions), and a disagreement fails
  the run. Included variants (e.g. ADA inside a parent type) are
  SUBTRACTED from parent counts; package scope applies once per assembly
  in every aggregation branch.
- EVIDENCE BINDING: schedule counts must correspond NUMERICALLY to the
  quoted evidence ("3" never supports 30; image-evidence counts cite
  `count_cells`); room reconciliation derives counts from the deduped tag
  records, not from the supplied summary; the image route RECOMPUTES the
  area from recorded selections (an edited result number over unchanged
  pixels is rejected), requires the crop bound to (source, page, bbox,
  zoom) and the overlay proof; `real_ft` overrides contradicting readable
  labels become callouts.
- CONSISTENT DEGRADATION: only the three DATA stops stop a job (a
  malformed job spec refuses separately, before any measuring). Image-range
  breaches, overlaps, duplicate boundaries, unplanned regions, and failed
  rechecks degrade LOCALLY — the affected records are withheld blank
  (numeric quantities NULLED; the measured value kept aside as
  `measured_area_sf` diagnostics) behind named callouts. Degraded fields
  are genuinely null — never a value wearing a blank declaration.
- CAD CORRECTNESS: metres are 1/0.3048 ft per m (V3 shipped 3.048);
  $INSUNITS 8 is MICROINCHES; MINSERT arrays expand row × col; layer-0
  block children inherit the insert's effective layer (filtering AFTER
  expansion); polyline bulges become disclosed arc approximations with
  chord counts solved for ≤0.5% area error per curve; non-standard OCS
  extrusions are named exclusions; CAD (and image) source bytes are
  re-hashed before measuring.
- ASSEMBLY-EA ESTIMATE (rate profile): EA × exact rate, never SF × price;
  unmatched/ambiguous rates and withheld quantities stay blank; explicit
  zero-rates price real 0.00 lines; Decimal + ROUND_HALF_UP to cents;
  estimate.md / .json / .pdf agree on the grand total (blank while any
  in-scope amount is unknown).

## V3 deltas over V2 (the rest of this section describes the shared
V2-established method)

- Image-coverage thresholds are PERCENT (20 / 60); raster fingerprints hash
  actual stored pixels (`get_image_info(xrefs=True)`).
- Content REGIONS: per-region raster/vector classification inside a sheet —
  a pasted bitmap schedule neither disappears nor disqualifies unrelated
  vector geometry. Region boundaries must sit OUTSIDE raster regions for
  the vector route; raster regions go through the image route or stay
  blank.
- Dimension parsing accepts total inches (211"), decimals (10.5'), explicit
  inch-only values (4", 1 1/2" — required by section sheets), fractions,
  and split labels.
- Calibration spans must be independent (unique segments AND unique parsed
  lengths); duplicate calibration keys for one viewport refuse; viewport
  boxes bound spans and region seeds.
- Graduated degradation: recoverable failures resolve to UNRESOLVED
  records with BLANK quantities + callouts; run status is complete /
  complete_with_callouts / stopped; exactly three DATA stops (see
  SKILL.md — malformed job specs refuse separately as spec-validation
  errors, they are not one of the three).
- Routes in order: vector PDF -> supplied DXF with verified units
  ($INSUNITS; unitless refuses without an explicit --units declaration,
  recorded operator-verified) -> calibrated image-space measurement
  (image_measure.py: crop hash, 2+ agreeing anchors, mandatory overlay).
- Counts: schedule evidence (text word boxes or hash-verified crop cells)
  cross-validated against plan room tags; unsupported counts are withheld.
- Dual BoQ: assemblies + pieces derive from one model; piece and assembly
  views are never summed with each other.

## 0. Why this design

Plan PDFs are vector drawings: every wall, counter edge, and dimension string
is stored as coordinates in PDF points (1/72 inch), not pixels. That means
quantities can be COMPUTED rather than estimated. V2's additional lesson: a
correct-looking number can still accompany the WRONG scope, a duplicated
region, a mispicked boundary, or a mis-calibrated scale. So V2 makes SCOPE,
BOUNDARIES, MULTIPLIERS, CALIBRATION, and REVIEW STATUS auditable from
recorded evidence:

- The agent recognizes and SELECTS: which sheets enter scope, which page is
  the authoritative revision, which schedule rows justify which counts,
  which dimension spans calibrate, which segments bound each counter.
- Code measures: hashes, classifications, lengths, closure, areas,
  reconciliation — and refuses to guess (every refusal is exit 2 with a
  named reason).
- The agent never types a quantity and never types a scale factor.
- Every result cites page/viewport/segment ids/factors; a fresh agent (or an
  independent human) audits the pack before anything ships.

Explicit rejection of unsupported geometry is a feature: an OCR'd scan or a
hybrid page is skipped WITH A RECORDED REASON, not measured-by-faith.

## 1. Pack preflight (`index_pdf.py`)

Per page: sheet id, title, rotation + crop metadata, vector operator counts
and linework bounds, raster image coverage, dimension-label count, type tags.
Plus a content CLASS computed from coverage and segment counts — text
presence NEVER establishes vector suitability (an OCR'd scan carries a full
text layer and zero usable linework):

| class | meaning |
|---|---|
| `vector` | linework only — measurable |
| `text_only` | schedule/notes pages — readable, not for linework |
| `searchable_raster` | image dominates + real text layer (OCR'd scan) |
| `raster` | image dominates, no text |
| `hybrid` | meaningful image AND vectors (e.g. scan pasted over a vector title block) — not trustworthy for area |
| `uncertain` | mixed/ambiguous — human must look |

Pack-level findings: source SHA-256, duplicate pages (identical content
fingerprints), sheet-id conflicts (same sheet number, different content —
one is a superseded revision), revision marks, and the list of pages that
need an explicit scope disposition before work continues.

## 2. Geometry extraction (`extract_geometry.py`)

Flattens drawing items into straight segments (lines; béziers → 8 chords;
rects/quads → 4 edges) and records, per segment, a stable integer id, its
source path and operator (`l`/`c`/`re`/`qu`). Words carry ids and boxes too.
Coordinates are normalized to DISPLAYED page space — page rotation is
applied — so seeds, boundaries, and rendered overlays all agree with what a
human sees. The file records the source PDF's SHA-256 and per-page preflight
data; measurement verifies the geometry belongs to the approved source.

Curve tolerance, stated honestly: an arc flattened to 8 chords per quarter
circle underestimates area by ≈ 0.02·r² pt² — a 3-ft radius loses ≈ 0.18 SF
(≈ 26 sq in), NOT "well under a square inch". Regions whose boundary
includes bézier segments are flagged `curved_boundary` in the evidence so
the reviewer knows where this applies; for tighter budgets raise the chord
count before measuring.

## 3. Calibration (`scripts/calibrate.py`)

**Rule: no measurement without calibration; calibration belongs to a
(source page, viewport) pair and needs TWO agreeing independent dimensions.**

The agent selects each span: which words carry the dimension text and which
segments make up the dimension line. Code joins split labels (`12'-` + `0"`),
parses feet-inches-fractions (`20'-6` + `1/2"`), sums the segment lengths,
and computes `pt_per_ft = length / real_ft`. Per (page, viewport): median of
the span factors; spread ≤ 2% passes, 2–5% warns (must be explained to the
reviewer), > 5% hard-fails. One span never calibrates — a single label
agreeing with itself is how v1 shipped a 36 pt/ft factor from a wrong
nearby segment. The ACTUAL factor used is recorded per region and shown in
the report, so a report can never say 18.00 while the math used 18.36.

Sanity band: compare against the title block (1/4"=1'-0" full size ⇒ 18
pt/ft; 1/8"=1'-0" ⇒ 9 pt/ft; half-size prints halve the factor). The title
block is a CHECK, never the source. No dimension strings at all → the skill
stops; a known real length on that sheet can be supplied as an explicit span
(`"real_ft"`) only if the label actually exists there.


## 4. Region measurement (`scripts/regions.py`)

The agent selects the boundary segment ids for each countertop; code then:

1. Snaps endpoints to a 0.05 pt grid and nodes the selection into a graph.
2. Requires EVERY node to have degree exactly 2 and the walk to close into
   ONE cycle. Dangling endpoints (open boundary, stray hatch tick, dimension
   line) and branched nodes (two loops touching = ambiguous) are REFUSED,
   with the offending coordinates named. There is no nearest-face fallback —
   the v1 crash on `nearest=None` came from guessing after polygonization.
3. Requires the seed to be STRICTLY interior (`Polygon.contains`, boundary
   distance > 0.01 pt) — v1's `.covers()` accepted a seed sitting on the shell.
4. Computes area by the shoelace formula: `SF = area_pt² / factor²`.
5. Applies the declared gross-area policy: `gross` subtracts nothing
   (observed inner loops like sink rims are recorded, not subtracted);
   `net_of_declared_cutouts` subtracts exactly the declared cutout loops,
   each verified to lie fully inside the boundary. V1 silently subtracted a
   sink loop while its own docs said cutouts were ignored — v2 makes the
   policy explicit and auditable.
6. Checks counted instances for overlaps: two base regions of the same
   (type, variant) sharing any area is a hard fail (this is the v1 bug that
   passed a duplicated Type B at 208.75 SF); cross-type overlap warns.

`edge_lf` (perimeter ÷ scale) stays INFORMATIONAL ONLY — front edge vs wall
edge identification is future scope.

## 5. Scope ledger, schedule evidence, audit

- **Scope**: every source page is `measured` (with expected region ids),
  `intentionally_skipped` (with a quoted reason), or `blocked` (prevents
  completion). The audit compares planned region ids vs completed results
  EXACTLY — deleting every Type B job or leaving a measured page empty
  cannot pass like it did in v1.
- **Schedule**: counts are positive integers read from quoted row text with
  recorded word boxes; missing counts fail (v1 defaulted to 1). Floor rows
  decompose counts; stated floor/project totals must reconcile. ADA-style
  variants declare `included_in_parent_total` explicitly so subsets are
  never double-counted; `individual_rooms` mode sums rooms independently
  with count 1 — a declared mode, not a silent fallback.
- **Rechecks**: an independently selected re-measure of a base region must
  agree within 2% (configurable) and is never extended into totals.
- **Status**: audit items are pass / warn / fail. Any fail = `failed` (no
  export, stale exports quarantined). No fails + warnings = `warning`
  (exportable, must be explained). Otherwise `ready`. Independently of both,
  `review_status` records the independent audit: `independent_audit_pending`
  until `audit_pack.py --record-receipt` writes the reviewer and verdict.

## 6. Known limitations (by design)

- **Raster / hybrid pages**: skipped or blocked with recorded reasons.
  Automatic raster tracing is out of scope.
- **Curved counters**: flagged, tolerance stated above (see §2).
- **Cutout detection**: only DECLARED cutouts subtract; finding un-declared
  inner loops automatically is drawing understanding — the fresh-agent audit
  checks overlays instead.
- **Boundary repair**: a selection that doesn't close is refused, never
  "repaired" by snapping to nearest linework.
- **Universal schedule extraction**: the agent reads schedule text and
  records evidence; nothing infers counts from prose.
- **Edge LF / backsplash / cutout pricing**: schema groundwork only.

## 7. Worked examples

- Clean fixture: `examples/run_example.md` — 168.75 SF exact.
- Hostile fixture: `uv run examples/make_fixture.py --case messy` then
  `examples/messy.jobs.json` — 990.00 SF gross (936.00 with declared
  cutouts), two viewports at 18/9 pt/ft on a rotated sheet, ADA variant
  allocation, revision conflict resolved, searchable raster explicitly
  skipped. Negative mutations and their refusals live in
  `examples/tests_v2.py`.
