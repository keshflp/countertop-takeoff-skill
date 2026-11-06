# Takeoff CLI

The agent supplies confirmed facts and records Dad's yes. The CLI owns geometry,
quantities, pricing, tool calls and saved step order. Production needs only Bun
and uv; it never installs JavaScript packages.

```powershell
bun countertop-takeoff/cli/takeoff.js preflight "$env:USERPROFILE\Takeoffs\kitchen" C:\private\sketch.png
# Read the checked pictures and save job.json in that private job folder.
bun countertop-takeoff/cli/takeoff.js check "$env:USERPROFILE\Takeoffs\kitchen"
# Show Dad preview.png and the readback; get his yes.
bun countertop-takeoff/cli/takeoff.js confirm "$env:USERPROFILE\Takeoffs\kitchen"
bun countertop-takeoff/cli/takeoff.js quote "$env:USERPROFILE\Takeoffs\kitchen"
bun countertop-takeoff/cli/takeoff.js next "$env:USERPROFILE\Takeoffs\kitchen"
```

`preflight.json` fingerprints the private input copies. `check.json` binds the
preview to those inputs and the exact bytes of job.json. `confirm.json` records
the same hashes, so editing facts, inputs or the preview requires a new check
and Dad's yes. A failed preflight clears previous success. The CLI refuses job
folders inside its repository, including paths through directory links.
`inputs.json` lists the inspected files and their rendered pages.

Missing facts are explicit nulls. They leave dependent results null and produce
one question each. Without slab dimensions, quote saves quantities and questions
with a shapes-only layout.png. Unknown labor leaves the invoice rate and amount
blank. Expected failures print one plain message and exit 1, without a traceback.

Leg-relative cutouts accept `centerFromStartIn: "center"`; the CLI centers along
the full outer leg without agent arithmetic. An optional cutout
`estimate: {fields: ["wIn", "hIn", "at"], note: "owner authorization and basis"}`
marks only explicitly authorized estimates. The fields list must be nonempty and
unique. `quote.geometryEstimates` always exists, preserves those fields and note,
and records the actual resolved rectangle. Both drawing modes receive the same
metadata. Check and quote visibly say `Preliminary: estimated geometry`; defaults
remain in `assumptions`, separate from geometry estimates. A centered position
alone does not mark anything estimated.

Optional installation `requiredPieceCount` requires exactly that many rectangular
fabrication pieces. It passes through to layout and drawing, remains on the quote
installation, and is checked independently against the successful kernel reply.
Fabrication splits do not split invoice lines or duplicate installed quantities.
Original-edge cutout-clearance warnings come from the installed geometry and
remain available in check/quote even when slab dimensions are still unknown.

Optional installation `seam: {kind: "center-through-cutout", cutoutIndex: 0}`
requests two equal rectangular blanks joined at the run's exact midpoint through
that centered opening. The CLI rejects incompatible shapes, counts, indices,
off-center openings and off-grid midpoints. It independently checks the returned
blank outlines and full join, retaining clearance rules for every other opening.
Check/quote readback and drawing inputs preserve the explicit join instruction.

`material.markupPercent` is required and nullable; use `"0"` explicitly for no
markup. This is a deliberate input-schema change. Markup applies to unrounded
supplier cost for all purchased slabs, before dividing by exact gross job SF.
Labor is added separately. `pricing.materialCost` remains supplier cost;
`materialCharge` includes markup. A null percentage preserves known supplier cost
and labor, leaves dependent charges/rates/amounts null, and produces one question.

## Development

Effect 4.1.2 was npm's stable release when checked on 2026-11-06. Commands use
`effect/cli`; Bun platform services supply filesystem and scoped child processes.

```powershell
cd countertop-takeoff/cli
bun install --frozen-lockfile
bun run check
bun run build
bun test
```

Commit takeoff.js whenever its source changes. The focused bundle test rebuilds
in memory and compares hashes, ignoring Git's Windows line-ending conversion.

`schema.ts` owns the wire contracts. `geometry.ts` and `exact.ts` use BigInt:
lengths are integer sixteenths; areas are integer square-sixteenths; SF and money
remain rational until the specified half-up rounding boundary. `core.ts` resolves
assumptions and calculates quantities and prices. `takeoff.ts` is shared by the
quote command and the stdin/stdout evaluator entry.

`Kernels` is a service because it owns Python process execution, reply decoding,
and dependency checks. Removing that seam would spread process and protocol
handling into both entrypoints and the workflow. Geometry, settings and pricing
stay pure values/functions. Tests replace only the kernel transport and exercise
the same schema decoders, with real temporary files for workflow state. The live
Layer runs `uv run <bundle-relative skillDir>/kernels/<name>.py` without a shell.

The development evaluator reads job.json from stdin and writes only quote.json
to stdout, without files, preflight, confirmation or PNGs. Its optional
`TAKEOFF_DEV_SKILL_DIR` environment variable points at detached sibling kernels;
the shipped CLI always resolves kernels relative to its own bundle.

## Contract readings

- A null slab makes layout and slab-derived prices null. A shapes-only picture
  remains possible; no slab size is invented.
- Explicit outline cutouts use top-left x/y. Leg-relative cutouts whose exact
  center would need a 1/32-inch coordinate are rejected with a request for an
  explicit sixteenth-inch top-left position. This preserves the brief's grid.
- `slabSf` can recur in decimal. Its display uses up to 18 fractional digits;
  pricing always uses the exact rational, never that display string.
- Gross SF, nominal slab pricing and the stated shape conventions appear as
  assumptions alongside every omitted named setting.
- The brief does not specify draw stdout. T2's concrete reply is decoded as
  `{ok: true, path: <requested PNG>}`; the returned path must match the request.
- Exact piece counts do not introduce a minimum piece width. A narrow end strip
  remains possible without an explicit center join; the CLI does not invent a
  fabrication limit. An explicit center join fixes equal halves and exempts only
  that seam and selected opening, without changing original-outer-edge warnings.

## Evaluation record

Baseline: the tagged starting code has no CLI, so a quote score is unavailable.
T1's naive layout baseline passes layout gates with score 11 on its 15 cases
with known slabs. The first CLI candidate with T2 layout passes all gates on the
same 16 public cases and has zero excess slabs on the 15 scored cases. Its later
evaluator revision correctly leaves the unknown-slab case unscored while still
checking its quantity, pricing and null propagation.

The base synthetic preflight/check/confirm/quote/next run passed against all three
real kernels, with the bundle outside the repository and no node_modules. The
extended evaluator and drawing integration evidence is recorded in the PR.
Real-case sources and results remain outside this public repository.
