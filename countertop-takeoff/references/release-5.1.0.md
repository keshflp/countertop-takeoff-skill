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

## Finding -> probe -> fix -> verdict

| Finding | Synthetic reproduced probe | Fix / checked outcome | Verdict |
|---|---|---|---|
| P0.1 bitmap evidence | Uncertain referenced TYPE A cell; fabricated ADA word evidence; uncertain/missing variant cell refs | Shared type/variant cell resolution withholds count + dependent standard EA, ledger unresolved. Upright crop/box preview encloses TYPE A ink; fresh source-render hash matches. Fixture truth explicitly is not recognition. | PASS |
| P0.2 identity | Remove reciprocal `p:k` membership; duplicate a geometry claim carrying edges/cutouts | SF/extensions/extended LF/cutouts withheld; conflicted assembly EA/pricing withheld. 802 -> 602 SF for membership defect; completeness false. Declared reuse still extends. Ordinary geometry failure retains valid priced EA. | PASS |
| P0.3 omitted scope | Remove kitchen assembly/piece, retain measured region; unavailable input/callout; arbitrary unresolved ledger entry; individual-room orphan | Structured unresolved contributions propagate. Known SF/price lines/subtotal survive; grand total blank; proposal JSON/MD/PDF carries reasons and known-subtotal labels. | PASS |
| P1.1 publishing | JOB -> JOB; uppercase/canonical aliases; output/output aliases; all proposal outputs -> estimate; copied-results alias; stopped integrity rerun; real pricing SystemExit; unexpected crash | Preflight rejects aliases without changing inputs. Current stopped JSON precedes dependent quarantine; registered proposals in another output directory, estimates and receipts go stale. | PASS |
| P1.2 provenance | Receipt after pricing; real `.json.stale-*` sibling; case-aliased stale file; `{}` payload | Receipt sidecar leaves results bytes/hash unchanged. Siblings named correctly; stale/empty/noncompleted results refused. Workflow places audit before pricing. | PASS |
| P1.3 pricing | Unknown `width_inches`/`variant`; 2 EA x 100 -> 999 with matching forged subtotal; missing results/profile hash; decimal beyond float precision | Both matcher validators refuse unknown keys. Every line multiplication and provenance hash validated. Exact decimal rate used for pricing/display. Estimate/package sums remain line sums. | PASS |
| P1.4 documents | Omitted scope; duplicate total; repeated assembly/room descriptions; raw Markdown; one corrupted repeated PDF amount | One qualified project total; known subtotals and omission reasons; readable identifiers; clean BLANK/exact rates; all rendered numeric tokens match the document computed from estimate.json. | PASS |
| P1.5 first run | Checklist content and workflow-order regression | Supervision checklist plus blind drawings-only synthetic exercise: upright crops, explicit transform, cell-box previews, independent cell reading. | PASS |
| P1.6 readiness | Secondary status scan; public total claims; substitute personal, arbitrary org and alternate owner URLs | Current statuses only; 123.00 resolved subset vs 146.98 full known subtotal qualified; any owner URL accepted; exact transfer swap and ff-only clone/copy guidance retained. | PASS |

## Test evidence

Run from `countertop-takeoff/`, using uv-provisioned Python on Windows:

| Command | Final result |
|---|---:|
| `uv run examples/tests_v2.py` | 47/47 |
| `uv run examples/tests_v3.py` | 34/34 |
| `uv run examples/tests_v4.py` | 40/40 |
| `uv run examples/tests_v5.py` | 125/125 |
| Total | 246/246 |

The original 194 checks remain, with only the deliberate replacements listed
above, plus 52 new checks. V5 runs the supplemental `tests_v51.py` and
`tests_v51_documents.py` modules. All four suites ran after each coherent
block; full logs remain local in ignored repo-root `build/`.

The upright schedule cell preview was also visually inspected. All data is
synthetic. This does not claim successful blind recognition on production plans.

## Decisions and execution notes

- Version is 5.1.0; existing v3-results/v5-pricing schema tags remain compatible.
- Separate receipts are the allowed P1.2 alternative. An artifact-manifest
  sidecar tracks arbitrary output locations for stopped-rerun quarantine.
- No new services, approval gates or additional catastrophic data stops.
- Process slip: the first baseline invocation streamed verbose suite output.
  Subsequent invocations captured full logs and emitted bounded summaries.
- Ignored root transcripts and the similarly named stray directory were left
  untouched and are not included in the commits.
