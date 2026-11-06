# Kitchen evaluator (development only)

This directory never ships to Dad. It calls the stdin/stdout development entry
points, independently expands job geometry, and checks their answers.

```powershell
uv run evals/kitchen/eval.py
uv run evals/kitchen/eval.py --json
uv run evals/kitchen/eval.py --layout-only --layout-cmd "uv run evals/kitchen/naive_layout.py"
uv run --no-project -m unittest discover -s evals/kitchen -p "test_*.py"
```

Default commands are `bun countertop-takeoff/cli/src/eval.ts` for quotes and
`uv run countertop-takeoff/kernels/layout.py` for layout-only runs. Override with
`--quote-cmd` / `--layout-cmd`; quote paths containing spaces inside the command.
Commands run at the repository root. `--timeout` defaults to 60 seconds per case.
Each process receives one JSON object on stdin and must return one on stdout.

## Gates

Every gate runs independently. A failure exits 1, even when a slab count looks
good. Layout-only runs omit the quantity, pricing, blanks, assumptions and
estimate-output gates.

| Gate | Independent check |
| --- | --- |
| response | Kernel succeeded. A crash, invalid JSON, or timeout fails execution. |
| tiling | Rectangular pieces cover exactly the installation outline, once. Coordinate compression and integer sixteenths find holes, overlaps and protrusions. |
| pieceFit | Each rectangle fits trimmed slab dimensions, with rotation only when allowed. |
| pieceCounts | Any `requiredPieceCount` is the exact number of fabrication rectangles for that installation, even when the unsplit run would fit. |
| placements | Every piece appears once, slab indices are contiguous, and placements stay inside usable area with the full kerf gap. Coordinates use the usable origin, so trim is not added again. |
| seams | Declared seams equal actual shared piece edges; no hidden seam crosses or approaches a cutout within the required distance. |
| seamMaterial | Every seam-made edge leaves the configured material beside each cutout, independently of seam clearance. |
| warnings | Insufficient material at original outline edges is reported as a cutout/material or edge warning. An unrelated search warning does not count. The violation does not make an otherwise valid layout fail. |
| bounds | Count matches slabs; lower bound is recomputed from exact area; a known optimum rejects false optimality claims. |
| quantity | Gross installation and total SF use exact area and half-up rounding. Total SF rounds once, independently of invoice line rounding. |
| pricing | Nominal slab area, purchased material cost, effective rate, labor and each installation invoice line match Decimal arithmetic. Expected prices assume the hand optimum; a wasteful valid layout must price its actual slab count. |
| blanks | Exactly one plain question per null input; dependent prices and amounts remain null. |
| assumptions | Every omitted setting appears once with its actual default and an instruction to confirm with Dad. |
| estimates | `geometryEstimates` faithfully copies each authorized estimate's installation/index, fields and note, and matches the independently resolved rectangle. Empty means `[]`, never a missing field. |

Seam distance is shortest Euclidean distance from the finite seam segment to the
cutout rectangle, compared using squared integers. Equality at the minimum is
allowed; intersection is always forbidden. Kerf requires separation along at
least one axis. Cutouts do not subtract gross SF.

`provenOptimal` is a claim, not a score bonus. Known hand optima can refute it;
private cases without an optimum cannot independently establish a stronger
packing proof than the area bound.

## Baseline and score

The score is the sum of `slabs - optimumSlabs`, using the recomputed area lower
bound when a partial answer key omits an optimum. Lower is better. A score is
eligible for comparison only when every gate passes. `--json` includes both
`score` and `scoreAvailable`, plus per-gate errors and case counts.

On 2026-11-06, `naive_layout.py` passed all layout gates on the 15 cases with
known slabs; the unknown-slab case was skipped. It used **27 slabs against 16
optimal slabs: score 11**. This is T2's fixed baseline to beat, with these cases
and these gates. The naive kernel seams at corners and only splits strips that
cannot fit a slab, moving splits away from cutouts, then puts one piece on each
slab. Difficult corner arrangements can return a plain failure instead of an
unsafe layout. It is deliberately not a packing algorithm.

`baseline-2026-11-06` cannot produce slab counts or layouts at all, so its layout
score is unavailable. The brief records 17,454 Python/Markdown lines at that
tag. The evaluator's broader line metric counts `.py`, `.md`, `.ts`, and `.json`
under `countertop-takeoff/`, excluding `cli/takeoff.js` and `node_modules`; the
first local measurement was 18,108. These are different file sets.

