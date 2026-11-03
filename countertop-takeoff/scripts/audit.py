"""Completeness + reconciliation audit (V2).

V1's audit unconditionally added a passing "coverage" item, so a job spec
with every Type B job deleted still passed at 114.75 SF, and empty region
lists passed at 0 SF. V2's audit:

  - verifies the geometry belongs to the hashed, approved source
  - requires EVERY source page to be dispositioned (measured with expected
    regions / intentionally_skipped with reason / blocked)
  - refuses to measure pages whose content class is not vector
  - resolves duplicate/revision-conflicted sheets: at most one page per
    sheet id may be measured, and every conflict page needs a disposition
  - compares planned region ids vs completed results exactly (missing OR
    unplanned = fail)
  - reconciles the schedule: every type needs a measured region, variant
    allocation must not double-count, stated totals must match
  - checks recheck deviations, expected ranges, calibration coverage

Audit items carry pass/warn/fail; any fail makes the run NOT ready.
"""

import os
import statistics

import preflight_lib as pl
from regions import check_duplicate_boundaries, check_overlaps
from spec_schema import SpecError, TakeoffError

RECHECK_TOLERANCE_PCT = 2.0


def validate_source_and_geometry(spec, geometry):
    """The frozen source: the PDF on disk and the geometry must both carry
    the approved digest."""
    want = spec["source"]["sha256"]
    pdf = spec["source"]["pdf"]
    if not os.path.exists(pdf):
        raise SpecError(f"source PDF not found: {pdf}")
    actual = pl.file_sha256(pdf)
    if actual != want:
        raise SpecError(
            f"source PDF hash mismatch: approved {want[:16]}..., on disk"
            f" {actual[:16]}... - the approved scope is frozen to a digest;"
            " re-approve the pack if the file changed")
    gsrc = (geometry.get("source") or {}).get("sha256")
    if gsrc != want:
        raise SpecError(
            "geometry file was extracted from a different source (geometry"
            f" {str(gsrc)[:16]}... != approved {want[:16]}...) - re-run"
            " extract_geometry.py on the approved PDF")
    page_count = (geometry.get("source") or {}).get("page_count")
    if not isinstance(page_count, int) or page_count < 1:
        raise SpecError("geometry does not record the source page count")
    return page_count


class Audit:
    """Collects pass/warn/fail items."""

    def __init__(self):
        self.items = []

    def add(self, check, status, detail):
        self.items.append({"check": check, "status": status, "detail": detail})

    @property
    def failed(self):
        return [i for i in self.items if i["status"] == "fail"]

    @property
    def warned(self):
        return [i for i in self.items if i["status"] == "warn"]


