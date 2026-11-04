# 5.1.0 correctness verification

Synthetic fixtures verify known geometry, not recognition on production plans.
Crop hashes prove pixel identity; schedule reading still needs independent checks.

## Deliberately superseded V5 checks

- Duplicate piece: V5 retained per-instance SF while blanking only extended
  SF. The replacement requires blank SF, extended SF, extended edge LF and
  cutout counts, plus withheld assembly EA. Declared reuse still extends.
- Estimate PDF: the one-assembly fixture omits measured vanity scope. Its
  old nonblank-grand-total assertion was incorrect. The replacement checks
  every priced line and the correctly blank grand total; pricing survives.

- V2 receipt check now reads `RESULTS.receipt.json` and asserts results bytes
  remain unchanged. V5 sibling detection now creates the real quarantine
  name `results.json.stale-*` and reads the sidecar. These replace inline
  receipt mutation and the incorrectly named synthetic stale sibling.

- V4 PDF and V5 PDF title/blank checks now expect rendered plain text:
  `Countertop Estimate` and `BLANK`; Markdown still carries its formatting.
- V5 priced-proposal checks now use a fully covered original fixture with
  both kitchen and vanity pieces. Previously they erased hotel omissions
  and fabricated a grand total. The same total/package assertions remain.

No V3 checks are superseded. No check is skipped.
SIMPLIFY round 2 migrates V3's sparse intake setup to structured `--entry`:
the ambiguous legacy invocation now refuses; its assertions/counts are unchanged.

## Test evidence

V2/V3/V4/V5 passed 47/34/40/125 checks (246 total): the original 194, with
the replacements above, plus 52. V5 runs `tests_v51.py` (evidence, membership,
omissions, publishing, receipts, docs) and `tests_v51_documents.py` (exact
pricing, provenance, PDF amounts/identifiers). The upright cell preview was
also visually inspected. Commands: [README verification](../../README.md#verification).

Version 5.1.0 retains v3-results/v5-pricing schema tags. Separate receipts and
the artifact-manifest sidecar are documented in [output contracts](output-format.md).
