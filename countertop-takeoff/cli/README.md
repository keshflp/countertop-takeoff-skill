# Takeoff CLI

The agent supplies confirmed facts and records Dad's yes. The CLI owns exact
geometry, quantities, pricing, kernel calls and saved step order. Python owns
the versioned manufacturer-rule model and automatic seam decisions. Production
needs Bun and uv; no JavaScript package install is needed.

```powershell
bun countertop-takeoff/cli/takeoff.js preflight "$env:USERPROFILE\Takeoffs\kitchen" C:\private\sketch.png
# Read the pictures; save confirmed facts in v2 job.json.
bun countertop-takeoff/cli/takeoff.js check "$env:USERPROFILE\Takeoffs\kitchen"
# Show Dad preview.png and the readback. Record only his actual yes.
bun countertop-takeoff/cli/takeoff.js confirm "$env:USERPROFILE\Takeoffs\kitchen"
bun countertop-takeoff/cli/takeoff.js quote "$env:USERPROFILE\Takeoffs\kitchen"
bun countertop-takeoff/cli/takeoff.js next "$env:USERPROFILE\Takeoffs\kitchen"
```

Preflight fingerprints private input copies. Check binds its preview to those
inputs and the exact bytes of job.json; confirm records the same hashes. Editing
facts, inputs or preview requires another check and Dad's yes. Failed preflight
clears prior success. Jobs inside the public repository are refused, including
other worktrees and paths through directory links. Expected failures print one
plain message and exit 1 without a traceback.

## Version 2 facts and outcomes

`src/schema.ts` is the strict serialized contract. v1 is rejected by normal
commands and eval. Material adds required nullable `profileId`,
`profileProvenance` and positive decimal-string `nominalThicknessMm`. Profile
selection must be explicit; a marketing name or supplier cannot select it.
Cutouts add required nullable `radiusMm` and `mount`. Installations add required
nullable `insideCornerRadiusMm`, `sourceArrangement`, and a `conditions` array.
Radius `"0"` is a known sharp corner, not an unanswered fact. An empty conditions
array does not assert support exists.

`sourceArrangement` describes a documented original rectangular run:
`{kind:"rectangular-run",axis:"x"|"y",rear:"min"|"max",provenance:string}`.
Rear is the selected edge on the transverse axis: x-run rear:min means min-y;
y-run rear:min means min-x. Unknown stays null. An L leg's bounding box does not
establish this datum or make it a supported rectangular arrangement.

Check assesses original geometry even with missing stock/profile facts. Quote
plans candidates. Each quote retains all original installation and material
facts, exact quantities, full source evidence/conditions and search limits.

- Unresolved, conflicting, or capped-without-incumbent assessments retain known
  quantities and labor but no final layout or slab-derived charges.
- Conditional candidates can price, with their outstanding requirements visible.
- Assessed means only the implemented product-rule subset and supplied evidence.
  Handling, transport, defects and reinforcement design remain unevaluated.
- A capped incumbent retains its limits and cannot claim proven optimality.

Unknown facts generate one plain question per field. Assessment questions come
from Python. Both drawings receive the complete assessment, numeric geometry,
cutout estimate metadata and actual nullable layout. Runtime snapshots must
include every imported kernel helper, including `layout_geometry.py`.

## Exact geometry and prices

Shape expansion and leg-relative placement use integer sixteenths. Symbolic
`centerFromStartIn:"center"` uses the full outer leg; a result between grid marks
is rejected rather than rounded. Radius/thickness strings preserve exact mm.
Authorized `estimate:{fields:["wIn"|"hIn"|"at"],note}` survives on original
cutouts and in `geometryEstimates` with the resolved rectangle. Readbacks say
`Preliminary: estimated geometry`. Default assumptions remain separate.

`requiredPieceCount` is an exact fabrication-piece count, independent of invoice
lines. `center-through-cutout` retains the historical rectangular equal-halves,
exact-two request. `opening-center` pins that selected join without imposing a
piece count; additional automatic joins remain permitted. Neither waives source
rules. Tangent intent is representable but unsupported in this bounded model.

TS independently checks reply coherence, pinned source identity, references,
polygon tiling/area, void attribution, solid connectivity, logical stone joins,
rigid quarter-turn placements, stock fit and interpiece kerf. Python owns the
source-distance/radius predicates and candidate admission. Holes remain reserved
gross stock. Cell decomposition edges are not fabrication joins.

SF and money stay exact rational BigInts until half-up rounding. Gross installed
area is charged; nominal untrimmed slabs determine supplier cost. Required nullable
`material.markupPercent` has no default; use `"0"` explicitly. Markup applies to
unrounded full purchased material cost before dividing by exact job SF. Labor is
separate. `materialCost` is supplier cost; `materialCharge` includes markup.
Invoice lines use displayed two-decimal SF and rate. Nulls propagate.

Only stock settings default: slab trim1 inch, kerf0.25 inch, rotation allowed.
Each omitted setting plus gross-SF/nominal-slab/shape conventions appears in
`assumptions` with `assumed, confirm with Dad`. Historical generic seam minima
are not normal v2 settings.

## Development and historical evidence

Effect4.1.2 was npm's stable release when checked on2026-11-06. Commands use
`effect/cli`; Bun platform services own filesystem and scoped processes.

```powershell
cd countertop-takeoff/cli
bun install --frozen-lockfile
bun run check
bun run build
bun test
```

Commit takeoff.js whenever its source changes. A focused test rebuilds in memory
and compares hashes, ignoring Windows line-ending conversion. Tests replace the
kernel transport and retain the real schema decoders and temporary workflow files.
The live service runs `uv run <bundle-relative skillDir>/kernels/<name>.py`.

`bun src/eval.ts` reads normal v2 job JSON on stdin and emits quote JSON on stdout,
without workflow state or PNGs. `TAKEOFF_DEV_SKILL_DIR` selects detached kernels
for this developer entry; the shipped bundle always resolves its own location.

`bun src/replay.ts` is a separate, development-only v1 geometry replay. It maps
absent model facts to null and emits `developmentOnly:"geometry-replay-unassessed"`
with an unresolved assessment even if legacy geometry and prices are available.
No normal command or runtime setting enables it. It cannot establish source-rule
feasibility or migrate unknown material facts.

Historical benchmark evidence remains frozen: CLI f487e16 with evaluator478f653
and layout/draw5544c8c passed19 old cases with zero excess slabs. The original
naive benchmark scored11 on15 known-stock cases; one unknown-stock case was
unscored. These results describe the earlier geometry workload. New physical
rules use a separate workload; their scores are not directly comparable.
The earlier external synthetic bundled workflow passed without node_modules.
Private source plans, prices and results remain outside the public repository.
