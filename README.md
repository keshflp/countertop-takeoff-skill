# countertop-takeoff-skill

An agent skill that does **countertop square-footage takeoffs** from
architectural plan/spec PDFs — built for countertop subcontractors bidding
apartments and hotels.

Give your AI agent a set of plan PDFs and it will:

1. **Preflight the pack** — page inventory with content classes (vector /
   searchable raster / hybrid), rotation and crop metadata, duplicate-page
   and revision-conflict detection, and a source SHA-256.
2. **Plan the scope and schedule with you** — every page dispositioned
   (measured / intentionally skipped with a reason / blocked), schedule
   counts quoted from the schedule text with recorded evidence, ADA-style
   variants handled without double-counting — and **wait for your approval**
   before touching geometry.
3. **Calibrate per sheet-and-viewport** from TWO agreeing labeled dimensions
   whose lengths the code computes (split and fractional labels included) —
   never from the title block, never typed by the agent.
4. **Measure agent-selected boundary segments** — exact polygon areas that
   must close into one loop, with strict seed placement, explicit gross/net
   cutout policy, and duplicate/overlap refusals.
5. **Audit completeness** — planned regions vs completed results, floor and
   project total reconciliation, per-region sanity ranges, QA rechecks.
6. **Render overlay evidence and get an independent audit** — full-page +
   close-up PNGs with the measured shells, then a fresh agent (or recorded
   human review) must approve before exports are delivered.

