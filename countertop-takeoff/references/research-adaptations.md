# Research adaptations: evidence navigation and supplied rates

Reviewed 2026-11-05. Research report: local commit
`4d0087544e0646bed33ff2d04e7d6e64bb642e64`, `takeoff-skills-landscape.md`.
Implementation base includes Dad's merged PR #1 (`5b0f2cfa2e04e73b68f5146e510662ab9d9fdc27`)
and the completed scan helper (`f94563a503677d8e44ad01e8444c0ef3f4c1feeb`).

## Bounded selection

Kept two adaptations, written independently from general ideas in the report:

1. **Detail application and count evidence in the audit index.** Assembly
   room/type/variant/handing, recorded quantity basis, earned EA and its reason,
   piece selections and source/overlay links are visible together. Original
   source hashes, schedule references/crop transforms, room tags, unresolved
   coverage and property completeness remain visible. No room or variant is
   allocated by this view; counts and quantities are read from existing results.
2. **Shop-supplied rate basis.** Optional per-rate `rate_basis` carries source,
   date and quote reference into the selected estimate line and unchanged
   proposal line. Documents show these fields and inclusions. Missing metadata
   stays BLANK. It never selects rates, changes amounts or applies expiry rules.

The application view is an adaptation of the report's template-versus-instance
idea; rate provenance follows the estimating/provenance idea. No third-party
code or instruction text was copied and no external skill runs at runtime.
Deferred: a new sheet/spec discovery index, schedule recognition/parser
dependencies, a new review UI, whole-job automation and recognition tuning.

## Baseline and verification

Before editing, **307 checks passed sequentially**: V2 47, V3 34, V4 40,
V5 125, simplify 37, Dad's output-contract tests 15, scan helper 9.
The baseline audit index lacked assembly application/count navigation and
discarded rate source/date/quote metadata from estimate lines.

`uv run --python 3.13 examples/tests_evidence_views.py` adds **13 tests**:

- Generated three-page, five-room/two-type PDF: prototype EA remain 3 and 2,
  known subtotal remains **168.75 SF**, property gaps remain incomplete, links
  resolve (including spaces/parentheses), and results bytes are unchanged by
  rendering the pack.
- Recorded-data presentation cases: included ADA count, withheld parent EA,
  unknown room variant, handing, excluded/missing pieces, multiple sources,
  stated-property selectors, image overlay/crop transforms and older results
  without structured quantity basis. Unused proposals never become rows.
  These test the view, not new room allocation or recognition.
- Generated hotel results written outside the job directory: schedule crop path
  stays bound to the original job's evidence; source crop hash is unchanged.
  The known subtotal remains **146.98 SF**, distinct from **123.00 SF** in the
  area-resolved assembly subset. Scope/property completeness remain false;
  omitted room 203, missing sheets and the unusable bar remain disclosed.
- Supplied rate, explicit zero, missing rate, ambiguous rates and withheld EA:
  **3 EA x 55.555 = 166.67**; explicit zero stays **0.00**; other amounts and
  grand total stay null. Supplied basis agrees across JSON/Markdown/PDF and
  proposal, profile hashes remain bound, old dates cause no expiry decision,
  and malformed optional metadata refuses in both profile loaders.

Final acceptance: **320 checks passed sequentially** (307 baseline + 13 new),
plus skill validation and `git diff --check`, using CPython 3.13.16. Relevant
document/pack regressions were rerun after the relocation correction. Local
logs and generated examples are under ignored `build/research-adaptation/`;
tests regenerate evidence and do not depend on those files being distributed.

Generated hotel index links were inspected, as were the rendered estimate and
proposal rate sections and linked vector/image overlays. That inspection caught
the relative schedule-crop link when results moved; resolving it at job intake
and testing relocation fixed it. Missing local files are labeled unavailable
instead of presented as working proof links.
The existing many-line estimate regression also caught a wrapped final-total
paragraph continuing onto a page without its heading. The renderer now keeps
paragraphs together when they fit one page. Shared rate provenance is listed
once per identical rate reference; every priced line still retains its own
unchanged metadata and arithmetic in JSON.
The focused regression checks both a wrapped final-total qualification and an
exactly full page, including the absence of a trailing blank page.

## Limits and stopping point

This change preserves the measurement routes, calibration/anchor requirements,
source hashes/transforms, explicit adoption and earned-count rules. It adds
navigation and supplied metadata, not a detector or an approval gate. No new
runtime dependency was added for these adaptations.

The scan experiment remains closed at three candidates. Its frozen generated
workload found 0 missed eligible outlines out of 8, 3 spurious proposals across
the details plus 4 negatives, and signed area differences -0.42% to -2.68%.
See [the existing experiment evidence](scan-detail-experiment.md).

No checked real/customer drawings, blind reading test or timed reviewer trial
were available. Real-plan recognition accuracy and time saved for Dad remain
unverified. Stop here: the selected output contracts pass; wider discovery or
recognition work needs its own bounded assignment and drawing evidence.
