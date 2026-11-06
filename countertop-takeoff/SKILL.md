---
name: countertop-takeoff
description: Use when Dad says "takeoff", sends a kitchen sketch, or asks about slabs or a kitchen quote.
---

# Kitchen takeoff

Talk to Dad like an estimator: sizes, square feet, slabs and price.

**You read, code computes.** Copy only numbers written on the sketch or told by Dad. The CLI does every calculation; you never do arithmetic.

**Blank, not guessed.** Unknown values stay `null`, with one plain question for each. Ask about unreadable dimensions before drawing the counter.

`<skill>` is this skill folder. Keep job folders outside the skill folder and its repository, for example `C:\Users\<user>\takeoff-private\<job>`, because plans are private.
All commands below use `bun <skill>/cli/takeoff.js`. Whenever you are unsure what comes next, run `bun <skill>/cli/takeoff.js next <jobDir>` after preflight.

## Steps

1. **Preflight.** The first command every run is `bun <skill>/cli/takeoff.js preflight <jobDir> <files>`. Use local input paths; quote paths containing spaces. This check is required, including when resuming a job. If it fails, stop and tell Dad in plain words what is missing.
   Done when: preflight passed and every input can be read, or Dad knows what to resend or fix and the run has stopped.

2. **Read the sketch.** Look at every input picture or rendered PDF page. Read [the job format](references/job-format.md), then write `<jobDir>/job.json` using `rect`, `L`, `U` or `outline`, and cutouts positioned on their legs. Run `bun <skill>/cli/takeoff.js check <jobDir>`. Send Dad the readback and `preview.png`, including the assumptions to confirm, and ask "Is this right?". Make corrections and check again as needed. After his yes, run `bun <skill>/cli/takeoff.js confirm <jobDir>`.
   Done when: Dad said yes to the readback and picture, and the CLI recorded confirmation of that exact job.

3. **Fill the gaps.** Ask for missing material name, vendor, material $/SF, slab length and width, and labor per SF. Keep unanswered values `null`. Each edit to `job.json` needs another check, readback and picture for Dad, his yes, and confirm before quoting.
   Done when: Dad's answers are recorded, each remaining blank has one plain question, and the current job is confirmed.

4. **Quote.** Run `bun <skill>/cli/takeoff.js quote <jobDir>`. Send `layout.png` when available, total SF, slab count, rate per SF and the invoice lines from `quote.json`. Explain warnings in plain words. List each remaining blank with its question. Ask ChatGPT to make the invoice PDF from `quote.json`, preserving blanks; ask Dad for the company header and customer details if needed.
   Done when: Dad has the available layout, quantities, pricing and invoice lines, every blank has its question, and ChatGPT has the PDF request and quote data.

## Reading phone sketches

- An inch mark means inches; a foot mark followed by inches means feet-inches. Keep that distinction in the readback. For notation the CLI cannot accept, ask Dad for decimal inches instead of converting it yourself.
- Match each written wall length to its own leg. Back runs left to right; side legs run from the back wall toward the front. Use the outer wall lengths and the written common depth. Ask when a dimension could belong to either leg.
- For a sink or cooktop, copy its width, depth and the written distance to its center along that leg. It sits centered front to back. If Dad measured to an edge instead, ask for the center distance; code needs a center, not an estimate.
- A missing, blurred or conflicting number gets one question. Keep it blank until Dad answers. Use an `outline` only when its corner coordinates are supplied; code draws the outline for other shapes.
- A PDF is another sketch: look at its rendered pages in the input's `previews` folder and read the written dimensions the same way.
