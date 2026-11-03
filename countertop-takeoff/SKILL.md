---
name: countertop-takeoff
version: 2.0.0
description: >-
  Countertop square-footage takeoff from architectural plan/spec PDFs for
  countertop subcontractors bidding apartments and hotels. Preflights the
  drawing pack (raster/hybrid detection, revision conflicts), plans an
  approved scope with a completeness ledger, records schedule evidence with
  quoted rows and word boxes, calibrates per viewport from TWO agreeing
  labeled dimensions, measures agent-SELECTED boundary segments with code,
  audits scope/schedule reconciliation, renders overlay evidence, and gates
  delivery behind an independent audit. Use when the user shares plan PDFs
  and asks for countertop quantities, square footage, SF, or a takeoff.
---

# Countertop Takeoff (V2: auditable square footage)

You are doing a countertop takeoff on a set of plan/spec PDFs for a
countertop subcontractor. Multifamily/hospitality sets are repetitive: a unit
schedule lists room types (Type A ×24, Type B ×12…) and each type has ONE
repeated plan. V2 scope is **square footage only**. Edge linear feet,
backsplash, cutout pricing, slab yield, pricing, and invoicing are later
phases — see "Extension points".

Every command runs from THIS skill folder (the folder containing `SKILL.md`).
Scripts are plain Python driven by `uv`:

```console
uv run scripts/index_pdf.py <file.pdf>
```

`uv` auto-provisions Python and the pinned dependencies (`pymupdf==2.1`,
`shapely==2.2.0`) on first use — no Python install needed. Machines without
uv: `pip install -r scripts/requirements.txt`, then run `python` directly.
This skill is developed on Windows: never assume Unix tools (`grep`,
`sed`) — filter JSON with Python one-liners or the printed summaries.

## Non-negotiable rules

1. **Vision for recognition, code for measurement.** You may LOOK at rendered
   pages only to decide WHAT to measure. You must NEVER produce a quantity by
   eyeballing an image, and you must never type a scale factor or a length:
   you SELECT recorded words/segments and the code computes everything.
