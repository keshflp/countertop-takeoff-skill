# First-run supervision checklist

Use this checklist to review the completed job and prepare the first production
run. The agent runs to completion, reports once, and adds no approval gates.
Use synthetic drawings for the exercise below; never commit customer plans.

## Operator checks

- **Intake:** requested files match the manifest. Unavailable inputs and missing
  indexed sheets have named scope callouts; quantities are blank, never zero.
- **Schedule:** verify headers against the upright crop, floor totals, project
  totals, explicit zeros, and whether ADA counts are included in the parent.
  Sum floor count cells once; do not add the total row again. Uncertain or
  unsupported type/variant cells withhold their counts and dependent standard
  allocations, with `unresolved` ledger entries.
- **Rooms:** independently inventory room tags. Deduplicate rooms across plan,
  enlargement, elevation and section views; a room is not an extra assembly
  just because it appears twice. Explain every schedule/tag discrepancy.
- **Shells are countertops:** inspect the highlighted polygons against the raw
  sheet. A closed shell might be a wall, cabinet, room, sink or hatch boundary.
  Verify counter extents, gross/net policy, holes, split segments and reuse.
- **Calibration:** anchors belong to the right source/page/viewport and match
  labeled dimensions. Two agreeing spans must independently support the scale;
  a nearby detail at another scale cannot calibrate the selected counter.
- **Identity:** piece and assembly membership is reciprocal. Identity conflicts
  blank SF, extended edge LF, cutouts and assembly pricing. Declared geometric
  reuse is explicit; ordinary missing geometry still permits valid EA pricing.
- **Omissions travel:** follow each omission through report -> estimate ->
  proposal. Check regions without assemblies, uncovered rooms, unavailable
  sources, and every unresolved ledger entry. Preserve known SF/priced
  subtotals; blank the grand total and prohibit "fully priced" package claims.
- **Totals:** compare the same fully resolved assembly subset across BoQ views.
  Compare the full known piece subtotal separately with project/report/CSV.
  The hotel case has 123.00 SF in the resolved subset and 146.98 SF in the full
  known subtotal; their different scopes must remain visible.
- **Receipt/hash consistency:** `results.json.receipt.json` hashes the exact
  immutable results bytes. Compare with `Get-FileHash -Algorithm SHA256`.
  Estimate/proposal results hashes must match those bytes. Check the estimate's
  rate-profile hash, proposal's estimate hash, and receipt's superseded siblings.
  `{}` or stopped results cannot receive a receipt. Re-measure after repairs.
- **Output paths:** inputs and outputs are distinct even after resolving case,
  symlinks and dot segments. Check JSON/MD/PDF/CSV filenames and delivery paths.
  Preserve `results.json.artifacts.json` so a stopped rerun can quarantine all
  dependent documents, including proposals stored in another output directory.
- **Documents:** project total appears once with its qualification. Repeated
  lines identify assembly/room. PDFs show plain `BLANK` and exact rates; every
  rendered amount is verified against estimate.json. Disclose audit availability.

## Blind synthetic exercise

1. The operator generates drawings with
   `uv run examples/make_fixture.py --case hotel --out build/blind-input/plans.pdf`.
   Keep fixture source, known truth, generated jobs, evidence and prior outputs
   outside the agent's exercise workspace. Hand the agent **only drawings** and
   the installed skill. No fixture spec or pretranscribed schedule is supplied.
2. Require the agent to inventory pages, discover the bitmap schedule, render
   upright schedule crops, and record the explicit displayed-page -> crop-pixel
   transform (clip origin, scale, rotation and pixel bounds). Save the original
   crop and a separate cell-box preview. Hashes prove pixel identity only;
   transcription and choosing the correct cell are the agent's job.
3. Require an independent count-cell reading from the crop: quote every relevant
   floor/type/variant cell, including zeros, then recompute floor/type totals.
   A second reader (fresh agent or human) checks cells without seeing the first
   transcription or fixture truth. Differences become uncertainty callouts.
4. Complete selections/spec, measurement, audit/receipt, pricing/proposal when
   rates are supplied, then delivery. Keep the autonomy and three-stop contract.
5. The operator compares the delivered evidence with withheld synthetic truth
   and runs the checks above. Record any recognition gap separately from hash
   verification. Repair locally and repeat with fresh synthetic drawings before
   relying on the process for a production takeoff.