def audit_scope(spec, geometry, audit):
    """Scope ledger + preflight resolution + planned-vs-completed."""
    page_count = validate_source_and_geometry(spec, geometry)
    pages_by_no = {p["page"]: p for p in geometry["pages"]}
    disp = {e["page"]: e for e in spec["scope"]["pages"]}
    missing = [p for p in range(1, page_count + 1) if p not in disp]
    if missing:
        audit.add("scope complete", "fail",
                  f"pages {missing} have no disposition - every source page"
                  " must be measured, intentionally_skipped (with reason), or"
                  " blocked")
    for e in spec["scope"]["pages"]:
        pno = e["page"]
        gp = pages_by_no.get(pno)
        cls = gp["preflight"]["class"] if gp else "not_extracted"
        if e["disposition"] == "blocked":
            audit.add("blocked page", "fail",
                      f"page {pno} is blocked: {e.get('reason', '')} - blocked"
                      " pages prevent completion")
        elif e["disposition"] == "measured":
            if gp is None:
                audit.add("measured page", "fail",
                          f"page {pno} is measured but its geometry was never"
                          " extracted")
            elif cls not in pl.VECTOR_CLASSES:
                audit.add("measurable page", "fail",
                          f"page {pno} is class {cls!r}, not vector-measurable"
                          f" ({'; '.join(gp['preflight']['class_reasons'])})"
                          " - text presence never establishes vector"
                          " suitability")
            else:
                audit.add("measured page", "pass",
                          f"page {pno} ({gp.get('sheet') or '?'}, class {cls},"
                          f" rot {gp['identity']['rotation']}) expects"
                          f" {len(e['expected_regions'])} region(s)")
        else:
            audit.add("skipped page", "pass",
                      f"page {pno} intentionally_skipped: {e.get('reason', '')[:110]}")
    # duplicate/revision conflicts: at most one measured page per sheet id
    sheets = {}
    for gp in geometry["pages"]:
        if gp.get("sheet"):
            sheets.setdefault(gp["sheet"], []).append(gp)
    for sheet, group in sorted(sheets.items()):
        fps = {gp["preflight"]["fingerprint"] for gp in group}
        measured = [gp["page"] for gp in group
                    if disp.get(gp["page"], {}).get("disposition") == "measured"]
        if len(fps) > 1:
            if len(measured) > 1:
                audit.add("revision resolved", "fail",
                          f"sheet {sheet} appears on pages {sorted(measured)}"
                          " with DIFFERENT content and more than one is"
                          " measured - pick the authoritative revision")
            else:
                audit.add("revision resolved", "pass",
                          f"sheet {sheet} conflict pages"
                          f" {[gp['page'] for gp in group]} have exactly one"
                          f" measured page {measured or 'NONE'}; others must be"
                          " skipped with a supersession reason")
        elif len(measured) > 1:
            audit.add("revision resolved", "fail",
                      f"sheet {sheet} pages {sorted(measured)} are identical"
                      " duplicates but more than one is measured")
    return pages_by_no


def audit_planned_vs_completed(spec, results, pages_by_no, audit):
    """Expected region ids per measured page must match completed exactly."""
    base_ids = {r["region_id"] for r in results if r["kind"] == "base"}
    recheck_ids = {r["region_id"] for r in results if r["kind"] == "recheck"}
    for e in spec["scope"]["pages"]:
        if e["disposition"] != "measured":
            continue
        expected = set(e["expected_regions"])
        on_page = {r["region_id"] for r in results if r["page"] == e["page"]}
        got_base = on_page & base_ids
        missing = expected - got_base
        extra = got_base - expected
        if missing or extra:
            audit.add("planned vs completed", "fail",
                      f"page {e['page']}: planned {sorted(expected)},"
                      f" completed {sorted(got_base)}"
                      + (f"; MISSING {sorted(missing)}" if missing else "")
                      + (f"; UNPLANNED {sorted(extra)}" if extra else ""))
        else:
            qa = sorted(on_page & recheck_ids)
            audit.add("planned vs completed", "pass",
                      f"page {e['page']}: all {len(expected)} planned region(s)"
                      f" measured" + (f" (+QA rechecks {qa})" if qa else ""))


def audit_schedule(spec, results, audit):
    """Every type/variant measured exactly once; totals reconcile."""
    sched = spec.get("schedule")
    if sched is None:
        audit.add("schedule", "pass",
                  "individual_rooms mode: no multiplier schedule; each region"
                  " counts once")
        return {}
    base = [r for r in results if r["kind"] == "base"]
    for t in sched["types"]:
        name = t["type"]
        std = [r for r in base if r["type"] == name and r["variant"] is None]
        incl = [v for v in sched.get("variants", [])
                if v["type"] == name and v["included_in_parent_total"]]
        std_units = t["count"] - sum(v["count"] for v in incl)
        if std_units < 0:
            audit.add("schedule coverage", "fail",
                      f"type {name}: variant counts exceed the type count"
                      f" ({t['count']})")
        elif std_units == 0:
            audit.add("schedule coverage", "pass",
                      f"type {name}: all {t['count']} unit(s) are declared as"
                      " variants; no standard region needed")
        elif not std:
            audit.add("schedule coverage", "fail",
                      f"type {name}: schedule count {t['count']} but NO"
                      " standard region measured - v1 shipped deleted scopes"
                      " because nothing cross-checked this")
        else:
            audit.add("schedule coverage", "pass",
                      f"type {name}: count {t['count']} = {std_units} standard"
                      + (f" + {sum(v['count'] for v in incl)} variant" if incl
                         else "")
                      + f" unit(s), {len(std)} standard region(s) measured"
                      f" (evidence: sheet {sched['sheet']}, page"
                      f" {sched['page']}, row {t['row_text'][:60]!r})")
    for v in sched.get("variants", []):
        vr = [r for r in base if r["type"] == v["type"] and r["variant"] == v["name"]]
        if not vr:
            audit.add("variant coverage", "fail",
                      f"variant {v['name']} of type {v['type']}: declared"
                      f" count {v['count']} but no region measured for it")
        else:
            audit.add("variant coverage", "pass",
                      f"variant {v['name']} of type {v['type']}: count"
                      f" {v['count']}, included_in_parent_total"
                      f" {v['included_in_parent_total']},"
                      f" measured separately (no double-count)")
    extras = [r for r in base if sched is not None
              and r["variant"] is None
              and r["type"] not in {t["type"] for t in sched["types"]}]
    if extras:
        audit.add("unplanned types", "fail",
                  "regions reference types outside the schedule: "
                  f"{sorted({r['type'] for r in extras})}")
    return sched


