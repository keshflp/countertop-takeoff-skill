# Kitchen job format

Write `job.json` with the facts Dad supplies. Length fields are inches in multiples of 1/16; prices are decimal strings. Material fields and labor may be `null`. Resolve missing shape or cutout dimensions with Dad before `check`.

The root has `version: 1`, `material`, `laborPerSf`, `installations` and `settings`.

- `material`: `name`, `vendor`, `pricePerSf`, and `slab` (`lengthIn`, `widthIn`, or `null` for the whole slab).
- `laborPerSf`: a decimal string or `null`.
- `installations`: one entry per perimeter, island or other installation, each with an `id`, `label`, `shape` and `cutouts` array. An empty cutouts array means Dad's sketch has none.
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

For a leg-relative position, `at` holds `leg` and `centerFromStartIn`. Use `main` for a rect, `back` for the back leg, and `left` or `right` for a side. Back and main start at the left end; sides start at the back wall's outer edge. The cutout is centered within the leg's depth. `wIn` is horizontal width and `hIn` is vertical depth on the installation picture.

When Dad supplies corner coordinates, `at` may instead hold `xIn` and `yIn`, the cutout's top-left corner. This is the only position format for an `outline`. Installation coordinates start at the outer top-left, x right and y down.

## Confirm and quote

Editing any job field voids confirmation. Run `check`, show the readback and picture, get Dad's yes, then run `confirm` again. `quote.json` supplies quantities, rates, invoice lines, assumptions, warnings and `blanks`, each with one question. Copy those results into the reply; leave calculation to the CLI.