2. **Text is not vectors.** A searchable raster page (OCR'd scan) has text
   but no linework. Only preflight class `vector` pages may be measured;
   everything else gets an explicit skip/block with a quoted reason.
3. **Multiplication is earned, never assumed.** Counts come from the
   schedule with quoted row text + word boxes, as integers, with explicit
   ADA-style variant allocation. A missing count is a FAILURE, not a default.
4. **Human approval gates measurement.** You present the scope ledger +
   schedule plan and WAIT. No extraction work before approval.
5. **Independent audit gates delivery.** After measurement you render the
   audit pack and a FRESH agent (or an independent human, recorded as such)
   must approve before exports are delivered.
6. **Cite everything.** Every number carries page, viewport, segment ids,
   and the actual calibration factor. Exit codes and `status` fields are
   law: a `failed` run's numbers must not be quoted.

## Workflow — run the steps IN THIS ORDER

### Step 1. Intake & pack QA (preflight)

- Ask for / locate the PDF(s). Plans on a planroom are downloaded BY THE USER
  manually (never scrape planrooms).
- Run `uv run scripts/index_pdf.py <file.pdf>` for each PDF. It prints the
  page table (sheet, class, rotation, segments, image coverage) and writes
  `<pdf>.index.json` with full page text + findings.
- READ the summary and the JSON. Note: pages classed `searchable_raster` /
  `raster` / `hybrid` / `uncertain`, duplicate pages, and sheet-id conflicts.
  These NEED a disposition in step 3. Conflicts mean one sheet number appears
  twice with different content — find the revision marks (REV A/B…) and
  figure out which page is authoritative, or list it as an open question.

### Step 2. Find the unit schedule and identify plan sheets

- Candidates: pages flagged `unit_schedule`. READ their TEXT in the index
  JSON. Build the table: `type -> count`, quoting each row verbatim, and
  record where it sits (sheet, page). Watch for: floor subtotals, ADA-style
  subset columns ("TYPE A (ADA)"), and stated project totals — these feed
  reconciliation later.
- Exception rules: corner/end units, ADA-modified units, ground/penthouse
  variants, and amenity spaces (lobby, clubroom, pool bath) are measured
  SEPARATELY with their own counts. An amenity counter on a raster page is
  an explicit skip with a "manual takeoff pending" reason — never silent.
- If there is NO schedule and rooms don't repeat → plan step 3 in
  `individual_rooms` mode.

### Step 3. Plan the approved scope + schedule evidence, then STOP for approval

Before ANY geometry work, write the plan:

1. **Scope ledger**: EVERY page gets `measured` (with the expected region
   ids you plan: kitchen, island, peninsula, vanity — including amenities)
   or `intentionally_skipped` with a quoted reason (schedule sheet,
   superseded revision, unmeasurable scan), or `blocked` if unresolved.
2. **Schedule evidence**: per type — the count (integer), the quoted row
   text, the schedule page/sheet, floor rows if the schedule has them, and
   explicit variants with `included_in_parent_total`.
3. **Declarations**: anything contradictory (plan/spec depth conflicts,
   suspected revisions, ambiguous labels) as `policy.declarations`.

Then present to the user and WAIT — this is the v2 human gate, BEFORE any
extraction:

- the page table with classes and your disposition plan;
- the schedule table as READ (quote the rows) + variant handling;
- the region plan per measured page;
- every open question (conflicts, unclear counts).

Only after explicit approval continue. If the user corrects a count, redo
step 3 and re-present. Do not skip the gate even if told "just do it" —
summarize and offer a one-line approve/fix choice.

### Step 4. Extract geometry, select spans/boundaries, measure

AFTER approval:

1. Extract vectors for the pages you plan to measure (plus any you need to
   inspect):
   `uv run scripts/extract_geometry.py <file.pdf> --pages all --out build/<name>.geometry.json`
   Segment ids are stable; coordinates are in DISPLAYED page space
   (rotation already applied).
2. Build the V2 job spec (`references/job-spec-v2.md` has the full schema;
   `examples/fixture.jobs.json` and `examples/messy.jobs.json` are working
   examples). You write ONLY selections and evidence:
   - **Calibration spans** per (page, viewport): pick TWO+ labeled
     dimensions on that sheet and the segments of their dimension lines.
     To find candidates, filter the geometry with Python (no grep):
     `uv run --with pymupdf==2.1 python -c "import json; g=json.load(open('build/x.geometry.json')); [print(w['id'], w['t'], round(w['x0'],1), round(w['y0'],1)) for w in g['pages'][1]['words'] if chr(39) in w['t'] or '\"' in w['t']]"`
     then look for long segments near the label bbox. Code parses split and
     fractional labels and computes every length; the factor is never typed.
   - **Region boundaries**: pick the segment ids that form each countertop's
     closed outline (walls included where they bound the counter). The
     selection must close into exactly one loop — dangling endpoints,
     hatch ticks, or dimension lines in the selection are REFUSED with the
     offending coordinates named. Give each region a strictly-interior seed
     and an honest `expected_sf_range` (apartment kitchens ~15–45 SF,
     vanities ~4–15 SF — a guard, not a target).
   - **Scope ledger + schedule evidence + declarations** from step 3.
3. Run:
   `uv run scripts/measure.py <jobs>.json --report build/report.md --csv build/takeoff.csv --json build/results.json`
   - exit 0 = required checks passed (`ready`/`warning`); exit 2 = refusal —
     READ the named reason, fix the spec or selections, re-run. Never edit
     outputs by hand; never quote numbers from a failed run.
4. Check `status` and every audit line: calibration spreads in the 2–5% band
   must be explained; expected-range breaches mean a wrong span or wrong
   boundary — never a "close enough".

### Step 5. Render the audit pack (overlays)

```console
uv run scripts/audit_pack.py build/results.json --pack build/audit_pack
```

Full-page + close-up PNGs per region: translucent measured shell, region id,
area, the ACTUAL factor, seed marker, calibration span highlights, cutouts.
`index.md` lists what the reviewer must check. These overlays are the
handoff to the independent audit — the reviewer sees whether shells sit on
real countertop linework, whether seeds are inside, and whether calibration
spans are on true dimension lines.

### Step 6. Independent audit (MANDATORY before delivery)

Give a FRESH agent (new session, no context from this takeoff) the audit
pack, the raw PDF, the index/geometry JSONs, and this prompt:

> You are auditing a countertop takeoff you did NOT perform. In the folder:
> the original plan PDF, `<pdf>.index.json` (preflight), the job spec
> `<name>.jobs.json`, `results.json`, `report.md`, and `audit_pack/` overlay
> PNGs. Do NOT trust the report. Verify from raw evidence:
> 1. RE-READ the unit schedule page text yourself and confirm every count,
>    floor total and ADA/subset handling matches what the spec used.
> 2. Check the scope ledger: every page dispositioned? Any skipped page that
>    actually contains countertop scope (amenities, scan pages)? Are the
>    stated reasons honest?
> 3. Check each overlay against the raw sheet: shell on the countertop
>    outline, seed strictly inside, nothing double-counted or missing
>    (islands, peninsulas), calibration spans on true dimension lines.
> 4. Spot-check one area by hand: pick a rectangular region, compute
>    length x width from the printed factor, compare to the recorded SF.
> 5. Check the CSV: base rows only carry extension; recheck rows are blank;
>    type totals + grand total match results.json.
> Reply with `VERDICT: approved` or `VERDICT: rejected` plus specific
> findings. You are the safety net, not a formality.

Record the outcome:

```console
uv run scripts/audit_pack.py build/results.json --record-receipt \
    --reviewer "fresh-agent: <session>" --verdict approved --notes "..."
```

If NO fresh agent is available, an INDEPENDENT HUMAN must do the same review,
recorded as `--reviewer "human: <name>"` — the substitution is recorded in
the evidence, never hidden. `verdict rejected` is recorded verbatim and the
issues go back to step 4.

### Step 7. Deliver exports

Only now deliver: `report.md`, `takeoff.csv`, `results.json`, the audit pack
and the recorded receipt. A `warning` status delivery must list the warnings
and the reviewer's disposition of them. A `failed` or still-`pending`
delivery is FORBIDDEN.

## Smoke test (2 minutes, no real project needed)

Prove the toolchain works on any machine (the generator is byte-deterministic,
so the example job spec's pinned source hash matches the regenerated PDF):

```console
uv run examples/make_fixture.py --out examples/fixture.pdf
uv run scripts/index_pdf.py examples/fixture.pdf
uv run scripts/extract_geometry.py examples/fixture.pdf --pages all --out build/fixture.geometry.json
uv run scripts/measure.py examples/fixture.jobs.json --report build/report.md --csv build/takeoff.csv --json build/results.json
```

Expected: total **168.75 SF** (Type A 38.25 ×3 + Type B 27.00 ×2), factors
18.0000 pt/ft from three agreeing spans per page, `status: ready`,
`review_status: independent_audit_pending`. Then:

```console
uv run scripts/audit_pack.py build/results.json --pack build/audit_pack
uv run examples/tests_v2.py
```

The full walkthrough lives in `examples/run_example.md`; the hostile fixture
(`--case messy`) and the complete refusal matrix are covered by the test
suite.

## Extension points (future phases — do NOT implement now)

- **Edge linear feet / backsplash**: the measured polygons and recorded
  policy are the groundwork; identifying front edge vs wall edge is next.
- **Cutout pricing**: cutouts are already selectable inner loops; pricing is
  out of scope until the profile groundwork activates.
- **Slab yield / seam planning, pricing + QuickBooks, shop drawings**:
  unchanged roadmap; none of it is built here.

## Method & output details

- Measuring method, calibration rules, boundary closure, curve tolerance,
  limitations: `references/method.md`.
- V2 job-spec schema: `references/job-spec-v2.md`.
- Exact output formats (report, CSV, results JSON, exit codes): 
  `references/output-format.md`.
- Company profile (identity groundwork): `references/company-profile.md`.
