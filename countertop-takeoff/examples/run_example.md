# Synthetic example walkthrough

Run from `countertop-takeoff/`. Fixtures contain known geometry; they do not
prove recognition on an unseen job. Use the [first-run checklist](../references/first-run-checklist.md)
for a supervised drawings-only exercise without oracle job selections.

## Clean fixture

```powershell
uv run examples/make_fixture.py --out examples/fixture.pdf
uv run scripts/index_pdf.py examples/fixture.pdf
uv run scripts/extract_geometry.py examples/fixture.pdf --pages all --out build/fixture.geometry.json
uv run scripts/measure.py examples/fixture.jobs.json --report build/report.md --csv build/takeoff.csv --json build/results.json
uv run scripts/audit_pack.py build/results.json --pack build/audit_pack
```

The deterministic fixture matches the job spec's pinned hash. Page 1 contains
the schedule; pages 2-3 contain selected countertops with three independent
calibration spans each, all 18.0000 pt/ft. The spec records schedule quotes,
word boxes, planned regions, rechecks, and the plan/spec depth conflict.

| Quantity | Known and measured |
|---|---:|
| Type A kitchen + vanity | 31.25 + 7.00 = 38.25 SF/unit |
| Type A x3 | 114.75 SF |
| Type B kitchen + vanity | 20.00 + 7.00 = 27.00 SF/unit |
| Type B x2 | 54.00 SF |
| Project total | 168.75 SF |

CSV base rows extend by schedule count; rechecks do not extend. Type and grand
totals reconcile. Results retain `independent_audit_pending` until a separate
receipt records the independent review without changing results bytes:

```powershell
uv run scripts/audit_pack.py build/results.json --record-receipt --reviewer "independent reviewer" --verdict approved --notes "Verified counts, spans, shells, omissions against raw sources"
```

Record that verdict only after independent checking. If no auditor is
available, disclose it and continue. Requested pricing/proposal follows audit;
deliver once at the end. See [output contracts](../references/output-format.md).

## Additional fixtures and regression coverage

- `make_fixture.py --case messy` / `messy.jobs.json`: rotated sheet, separate
  18/9 pt/ft viewports, ADA allocation, revision conflict, searchable raster,
  island/sink loop, split/fractional labels. Gross 990.00 SF; declared-cutout
  net 936.00 SF. `tests_v2.py` covers exactness and negative mutations.
- `hotel_fixture.py` / `make_hotel_jobs.py`: rotated pages, bitmap schedule
  crop/cell evidence, room reconciliation, identity conflicts, three viewport
  scales, section/length joins, package exclusions, legible and unusable scans.
  The fully resolved assembly subset is 123.00 SF; project/report/CSV retain
  the 146.98 SF full known piece subtotal. Omissions keep completeness false.
- `tests_v4.py`: mixed repeated/enumerated/public/excluded scope, evidence
  binding, CAD units/inserts/arcs, pricing, and intake.
- `tests_v5.py`: quantity identity, blank-vs-zero, publish safety, immutable
  receipts, exact pricing, proposal documents, and current doc contracts.

## Acceptance commands (sequential: shared generated paths)

```powershell
uv run examples/tests_v2.py  # 47
uv run examples/tests_v3.py  # 34
uv run examples/tests_v4.py  # 40
uv run examples/tests_v5.py  # 125
```

A failed boundary/span/recheck, unusable raster, or unsupported count degrades
locally to BLANK + callout. Only no calibration anywhere, no schedule AND no
repeatable pattern, or source integrity mismatch are catastrophic data stops.
Malformed specs refuse separately. Completed runs return 0 (`complete` or
`complete_with_callouts`); stopped runs return 2 and quarantine stale exports.
