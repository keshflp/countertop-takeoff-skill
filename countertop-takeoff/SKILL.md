---
name: countertop-takeoff
description: Use when Dad says "takeoff", sends a kitchen sketch, or asks about slabs or a kitchen quote.
---

# Kitchen takeoff

Talk to Dad like an estimator: sizes, square feet, slabs and price.

**You read, code computes.** Copy numbers written on the sketch or told by Dad, plus preliminary cutout inputs he or the owner explicitly authorizes you to estimate. The CLI does every calculation; you never do arithmetic.

**Blank, not guessed.** Unknown values stay `null`, with one plain question for each. Keep unresolved geometry as questions until supplied or covered by an explicitly authorized preliminary estimate.

**Authorized estimates are preliminary.** Mark assumed cutout fields in `estimate`, with a note recording the authorization and basis. Keep measured fields separate. Carry `geometryEstimates` into every delivery and label the invoice PDF "Preliminary: estimated geometry". Actual opening templates are needed before cutting. Prices, markup and labor come from Dad, not estimates.

`<skill>` is this skill folder. Keep job folders outside the skill folder and its repository, for example `C:\Users\<user>\takeoff-private\<job>`, because plans are private.
Whenever you are unsure what comes next, run `bun <skill>/cli/takeoff.js next <jobDir>` after preflight.

## Steps

1. **Preflight.** The first command every run is `bun <skill>/cli/takeoff.js preflight <jobDir> <files>`. Use local input paths; quote paths containing spaces. This check is required, including when resuming a job. If it fails, stop and tell Dad in plain words what is missing.
   Done when: preflight passed and every input can be read, or Dad knows what to resend or fix and the run has stopped.

2. **Read the sketch.** Look at every input picture or rendered PDF page. Resolve the sketch questions below with Dad. Read [the job format](references/job-format.md), then write v2 `<jobDir>/job.json` using `rect`, `L`, `U` or `outline`, and cutouts positioned on their legs. The program proposes seams; Dad need not supply joins or piece counts. Run `bun <skill>/cli/takeoff.js check <jobDir>`. Send Dad the readback and `preview.png`, including model facts, outstanding conditions and assumptions. Reuse his explicit approval for matching facts; ask "Is this right?" about changed or unresolved facts. Correct and check again as needed. After approval, run `bun <skill>/cli/takeoff.js confirm <jobDir>`.
   Done when: Dad explicitly approved the facts shown, and the CLI recorded confirmation of that exact job.

3. **Fill the gaps.** Ask for missing material name, vendor, supplier $/SF, markup percent on material cost, slab size and labor per SF. Ask which documented product rules apply and why, actual nominal thickness, opening/inside-corner radii, the run's rear side and scoped support evidence, using the reference. A name or vendor alone cannot select product rules. Keep unanswered facts `null` or empty evidence; zero markup needs an explicit answer. Each edit needs another check and confirmation against Dad's explicit approvals before quoting.
   Done when: Dad's answers are recorded, each remaining blank has one plain question, and the current job is confirmed.

4. **Quote.** Run `bun <skill>/cli/takeoff.js quote <jobDir>`. Send `layout.png`, total SF, available slab count/rate and invoice lines from `quote.json`. Explain whether the result is unresolved, conditional, assessed within named rules, a conflict or search-incomplete. A conditional layout stays preliminary with its unmet conditions; unavailable layout/slab charges stay blank. Show supplier cost, markup and material charge separately from labor. Code marks up exact purchased material cost before calculating the rate; labor has no markup. Carry warnings, default assumptions, estimates, source scope and search limits into the delivery; handling remains not evaluated. List each remaining blank with its question. Ask ChatGPT to make the invoice PDF from `quote.json`, preserving these labels and blanks; ask Dad for company/customer details if needed.
   Done when: Dad has the available quantities, layout, prices and their limits, every blank has its question, and ChatGPT has the PDF request and quote data with the same labels.

## Reading phone sketches

- Confirm units, unfamiliar symbols and which drawings belong together. An installation is an installed counter or run; fabrication pieces are its slab parts. Ask what each drawn item is for before deciding whether it belongs. Keep finishing observations in private notes. For an explicitly supplied join or exact count, use the reference; otherwise let code propose the pieces.
- An inch mark means inches; a foot mark followed by inches means feet-inches. Keep that distinction in the readback. For notation the CLI cannot accept, ask Dad for decimal inches instead of converting it yourself.
- Match each written wall length to its own leg. Back runs left to right; side legs run from the back wall toward the front. Use the outer wall lengths and the written common depth. Ask when a dimension could belong to either leg.
- For a sink or cooktop, copy its width, depth and the written distance to its center along that leg. Use `centerFromStartIn: "center"` when Dad requests the midpoint; code resolves it. It sits centered front to back. If Dad measured to an edge instead, ask for the center distance.
- Treat inner shapes as possible openings until Dad identifies them. Ask for their kind, dimensions and position, or explicit permission for a preliminary estimate; use `cutouts: []` only when Dad confirms there are none. Read written measurements instead of measuring sketch proportions.
- A missing, blurred or conflicting number gets one question. Keep it blank until answered or an estimate is explicitly authorized. Use an `outline` only when its corner coordinates are supplied; code draws the outline for other shapes.
- A PDF is another sketch: look at its rendered pages in the input's `previews` folder and read the written dimensions the same way.
- For one faint or unreadable raster detail, see [selected scan-detail suggestions](references/scan-detail.md); review the overlay and ask Dad for measurements.
