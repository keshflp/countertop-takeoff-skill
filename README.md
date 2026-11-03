# countertop-takeoff-skill

An agent skill that does **countertop takeoffs** — square feet, edge linear
feet, splash, and cutout counts — from architectural plan/spec PDFs, DXF
exports, and rasters. Built for countertop subcontractors bidding
apartments and hotels.

Give your AI agent a set of plans and it will:

1. **Intake** — collect every file (local paths, chat attachments, Google
   Drive / OneDrive) into one job directory with a manifest: requested vs
   resolved, sizes, SHA-256 hashes, page counts, expected-count verdict.
2. **Preflight the pack** — page inventory with content classes and content
   regions (a pasted bitmap schedule under a vector header is flagged for
   vision reading), duplicate pages, revision conflicts, tolerant sheet
   identity (wrong duplicate title blocks and sheets missing from the
   drawing index become named callouts).
3. **Transcribe schedules with evidence** — text rows quoted with word
   boxes; bitmap schedules read from a hash-verified crop; counts
   cross-validated against plan room tags so invented counts (a schedule
   cell "edited" from 3 to 30) are caught and withheld.
4. **Calibrate per sheet-and-viewport** from TWO agreeing labeled
   dimensions the code measures — never the title block, never typed.
5. **Measure three ways, in order** — vector PDF geometry; supplied DXF
   with verified units (DWG: convert first with the free ODA File
   Converter); calibrated image-space measurement for decent rasters.
6. **Audit and deliver** — coverage ledger reconciling every room/type/
   assembly (measured | package_excluded | superseded | unresolved),
   overlay PNGs, an independent-audit receipt, a PIECE BoQ and an ASSEMBLY
   BoQ from the same records (never summed).

The skill **runs to completion** and reports once at the end. Anything
unresolvable stays **BLANK** (never zero) behind a named CALLOUT; the run
status is `complete`, `complete_with_callouts`, or `stopped` (exit codes
0 / 0 / 2). Exactly three things stop a job: no valid calibration anywhere,
no schedule and no repeatable pattern, or a source-file integrity mismatch.

## Who it's for

- **The countertop subcontractor** who bids multifamily/hospitality jobs
  and today counts square feet by hand from printed plans.
- **Their AI agent** — Codex, Claude Code, Cursor, pi, or any agent that
  can install skills and run shell commands. Harness-agnostic; people are
  referred to neutrally throughout (operator, installer, reviewer).

## Install (Windows, copy-paste)

### Step 1 — install uv (one-time, ~30 seconds)

