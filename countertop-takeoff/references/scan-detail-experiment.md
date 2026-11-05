# Selected scan-detail experiment

2026-11-04; base `4f7e0fd4db0d652057fa3cc3f51c874acb380863`.
Objective: clean selected scan crops and offer useful outlines for inspection
using free local tools. Three tested candidates total; stopped at that cap.
Kept candidate 3. No whole-plan recognition or automatic adoption was added.

## Workload and evaluator

`examples/evaluate_scan_detail.py` prepares twelve 800 x 520 PNG crops from a
generated scanned PDF, with two distinct visible labeled dimensions on eight
eligible details. Cases: rectangle, L, notch, speckle, two lighting gradients,
3-degree skew, nested cabinet/sink distractions; negatives: broken shell,
no shell, unreadable downsampled scan, cabinet-only without dimensions.
PyMuPDF draws the reference strokes; OpenCV never receives truth geometry.
Seed 20261104. The workload and evaluator were frozen before candidate 1.

A suggestion matches at intersection-over-union >=0.90. A missed outline is
an eligible detail without a match; spurious means every unmatched proposal,
including all proposals on negative cases. Only one proposal can match each
detail. This is a generated-workload matching rule, not a universal field
accuracy threshold. Report signed polygon-area difference, Hausdorff boundary
distance in original pixels, and coordinate-mapping discrepancy separately.
Cleanup metrics are retained dark reference pixels and residual background
darkness outside a seven-pixel neighborhood of reference ink. Neither proves
OCR readability or an unfamiliar plan's accuracy.

Baseline: existing scripts produce no automatic outlines or cleaned images.
Its eight missing suggestions are NOT eight failed manual measurements.
With exact oracle points/anchors, the existing arithmetic remains accurate;
the new tests check that separately. There was no blind agent/human reading
trial, checked real takeoff, or real-plan validation in this experiment.

## Candidates and decisions

| Version | Missing / 8 | Spurious | Boundary error on matches | Signed area difference on matches | Decision |
|---|---:|---:|---|---|---|
| Baseline (no suggestions) | 8 | 0 | unavailable | unavailable | Reference |
| 1: Otsu threshold + enclosed contours | 2 | 6 | 2.24-2.97 px | -2.41% to -1.29% | Reject: shadows became foreground; both gradient outlines missed |
| 2: local threshold + removal of <=2-pixel specks | 0 | 3 | 2.24-3.11 px | -2.68% to -1.74% | Superseded by 3 |
| 3: paired inner/outer stroke corner midpoints | 0 | 3 | 1.12-3.11 px | -2.68% to -0.42% | Keep after correctness gates |

Candidate 3 falls back to the enclosed inner face when corner counts differ
or corresponding corners are over six pixels apart; it does not extrapolate
missing edges. Speckle and skew retain candidate 2 geometry. The exact
per-case measurements and hashes are in
[`examples/scan_detail_evidence.json`](../examples/scan_detail_evidence.json).
All candidates reused identical crops, references, and evaluator settings.
Final correctness hardening changed path-alias rejection and provenance
validation, with identical final outline and cleanup metrics.

Final cleanup: both gradients' residual background darkness fell from
36.62%/36.55% to zero; speckle fell from 0.6038% to 0.0023%. All dark reference
pixels were retained on the eight eligible cases. The unreadable negative
retains only 23.27% of reference ink after cleanup: cleaning did NOT recover
readable dimensions. It produces no outline; that says nothing about every
other blurry scan. Inspected actual gradient cleanup, skew, notch, unreadable,
and nested-distraction overlays during the experiment.

False-positive boundary: a sink rim, the enclosing cabinet border, and the
cabinet-only rectangle are still proposed. Closed geometry cannot identify
the object. On this workload the broken, absent, and unreadable shells yield
no suggestions. Other small, curved (>12 vertices), faint, touching, cropped,
or heavily hatched outlines can be missed. No global threshold establishes
whether an image is adequate. Agent inspection of original pixels is required.

At the generated 40 px/ft scale, final rectangle area is 29.7442 SF versus
30.0000 SF truth (-0.2558 SF); skew is 29.1969 SF (-0.8031 SF). These are
selection/geometry differences, not arithmetic errors or acceptable bidding
tolerances. Inspect/edit points and perform independent rechecks as usual.

## Correctness and reproduction

Original hashes unchanged, pixel dimensions unchanged, cleanup mapping is
identity. All tested points and crop corners map back with zero discrepancy;
the separate zoom-1.5 test checks against the PDF render and existing
crop-to-page conversion. Fractional pixel origins refuse because the current
measurement route assumes bbox-origin mapping. No raster deskew/resizing or
gap repair is performed. Provenance is declared, never falsely marked verified.

No quantities or job status exist in suggestion artifacts. All twelve raw
suggestion artifacts are rejected by the existing measurement loader. Explicit
test-only oracle adoption exercises the existing image route; duplicate
anchors, wrong source/page, edited result, wrong hash, and missing overlay
still withhold area. Full acceptance preserves counts, nulls, known subtotals,
repeated-type/exception handling, scope completeness, and pricing behavior.

Validation: V2 47, V3 34, V4 40, V5 125, simplify 37 = **283 passed**, run
sequentially. **9 new scan contract tests passed**; helper CLI and skill
validation passed. Acceptance used CPython 3.13.16. An initial Python 3.11 run
stopped on pre-existing multiline f-string syntax in `audit.py` before tests;
no unrelated compatibility edits were made. Candidate comparisons used
CPython 3.11.17, OpenCV 4.12.0 (package 4.12.0.88), NumPy 2.2.6, PyMuPDF 2.1,
Shapely 2.2.0. Both new scripts/tests also passed with Python 3.13.

From `countertop-takeoff/`, on a fresh generated-artifact directory:

```powershell
uv run --python 3.13 examples/evaluate_scan_detail.py --prepare --baseline --tag baseline
uv run --python 3.13 examples/evaluate_scan_detail.py --tag final
uv run --python 3.13 examples/tests_scan_detail.py
```

Run the README acceptance commands sequentially with Python 3.13. `build/`
is ignored; crops, overlays, snapshots of rejected candidates and logs remain
local in `build/scan-detail/`, never presumed present in a fresh checkout.
PDF internal IDs can change on regeneration; compare within one prepared
workload, whose source/crop/reference bytes are hashed before every evaluation.
Tracked scripts regenerate the workload and final results; the JSON evidence
preserves the original baseline/candidate/final measurements for review.

No real/customer plans were supplied or acquired. Real-plan verification
remains a separate subsequent pass when drawings and checked answers exist.