def reconcile_totals(sched, audit):
    """Stated floor/project totals must match the allocated counts."""
    if not sched:
        return None
    totals = sched.get("stated_totals") or {}
    per_floor = totals.get("per_floor") or {}
    unit_total = sum(t["count"] for t in sched["types"])
    unit_total += sum(v["count"] for v in sched.get("variants", [])
                      if not v["included_in_parent_total"])
    if "project" in totals and totals["project"] != unit_total:
        audit.add("schedule reconciliation", "fail",
                  f"allocated unit count {unit_total} != stated project total"
                  f" {totals['project']} - double-counted ADA-style subsets or"
                  " missed rows")
    else:
        audit.add("schedule reconciliation", "pass",
                  f"allocated unit count {unit_total}"
                  + (f" == stated project total {totals['project']}"
                     if "project" in totals else " (no stated total given)"))
    if per_floor:
        floors = {}
        for t in sched["types"]:
            for fl, c in t.get("_floor_counts", {}).items():
                floors[fl] = floors.get(fl, 0) + c
        for v in sched.get("variants", []):
            if v["included_in_parent_total"]:
                continue
            for r in v.get("rows", []) or []:
                floors[r["floor"]] = floors.get(r["floor"], 0) + r["count"]
        for fl, stated in per_floor.items():
            got = floors.get(fl)
            if got != stated:
                audit.add("floor reconciliation", "fail",
                          f"floor {fl!r}: allocated {got} != stated"
                          f" {stated}")
            else:
                audit.add("floor reconciliation", "pass",
                          f"floor {fl!r}: allocated {got} == stated {stated}")
    return unit_total


