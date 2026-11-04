"""Output writers for the V2 takeoff: report, CSV, results JSON.

V2 output rules:
  - the CSV is BASE measurement rows plus per-type and grand total rows;
    rechecks are separate rows with no extension (v1 multiplied recheck rows
    by the full schedule count and totaled 567.00 SF instead of 168.75)
  - every row records the ACTUAL calibration factor used for that region
  - the results JSON is an evidence package: measured polygon coordinates,
    selected segment ids, cutouts, per-region factors, source hashes,
    runtime versions
  - status is complete / complete_with_callouts / stopped; independent
    review status is recorded in the immutable-results receipt sidecar; final CSV
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


def _fmt_factor(v):
    return "" if v is None else (f"{v:.4f}" if isinstance(v, (int, float))
                                 else str(v))


def takeoff_lines(spec, types, total, totals_meta=None):
    lines = ["", "## Takeoff by region", ""]
    mode = spec.get("mode")
    for t in types:
        title = f"### {t['room_type']}"
        if spec.get("_assemblies"):
            title += (f" - resolved EA {_fmt(t['std_units'])}"
                      + (f" (schedule count {t['schedule_count']})"
                         if t.get("schedule_count") is not None else ""))
        elif mode == "repeated_types" and "schedule_count" in t:
            title += (f" - schedule count {t['schedule_count']}"
                      f" ({_fmt(t['std_units'])} standard unit(s) + variants)")
        lines += [title, "",
                  "| region | variant | assembly/material | sheet (page, viewport) | SF |"
                  " count | extended SF | factor pt/ft |",
                  "|--------|---------|-------------------|------------------------|---:|---:"
                  "|-----------:|-------------:|"]
        for row in t["rows"]:
            r = row["regions"][0]
            ident = row.get("assembly") or row.get("region_id") or "-"
            if row.get("material_canonical"):
                ident += f" / {row['material_canonical']}"
            lines.append(
                f"| {row.get('region_id') or '-'} | {row.get('variant') or '-'} "
                f"| {ident} "
                f"| {r.get('sheet') or '?'} ({r.get('page') or '-'},"
                f" {r.get('viewport') or '-'}) "
                f"| {_fmt(row.get('sf'))} | {_fmt(row.get('count'))} "
                f"| {_fmt(row.get('extended_sf'))} "
                f"| {_fmt_factor(r.get('factor_pt_per_ft')) or '-'} |")
        if t.get("excluded_extended_sf"):
            lines.append("")
            lines.append("Package-excluded scope in this type: "
                         f"**{t['excluded_extended_sf']:.2f} SF** (reported"
                         " separately, excluded from totals)")
        if mode == "repeated_types" or spec.get("_assemblies"):
            t_total = t.get("extended_sf")
            lines.append("")
            if t_total is None:
                # V5 (P1.1): an all-unknown type shows a BLANK total
                lines.append("Type total: **__blank__** (no measured amounts"
                             " for this type - see CALLOUTS)")
            else:
                lines.append(f"Type total: **{t_total:.2f} SF**"
                             + ("" if t.get("complete", True) else
                                " (known subtotal; some contributions are"
                                " unknown - see CALLOUTS)"))
        lines.append("")
    meta = totals_meta or {}
    total_line = f"**Project total: {total:.2f} SF**"
    if meta.get("project_sf_complete") is False:
        total_line += (f" (known subtotal;"
                       f" {meta.get('unknown_contribution_count', '?')}"
                       " contribution(s) unknown - see CALLOUTS)")
    lines.append(total_line)
    if spec.get("_assemblies"):
        lines.append("")
        lines.append(
            f"**Assembly EA total: {_fmt(meta.get('assembly_ea'))} EA** (summed resolved"
            " assembly quantities - DISTINCT from the"
            f" {_fmt(meta.get('unit_count'))} unit(s) in the room schedule;"
            " one counts rooms, the other counts assembled instances)")
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


def status_line(run_status, audit):
    failed, warned = audit.failed, audit.warned
    if run_status == "stopped":
        return (f"**Run status: STOPPED** ({len(failed)} required check(s)"
                f" failed, {len(warned)} warning(s)) - numbers must not be"
                " quoted or exported")
    if warned:
        return (f"**Run status: COMPLETE WITH CALLOUTS**"
                f" ({len(warned)} callout(s)) - quantities for the named"
                " scope stay blank; everything else is deliverable")
    return "**Run status: COMPLETE** (0 fail, 0 callout)"


def callout_lines(audit):
    if not audit.callouts:
        return []
    lines = ["", "## CALLOUTS (degraded-but-disclosed; blank fields, never"
             " zeros)", ""]
    for i, c in enumerate(audit.callouts, 1):
        src = c.get("source") or {}
        where = []
        if src.get("source_id"):
            where.append(f"source {src['source_id']}")
        if src.get("pages"):
            where.append(f"pages {src['pages']}")
        lines.append(f"{i}. **{c['scope']}**"
                     + (f" [{'; '.join(where)}]" if where else ""))
        lines.append(f"   - reason: {c['reason']}")
        if c.get("blank_fields"):
            lines.append(f"   - excluded/blank fields: {c['blank_fields']}")
    return lines


def _fmt(v, nd=2):
    """Blank-aware formatter: unknown quantities render as a blank marker,
    never as zero."""
    if v is None:
        return "__blank__"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def assembly_boq_lines(assembly_rows, excluded_packages):
    if not assembly_rows:
        return []
    lines = ["", "## ASSEMBLY BoQ", "",
             "One row per assembly; EA is the RESOLVED quantity (P0.1: one"
             " model; included variants subtracted from parent counts)."
             " **This view is never summed with the PIECE BoQ below** -"
             " both derive from the same resolved records.", "",
             "| assembly | room/type/variant | package | finish | W x D x H"
             " (in) | hand | EA | SF/instance | ext SF | basis | state |",
             "|----------|-------------------|---------|--------|-----------"
             "----|------|---:|---:|-------:|-------|-------|"]
    for r in assembly_rows:
        dims = " x ".join(_fmt(r.get(k)) for k in
                           ("width_in", "depth_in", "height_in"))
        lines.append(
            f"| {r['assembly_id']} | {r.get('room') or '-'}/{r['type']}"
            f"/{r.get('variant') or '-'} | {r['package']}"
            f" | {r.get('finish_tag') or '-'} | {dims}"
            f" | {r.get('handing') or '-'} | {_fmt(r.get('ea'))}"
            f" | {_fmt(r.get('sf_per_instance'))}"
            f" | {_fmt(r.get('extended_sf'))}"
            f" | {r['basis'][:40]} | {r['state']} |")
    if excluded_packages:
        lines += ["", f"Excluded packages ({', '.join(sorted(excluded_packages))})"
                  " are listed above with state `package_excluded` and are"
                  " reported separately - excluded from main totals."]
    return lines


def piece_boq_lines(piece_rows):
    if not piece_rows:
        return []
    lines = ["", "## PIECE BoQ", "",
             "Per piece: inch dims, SF, edge LF by profile, splash LF/SF"
             " (returns + handing preserved), cutout EA - extensions x the"
             " SAME resolved EA (LF and cutouts extend with assembly"
             " quantities). **Never summed with the ASSEMBLY BoQ.**", "",
             "| piece | assembly | dims (in) | SF | edge LF by profile |"
             " edge LF xEA | splash LF/SF | splash xEA | cutouts EA | cutouts"
             " xEA | EA | ext SF | finish |",
             "|-------|----------|-----------|---:|--------------------|"
             "-------------|--------------|------------|------------|------"
             "-------|---:|-------:|--------|"]
    finishes = {}
    for r in piece_rows:
        d = r.get("dims_in") or {}
        dims = " x ".join(_fmt(d.get(k)) for k in
                           ("width", "depth", "height")) if d else \
            "(geometry route)"
        edges = ", ".join(
            (f"{k}={v:.2f}" if v is not None else f"{k}=BLANK")
            for k, v in (r.get("edge_lf_by_profile") or {}).items()) or "-"
        edge_ext = ", ".join(
            f"{k}={v:.2f}" for k, v in (r.get("edge_lf_ext") or {}).items()
        ) or ("-" if r.get("edge_lf_ext") is None or
              not r.get("edge_lf_ext") else "-")
        splash = (f"{_fmt(r.get('splash_lf'))}/{_fmt(r.get('splash_sf'))}"
                  if (r.get("splash_lf") is not None
                      or r.get("splash_sf") is not None) else "-")
        splash_x = (f"{_fmt(r.get('splash_lf_ext'))}/"
                    f"{_fmt(r.get('splash_sf_ext'))}"
                    if (r.get("splash_lf_ext") is not None
                        or r.get("splash_sf_ext") is not None) else "-")
        cuts = ", ".join(f"{k}={v}" for k, v in
                         (r.get("cutouts_ea") or {}).items()) or "-"
        cuts_x = ", ".join(f"{k}={v}" for k, v in
                           (r.get("cutouts_ea_ext") or {}).items()) or "-"
        lines.append(
            f"| {r['piece_id']} | {r['assembly_id']} | {dims}"
            f" | {_fmt(r.get('sf'))} | {edges} | {edge_ext} | {splash}"
            f" | {splash_x} | {cuts} | {cuts_x}"
            f" | {_fmt(r.get('ea'))} | {_fmt(r.get('extension_sf'))}"
            f" | {r.get('finish_tag') or '-'} |")
        for sd in r.get("splash_detail") or []:
            if sd.get("handing") or sd.get("returns_in") is not None:
                lines.append(
                    f"  - splash run: handing {sd.get('handing') or '-'},"
                    f" returns {sd.get('returns_in') or '-'} in,"
                    f" length {_fmt(sd.get('length_in'))} in,"
                    f" height {_fmt(sd.get('height_in'))} in")
        tag = r.get("finish_tag")
        if tag:
            finishes.setdefault(tag, 0)
            finishes[tag] += 1
    for tag, n in sorted(finishes.items()):
        lines.append("")
        lines.append(f"Finish group **{tag}** ({n} piece(s)): brand/color TBD"
                     " - verify in the FF&E manual before ordering.")
    return lines


def ledger_lines(ledger):
    lines = ["", "## Coverage ledger", "",
             "Every inventoried item reconciles to exactly one state:",
             "`measured | included_scope | package_excluded | superseded |"
             " unresolved`.", "",
             "| item | kind | state | source | detail |",
             "|------|------|-------|--------|--------|"]
    for e in ledger:
        src = e.get("source") or {}
        where = ",".join(filter(None, [str(src.get("source_id") or ""),
                                       str(src.get("pages") or "")]))
        lines.append(f"| {e['item']} | {e['kind']} | **{e['state']}** |"
                     f" {where} | {e.get('detail', '')[:80]} |")
    return lines


def build_report(spec, calibrations, types, total, audit, review_status,
                 run_status="complete", ledger=None, assembly_rows=None,
                 piece_rows=None, totals_meta=None):
    lines = ["# Countertop Takeoff Report (V4)", ""]
    lines.append(f"- source(s): {sources_line(spec)}")
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
    lines += takeoff_lines(spec, types, total, totals_meta=totals_meta)
    lines += callout_lines(audit)
    if ledger is not None:
        lines += ledger_lines(ledger)
    lines += assembly_boq_lines(assembly_rows or [],
                                spec.get("_excluded_packages") or set())
    lines += piece_boq_lines(piece_rows or [])
    lines += audit_lines(audit, review_status)
    lines += ["", status_line(run_status, audit), ""]
    return "\n".join(lines) + "\n"


def sources_line(spec):
    parts = []
    for s in spec.get("_sources") or []:
        parts.append(f"`{s['source_id']}: {s['path']}`"
                     f" (sha256 {s['sha256'][:16]}...)")
    return "; ".join(parts) or source_line(spec)


def _csv_rows(spec, types, results):
    """Legacy (no-assemblies) CSV: base rows carry the extension; recheck
    rows are separate with no extension; then one totals row per type and
    a grand total row."""
    rows = []
    src = (spec.get("source") or {}).get("pdf")         or spec["_sources"][0]["path"]
    recheck_ids = {r["region_id"] for r in results if r["kind"] == "recheck"}
    base_by_id = {}
    for t in types:
        for row in t["rows"]:
            r = row["regions"][0]
            base_by_id[row.get("region_id")] = (row, r)
    for rid, (row, r) in base_by_id.items():
        notes = (f"factor from page {r['page']} viewport {r['viewport']}"
                 f" ({r.get('gross_area_policy')})")
        factor = r.get("factor_pt_per_ft")
        if factor is None:
            factor = r.get("factor_px_per_ft")
            notes = f"image route at {factor} px/ft ({r.get('gross_area_policy')})"
        rows.append([
            "base", row["room_type"], row.get("variant") or "", rid or "",
            r.get("sheet") or "?", r.get("page") or "",
            r.get("viewport") or "", f"{row['sf']:.2f}", _fmt(row["count"]),
            _fmt(row["extended_sf"]), _fmt_factor(factor),
            f"{src} p.{r.get('page')} ({r.get('sheet') or '?'})", notes])
    for r in results:
        if r["kind"] != "recheck":
            continue
        base = base_by_id.get(r.get("of"))
        if r.get("status") == "unresolved":
            rows.append([
                "recheck_of_base", r["type"], r.get("variant") or "",
                r["region_id"], r.get("sheet") or "?", r["page"],
                r.get("viewport") or "main",
                "", 0, "", "",
                f"{src} p.{r['page']} ({r.get('sheet') or '?'})",
                f"QA recheck of {r.get('of')}; UNRESOLVED -"
                f" {r.get('unresolved_reason', '')[:80]}"])
            continue
        rows.append([
            "recheck_of_base", r["type"], r.get("variant") or "", r["region_id"],
            r.get("sheet") or "?", r["page"], r.get("viewport") or "main",
            f"{r['area_sf']:.2f}", 0,
            "", _fmt_factor(r.get("factor_pt_per_ft")
                            or r.get("factor_px_per_ft")) or "0",
            f"{src} p.{r['page']} ({r.get('sheet') or '?'})",
            f"QA recheck of {r.get('of')}; never extended"])
    for t in types:
        rows.append(["type_total", t["room_type"], "", "", "", "", "",
                     "", "", _fmt(t["extended_sf"]), "", "", ""])
    total = round(sum(t["extended_sf"] for t in types if t["extended_sf"] is not None), 2)
    rows.append(["grand_total", "", "", "", "", "", "", "", "",
                 f"{total:.2f}", "", "", ""])
    return rows, total


def _resolved_csv_rows(spec, types, piece_rows, project_total):
    """V4 CSV (jobs with assemblies): rows DERIVED from the ONE resolved
    model - one base row per piece (blank extensions stay blank), the
    resolved type totals, a documented excluded-package total row, and a
    grand total row that EQUALS the project total and both BoQ views."""
    src = (spec.get("source") or {}).get("pdf") or spec["_sources"][0]["path"]
    rows = []
    for r in piece_rows:
        meta = r.get("region_meta") or {}
        blanks = r.get("blank_fields") or []
        notes = (f"state {r['state']}"
                 + (f"; blank: {', '.join(blanks)}" if blanks else "")
                 + ("; ORPHAN piece (assembly not declared)"
                    if r.get("orphan") else ""))
        rows.append([
            "base", r.get("type") or "", r.get("assembly_id") or "",
            r.get("region_id") or r["piece_id"],
            meta.get("sheet") or "?", meta.get("page") or "",
            meta.get("viewport") or "stated",
            _fmt(r.get("sf")), _fmt(r.get("ea")), _fmt(r.get("extension_sf")),
            _fmt_factor(meta.get("factor")),
            (f"{src} p.{meta.get('page')}" if meta.get("page")
             else f"{src} (stated dims)"),
            notes])
    for t in types:
        t_total = t.get("extended_sf")
        rows.append(["type_total", t["room_type"], "", "", "", "", "",
                     "", "", "__blank__" if t_total is None
                     else f"{t_total:.2f}", "", "",
                     "" if t_total is not None else
                     "no measured amounts for this type (blank, never"
                     " 0.00)"])
    excluded = round(sum(t.get("excluded_extended_sf") or 0.0
                         for t in types), 2)
    if excluded:
        rows.append(["excluded_package_total", "", "", "", "", "", "",
                     "", "", f"{excluded:.2f}", "", "",
                     "package-excluded scope; reported separately, NEVER"
                     " added into the grand total"])
    rows.append(["grand_total", "", "", "", "", "", "", "", "",
                 f"{round(project_total, 2):.2f}", "", "",
                 "equals the project total and BOTH BoQ view totals (one"
                 " resolved model)"])
    return rows, round(project_total, 2)


def write_csv(path, spec, types, results, resolved=None, project_total=None):
    if resolved is not None:
        rows, total = _resolved_csv_rows(spec, types, resolved,
                                         project_total or 0.0)
    else:
        rows, total = _csv_rows(spec, types, results)
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)
        w.writerows(rows)
    return total


PIECE_CSV_COLUMNS = ["piece_id", "assembly_id", "room", "type", "package",
                     "finish_tag", "route", "width_in", "depth_in",
                     "height_in", "sf", "edge_lf_by_profile",
                     "edge_lf_by_profile_xEA", "splash_lf", "splash_sf",
                     "splash_lf_xEA", "splash_sf_xEA", "splash_runs",
                     "cutouts_ea", "cutouts_ea_xEA", "ea", "extension_sf",
                     "state", "blank_fields", "source_pages"]

ASSEMBLY_CSV_COLUMNS = ["assembly_id", "room", "type", "variant", "package",
                        "finish_tag", "width_in", "depth_in", "height_in",
                        "handing", "ea", "basis", "state"]


def _num(v):
    return "" if v is None else (f"{v:.4f}" if isinstance(v, float) else v)


def write_piece_csv(path, piece_rows):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(PIECE_CSV_COLUMNS)
        for r in piece_rows:
            d_ = r.get("dims_in") or {}
            links = r.get("source_links") or {}
            pages = sorted({l.get("page") for l in links.values()
                            if l.get("page")})
            w.writerow([
                r["piece_id"], r["assembly_id"], r.get("room") or "",
                r.get("type") or "", r.get("package") or "",
                r.get("finish_tag") or "", r["route"],
                _num(d_.get("width")), _num(d_.get("depth")),
                _num(d_.get("height")), _num(r.get("sf")),
                json.dumps(r.get("edge_lf_by_profile") or {}, sort_keys=True),
                json.dumps(r.get("edge_lf_ext") or {}, sort_keys=True)
                if r.get("edge_lf_ext") is not None else "",
                _num(r.get("splash_lf")), _num(r.get("splash_sf")),
                _num(r.get("splash_lf_ext")), _num(r.get("splash_sf_ext")),
                json.dumps(r.get("splash_detail") or [], sort_keys=True),
                json.dumps(r.get("cutouts_ea") or {}, sort_keys=True),
                json.dumps(r.get("cutouts_ea_ext") or {}, sort_keys=True)
                if r.get("cutouts_ea_ext") is not None else "",
                _num(r.get("ea")), _num(r.get("extension_sf")),
                r["state"], ";".join(r.get("blank_fields") or []),
                ";".join(str(p) for p in pages)])
    return len(piece_rows)


def write_assembly_csv(path, assembly_rows):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(ASSEMBLY_CSV_COLUMNS)
        for r in assembly_rows:
            w.writerow([
                r["assembly_id"], r.get("room") or "", r["type"],
                r.get("variant") or "", r["package"],
                r.get("finish_tag") or "", _num(r.get("width_in")),
                _num(r.get("depth_in")), _num(r.get("height_in")),
                r.get("handing") or "", _num(r.get("ea")), r["basis"],
                r["state"]])
    return len(assembly_rows)


def quarantine_stale_export(path, when_utc):
    """A failed run must not leave an older export looking current."""
    if os.path.exists(path):
        stamp = when_utc.replace(":", "").replace("-", "")
        dest = f"{path}.stale-{stamp}"
        n = 1
        while os.path.exists(dest):
            dest = f"{path}.stale-{stamp}-{n}"
            n += 1
        os.replace(path, dest)
        return dest
    return None


def calibration_key(source_id, page, viewport, multi):
    """Results-JSON calibration key. Single-source runs keep the V2 shape
    'page:viewport'; multi-source runs qualify with the source id."""
    return (f"{source_id}:{page}:{viewport}" if multi
            else f"{page}:{viewport}")


def build_results(spec, geometry_map, calibrations, types, total, audit,
                  results, review_status, settings, unit_total,
                  coverage_ledger=None):
    """Evidence package: polygons, segment ids, factors, hashes, versions,
    callouts + the coverage ledger."""
    versions = runtime_versions()
    multi = len(spec["_sources"]) > 1
    return {
        "schema": "countertop-takeoff/v3 results",
        "sources": spec["_sources"],
        "source": dict(spec.get("source") or {
            "pdf": spec["_sources"][0]["path"],
            "sha256": spec["_sources"][0]["sha256"]}),
        "geometry": spec["geometry"],
        "mode": spec.get("mode"),
        "policy": spec["policy"],
        "runtime_versions": versions,
        "settings": settings,
        "scope": spec["scope"],
        "schedule": spec.get("schedule"),
        "calibrations": {
            calibration_key(k[0], k[1], k[2], multi): cal
            for k, cal in calibrations.items()},
        "regions": results,
        "types": types,
        "totals": {"project_sf": total, "unit_count": unit_total},
        "audit": audit.items,
        "callouts": audit.callouts,
        "coverage_ledger": coverage_ledger or [],
        "run_status": None,  # set by measure.finish
        "status": None,      # set by measure.finish (complete/.../stopped)
        "review_status": review_status,
        "declarations": spec["policy"].get("declarations", []),
        "geometry_page_classes": {
            f"{sid}:{p['page']}": p["preflight"]["class"]
            for sid, geo in (geometry_map or {}).items()
            for p in geo["pages"]},
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
