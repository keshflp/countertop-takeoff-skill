# Kitchen job format

Write `job.json` with the facts Dad supplies or preliminary cutout geometry he or the owner explicitly authorizes you to estimate. Length fields are inches in multiples of 1/16; prices are decimal strings. Material fields and labor may be `null`. Keep other unknown geometry as questions until resolved, then write a valid job for `check`.

For explicitly authorized preliminary cutout estimates, use the cutout's `estimate` metadata below. Keep installation names descriptive; the quote and drawings carry estimate annotations themselves. Generated `assumptions` still describe CLI defaults, separately from `geometryEstimates`.

The root has `version: 1`, `material`, `laborPerSf`, `installations` and `settings`.

- `material`: `name`, `vendor`, supplier `pricePerSf`, required `markupPercent` (nonnegative decimal string or `null`), and `slab` (`lengthIn`, `widthIn`, or `null` for the whole slab). Include markup even when unknown; use `"0"` only when Dad explicitly specifies no markup.
- `laborPerSf`: a decimal string or `null`.
- `installations`: one entry per perimeter, island or other installation, each with an `id`, `label`, `shape` and `cutouts` array. Confirm grouping with Dad. Optional `requiredPieceCount` is an exact positive fabrication-piece count Dad requests, not a preference; omit it when layout should decide. An unsatisfiable count needs clarification with Dad. An empty cutouts array means Dad confirmed there are none; resolve visible possible openings before writing the job.
- `settings`: start with `{}`. The CLI reports defaults as assumed so Dad can confirm them. Record supplied overrides here: `slabTrimIn`, `kerfIn`, `minSeamToCutoutIn`, `minMaterialBesideCutoutIn`, `allowRotate`.

## Shapes

| `kind` | Other fields | Meaning |
|---|---|---|
| `rect` | `lengthIn`, `depthIn` | Straight run or island |
| `L` | `backIn`, `sideIn`, `depthIn`, `side` (`left` or `right`) | Back wall plus one return |
| `U` | `leftIn`, `backIn`, `rightIn`, `depthIn` | Back wall plus two returns |
| `outline` | `points`: clockwise `[x, y]` corners | Supplied axis-aligned outline |

Leg lengths are the outer wall lengths. All legs share the written depth. The CLI computes overlaps, outlines and areas. An L describes the installation; layout splits it into rectangular slab pieces.

## Cutouts

Each cutout has `kind` (`sink`, `cooktop` or `other`), `wIn`, `hIn` and `at`.

For a leg-relative position, `at` holds `leg` and `centerFromStartIn`: either the written inch value or `"center"` for that leg's midpoint, resolved by the CLI. Use `main` for a rect, `back` for the back leg, and `left` or `right` for a side. Back and main start at the left end; sides start at the back wall's outer edge. The cutout is centered within the leg's depth. `wIn` is horizontal width and `hIn` is vertical depth on the installation picture.

When Dad supplies corner coordinates, `at` may instead hold `xIn` and `yIn`, the cutout's top-left corner. This is the only position format for an `outline`. Installation coordinates start at the outer top-left, x right and y down.

Optional `estimate` holds `fields`, a nonempty unique list drawn from `"wIn"`, `"hIn"`, `"at"`, and a plain `note` recording the explicit authorization and basis for the estimate. Mark only the estimated fields; omit it for measured cutouts. Authorized centered estimates include `"at"`; a confirmed centered placement alone is not an estimate. `quote.geometryEstimates` preserves each cutout's installation, index, estimated fields, note and resolved rectangle; send it with the quote and preliminary invoice.

For Dad's explicit equal-half join through a centered opening on a `rect`, add installation `seam: {kind: "center-through-cutout", cutoutIndex}`. The zero-based index selects the opening. Code fixes the seam at the run midpoint and makes two equal blanks; `requiredPieceCount`, if supplied, must be two. Only that seam/selected opening gets the crossing and seam-edge clearance exception. Other openings, original-edge warnings and slab rules remain. The drawing shows the joint in stone on either side of the empty opening. Omit `seam` for the ordinary safe-seam choice.

## Confirm and quote

Editing any job field voids its recorded confirmation. Run `check`, compare the readback and picture with Dad's explicit approvals, ask about changed or unresolved facts, then run `confirm` for the current job. `quote.json` supplies quantities, rates, invoice lines, assumptions, warnings and `blanks`, each with one question. Copy those results into the reply; leave calculation to the CLI.

Markup applies to the exact cost of all purchased slab material, including waste, before code divides by exact job SF and rounds the material rate. Labor is added separately without markup. `pricing.materialCost` stays supplier cost; `markupPercent` and `materialCharge` show markup and the marked-up charge. Unknown markup leaves the charge, material rate and invoice totals blank, with one question; known supplier cost and labor remain visible.