def audit_region_checks(spec, results, calibrations, audit,
                        recheck_tolerance=RECHECK_TOLERANCE_PCT):
    """Per-region QA: ranges, calibration coverage, recheck deviations,
    duplicate/overlap within counted instances."""
    for r in results:
        key = (r["page"], r["viewport"])
        cal = calibrations.get(key)
        if cal is None:
            audit.add("region calibration", "fail",
                      f"region {r['region_id']}: no calibration for page"
                      f" {r['page']} viewport {r['viewport']!r}")
        if not r["expected_range_ok"]:
            audit.add("expected range", "fail",
                      f"region {r['region_id']}: {r['area_sf']:.2f} SF outside"
                      f" expected {r['expected_sf_range']} - wrong calibration"
                      " or wrong boundary")
        else:
            audit.add("expected range", "pass",
                      f"region {r['region_id']}: {r['area_sf']:.2f} SF within"
                      f" {r['expected_sf_range']} (factor"
                      f" {r['factor_pt_per_ft']:.4f} pt/ft, policy"
                      f" {r['gross_area_policy']})")
    dup = check_duplicate_boundaries(results)
    for e in dup:
        audit.add("duplicate boundaries", "fail", e)
    ov_err, ov_warn = check_overlaps(results)
    for e in ov_err:
        audit.add("instance overlap", "fail", e)
    for w in ov_warn:
        audit.add("instance overlap", "warn", w)
    base_by_id = {r["region_id"]: r for r in results if r["kind"] == "base"}
    for r in results:
        if r["kind"] != "recheck":
            continue
        base = base_by_id.get(r.get("of"))
        if base is None:
            audit.add("recheck", "fail",
                      f"recheck {r['region_id']}: base region"
                      f" {r.get('of')!r} missing")
            continue
        dev = (abs(r["area_sf"] - base["area_sf"]) / base["area_sf"] * 100.0
               if base["area_sf"] else 0.0)
        if dev > recheck_tolerance:
            audit.add("recheck", "fail",
                      f"recheck {r['region_id']}: {r['area_sf']:.2f} SF vs base"
                      f" {base['area_sf']:.2f} SF (dev {dev:.2f}% >"
                      f" {recheck_tolerance}%) - resolve before shipping")
        else:
            audit.add("recheck", "pass",
                      f"recheck {r['region_id']}: {r['area_sf']:.2f} SF vs base"
                      f" {base['area_sf']:.2f} SF (dev {dev:.2f}%)")


def aggregate_types(spec, results, audit):
    """Build the per-type totals. Returns (types, project_total_sf)."""
    base = [r for r in results if r["kind"] == "base"]
    rechecks = [r for r in results if r["kind"] == "recheck"]
    if not base:
        audit.add("measured scope", "fail", "no base regions were measured")
        return [], 0.0
    if spec.get("mode") == "individual_rooms":
        rows = []
        total = 0.0
        for r in sorted(base, key=lambda r: r["region_id"]):
            rows.append({"room_type": r["type"], "variant": r["variant"],
                         "region_id": r["region_id"], "sf": r["area_sf"],
                         "count": 1, "extended_sf": round(r["area_sf"], 2),
                         "regions": [r]})
            total += r["area_sf"]
        audit.add("totals", "pass",
                  f"individual_rooms: {len(rows)} room(s) summed independently"
                  f" = {total:.2f} SF (count 1 each, by mode declaration)")
        return rows, round(total, 2)
    sched = spec["schedule"]
    types = []
    total = 0.0
    for t in sched["types"]:
        name = t["type"]
        std = [r for r in base if r["type"] == name and r["variant"] is None]
        incl = [v for v in sched.get("variants", [])
                if v["type"] == name and v["included_in_parent_total"]]
        std_units = t["count"] - sum(v["count"] for v in incl)
        sf_unit = round(sum(r["area_sf"] for r in std), 4)
        ext = sf_unit * std_units
        rows = [{"room_type": name, "variant": None, "region_id": r["region_id"],
                 "sf": r["area_sf"], "count": std_units,
                 "extended_sf": round(r["area_sf"] * std_units, 2),
                 "regions": [r]} for r in std]
        for v in sched.get("variants", []):
            if v["type"] != name:
                continue
            vr = [r for r in base if r["type"] == name
                  and r["variant"] == v["name"]]
            vsf = round(sum(r["area_sf"] for r in vr), 4)
            ext += vsf * v["count"]
            rows += [{"room_type": name, "variant": v["name"],
                      "region_id": r["region_id"], "sf": r["area_sf"],
                      "count": v["count"],
                      "extended_sf": round(r["area_sf"] * v["count"], 2),
                      "regions": [r]} for r in vr]
        types.append({"room_type": name, "schedule_count": t["count"],
                      "std_units": std_units, "sf_per_unit": sf_unit,
                      "extended_sf": round(ext, 2), "rows": rows})
        total += ext
    total = round(total, 2)
    units = sum(t["schedule_count"] for t in sched["types"]) + sum(
        v["count"] for v in sched.get("variants", [])
        if not v["included_in_parent_total"])
    audit.add("totals", "pass",
              f"repeated_types: {len(types)} type(s), {units} unit(s),"
              f" project total {total:.2f} SF")
    return types, total
