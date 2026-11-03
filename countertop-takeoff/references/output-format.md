# Output format spec

Exact formats produced by the V1 pipeline. Consumers (the agent's report to
the user, and later phases) should rely on these, not on prose.

## 1. Markdown report (`measure.py --report`)

Sections, in order:

1. **Header** — source PDF, generation timestamp (UTC), schedule sheet id.
2. **Calibration** — table `page | sheet | label | segment pt | real ft |
   pt/ft`, one row per matched dimension label, followed by the scale used per
   page (`median of N labels, spread X%`).
3. **Takeoff by type** — per type: instance/region table
   (`instance | sheet (page) | region | SF | edge LF (info)`), then per-unit
   total, extension (`×count = extended`), spot-check lines
   (`dev X% PASS/FAIL`), and any count warnings.
4. **Totals** — `type | SF/unit | units | extended SF` with a bold total row.
5. **QA table** — `room type | instance measured | SF | schedule count |
   extended SF | source` where source = `<pdf> p.<page> (<sheet>)`.
   Spot-check instances appear too, flagged in the CSV notes.
6. **Self-audit** — checklist with `PASS/WARN/FAIL` per item and an overall
   verdict line: `**Overall: PASS** (0 fail, 0 warn)`.

## 2. CSV (`--csv`), one row per region per instance

| column | meaning |
|---|---|
| `room_type` | unit/room type letter or name (e.g. `A`) |
| `instance` | measured instance label (e.g. `Unit 101`, `Unit 101 recheck`) |
| `region` | region name within the instance (e.g. `kitchen`) |
| `sheet` | sheet id cited for the measurement (e.g. `A-101`) |
| `page` | 1-based PDF page number |
| `region_sf` | computed square footage of this region (2 dp) |
| `edge_lf_info` | informational edge length, LF — NOT a V1 deliverable |
| `instance_sf` | sum of the instance's regions |
| `schedule_count` | unit count applied (from the schedule) |
| `extended_sf` | `instance_sf × schedule_count` for the base instance |
| `source` | `pdf path p.N (SHEET)` citation |
| `notes` | audit notes (`spot-check instance`, range breaches, nested loops) |

Rule: extended SF is computed from the FIRST (base) instance of each type;
spot-check instances are recorded but never averaged in.

## 3. Results JSON (`--json`)

```json
{
  "pdf": "...", "generated_utc": "...",
  "settings": {"snap_pt": 0.05, "pad_pt": 12.0,
               "spot_tolerance_pct": 2.0, "spread_fail_pct": 5.0},
  "calibrations": {"<page>": {"scale_pt_per_ft": 18.0, "labels": [...],
                              "unmatched": [...], "spread_pct": 0.0}},
  "types": [{"room_type": "A", "schedule_count": 3, "sf_per_unit": 38.25,
             "extended_sf": 114.75, "spot_checks": [...], "count_note": null}],
  "jobs": [ ...echoed job spec... ],
  "audit": [{"check": "calibration", "status": "pass", "detail": "..."}],
  "status": "PASS"
}
```

## 4. Exit codes

| code | meaning |
|---|---|
| 0 | success; warnings possible (read the self-audit) |
| 2 | hard stop — calibration failed, region unclosed, conflicting scales, or audit FAIL. Numbers produced in this run must not be quoted. |

## 5. Index/geometry side files (regenerable, gitignored)

- `<pdf>.index.json` — `{pdf, page_count, pages:[{page, sheet, title, width,
  height, dim_labels[], dim_count, flags{unit_schedule, plan, spec, ...,
  counter_terms, type_tags[]}, text}]}`
- `<pdf>.geometry.json` — `{pdf, pages:[{page, sheet, width, height,
  segment_count, word_count, segments:[{x0,y0,x1,y1,w}], words:[{t,x0,y0,x1,
  y1}]}]}` (1-based `page`, coordinates in PDF points, origin top-left).
