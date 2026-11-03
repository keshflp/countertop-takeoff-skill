"""Output writers for the V2 takeoff: report, CSV, results JSON.

V2 output rules:
  - the CSV is BASE measurement rows plus per-type and grand total rows;
    rechecks are separate rows with no extension (v1 multiplied recheck rows
    by the full schedule count and totaled 567.00 SF instead of 168.75)
  - every row records the ACTUAL calibration factor used for that region
  - the results JSON is an evidence package: measured polygon coordinates,
    selected segment ids, cutouts, per-region factors, source hashes,
    runtime versions
  - status distinguishes failed / warning / ready, plus review_status for
    the independent audit (pending until a receipt is recorded); final CSV
    exports are written only when no required check failed, and stale
    exports from earlier runs are quarantined on failure
"""

import csv
import json
import os
import platform
import sys
from datetime import datetime, timezone

try:
    import pymupdf
except ImportError:
    pymupdf = None
try:
    import shapely
except ImportError:
    shapely = None

CSV_COLUMNS = ["row_kind", "room_type", "variant", "region_id", "sheet",
               "page", "viewport", "region_sf", "count_applied",
               "region_extended_sf", "pt_per_ft_used", "source", "notes"]


def runtime_versions():
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "pymupdf": getattr(pymupdf, "__version__", None),
        "shapely": getattr(shapely, "__version__", None),
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def source_line(spec):
    src = spec["source"]
    return f"`{src['pdf']}` (sha256 {src['sha256'][:16]}...)"


def scope_table_lines(spec):
    lines = ["", "## Approved scope (frozen to the source digest)", "",
             "| page | sheet | disposition | detail |",
             "|-----:|-------|-------------|--------|"]
    for e in spec["scope"]["pages"]:
        if e["disposition"] == "measured":
            detail = ", ".join(e["expected_regions"])
        else:
            detail = (e.get("reason") or "")[:90]
        lines.append(f"| {e['page']} | {e.get('sheet') or '?'} "
                     f"| {e['disposition']} | {detail} |")
    return lines


def schedule_table_lines(spec):
    sched = spec.get("schedule")
    if sched is None:
        return ["", "## Schedule evidence", "",
                "Mode `individual_rooms`: no multiplier schedule; rooms are"
                " measured and summed individually.", ""]
    lines = ["", "## Schedule evidence", "",
             f"Sheet **{sched['sheet']}** (page {sched['page']}); counts are"
             " agent-read from the quoted row text with word boxes recorded"
             " in the job spec.", "",
             "| type | count | evidence row | variants |",
             "|------|------:|--------------|----------|"]
    for t in sched["types"]:
        vs = [v["name"] for v in sched.get("variants", [])
              if v["type"] == t["type"]]
        lines.append(f"| {t['type']} | {t['count']} | {t['row_text'][:60]} "
                     f"| {', '.join(vs) or '-'} |")
    for v in sched.get("variants", []):
        flag = ("included in parent total" if v["included_in_parent_total"]
                else "additional")
        lines.append(f"| {v['type']}:{v['name']} | {v['count']} "
                     f"| {v['row_text'][:60]} | {flag} |")
    st = sched.get("stated_totals")
    if st:
        pf = st.get("per_floor") or {}
        fl = ", ".join(f"floor {k}: {v}" for k, v in pf.items())
        proj = st.get("project")
        lines.append("")
        lines.append(f"Stated totals: {fl}"
                     + (f"; project {proj}" if proj is not None else "")
                     + " - reconciled in the audit.")
    return lines


