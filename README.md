# countertop-takeoff-skill

Version **5.1.0**. An agent skill for countertop takeoffs from architectural
PDFs, DXF exports, and rasters: square feet, edge feet, splash, and cutouts.
Built for subcontractors bidding apartments and hotels; harness-agnostic.

The agent inventories inputs, reads schedules with evidence, reconciles room
tags, calibrates each viewport, measures, audits, and delivers once at the end.
Unresolvable quantities stay **BLANK**, never zero, behind named CALLOUTS.
Run status: `complete`, `complete_with_callouts`, or `stopped` (exit 0/0/2).

Exactly three kinds of DATA failure stop a job: no valid calibration anywhere
(verified CAD units qualify), no schedule and no repeatable pattern, or a
source-file integrity mismatch. Malformed job specs refuse before measurement:
that is spec validation, not a fourth takeoff stop.

## Quick start (Windows PowerShell)

Install uv once, then reopen PowerShell and check `uv --version`:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://get.uv.dev | iex"
```

No admin rights or system Python needed; uv provisions Python and script deps.
Clone the repository (or use GitHub's **Code > Download ZIP**):

```powershell
cd $env:USERPROFILE\Downloads
git clone https://github.com/keshflp/countertop-takeoff-skill.git
cd countertop-takeoff-skill
```

Tell your agent where `countertop-takeoff/SKILL.md` is, or copy the skill
folder to the skills directory its documentation specifies. For Claude Code,
run from the repository root:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
Copy-Item -Recurse -Force .\countertop-takeoff "$env:USERPROFILE\.claude\skills\countertop-takeoff"
```

Then ask: "Do the countertop takeoff on `C:\Jobs\Riverside\plans`.
I need total SF by unit type and CSVs." The agent follows the
[workflow](countertop-takeoff/SKILL.md); commands run from the skill folder.

## Host matrix

| Interface | Where the job runs | Setup |
|---|---|---|
| Desktop app | Local machine with access to the plans | Sign in, enable session auto-start, keep host awake (Sleep Never when plugged in) |
| Phone | Paired desktop host | Pair using the host app's remote QR code; phone steers, desktop runs |
| Web chat | Cloud workspace | Transfer plans, skill folder, and profile into that workspace first |
| CLI | Local machine | Agent CLI + PowerShell + uv; keep host awake |

A cloud workspace cannot see local files or profiles automatically.

## Intake and delivery

Supply local paths, chat attachments, or Drive/OneDrive files fetched by your
agent. The scripts import local files; the agent fetches cloud binaries first.
Intake records requested/resolved files, sizes, hashes, page counts, and the
expected-count verdict in one job directory. Unavailable inputs get callouts.

Routes, in order: selected vector PDF boundaries; supplied DXF with verified
units (convert DWG first); calibrated image measurement for legible rasters.
Schedule counts need word-box or crop/cell evidence plus plan-tag reconciliation.

Delivery includes a report, `takeoff.csv`, `pieces.csv`, `assemblies.csv`,
`results.json`, overlay PNGs, and an independent-audit receipt (or disclosed
unavailability). A rate profile adds `estimate.md/.json/.pdf`; a quote request
adds proposal-lite documents. See [output formats](countertop-takeoff/references/output-format.md)
and the [rate-profile example](countertop-takeoff/examples/example.rate-profile.json).

The run asserts, for jobs that declare assemblies, that both BoQs reconcile over the
same fully resolved subset; project/report/CSV show the full known piece
subtotal, including valid parts of incomplete assemblies. The hotel fixture
has **123.00 SF** in the resolved subset and **146.98 SF** full known subtotal.
Omissions keep completeness false and the pricing grand total blank.

## Updating

- **Cloned repo (recommended):** run `git pull --ff-only` in the clone.
  If it refuses, preserve local edits on their own branch before updating.
- **Separately-copied skill folder:** a copy does NOT update itself.
  Update/re-download the repo, then re-copy `countertop-takeoff/` into the
  agent's skills directory, preserving any local edits separately.

## Organization transfer

Transfer the repository on GitHub, then publish the new clone URL and update
existing remotes. From the repo root, substitute the actual organization URL:

```powershell
$repoUrl = 'https://github.com/YOUR-ORG/countertop-takeoff-skill.git'
$readmePath = Join-Path (Get-Location) 'README.md'
$readmeText = [IO.File]::ReadAllText($readmePath)
[IO.File]::WriteAllText($readmePath, $readmeText.Replace('https://github.com/keshflp/countertop-takeoff-skill.git', $repoUrl), [Text.UTF8Encoding]::new($false))
git remote set-url origin $repoUrl
Push-Location countertop-takeoff
uv run examples/tests_v5.py
Pop-Location
git add README.md
git commit -m "docs: publish organization clone URL"
git push origin main
```

Existing clones then use `git pull --ff-only`; separately installed copies
still need re-copying. Any published GitHub owner/org URL is supported.

## Verification

Run from `countertop-takeoff/` (sequentially; suites share fixture paths):

```powershell
uv run examples/make_fixture.py --out examples/fixture.pdf
uv run scripts/index_pdf.py examples/fixture.pdf
uv run scripts/extract_geometry.py examples/fixture.pdf --pages all --out build/fixture.geometry.json
uv run scripts/measure.py examples/fixture.jobs.json --report build/report.md --csv build/takeoff.csv --json build/results.json
uv run scripts/audit_pack.py build/results.json --pack build/audit_pack
uv run examples/tests_v2.py     # 47 checks
uv run examples/tests_v3.py     # 34 checks
uv run examples/tests_v4.py     # 40 checks
uv run examples/tests_v5.py     # 125 checks, including 5.1 regressions
```

The [example walkthrough](countertop-takeoff/examples/run_example.md) describes
synthetic fixtures. They verify known geometry and failure handling; they do
not prove recognition on an unseen job. Use the [first-run checklist](countertop-takeoff/references/first-run-checklist.md)
for supervised validation and a drawings-only blind exercise.

## Limits and legal notes

- No guessed scales or counts. Unusable geometry/evidence withholds affected
  fields; supported routes and evidence requirements are in the [method](countertop-takeoff/references/method.md)
  and [job-spec contract](countertop-takeoff/references/job-spec-v3.md).
- Proposal-lite is a quote document. Official invoices, payments, tax/progress
  billing, shop drawings, slab nesting/yield, and hosted integrations are out
  of scope. V6 drawing outputs are **Exploratory** only, **not promised**.
- [QuickBooks mapping](countertop-takeoff/references/quickbooks-mapping.md) is
  CSV groundwork requiring a real account sample, with no API/OAuth/sync.
- Do not auto-scrape planrooms; download manually under the vendor's terms.
- Plans belong to the client/GC. Scripts keep files on the execution host,
  but agent vision may send crops/quotes to its model provider. Check that
  provider's data terms before using confidential drawings.
- Verify before bidding: evidence, callouts, coverage, and independent audit
  assist judgment; this tool is not a stamp. Fixtures are entirely synthetic.

[5.1.0 release details](countertop-takeoff/references/release-5.1.0.md) document
correctness fixes and probe coverage. MIT licensed; see [LICENSE](LICENSE).
