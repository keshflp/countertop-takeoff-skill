# Output format spec (V2)

Exact formats produced by the V2 pipeline. Consumers (the agent's report,
the audit pack, later phases) rely on these, not prose.

## 1. Markdown report (`measure.py --report`)

Sections, in order:

1. **Header** — source PDF + sha256 prefix, UTC timestamp, mode and
   gross-area policy, declarations (conflicts/omissions/revision decisions)
   recorded for the auditor.
2. **Approved scope** — table `page | sheet | disposition | detail` (detail
   = expected region ids, or the quoted skip/block reason). Every source
   page appears exactly once.
3. **Schedule evidence** — the quoted rows, counts, variant flags
   (included in parent total vs additional), stated totals; or the
   `individual_rooms` declaration.
4. **Calibration** — per (page, viewport): one row per span
   (`label | seg pt | real ft | pt/ft`), then the factor actually used and
   the spread verdict (OK / WARNING).
5. **Takeoff by region** — per type: region rows with `region | variant |
   assembly/material | sheet (page, viewport) | SF | count | extended SF |
   factor pt/ft` (the ACTUAL per-region factor — v1's report could say 18.00
   while the math used 18.36), type totals, and the project total.
6. **Audit checklist** — every pass/warn/fail item with detail, the review
   status line (pending / approved / rejected with reviewer), and the
   overall verdict: `READY`, `WARNING`, or `FAILED`.

## 2. CSV (`--csv`) — written ONLY when no required check failed

Columns: `row_kind, room_type, variant, region_id, sheet, page, viewport,
region_sf, count_applied, region_extended_sf, pt_per_ft_used, source, notes`

Row kinds:
- `base` — one row per measured base region; `count_applied` = the units
  this region's SF multiplies (standard units, or the variant's count);
  `region_extended_sf = region_sf × count_applied`
- `recheck_of_base` — QA recheck rows: `count_applied` 0, `region_extended_sf`
  EMPTY (v1 multiplied recheck rows by full counts and totaled 567.00 SF for
  a 168.75 SF job — never again)
- `type_total` — exactly one per type with the type's extended SF
- `grand_total` — one row, project total

On a failed run the CSV is not written, and any pre-existing export file is
renamed `<name>.stale-<utc>` so an old export can't look current.

## 3. Results JSON (`--json`) — the evidence package

```json
{
  "schema": "countertop-takeoff/v2 results",
  "source": {"pdf": "...", "sha256": "..."},
  "mode": "repeated_types", "policy": {...}, "declarations": [...],
  "runtime_versions": {"python": "...", "pymupdf": "2.1",
                       "shapely": "2.2.0", "platform": "...", ...},
  "settings": {"snap_pt": 0.05, "recheck_tolerance_pct": 2.0},
  "scope": {...}, "schedule": {...}, "profile": {...},
  "calibrations": {"<page>:<viewport>": {"spans": [...],
                  "factor_pt_per_ft": 18.0, "spread_pct": 0.0,
                  "status": "pass"}},
  "regions": [{"region_id": "A:kitchen", "kind": "base", "type": "A",
               "page": 2, "viewport": "main", "sheet": "A-101",
               "boundary_seg_ids": [4,5,6,7,8,9], "seed": [160, 390],
               "polygon": [[x, y], ...], "cutout_polygons": [...],
               "area_sf": 31.25, "gross_area_sf": 31.25,
               "factor_pt_per_ft": 18.0, "gross_area_policy": "gross",
               "curved_boundary": false, "expected_sf_range": [25, 40],
               "expected_range_ok": true, "assembly": null,
               "material_canonical": null}],
  "types": [{"room_type": "A", "schedule_count": 3, "std_units": 3,
             "sf_per_unit": 38.25, "extended_sf": 114.75, "rows": [...]}],
  "totals": {"project_sf": 168.75, "unit_count": 5},
  "audit": [{"check": "...", "status": "pass|warn|fail", "detail": "..."}],
  "run_status": "complete | complete_with_callouts | stopped",
  "callouts": [{"scope", "reason", "blank_fields", "source"}],
  "coverage_ledger": [{"item", "kind", "state":
                       "measured|package_excluded|superseded|unresolved"}],
  "assembly_boq": [...],
  "piece_boq": [...],
  "review_status": "independent_audit_pending",
  "geometry_page_classes": {"1": "text_only", "2": "vector"}
}
```

After an independent audit, `audit_pack.py --record-receipt` adds:

```json
"review": {"status": "independent_audit_recorded", "reviewer": "...",
           "verdict": "approved|rejected", "notes": "...",
           "pack_dir": "...", "recorded_utc": "..."},
"review_status": "independent_audit_approved"
```

## 4. Audit pack (`audit_pack.py --pack DIR`)

- `<region_id>_full.png` / `<region_id>_closeup.png` per measured region:
  base page render (recorded rotation applied) + translucent measured shell,
  region id, area, ACTUAL factor, policy, seed marker, calibration span
  highlights, declared cutouts
- `index.md`: run summary (run status, review status, totals), the CALLOUTS
  the reviewer must confirm, plus what to check: raw sheets, schedule
  evidence, omissions, overlays. Unresolved regions render a marker page
  naming the blank; image-route regions point at the route's own overlay

## 5. Exit codes

| code | meaning |
|---|---|
| 0 | `complete` (deliverable) or `complete_with_callouts` (deliver with the CALLOUTS list: blank fields named, never zeros); CSVs written |
| 2 | `stopped` — one of the three catastrophic cases: no valid calibration anywhere (verified-units CAD qualifies), no schedule and no repeatable pattern, or source integrity mismatch; also spec malformation. Diagnostics (report + results JSON) are still written; no exports; stale exports quarantined — even when the pipeline itself crashes |

## 6. Side files (regenerable, gitignored)

- `<pdf>.index.json` — `{pdf, generated_utc, source:{sha256}, page_count,
  pages:[{page, sheet, title, width, height, dim_labels, dim_count, flags,
  identity{rotation, mediabox, cropbox, displayed_*}, word_count,
  preflight{op_counts, segment_count, segment_bounds, images, image_cover_pct,
  class, class_reasons, fingerprint, revision_marks}, text}],
  findings{duplicate_pages, sheet_id_conflicts, pages_needing_disposition}}`
- `<pdf>.geometry.json` — `{pdf, generated_utc, source:{sha256, page_count},
  pages:[{page, sheet, identity, coordinate_space:"displayed", segment_count,
  word_count, segments:[{id, path, op, x0, y0, x1, y1, w}], words:[{id, t,
  x0, y0, x1, y1}], preflight{...}, text_chars}]}`
