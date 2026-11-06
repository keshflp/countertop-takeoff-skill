# Kitchen job format

Write `job.json` with supplied facts and explicitly authorized preliminary cutout estimates. The root has `version: 2`, `material`, `laborPerSf`, `installations` and `settings`. Objects accept only the fields described here. Include every nullable field; unknown means `null`. Resolve unknown outline/opening dimensions as questions before making a valid job, unless the owner authorizes a preliminary cutout estimate.

Inch lengths are numbers on the 1/16-inch grid. Prices, markup and metric measurements are nonnegative decimal strings; sizes and thickness are positive. Code computes conversions and derived geometry. Radius `"0"` means a supplied sharp corner, which may fail a product rule; it is different from unknown. Metric radii/thickness stay exact in mm, off the inch grid.

## Material and settings

- `material`: `name`, `vendor`, supplier `pricePerSf`, `markupPercent`, `slab`, `profileId`, `profileProvenance`, `nominalThicknessMm`. Each accepts `null`; a known slab is `{lengthIn, widthIn}`. Use `"0"` markup only when explicitly supplied.
- `profileId` selects documented product rules: `silestone-2024-02` or sparse `msi-q-pinned`. `profileProvenance` is a nonempty note identifying the explicit product/source basis. A marketing name or supplier alone establishes neither. Other ids remain unsupported. Missing profile/provenance/thickness leaves automatic planning unresolved.
- `nominalThicknessMm` records the actual supplied nominal class, without rounding or interpolation. Use the selected source's supported class; ask when it is unknown.
- `laborPerSf`: decimal string or `null`, separate from material markup.
- `settings`: start with `{}`. Supplied overrides are only `slabTrimIn`, `kerfIn`, `allowRotate`. The CLI lists defaults as assumptions for Dad. Product rules supply opening requirements; generic opening-clearance settings are retired.

## Installations and shapes

One entry per installed perimeter, run or island: `id`, `label`, `shape`, `cutouts`, `insideCornerRadiusMm`, `sourceArrangement`, `conditions`, plus optional supplied `seam`/`requiredPieceCount`. Confirm grouping with Dad. The program proposes fabrication pieces, including whole L candidates. An empty `cutouts` array means confirmed none; retain visible possible openings as questions until identified.

| `shape.kind` | Other fields | Meaning |
|---|---|---|
| `rect` | `lengthIn`, `depthIn` | Straight run or island |
| `L` | `backIn`, `sideIn`, `depthIn`, `side` (`left` or `right`) | Back wall and one return |
| `U` | `leftIn`, `backIn`, `rightIn`, `depthIn` | Back wall and two returns |
| `outline` | `points`: clockwise `[x,y]` corners, without repeated closing point | Supplied simple orthogonal outline |

Leg lengths are outer wall lengths with a common written depth. Code computes overlaps, outlines and gross SF. Coordinates start at the outer top-left, x right/y down. Whole pieces remain connected polygons; internal packing cells are not cuts. U/general shapes are representable, while undocumented source arrangements remain unsupported.

`insideCornerRadiusMm` is the minimum actual continuous inside-corner radius, or `null`. `sourceArrangement` is `null` or `{kind:"rectangular-run", axis:"x"|"y", rear:"min"|"max", provenance}`. The axis runs along the original rectangle; rear identifies the low/high edge on its transverse axis. Record intake evidence for that rear datum in the nonempty provenance note. An L/U leg is not this documented rectangular-run arrangement.

`conditions` is an array of scoped evidence: `{kind, cutoutIndex, status, note}`. `kind` is `level-support`, `corner-continuous-support`, `corner-reinforcement`, `opening-continuous-support`, `fixture-support` or `installation-support`. `cutoutIndex` is a zero-based opening index, or `null` for the whole installation. `status` is `documented`, `failed` or `unknown`; `note` is required and nonempty for documented/failed, otherwise nullable. Empty evidence means no evidence. Continuous front/back rail support at a join differs from independent fixture support. Notes establish supplied facts, not manufacturer authority or a reinforcement design; apply only the selected source's conditions.

## Cutouts and supplied joins