Open **PowerShell** and run:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://get.uv.dev | iex"
```

Close and reopen PowerShell, then check `uv --version`. No admin rights and
no Python install needed — uv provisions Python for the skill's scripts.

### Step 2 — get the skill folder

```powershell
cd $env:USERPROFILE\Downloads
git clone https://github.com/keshflp/countertop-takeoff-skill.git
```

(No git? Click **Code → Download ZIP** on the GitHub page and unzip.)

### Step 3 — put it where your agent looks

- **Claude Code**: copy the skill into your skills folder:
  ```powershell
  New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
  Copy-Item -Recurse -Force .\countertop-takeoff-skill\countertop-takeoff "$env:USERPROFILE\.claude\skills\countertop-takeoff"
  ```
- **Any other agent**: copy the `countertop-takeoff\` folder into the
  skills directory your agent documents — or skip copying and just tell the
  agent where the folder is.
- **Zero-step option**: tell your agent *"Install the skill from
  github.com/keshflp/countertop-takeoff-skill"* — a good agent will clone
  the repo and follow `SKILL.md` on its own.

## Keep the working machine on (always-on target machine)

The takeoff runs on the machine where the agent desktop app is signed in —
it must stay awake for the whole job. One-time setup on that machine:

1. **Agent desktop app**: install it, sign in, and enable auto-start with
   the session so a job can run unattended.
2. **Settings → Connections → Keep this PC awake** — turn it on while
   working; the app holds the machine awake for running tasks.
3. **Windows power settings** (Settings → System → Power):
   **Sleep: Never** (when plugged in), **Close lid: Do nothing**,
   **Hibernate: off**. A machine that sleeps mid-job stalls the takeoff.
4. **Phone pairing**: in the desktop app, open Connections and pair your
   phone via the QR code. The phone chat app can then launch, steer, and
   approve local agent tasks from the job site.
5. **chatgpt.com in a browser reaches the cloud workspace only** — it
   cannot reach this local machine. Local takeoffs are launched/steered
   from the desktop app or the paired phone.

## Usage

Put the project files anywhere (or drag them into the chat / share a Drive
folder), open your agent, and say:

> Here's a project — do the countertop takeoff. Plans are in
> `C:\Jobs\Riverside\plans\`. I need total SF by unit type and a CSV.

or just:

> Install the skill from github.com/keshflp/countertop-takeoff-skill, then
> do the countertop takeoff on the PDFs in this folder.

The agent runs to completion and reports once: a markdown report (scope
ledger, schedule evidence, calibration spans with actual factors, CALLOUTS,
coverage ledger, both BoQ views), `takeoff.csv` + `pieces.csv` +
`assemblies.csv`, `results.json` (the full evidence package), overlay PNGs,
and the independent-audit receipt.

### Does it actually work?

Yes — on synthetic fixtures with **known** dimensions the pipeline recovers
the areas exactly:

- Clean apartment fixture: **168.75 SF** exact (18.0000 pt/ft from three
  agreeing spans per page).
- Hostile "messy" fixture: **990.00 SF** gross / **936.00 SF** net exact —
  rotated sheet with two viewports at different scales, island + sink loop,
  ADA variant, split/fractional dimension text, a REV B duplicate sheet,
  and a searchable raster scan — plus thirteen refusal/degradation
  mutations verified.
- Hotel fixture (V3): every page rotated 270°, a bitmap room schedule under
  a vector header read via crop-hash evidence, room-tag reconciliation
  (an omitted room is caught as a coverage callout), three viewports with
  three scales on one sheet, a wrong duplicate title block, sheets missing
  from the drawing index, cross-sheet section→length joins, GR guestroom
  FF&E excluded as a package and reported separately, one legible scan
  measured through the image route (~24 SF) and one unusable scan left
  blank — **~147 SF measured** with every deviation disclosed.

Reproduce:

```powershell
cd countertop-takeoff
uv run examples\make_fixture.py --out examples\fixture.pdf
uv run scripts\index_pdf.py examples\fixture.pdf
uv run scripts\extract_geometry.py examples\fixture.pdf --pages all --out build\fixture.geometry.json
uv run scripts\measure.py examples\fixture.jobs.json --report build\report.md --csv build\takeoff.csv --json build\results.json
uv run scripts\audit_pack.py build\results.json --pack build\audit_pack
uv run examples\tests_v2.py     # 47 checks (V2 exactness + behavior)
uv run examples\tests_v3.py     # 34 checks (V3 hotel traps, routes, intake)
```

### Without uv (pip users)

```powershell
py -m pip install -r countertop-takeoff\scripts\requirements.txt
py countertop-takeoff\scripts\index_pdf.py plans.pdf
```

## Legal / data-handling notes

- **Do not auto-scrape planroom websites.** Download plans manually, per
  the planroom vendor's terms of service. The skill contains no scraping.
- **Confidentiality**: plan sets are the client's/GC's property. Measured
  quantities are for your own bid. Both fixtures are 100% synthetic.
- **Verify before you bid.** The skill is a measuring tool with guardrails
  — evidence-backed counts, coverage ledger, CALLOUTS, an independent
  audit — not a stamp.

## Updating

`git pull` inside the cloned repo (or just tell your agent: *"update the
countertop-takeoff skill from GitHub"*).

## Roadmap

| Phase | Scope |
|---|---|
| V1 | Square footage per unit type, schedule multiplication, QA report + CSV |
| V2 | Pack preflight, scope ledger, evidence-backed schedule, per-viewport calibration, selected-boundary measurement, audit pack |
| V3 (this repo) | Multiple sources (PDF/DXF/raster), bitmap-schedule transcription, room-tag reconciliation, graduated degradation with CALLOUTS + coverage ledger, assemblies/pieces with edges/splash/cutouts, dual BoQ views, package rules, intake manifest, hotel-grade field traps |
| V4 | Cutout pricing (sinks, ranges); slab yield and seam planning |
| V5 | Pricing (SF × material price matrix), quotes and QuickBooks invoices |
| V6 | Shop-drawing PDFs generated from the measured polygons |

## Repo layout

```
countertop-takeoff/            <- the skill folder (this is what you install)
  SKILL.md                     <- the V3 workflow your agent follows
  references/job-spec-v3.md    <- the V3 job-spec (evidence document) schema
  references/method.md         <- preflight, calibration, boundaries, audit
  references/output-format.md  <- exact report/CSV/JSON/pack formats
  references/company-profile.md<- profile schema + package defaults
  references/cad-context.md    <- CAD landscape + optional escalations
  scripts/preflight_lib.py     <- shared page stats/fingerprints/classes
  scripts/index_pdf.py         <- pack preflight + page inventory
  scripts/extract_geometry.py  <- id'd, rotation-aware vectors
  scripts/cad_input.py         <- DXF adapter (verified units; DWG=convert)
  scripts/image_measure.py     <- calibrated image-space route
  scripts/intake.py            <- step 0: job dir + intake manifest
  scripts/measure.py           <- the V3 measurement pipeline
  scripts/spec_schema.py       <- job-spec validation (v2 + v3)
  scripts/calibrate.py         <- per-viewport span calibration
  scripts/regions.py           <- boundary closure + measurement
  scripts/sheet_identity.py    <- tolerant sheet identity
  scripts/audit.py             <- completeness/reconciliation/BoQ audit
  scripts/report_out.py        <- report/CSV/evidence-JSON writers
  scripts/audit_pack.py        <- overlay PNGs + audit receipt
  scripts/requirements.txt     <- pinned: pymupdf, shapely, ezdxf
  examples/make_fixture.py     <- fixtures (--case original|messy|hotel)
  examples/make_hotel_jobs.py  <- canonical V3 hotel job-spec builder
  examples/tests_v2.py         <- V2 acceptance suite (47 checks)
  examples/tests_v3.py         <- V3 acceptance suite (34 checks)
README.md                      <- this file
LICENSE                        <- MIT
```

MIT licensed. No client data leaves the machine, no planroom scraping, no
guessed scales.