def calibration_table_lines(calibrations):
    lines = ["", "## Calibration (selected spans, computed lengths)", ""]
    if not calibrations:
        return lines + ["No calibrations were performed."]
    lines += ["| page | viewport | span label | seg pt | real ft | pt/ft |",
              "|-----:|----------|-----------|-------:|--------:|------:|"]
    for key in sorted(calibrations, key=lambda k: (k[0], k[1])):
        cal = calibrations[key]
        for s in cal["spans"]:
            lines.append(f"| {cal['page']} | {cal['viewport']} "
                         f"| {s['label']} | {s['length_pt']:.2f} "
                         f"| {s['real_ft']:.4f} | {s['pt_per_ft']:.4f} |")
        lines.append("")
        verdict = ("OK" if cal["status"] == "pass"
                   else "WARNING - explain or fix")
        lines.append(f"Factor used on page {cal['page']} viewport"
                     f" {cal['viewport']!r}: **{cal['factor_pt_per_ft']:.4f}"
                     f" pt/ft** (median of {len(cal['spans'])} spans, spread"
                     f" {cal['spread_pct']:.2f}%) -> {verdict}")
        lines.append("")
    return lines


def takeoff_lines(spec, types, total):
    lines = ["", "## Takeoff by region", ""]
    mode = spec.get("mode")
    for t in types:
        title = f"### {t['room_type']}"
        if mode == "repeated_types":
            title += (f" - schedule count {t['schedule_count']}"
                      f" ({t['std_units']} standard unit(s) + variants)")
        lines += [title, "",
                  "| region | variant | assembly/material | sheet (page, viewport) | SF |"
                  " count | extended SF | factor pt/ft |",
                  "|--------|---------|-------------------|------------------------|---:|---:"
                  "|-----------:|-------------:|"]
        for row in t["rows"]:
            r = row["regions"][0]
            ident = row.get("assembly") or "-"
            if row.get("material_canonical"):
                ident += f" / {row['material_canonical']}"
            lines.append(
                f"| {row['region_id']} | {row['variant'] or '-'} "
                f"| {ident} "
                f"| {r['sheet']} ({r['page']}, {r['viewport']}) "
                f"| {row['sf']:.2f} | {row['count']} "
                f"| {row['extended_sf']:.2f} "
                f"| {r['factor_pt_per_ft']:.4f} |")
        if mode == "repeated_types":
            lines.append("")
            lines.append(f"Type total: **{t['extended_sf']:.2f} SF**")
        lines.append("")
    lines.append(f"**Project total: {total:.2f} SF**")
    lines.append("")
    return lines


def audit_lines(audit, review_status):
    lines = ["", "## Audit checklist", "", ]
    mark = {"pass": "x", "warn": " ", "fail": "!!"}
    for item in audit.items:
        lines.append(f"- [{mark[item['status']]}] {item['check']}: "
                     f"{item['status'].upper()} - {item['detail']}")
    review = {
        "independent_audit_pending":
            "PENDING - run scripts/audit_pack.py and have a FRESH agent (or an"
            " independent human) review the raw sheets, schedule evidence,"
            " omissions and overlays before delivering; record the receipt.",
    }
    lines += ["", f"Review status: {review_status}"
              + (f" - {review[review_status]}"
                 if review_status in review else "")]
    return lines


def status_line(audit):
    failed, warned = audit.failed, audit.warned
    if failed:
        return (f"**Overall: FAILED** ({len(failed)} required check(s) failed,"
                f" {len(warned)} warning(s)) - numbers must not be quoted or"
                " exported")
    if warned:
        return (f"**Overall: WARNING** ({len(warned)} warning(s)) - required"
                " checks passed; deliverables need review of the warnings")
    return "**Overall: READY** (0 fail, 0 warn)"


def build_report(spec, calibrations, types, total, audit, review_status):
    lines = ["# Countertop Takeoff Report (V2)", ""]
    lines.append(f"- source: {source_line(spec)}")
    lines.append(f"- generated: {runtime_versions()['generated_utc']}")
    lines.append(f"- mode: `{spec.get('mode')}`; gross-area policy:"
                 f" `{spec['policy']['gross_area']}`")
    decls = spec["policy"].get("declarations", [])
    if decls:
        lines.append("- declarations (recorded for the auditor):")
        for d in decls:
            lines.append(f"  - [{d['kind']}] {d['detail']}")
    lines += scope_table_lines(spec)
    lines += schedule_table_lines(spec)
    lines += calibration_table_lines(calibrations)
    lines += takeoff_lines(spec, types, total)
    lines += audit_lines(audit, review_status)
    lines += ["", status_line(audit), ""]
    return "\n".join(lines) + "\n"


