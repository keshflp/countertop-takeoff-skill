# Kitchen evaluator (development only)

This directory never ships to Dad. It calls the stdin/stdout development entry
points, independently expands job geometry, and checks their answers.

```powershell
uv run evals/kitchen/eval.py
uv run evals/kitchen/eval.py --json
uv run evals/kitchen/eval.py --layout-only
uv run evals/kitchen/eval.py --layout-only --cases evals/kitchen/cases --layout-cmd "uv run evals/kitchen/naive_layout.py"
uv run --no-project -m unittest discover -s evals/kitchen -p "test_*.py"
```

Default commands are `bun countertop-takeoff/cli/src/eval.ts` for quotes and
`uv run countertop-takeoff/kernels/layout.py` for layout-only runs. Override with
`--quote-cmd` / `--layout-cmd`; quote paths containing spaces inside the command.
Commands run at the repository root. `--timeout` defaults to 60 seconds per case.
Each process receives one JSON object on stdin and must return one on stdout.
Normal runs default to `source-cases/` and clean v2 jobs. Source cases with a
null slab still run in layout-only mode: rule assessment must survive without
packing. Historical v1 quote commands require an explicit older `--quote-cmd`
or the development replay flag below; there is no normal material fallback.

## Milestone 03 independent oracle

The original 19 fixtures remain historical geometry/pricing evidence. Their
hashes and accepted measurements are recorded in `historical-baseline.json`;
they do not assert material/profile/thickness facts. Source-assessed automatic
planning uses a separate workload and cannot inherit the old score as evidence
of manufacturer-rule compliance.

`polygon_oracle.py` independently checks gross polygon tiling, solid connectivity,
clockwise quarter turns, polygon kerf, reserved opening footprints and actual
stone join segments. Internal rectangle cells are never fabrication seams.
`source_predicates.py` compares the narrow documented predicates in exact mm:
one sixteenth inch is 1.5875 mm; 100/150 mm require 63/95 ticks respectively.
Metric thickness and radius metadata are not rounded onto that geometry grid.

The pinned Silestone diagram relationships are sink rear 100 mm, cooktop rear
50 mm and adjacent illustrated opening gap 50 mm. The earlier research table's
100 mm adjacent-gap statement is incorrect. Original front/rear/end constraints
remain on the original installation after splitting, including inside joins.
MSI's exact 3/8-inch radius is 9.525 mm and cannot substitute for Silestone's
10 mm sink/cooktop radius. Neither profile applicability nor thickness is inferred
from a material or supplier name. Arithmetic/geometry predicates do not by
themselves establish satisfied support conditions or fabrication certification.

`source-cases/` is a separate 19-case synthetic workload with written arithmetic:
off-center automatic opening joins, thickness-dependent original ends, failed
rails that splitting cannot cure, whole Ls and corner seams, transposed/reversed
source datum, 50 mm adjacent gaps, missing facts, sharp radii, sparse MSI scope,
uninspected U scope, and unchanged exact markup/labor pricing. Each source
arrangement and support note is explicitly synthetic. No real job supplies a
public benchmark or a profile/thickness assumption.

| V2 gate | Independent check |
|---|---|
| originalGeometry | Orthogonal original footprint, contained disjoint openings, connected stone. |
| assessment | Exact applicability, missing paths/questions, outcome admission, caps and handling limits. |
| sourceRules | Recomputed original rails/radii/gaps and join distances; exact units, pinned hash/edition/pages; omitted, false and contradictory evidence rejected. |
| conditions | Supplied scoped support status and note; each outside/inside join retains its applicable rail-support obligation. |
| reasons | Stock-fit/source necessity has a physical witness; supplied joins/counts are labelled supplied. |
| tiling / solidAndCutouts | Gross pieces tile exactly; each clipped void has the right original index; remaining stone is connected. |
| pieceFit / pieceCounts | Actual whole polygon fits; only the legacy equal-halves request implies exactly two pieces. |
| placements | One rigid quarter-turn/translation per piece; reserved holes, usable bounds, orthogonal-axis kerf and unique coverage. |
| joins | Logical boundaries equal actual physical boundaries; precise stone segments, participant ids, selected-opening-only exemption. |
| bounds | Independently recomputed area lower bound; global proof and cap/fallback claims agree. |
| quantity / pricing | Full original facts retained; exact gross SF, supplier cost, unrounded markup, separate labor and null-derived prices. |
| blanks / assumptions / estimates | Unique actual missing facts; three named defaults; authorized estimate fields and resolved rectangles preserved. |

Sink rear 100 mm uses a confirmed source-facing datum; an L leg envelope is not
a documented rectangular run. S1 and S2 support categories are not interchangeable:
the sparse MSI guide establishes perimeter/front/back support and independent
sink support, not generic corner reinforcement or independent cooktop support.
MSI radius evidence retains the original `{value:"0.375",unit:"in"}` while
comparing exact 9.525 mm. Missing facts never become zero or a source pass.