Integration check: T2's first pushed kernel, `e76f2bf`, passed all 15 layout
cases with **16 slabs, score 0**, proving each optimum by the area bound. This
is a measured comparison against the same baseline workload and gates, not a
claim that arbitrary private kitchens are solved optimally.

Before contract addendum 01, CLI `8b86689` with that kernel passed every gate on all 16
synthetic cases, including the null-slab quote. For detached checkouts, set
`TAKEOFF_DEV_SKILL_DIR` to the layout checkout's `countertop-takeoff` directory,
then point `--quote-cmd` at the CLI checkout's `cli/src/eval.ts`. Install the
CLI's locked dependencies in that development checkout first. Sibling files
are never copied into the evaluator branch.

## Contract additions, separate workload

`cases/` is the frozen 16-case baseline. New addendum coverage lives separately
in `contract-cases/`; it does not change the historical slab score or workload.

```powershell
uv run evals/kitchen/eval.py --cases evals/kitchen/contract-cases
uv run evals/kitchen/eval.py --layout-only --cases evals/kitchen/contract-cases
```

The synthetic interaction case requires exactly two pieces even though the run
fits unseamed, centers an explicitly estimated cutout, and has a one-slab hand
packing proof. The old naive kernel legitimately fails its count constraint;
that result is unscored, not an improvement over baseline 11. Failed runs emit
`score: null` and `scoreAvailable: false`.

Leg-relative `centerFromStartIn: "center"` resolves halfway along the named full
outer leg. Numeric rectangles must still land on the sixteenth grid. Centering
does not itself mark a cutout as estimated. Estimate metadata reports exactly
the authorized fields and resolved rectangle in a standalone quote; default
assumptions retain their existing meaning. The evaluator checks this output,
while the drawing kernel's own tests cover the visible preliminary annotations.

## Cases and private plans

Public synthetic cases live in `cases/*.json`: `{ "job": <job.json>,
"expected": { ... }, "why": "hand arithmetic and a feasible optimal packing" }`.
Expected installation SF is keyed by installation id, prices are decimal
strings, `blanks` lists field paths, and `optimumSlabs` is an integer when proved.
The evaluator always recomputes answers instead of trusting the answer key.

Real plans live outside this public repository in `takeoff-private/cases/`.
An incomplete source folder containing `INTAKE.md` is **pending** until it has
an explicit `case.json` wrapper. Discovery includes intake folders immediately
inside a supplied directory, or pass one intake folder directly. Pending intakes
never reach geometry expansion or the quote/layout command, never count as
passing numeric cases, and never contribute a zero to the slab score. JSON
wrappers can also use `{ "status": "pending", "reason": "awaiting confirmed facts" }`
without a job. No real image, dimensions, or transcript belongs in git or CI.

Only after the needed facts are confirmed, put the job in `case.json` alongside
the private source. Do not replace unknown cutouts with `[]`, unresolved lengths
with zero or standard dimensions, or guess installation grouping. No pending
intake should become a runnable job just to obtain a benchmark number.
Owner-authorized geometry estimates may be recorded explicitly in each cutout's
`estimate` object. Preserve their authorization notes; they are preliminary
inputs, not measured facts or an independent contractor answer key. A partial
quantity/blank-propagation case may run without a slab once its geometry is
confirmed or explicitly authorized. Its packing remains unscored, and layout-only
mode skips it. Keep any still-unrepresentable intake pending.
Missing answer-key entries are allowed, including an absent
`expected` or absent `optimumSlabs`. The evaluator reads only `*.json` and writes
no case data or images. Include both directories explicitly to run both:

```powershell
uv run evals/kitchen/eval.py --cases evals/kitchen/cases --cases C:/Users/keshflp/takeoff-private/cases
```

Supplying `--cases` replaces the default directory; repeat it to combine suites.
Unknown slab dimensions skip layout-only evaluation; quote mode still checks
quantities, null propagation, pricing and assumptions. Never commit real plans.
Null-slab quote cases set `layoutApplicable: false` and contribute no slab score;
they do not disqualify the scored cases when their own quote gates pass.
JSON reports separate evaluated, pending and skipped counts. Exit 2 means no
numeric cases were evaluated; an exclusively pending selection cannot pass.
Mixed runs score only the explicitly evaluated workload; list pending counts
when reporting results.