V2 scope is **square footage only** (assembly/material identity is recorded
groundwork). Edge linear feet, backsplash, cutout pricing, slab yield,
pricing, and QuickBooks invoices are planned phases (see
[Roadmap](#roadmap)).

## What V2 changes over V1

V1 could produce a correct-looking total that accompanied missing scope,
duplicated regions, or a mis-calibrated scale. V2 makes all of it auditable:

| V1 problem | V2 fix |
|---|---|
| Text presence implied measurability | Pack preflight classes pages; raster/hybrid pages cannot be measured, only skipped/blocked with reasons |
| Deleting all Type B jobs still passed | Scope ledger: every page dispositioned; planned vs completed regions compared exactly |
| Missing counts silently defaulted to 1 | Counts are required, integer, evidence-backed; missing = hard fail |
| One dimension label could calibrate (wrong segment → 36 pt/ft, zero spread) | Two+ agreeing spans per (page, viewport); wrong picks refuse on spread; the actual per-region factor is reported |
| bbox + smallest-face guessing; crashed on unclosed loops | Agent-selected boundary segment ids must close into exactly one cycle; refusals name the offending coordinates |
| Duplicated region passed at 208.75 SF | Overlap/duplicate checks within counted instances fail the run |
| CSV totaled 567.00 SF for a 168.75 SF job | CSV is base rows + rechecks (never extended) + one totals row per type |
| PASS with warnings | `ready / warning / failed` states, independent-review status, exports gated on required checks |
| Rotation ignored in overlays | Extraction is displayed-space; overlays align pixel-exact |
| "Well under a square inch" curve claim | Real tolerance stated (≈0.18 SF at 3-ft radius); curved boundaries flagged |

## Who it's for

- **The countertop subcontractor** who bids multifamily/hospitality jobs and
  today counts SF by hand from printed plans.
- **Their AI agent** — Claude Code, Codex/Cursor, pi, or any agent that can
  install skills and run shell commands. The skill is harness-agnostic.

## Install (Windows, copy-paste)

### Step 1 — install uv (one-time, ~30 seconds)

Open **PowerShell** and run:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://get.uv.dev | iex"
```

Close and reopen PowerShell. Check it worked:

```powershell
uv --version
```

(No admin rights needed. `uv` automatically provides Python for the skill's
scripts — you do NOT need to install Python itself.)

### Step 2 — get the skill folder

In PowerShell:

```powershell
cd $env:USERPROFILE\Downloads
git clone https://github.com/keshflp/countertop-takeoff-skill.git
```

(If you don't have git, click **Code → Download ZIP** on the GitHub page and
unzip it instead.)

### Step 3 — put it where your agent looks

- **Claude Code**: copy the skill into your skills folder:
  ```powershell
  New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
  Copy-Item -Recurse -Force .\countertop-takeoff-skill\countertop-takeoff "$env:USERPROFILE\.claude\skills\countertop-takeoff"
  ```
- **Any other agent (Codex, Cursor, pi, …)**: copy the
  `countertop-takeoff\` folder into the equivalent skills directory your
  agent documents — **or skip copying entirely** and just tell the agent
  where the folder is.
- **The zero-step option**: tell your agent
  *"Install the skill from github.com/keshflp/countertop-takeoff-skill"* —
  a good agent will clone the repo and follow `SKILL.md` on its own.


## Usage

Put the project PDFs in a folder, open your agent there, and say:

> Here's a project — do the countertop takeoff.
> Plans are in `C:\Users\dad\Jobs\Riverside\plans\`. I need total SF by unit
> type and a CSV.

or just:

> Install the skill from github.com/keshflp/countertop-takeoff-skill, then do
> the countertop takeoff on the PDFs in this folder.

The agent will preflight the pack, show you the schedule it found **and wait
for your OK** on the scope + counts, then measure, render overlays, and get
an independent audit before delivering:

- a markdown report: scope ledger, schedule evidence, calibration spans with
  the actual factors, per-region takeoff, audit checklist, review status;
- `takeoff.csv`: base measurement rows (rechecks separate), one totals row
  per type, grand total;
- `results.json`: the full evidence package (polygons, segment ids, source
  hashes, runtime versions);
- an audit pack of PNG overlays plus the recorded independent-audit receipt.

### Does it actually work?

Yes — on a synthetic fixture with **known** dimensions, the pipeline recovers
the areas exactly: Type A 38.25 SF ×3 + Type B 27.00 SF ×2 = **168.75 SF**,
calibration 18.0000 pt/ft from three agreeing spans per page, self-audit
READY. See
[`countertop-takeoff/examples/run_example.md`](countertop-takeoff/examples/run_example.md).
A second, deliberately **messy** fixture (rotated sheet with two viewports at
different scales, an island with a sink loop, an ADA variant, a peninsula,
split/fractional dimension text, a REV B duplicate sheet, and a searchable
raster scan) is recovered at exactly **990.00 SF**, and thirteen hostile
mutations are verified to **refuse** with specific reasons. Reproduce:

```powershell
cd countertop-takeoff
uv run examples\make_fixture.py --out examples\fixture.pdf
uv run scripts\index_pdf.py examples\fixture.pdf
uv run scripts\extract_geometry.py examples\fixture.pdf --pages all --out build\fixture.geometry.json
uv run scripts\measure.py examples\fixture.jobs.json --report build\report.md --csv build\takeoff.csv --json build\results.json
uv run scripts\audit_pack.py build\results.json --pack build\audit_pack
uv run examples\tests_v2.py     # 47 checks: exact numbers + refusal matrix
```

### Without uv (pip users)

```powershell
py -m pip install -r countertop-takeoff\scripts\requirements.txt
py countertop-takeoff\scripts\index_pdf.py plans.pdf
```

## Legal / data-handling notes

- **Do not auto-scrape planroom websites.** Download plans manually, per the
  planroom vendor's terms of service. The skill deliberately contains no
  web-scraping.
- **Confidentiality**: plan sets are the client's/GC's property. Measured
  quantities are for your own bid. Don't upload plan PDFs to services that
  don't respect that. Both fixtures in this repo are 100% synthetic.
- **Verify before you bid.** The skill is a measuring tool with guardrails —
  approval gates, scope ledger, evidence-backed counts, an independent audit
  — not a stamp. The independent review exists so YOU (or a fresh agent you
  direct) confirm the work before anything ships.

## Roadmap

| Phase | Scope |
|---|---|
| V1 | Square footage per unit type, schedule multiplication, QA report + CSV |
| V2 (this repo) | Pack preflight, approved scope + completeness ledger, evidence-backed schedule, per-viewport two-span calibration, selected-boundary measurement, safe exports, audit pack + independent audit, company-profile groundwork |
| V3 | Edge linear feet (front edge vs wall edge), backsplash SF |
| V4 | Cutout pricing (sinks, ranges); slab yield and seam planning |
| V5 | Pricing (SF × material price matrix), quotes and QuickBooks invoices |
| V6 | Shop-drawing PDFs generated from the measured polygons |

## Repo layout

```
countertop-takeoff/            <- the skill folder (this is what you install)
  SKILL.md                     <- the V2 workflow your agent follows
  references/job-spec-v2.md    <- the V2 job-spec (evidence document) schema
  references/method.md         <- preflight, calibration, boundaries, audit
  references/output-format.md  <- exact report/CSV/JSON/pack formats
  references/company-profile.md<- profile schema (identity groundwork)
  scripts/preflight_lib.py     <- shared page stats/fingerprints/classes
  scripts/index_pdf.py         <- step 1: pack preflight + page inventory
  scripts/extract_geometry.py  <- step 2: id'd, rotation-aware vectors
  scripts/measure.py           <- step 3: the V2 measurement pipeline
  scripts/spec_schema.py       <- job-spec validation
  scripts/calibrate.py         <- per-viewport span calibration
  scripts/regions.py           <- boundary closure + measurement
  scripts/audit.py             <- scope/schedule completeness + reconciliation
  scripts/report_out.py        <- report/CSV/evidence-JSON writers
  scripts/audit_pack.py        <- overlay PNGs + independent-audit receipt
  scripts/requirements.txt     <- pinned: pymupdf==2.1, shapely==2.2.0
  examples/make_fixture.py     <- fixture generator (--case original|messy)
  examples/messy_fixture.py    <- the hostile fixture builder
  examples/fixture.jobs.json   <- example V2 job spec (clean fixture)
  examples/messy.jobs.json     <- example V2 job spec (messy fixture)
  examples/example.profile.json<- example company profile
  examples/tests_v2.py         <- acceptance suite (47 checks)
  examples/run_example.md      <- verified end-to-end run (168.75 SF exact)
README.md                      <- this file
LICENSE                        <- MIT
```

MIT licensed. No client data, no planroom scraping, no guessing scales.