An `opening-center` request pins that opening's exact center join and permits
additional automatic joins. Only `center-through-cutout` requires two equal
blanks and one midpoint join. An exemption never fixes an original rail or
another opening's clearance. Tangencies receive no inside-join exemption.

The scoreboard prints the assessment status. A correct conditional/unresolved/
conflict result can pass evaluator gates, but only **assessed layouts** enter
the new slab objective. JSON includes `assessmentCounts` and workload labels.
Mixed historical/source runs have no combined score. Assessed means the named
implemented subset passed; it never certifies fabrication or handling.

`test_source_eval.py` uses hand-built outputs, not the kernel or the oracle's
own predicate generator. Positive whole-L placements accompany corruption
tests, including the placement-key counting bug. Assessment-only tests retain
exactly one stock question with a null slab; that exception cannot admit a
normal plan layout. Capped incumbents cannot claim proven optimality, and a
cap alone cannot prove physical conflict.

Development replay is explicit and remains unassessed:

```powershell
uv run evals/kitchen/eval.py --geometry-replay --cases evals/kitchen/cases --cases evals/kitchen/contract-cases
uv run evals/kitchen/eval.py --geometry-replay --layout-only --cases evals/kitchen/cases
```

Replay quotes default to `bun countertop-takeoff/cli/src/replay.ts` and must carry
`developmentOnly:"geometry-replay-unassessed"`. Layout-only replay sends the v2
`mode:"geometry-replay"` request with the frozen legacy settings. Neither path
adds facts to fixture files or claims manufacturer assessment. The original
naive code, 19 fixture hashes, and score evidence remain frozen. Changing the
physical model does not establish an improvement over historical excess 11.

At this adapter handoff, 99 focused tests pass, including all synthetic answer
key arithmetic and frozen fixture hashes. First integration used kernel
`1441ff9`, CLI `bf1b01b` and evaluator `0802422`: all 19 cases executed, but the
run was unscored. It exposed an oracle mismatch (nominal thickness carries the
supplied numeric mm value) and two new fixtures that intended a documented
50 mm pair but used `other` for one opening. The corrected fixtures explicitly
use two cooktops with radius 10 mm and retain 49.2125 mm reject / 50.8 mm pass.
An independent hand-built `other` witness retains unsupported/conditional scope;
no universal pair rule was added. This is a workload/oracle correction requiring
rebaselining, not an optimizer improvement. MSI known positive thickness still
admits sparse calculations, but its missing applicability table is explicitly
unsupported, not a manufacturer class pass. Cooktop pair evidence uses the
inspected file p.6 / printed p.10, which also illustrates the 50 mm gap.

The same snapshot's diagnostic quote recheck reached all 19 cases. The remaining
actual kernel question defect (source datum text lacked a question mark) was
reported to T2. Final corrected-evaluator runtime integration and drawings await
the next coordinated phase; there is no accepted new optimizer score yet.
Copy all imported helpers with a runtime snapshot, including
`layout_geometry.py`, `seam_model.py`, `seam_planner.py` and `polygon_pack.py`.

## Historical v1 gates and evidence

Every gate runs independently. A failure exits 1, even when a slab count looks
good. Layout-only runs omit the quantity, pricing, blanks, assumptions and
estimate-output gates.

| Gate | Independent check |
| --- | --- |
| response | Kernel succeeded. A crash, invalid JSON, or timeout fails execution. |
| tiling | Rectangular pieces cover exactly the installation outline, once. Coordinate compression and integer sixteenths find holes, overlaps and protrusions. |
| pieceFit | Each rectangle fits trimmed slab dimensions, with rotation only when allowed. |
| pieceCounts | Any `requiredPieceCount` is the exact number of fabrication rectangles for that installation, even when the unsplit run would fit. |
| fixedJoins | An explicit `center-through-cutout` request produces exactly two equal gross blanks with a declared full-depth seam at the exact midpoint. Correct count alone is insufficient. |
| placements | Every piece appears once, slab indices are contiguous, and placements stay inside usable area with the full kerf gap. Coordinates use the usable origin, so trim is not added again. |
| seams | Declared seams equal actual shared piece edges; no hidden seam crosses or approaches a cutout within the required distance. |
| seamMaterial | Every seam-made edge leaves the configured material beside each cutout, independently of seam clearance. |
| warnings | Insufficient material at original outline edges is reported as a cutout/material or edge warning, including quotes with unknown slabs. An unrelated search warning does not count. The violation does not make an otherwise valid layout fail. |
| bounds | Count matches slabs; lower bound is recomputed from exact area; a known optimum rejects false optimality claims. |
| quantity | Gross installation and total SF use exact area and half-up rounding. Total SF rounds once, independently of invoice line rounding. |
| pricing | Nominal slab area, supplier purchase cost, markup on unrounded full purchased cost, material charge, effective rate, separate labor and invoice lines match Decimal arithmetic. Expected prices assume the hand optimum; a wasteful valid layout must price its actual slab count. |
| blanks | Exactly one plain question per null input; dependent prices and amounts remain null. |
| assumptions | Every omitted setting appears once with its actual default and an instruction to confirm with Dad. |
| estimates | `geometryEstimates` faithfully copies each authorized estimate's installation/index, fields and note, and matches the independently resolved rectangle. Empty means `[]`, never a missing field. |

