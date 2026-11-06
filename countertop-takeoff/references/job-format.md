# Kitchen job format

Write `job.json` with the facts Dad supplies or preliminary cutout geometry he or the owner explicitly authorizes you to estimate. Length fields are inches in multiples of 1/16; prices are decimal strings. Material fields and labor may be `null`. Keep other unknown geometry as questions until resolved, then write a valid job for `check`.

For explicitly authorized preliminary cutout estimates, use the cutout's `estimate` metadata below. Keep installation names descriptive; the quote and drawings carry estimate annotations themselves. Generated `assumptions` still describe CLI defaults, separately from `geometryEstimates`.

The root has `version: 1`, `material`, `laborPerSf`, `installations` and `settings`.

- `material`: `name`, `vendor`, `pricePerSf`, and `slab` (`lengthIn`, `widthIn`, or `null` for the whole slab).
- `laborPerSf`: a decimal string or `null`.
- `installations`: one entry per perimeter, island or other installation, each with an `id`, `label`, `shape` and `cutouts` array. Confirm grouping with Dad. Optional `requiredPieceCount` is an exact positive fabrication-piece count Dad requests, not a preference; omit it when layout should decide. An empty cutouts array means Dad confirmed there are none; resolve visible possible openings before writing the job.
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

Optional `estimate` holds `fields`, a nonempty unique list drawn from `"wIn"`, `"hIn"`, `"at"`, and a plain `note` recording what was authorized and assumed. Mark only the estimated fields; omit it for measured cutouts. Authorized centered estimates include `"at"`; a confirmed centered placement alone is not an estimate. `quote.geometryEstimates` preserves each cutout's installation, index, estimated fields, note and resolved rectangle; send it with the quote and preliminary invoice.

## Confirm and quote

Editing any job field voids confirmation. Run `check`, show the readback and picture, get Dad's yes, then run `confirm` again. `quote.json` supplies quantities, rates, invoice lines, assumptions, warnings and `blanks`, each with one question. Copy those results into the reply; leave calculation to the CLI.
