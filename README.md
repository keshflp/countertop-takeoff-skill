# countertop-takeoff-skill

An agent skill that does **countertop square-footage takeoffs** from
architectural plan/spec PDFs — built for countertop subcontractors bidding
apartments and hotels.

Give your AI agent a set of plan PDFs and it will:

1. **Index the set** — find the unit schedule (Type A ×24, Type B ×12 …), the
   floor plans, and every page that mentions countertops.
2. **Calibrate the scale** — recover pt→feet from labeled dimensions on the
   same sheet (never from the title block, never guessed).
3. **Measure one unit per type from the vector linework** — exact polygon
   areas computed by code, not eyeballed from images.
4. **Spot-check and hunt exceptions** — corner units, ADA units, mirrored
   units, amenity spaces.
5. **Pause for your approval** before measuring (you confirm the schedule
   counts it read).
6. **Multiply by the schedule** and deliver a cited report + CSV with a
   self-audit: every number traces to a sheet and page.

V1 scope is **square footage only**. Edge linear feet, backsplash, cutouts,
slab yield, pricing, and QuickBooks invoices are planned phases (see
[Roadmap](#roadmap)).

## Who it's for

- **The countertop subcontractor** ("dad") who bids multifamily/hospitality
  jobs and today counts SF by hand from printed plans.
- **His AI agent** — Claude Code, Codex/Cursor, pi, or any agent that can
  install skills and run shell commands. The skill is harness-agnostic: it's
  a folder of markdown instructions + small Python scripts.

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

The agent will index the set, show you the unit schedule it found **and wait
for your OK**, then measure and deliver:

- a markdown report: calibration table, per-type takeoff, totals, QA table,
  self-audit — every number cited to sheet + page;
- `takeoff.csv`: one row per measured region, with schedule counts and
  extended SF.

### Does it actually work?

Yes — on a synthetic fixture with **known** dimensions, the pipeline recovers
the areas exactly: Type A 38.25 SF ×3 + Type B 27.00 SF ×2 = **168.75 SF**,
calibration 18.0000 pt/ft from six labels, self-audit PASS. See
[`countertop-takeoff/examples/run_example.md`](countertop-takeoff/examples/run_example.md)
for the full verified run. You can reproduce it yourself:

```powershell
cd countertop-takeoff
uv run examples/make_fixture.py --out build\smoke.pdf
uv run scripts\index_pdf.py build\smoke.pdf
uv run scripts\extract_geometry.py build\smoke.pdf --pages 2,3 --out build\smoke.geometry.json
uv run scripts\measure.py examples\fixture.jobs.json --report build\report.md --csv build\takeoff.csv
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
  don't respect that. The example fixture in this repo is 100% synthetic.
- **Verify before you bid.** The skill is a measuring tool with guardrails
  (calibration, spot-checks, self-audit), not a stamp. The check-in gate
  exists so YOU confirm the schedule counts before anything is multiplied.

## Roadmap

| Phase | Scope |
|---|---|
| V1 (this repo) | Square footage per unit type, schedule multiplication, QA report + CSV |
| V2 | Edge linear feet (front edge vs wall edge), backsplash SF |
| V3 | Cutouts (sinks, ranges) subtracted; island/return handling |
| V4 | Slab yield and seam planning against standard slab sizes |
| V5 | Pricing (SF × material price matrix), quotes and QuickBooks invoices |
| V6 | Shop-drawing PDFs generated from the measured polygons |

## Repo layout

```
countertop-takeoff/          <- the skill folder (this is what you install)
  SKILL.md                   <- the workflow your agent follows
  references/method.md       <- measuring method (calibration, polygons, exceptions)
  references/output-format.md<- exact report/CSV/JSON formats
  scripts/index_pdf.py       <- step 1: page inventory
  scripts/extract_geometry.py<- step 2: vector line/curve extraction
  scripts/measure.py         <- step 3: calibration + areas + multiplication
  scripts/requirements.txt   <- pymupdf, shapely
  examples/make_fixture.py   <- synthetic plan generator with KNOWN areas
  examples/fixture.pdf       <- the generated fixture
  examples/fixture.jobs.json <- example job spec for measure.py
  examples/run_example.md    <- verified end-to-end run (168.75 SF exact)
README.md                    <- this file
LICENSE                      <- MIT
```

MIT licensed. No client data, no planroom scraping, no guessing scales.