Seam distance is shortest Euclidean distance from the finite seam segment to the
cutout rectangle, compared using squared integers. Equality at the minimum is
allowed; ordinary seams cannot intersect cutouts. Kerf requires separation along at
least one axis. Cutouts do not subtract gross SF.

The sole crossing exception is an explicit `seam: {kind: "center-through-cutout",
cutoutIndex: 0}` on a rectangular run with the selected opening centered along
its length. Only the exact full midpoint seam and selected opening are exempt
from crossing, seam-gap and seam-made-edge clearance. Other openings, original
edges, gross tiling, slab fit and kerf retain their checks. The request implies
exactly two pieces; a conflicting count or off-grid midpoint is an input error.
Omitting the request retains the ordinary crossing prohibition.

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
Addendum 02 requires nullable `material.markupPercent`. Existing jobs now state
`"0"`, with matching zero-markup output fields. This is a schema-only migration:
their geometry, slab sizes, optima, original expected prices and `naive_layout.py`
are unchanged. Repeating the frozen layout run still yields 27 slabs versus 16,
excess 11. New explicit-join constraints do not change that comparison.

```powershell
uv run evals/kitchen/eval.py --geometry-replay --cases evals/kitchen/contract-cases
uv run evals/kitchen/eval.py --geometry-replay --layout-only --cases evals/kitchen/contract-cases
```

The synthetic interaction case requires exactly two pieces even though the run
fits unseamed, centers an explicitly estimated cutout, and has a one-slab hand
packing proof. The old naive kernel legitimately fails its count constraint;
that result is unscored, not an improvement over baseline 11. Failed runs emit
`score: null` and `scoreAvailable: false`.
CLI `5e310a0` with layout `73b4f72` passes this interaction case with two pieces
and one slab. The original workload and the constrained workload are reported
separately.
CLI `2daac6f` with the same layout kernel also passes all 17 public/contract
quote cases and the unrelated synthetic null-slab original-edge-warning check.
The latter verifies that geometry warnings survive when there is no layout.

Leg-relative `centerFromStartIn: "center"` resolves halfway along the named full
outer leg. Numeric rectangles must still land on the sixteenth grid. Centering
does not itself mark a cutout as estimated. Estimate metadata reports exactly
the authorized fields and resolved rectangle in a standalone quote; default
assumptions retain their existing meaning. The evaluator checks this output,
while the drawing kernel's own tests cover the visible preliminary annotations.

The second contract case fixes a midpoint join and uses unrelated synthetic
12.5% markup. Its exact purchase cost rounds to 476.75, marked charge to 536.35,
and material rate to 27.50. Marking rounded supplier cost gives the wrong charge
536.34; dividing rounded charge gives the wrong rate 27.51. Labor remains 9.35,
and the line amount exercises a half-cent tie. The third case leaves markup
null: supplier cost and labor remain known, with one markup question and null
charge/rates/amount. Zero is explicit, never a financial default.

With layout `1839f38`, all 18 layout-applicable public/contract cases pass
(one unknown-slab skip), including the equal-blank join. Focused hand-layout
tests reject displaced or missing seams, crossings without a request, and
crossing/nearby additional openings. They also retain original-edge warnings.
CLI `f487e16` with that layout passes all 19 quote cases. The focused evaluator
suite has 55 passing tests. These checks validate the stated model, not actual
fabrication templates or engineering approval.

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
uv run evals/kitchen/eval.py --cases evals/kitchen/source-cases --cases C:/Users/keshflp/takeoff-private/cases
```

Supplying `--cases` replaces the default directory; repeat it to combine suites.
Unknown slab dimensions skip only historical v1 layout/replay evaluation. Normal
v2 still assesses original rules and reports unresolved packing. Quote mode
checks quantities, null propagation, pricing and assumptions. Never commit real plans.
Null-slab quote cases set `layoutApplicable: false` and contribute no slab score;
they do not disqualify the scored cases when their own quote gates pass.
JSON reports separate evaluated, pending and skipped counts. Exit 2 means no
numeric cases were evaluated; an exclusively pending selection cannot pass.
Mixed runs score only the explicitly evaluated workload; list pending counts
when reporting results.

A new private automatic assessment wrapper must be separate from historical
supplied-count/join artifacts. Preserve the original intake statements and
authorized estimates; omit count/join constraints only for that explicit new
automatic scenario. Profile/provenance/thickness remain null until confirmed,
so the actual result remains unresolved with null slab-derived charges. Coordinate
with the parent before replacing any canonical wrapper; never infer a thickness
or fabrication profile from a trade name. This evaluator does not confirm jobs.
