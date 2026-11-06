# Kitchen countertop takeoff

Rishi: Dad confirms a kitchen sketch readback; the program proposes seams, checks the documented product rules and nests connected pieces on slabs. It computes gross SF, material markup and separate labor. Missing product facts leave a partial result; conditional layouts keep outstanding requirements visible. Explicitly authorized estimates stay preliminary. Results name the assessed scope; handling is not evaluated. ChatGPT makes the invoice PDF from `quote.json` with the same labels and blanks.

## Laptop setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and [Bun](https://bun.sh/docs/installation), one PowerShell line each, then reopen PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
powershell -c "irm bun.sh/install.ps1 | iex"
```

Clone this repo or download its ZIP. Copy the whole `countertop-takeoff/` folder to `%USERPROFILE%\.agents\skills\countertop-takeoff\`, the [Codex user skills location](https://developers.openai.com/codex/skills). The committed CLI bundle needs no `bun install`; uv handles Python and kernel dependencies. Preflight checks the laptop and input files before every run.

To update, run `git pull --ff-only` in the clone (or download a fresh ZIP), then replace the installed skill folder with the updated `countertop-takeoff/` folder. The installed copy does not update itself.

Keep private jobs in `%USERPROFILE%\takeoff-private\<job>\`, outside the skill and repository. Sketches, rendered pages, `job.json`, `quote.json` and pictures stay there. Real sketches and evaluation cases never belong in this public repo. See the [workflow](countertop-takeoff/SKILL.md).

## Evaluate

For evaluator development, run `bun install --cwd countertop-takeoff/cli` once. From the repo root, run the public synthetic source-rule workload:

```powershell
uv run evals/kitchen/eval.py
```

Pass `--cases C:\Users\<user>\takeoff-private\<cases>` for private cases. The evaluator independently checks polygons, source predicates/evidence, conditions, quantities, prices and blanks. It reports assessment counts and scored slab results separately. The frozen historical geometry/pricing workload uses the developer-only `--geometry-replay` flag; its score is separate and provides no source-rule assessment. See [evaluator details](evals/kitchen/README.md). Dad uses the bundled CLI and v2 [job format](countertop-takeoff/references/job-format.md).

[Parked ideas](IDEAS.md) enter the skill when a real job needs them. The tag `baseline-2026-11-06` preserves the removed multi-family pipeline. [MIT license](countertop-takeoff/LICENSE).