Each cutout has `kind` (`sink`, `cooktop`, `other`), `wIn`, `hIn`, `at`, required nullable `radiusMm` and `mount` (`top`, `under`, `flush`, `other`). A rectangular envelope establishes neither its radius nor mount.

For leg-relative positioning, `at` is `{leg, centerFromStartIn}`. Use `main` for a rect, `back` for the back leg, `left`/`right` for sides. Back/main start at the left end; sides start at the back wall's outer edge. Copy a written center offset or `"center"` for the full leg midpoint, resolved by code. The cutout is centered within the leg depth. `wIn`/`hIn` are horizontal/vertical on the installation picture. Supplied top-left coordinates use `{xIn,yIn}` instead; this is the only position form for `outline`.

Optional `estimate` is `{fields, note}`. `fields` is a nonempty unique list of `"wIn"`, `"hIn"`, `"at"`; the note records authorization and basis. Mark only assumed fields. An authorized estimated location includes `"at"`; a confirmed centered placement alone is not estimated. `quote.geometryEstimates` retains fields, note and resolved rectangles for drawings and the preliminary PDF. Keep measured facts distinct.

Ordinary automatic planning needs no supplied constraints:

- `requiredPieceCount`: an exact positive fabrication-piece count, only when explicitly supplied.
- `seam: {kind:"opening-center", cutoutIndex}`: pins a join at the selected opening's center; additional joins remain possible unless an exact count constrains them.
- `seam: {kind:"center-through-cutout", cutoutIndex}`: historical explicit equal-halves request on a rectangular run with a centered opening; fixes the exact midpoint and exactly two equal blanks. A supplied count must agree.
- `seam: {kind:"tangent-cutout", cutoutIndex, side:"start"|"end"}`: representable but unsupported in this implementation.

Supplied joins/counts never waive product rules, original opening-strip checks or other openings' requirements. Inside-opening permission is scoped to that opening; drawings show joins only in stone beside the void.

## Check, confirm and deliver

`check` evaluates original geometry and source facts and draws the input preview; it does not solve a slab layout. Show product/provenance/thickness, datum, radii/mount/support evidence, checks, outstanding conditions and assumptions before confirmation. Reuse explicit approvals for matching facts. Every edit invalidates confirmation: check again, compare with approvals, resolve changed facts, then confirm the exact current job.

`quote` retains all input facts, estimates and source evidence in standalone `quote.json`. Copy its computed quantities/prices and `blanks` questions; one question per missing fact. Explain automatic joins as stock-fit, source-rule or yield choices; supplied constraints retain their own reason. A seam is not automatically a strength requirement.

| Assessment | Delivery |
|---|---|
| `unresolved` | Known SF, input preview and independent prices; no final layout or slab-derived charges. Ask the listed missing-fact questions. |
| `conditional` | Candidate layout and preliminary quote with every outstanding radius/support/source condition visible. |
| `assessed` | Layout assessed only within the named implemented rule scope. |
| `conflict` | Particular failed rule/condition or incompatible supplied constraint; retain independent quantities, with no qualifying final layout. |
| `search-incomplete` | Search cap without a qualifying incumbent, not proof of physical impossibility. |

A capped incumbent retains proof/coverage limits. An assessed original-rule subset from `check` does not imply a solved stock layout. Handling remains `not-evaluated` for every result. Sparse MSI stays incomplete; it inherits no Silestone corner conditions or numerical opening rules, and its independent sink-support statement is not a cooktop rule.

Preserve source profile/version, rule status, URL/pages, outstanding conditions, estimates, assumptions and search limits in both drawings and the invoice-PDF request. These are estimator results within stated scope, rather than fabrication certification. Estimated geometry retains the visible label "Preliminary: estimated geometry" and needs actual templates before cutting.

Code applies markup to exact full purchased-slab supplier cost, including waste, before dividing by exact job SF and rounding the material rate. Labor is unmarked-up. `pricing.materialCost` stays supplier cost; `markupPercent` and `materialCharge` show markup and marked-up charge. Unknown markup keeps dependent totals blank. With no layout, purchased cost/charge/rates/amounts stay null while known supplier unit price, markup and labor remain available.
