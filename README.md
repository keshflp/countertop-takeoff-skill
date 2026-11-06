# Kitchen countertop takeoff

Rishi: this skill replaces the kitchen sketch handoff to the contractor. Dad confirms a picture of the counter, then gets total SF, slab count, a slab layout and invoice lines. The CLI computes quantities and prices, applying Dad's supplied markup to purchased material and adding labor separately; unanswered inputs stay blank. Explicitly authorized cutout estimates stay labeled preliminary, and requested equal-half joins through centered openings are recorded explicitly. ChatGPT makes the invoice PDF from `quote.json`.

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

For evaluator development, run `bun install --cwd countertop-takeoff/cli` once. From the repo root, run the public synthetic cases:

```powershell
uv run evals/kitchen/eval.py --layout-cmd "uv run countertop-takeoff/kernels/layout.py" --quote-cmd "bun countertop-takeoff/cli/src/eval.ts"
```

Pass `--cases C:\Users\<user>\takeoff-private\<cases>` for private cases. The evaluator checks quantities, slab placement and seams, pricing, and blanks, then reports excess slabs against the case optimum. Dad runs the bundled CLI.

[Parked ideas](IDEAS.md) enter the skill when a real job needs them. The tag `baseline-2026-11-06` preserves the removed multi-family pipeline. [MIT license](countertop-takeoff/LICENSE).
