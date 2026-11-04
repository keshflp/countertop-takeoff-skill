# 5.1.0 correctness verification

All fixtures are synthetic. Crop hashes verify pixel identity only; the
operator/agent must independently read the schedule. The hotel generator
supplies known truth, an upright crop, its explicit rotation/scale, and a
cell-box preview. It is not a recognition benchmark.

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

## Receipt/provenance decision

Receipts are separate from results. They hash the exact results file; recording
one never modifies the results that pricing/proposals hash. They are delivered
beside results, never embedded into estimates. The normal operator sequence is
intake -> inventory/evidence -> selections/spec -> measurement -> audit/receipt
-> pricing/proposal -> delivery. No audit approval gate is added; an unavailable
independent audit remains a disclosed condition.