def _csv_rows(spec, types, results):
    """Base rows carry the extension; recheck rows are separate with no
    extension; then one totals row per type and a grand total row."""
    rows = []
    src = spec["source"]["pdf"]
    recheck_ids = {r["region_id"] for r in results if r["kind"] == "recheck"}
    base_by_id = {}
    for t in types:
        for row in t["rows"]:
            r = row["regions"][0]
            base_by_id[r["region_id"]] = (row, r)
    for rid, (row, r) in base_by_id.items():
        notes = (f"factor from page {r['page']} viewport {r['viewport']}"
                 f" ({r['gross_area_policy']})")
        rows.append([
            "base", row["room_type"], row["variant"] or "", rid, r["sheet"],
            r["page"], r["viewport"], f"{row['sf']:.2f}", row["count"],
            f"{row['extended_sf']:.2f}", f"{r['factor_pt_per_ft']:.4f}",
            f"{src} p.{r['page']} ({r['sheet']})", notes])
    for r in results:
        if r["kind"] != "recheck":
            continue
        base = base_by_id.get(r.get("of"))
        rows.append([
            "recheck_of_base", r["type"], r["variant"] or "", r["region_id"],
            r["sheet"], r["page"], r["viewport"], f"{r['area_sf']:.2f}", 0,
            "", f"{r['factor_pt_per_ft']:.4f}",
            f"{src} p.{r['page']} ({r['sheet']})",
            f"QA recheck of {r.get('of')}; never extended"])
    for t in types:
        rows.append(["type_total", t["room_type"], "", "", "", "", "",
                     "", "", f"{t['extended_sf']:.2f}", "", "", ""])
    total = round(sum(t["extended_sf"] for t in types), 2)
    rows.append(["grand_total", "", "", "", "", "", "", "", "",
                 f"{total:.2f}", "", "", ""])
    return rows, total


def write_csv(path, spec, types, results):
    rows, total = _csv_rows(spec, types, results)
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)
        w.writerows(rows)
    return total


def quarantine_stale_export(path, when_utc):
    """A failed run must not leave an older export looking current."""
    if os.path.exists(path):
        stamp = when_utc.replace(":", "").replace("-", "")
        dest = f"{path}.stale-{stamp}"
        os.replace(path, dest)
        return dest
    return None


def build_results(spec, geometry, calibrations, types, total, audit, results,
                  review_status, settings, unit_total):
    """Evidence package: polygons, segment ids, factors, hashes, versions."""
    versions = runtime_versions()
    return {
        "schema": "countertop-takeoff/v2 results",
        "source": dict(spec["source"]),
        "geometry": spec["geometry"],
        "mode": spec.get("mode"),
        "policy": spec["policy"],
        "runtime_versions": versions,
        "settings": settings,
        "scope": spec["scope"],
        "schedule": spec.get("schedule"),
        "calibrations": {f"{p}:{v}": calibrations[(p, v)]
                         for p, v in calibrations},
        "regions": results,
        "types": types,
        "totals": {"project_sf": total, "unit_count": unit_total},
        "audit": audit.items,
        "status": ("failed" if audit.failed
                   else ("warning" if audit.warned else "ready")),
        "review_status": review_status,
        "declarations": spec["policy"].get("declarations", []),
        "geometry_page_classes": {
            str(p["page"]): p["preflight"]["class"]
            for p in geometry["pages"]},
    }


def write_json(path, payload):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)


def write_report(path, text):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
