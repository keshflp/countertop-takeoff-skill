"""Completeness + reconciliation audit (V3).

V2 established: geometry belongs to the hashed approved source; every page
dispositioned; only vector content measured by the vector route; planned vs
completed compared exactly; schedule counts evidence-backed; rechecks/ranges
checked.

V3 changes (graduated degradation + tolerant identity):
  - pages are keyed (source_id, page_number); multi-source jobs supported
  - sheet identity conflicts / index gaps are CALLOUTS, never silent scope
    drops (sheet_identity.audit_identity)
  - most per-region failures become UNRESOLVED quantities + callouts instead
    of whole-job refusals; only the three catastrophic stops (no valid
    calibration anywhere, no schedule and no repeatable pattern, source
    integrity mismatch) stop the job (measure.py owns the stop decisions)
  - the coverage ledger reconciles every inventoried item to
    measured | package_excluded | superseded | unresolved
"""

import os
import re
import statistics

import preflight_lib as pl
import sheet_identity
from regions import check_duplicate_boundaries, check_overlaps
from spec_schema import SpecError, TakeoffError

RECHECK_TOLERANCE_PCT = 2.0
_NUM_TOKEN_RE = re.compile(r"\d+(?:\.\d+)?")


def _count_supported_by_evidence(count, box_texts, rows=None, row_text=""):
    """Numeric correspondence, not word existence (P0.2): the count VALUE
    must be supported by the quoted evidence. A word box containing '3'
    must not support a count of 30. Accepted shapes:
      - the count appears as an exact NUMBER token in the quoted box texts
        or the quoted row text; or
      - every quoted box text is a PURE integer and they SUM to the count
        (floor cells quoted per floor, e.g. '5'+'5' -> 10); or
      - the type declares floor rows and EVERY row's count appears as a
        number token in its own quoted text (and the rows sum to the
        count, which validate_schedule_consistency enforces separately).
    Returns (ok, reason)."""
    texts = [str(t) for t in (box_texts or []) if str(t).strip()]
    if row_text:
        texts.append(str(row_text))
    tokens = [m.group(0) for t in texts
              for m in _NUM_TOKEN_RE.finditer(t)]
    for tok in tokens:
        try:
            if float(tok) == float(count):
                return True, f"count {count} appears as a quoted number"
        except (ValueError, OverflowError):
            continue
    box_only = [str(t).strip() for t in (box_texts or []) if str(t).strip()]
    if box_only and all(re.fullmatch(r"\d+", t) for t in box_only):
        total = sum(int(t) for t in box_only)
        if total == int(count):
            return True, (f"count {count} equals the sum of the quoted"
                          f" row values {box_only}")
    if rows:
        joined = " ".join(texts)
        row_tokens = {m.group(0) for m in _NUM_TOKEN_RE.finditer(joined)}
        supported_rows = []
        for r in rows:
            rtxt = str(r.get("row_text") or "")
            rtoks = {m.group(0) for m in _NUM_TOKEN_RE.finditer(rtxt)} \
                | row_tokens
            hit = any(float(tok) == float(r["count"]) for tok in rtoks)
            supported_rows.append(hit)
        if all(supported_rows) and sum(r["count"] for r in rows) == int(count):
            return True, (f"count {count} equals the quoted floor rows"
                          f" {[r['count'] for r in rows]}, each value quoted"
                          " in the evidence")
    return False, (f"quoted evidence {[t[:20] for t in texts]} does not"
                   f" contain the count {count} (numeric correspondence"
                   " required)")


def validate_source_and_geometry(spec, geometry_map):
    """The frozen sources: each source file on disk and its geometry
    payload must both carry the declared digest (integrity mismatch = one
    of the three catastrophic stops). V4: CAD and image sources are
    re-hashed TOO - a moved/edited DXF must never silently produce results
    from cached geometry (P0.4)."""
    for src in spec["_sources"]:
        want = src["sha256"]
        path = src["path"]
        if not os.path.exists(path):
            raise SpecError(f"source file not found: {path}")
        actual = pl.file_sha256(path)
        if actual != want:
            raise SpecError(
                f"source file hash mismatch ({src['source_id']}):"
                f" approved {want[:16]}..., on disk {actual[:16]}... - the"
                " scope is frozen to digests; re-run intake/preflight if"
                " the file changed")
        geo = geometry_map.get(src["source_id"])
        if geo is None:
            raise SpecError(
                f"no geometry payload for source {src['source_id']!r} -"
                " extract/import it before measuring")
        gsrc = (geo.get("source") or {}).get("sha256")
        if gsrc != want:
            raise SpecError(
                f"geometry for source {src['source_id']!r} was extracted from"
                f" a different file (geometry {str(gsrc)[:16]}... != approved"
                f" {want[:16]}...) - re-run the extractor on the approved"
                " source")
        page_count = (geo.get("source") or {}).get("page_count")
        if not isinstance(page_count, int) or page_count < 1:
            raise SpecError(
                f"geometry for {src['source_id']!r} does not record the"
                " source page count")
    return {s["source_id"] for s in spec["_sources"]}


class Audit:
    """Collects pass/warn/fail items + callouts.

    A CALLOUT is a degraded-but-disclosed finding: the affected scope,
    source pages, the reason, and which quantity fields stay blank. Any
    callout makes the run `complete_with_callouts` (never silent). A FAIL
    makes it `stopped`.
    """

    def __init__(self):
        self.items = []
        self.callouts = []

    def add(self, check, status, detail):
        self.items.append({"check": check, "status": status, "detail": detail})

    def add_callout(self, scope, detail, blank_fields=None, pages=None,
                    source_id=None):
        """Record a graduated-degradation callout (audit severity: warn)."""
        entry = {"scope": scope, "reason": detail,
                 "blank_fields": blank_fields or [],
                 "source": ({"source_id": source_id, "pages": pages}
                            if (source_id or pages) else None)}
        self.callouts.append(entry)
        self.items.append({"check": f"callout: {scope}", "status": "warn",
                           "detail": detail})

    @property
    def failed(self):
        return [i for i in self.items if i["status"] == "fail"]

    @property
    def warned(self):
        return [i for i in self.items if i["status"] == "warn"]


def audit_scope(spec, geometry_map, audit):
    """Scope ledger + preflight resolution + tolerant sheet identity.
    Returns pages_by_no keyed (source_id, page)."""
    validate_source_and_geometry(spec, geometry_map)
    pages_by_no = {}
    for sid, geo in geometry_map.items():
        for p in geo["pages"]:
            pages_by_no[(sid, p["page"])] = p
    disp = {(e.get("source_id") or spec["_sources"][0]["source_id"],
             e["page"]): e for e in spec["scope"]["pages"]}
    declared_pages = {(s["source_id"], p["page"]) for s in spec["_sources"]
                      for p in geometry_map.get(s["source_id"],
                                                {"pages": []})["pages"]}
    missing = sorted(k for k in declared_pages if k not in disp)
    if missing:
        audit.add_callout(
            "coverage", f"pages {missing} have NO scope disposition - every"
            " inventoried item on them is recorded unresolved (blank"
            " quantities + this callout), never silently dropped",
            blank_fields=["all quantities"], pages=[k[1] for k in missing])
    for e in spec["scope"]["pages"]:
        key = (e.get("source_id"), e["page"])
        pno = e["page"]
        gp = pages_by_no.get(key)
        cls = gp["preflight"]["class"] if gp else "not_extracted"
        if e["disposition"] == "measured":
            if gp is None:
                audit.add("measured page", "fail",
                          f"page {pno} of source {key[0]!r} is measured but"
                          " its geometry was never extracted")
            else:
                # V3: page class is advisory; per-region measurability is
                # decided by content regions + route in measure.py
                regions = gp.get("content_regions") or []
                vec = [r for r in regions if r.get("kind") == "vector"]
                audit.add(
                    "measured page", "pass",
                    f"page {pno} ({gp.get('sheet') or '?'}, class {cls},"
                    f" rot {gp['identity']['rotation']}) expects"
                    f" {len(e['expected_regions'])} region(s);"
                    f" {len(vec)} vector content region(s),"
                    f" {len(regions) - len(vec)} raster region(s)")
        elif e["disposition"] == "superseded":
            audit.add("superseded page", "pass",
                      f"page {pno} superseded: {e.get('reason', '')[:110]}")
        else:
            audit.add("skipped page", "pass",
                      f"page {pno} intentionally_skipped:"
                      f" {e.get('reason', '')[:110]}")
    # tolerant sheet identity per source (callouts, never silent drops)
    index_sheets = (spec.get("sheet_index") or {}).get("lists") or []
    for sid, geo in geometry_map.items():
        scope_by_page = {e["page"]: e for e in spec["scope"]["pages"]
                         if (e.get("source_id")
                             or spec["_sources"][0]["source_id"]) == sid}
        sheet_identity.audit_identity(
            geo["pages"], scope_by_page, index_sheets,
            lambda scope, detail, _sid=sid: audit.add_callout(
                scope, detail, source_id=_sid))
    return pages_by_no


def audit_planned_vs_completed(spec, results, pages_by_no, audit):
    """Expected region ids per measured page must match completed exactly
    (per source page; missing = unresolved callout, unplanned = fail)."""
    base_ids = {r["region_id"] for r in results if r["kind"] == "base"}
    recheck_ids = {r["region_id"] for r in results if r["kind"] == "recheck"}
    unresolved_ids = {r["region_id"] for r in results
                      if r.get("status") == "unresolved"}
    for e in spec["scope"]["pages"]:
        if e["disposition"] != "measured":
            continue
        expected = set(e["expected_regions"])
        on_page = {r["region_id"] for r in results
                   if r["page"] == e["page"]
                   and (r.get("source_id") == e.get("source_id") or
                        e.get("source_id") is None)}
        got_base = on_page & base_ids
        missing = expected - got_base - unresolved_ids
        extra = got_base - expected
        if unresolved_ids & expected:
            audit.add_callout(
                "coverage",
                f"page {e['page']}: planned region(s)"
                f" {sorted(unresolved_ids & expected)} could not be measured"
                " - their quantity fields stay blank",
                blank_fields=["area_sf", "edge_lf"], pages=[e["page"]])
        if missing:
            # planned regions with no result record: treated as unresolved
            # (blank quantities + callout), never silently dropped
            audit.add_callout(
                "coverage",
                f"page {e['page']}: planned region(s) {sorted(missing)}"
                " produced no measurement record - recorded unresolved"
                " (blank quantities)",
                blank_fields=["area_sf", "edge_lf"], pages=[e["page"]])
        if extra:
            audit.add("planned vs completed", "fail",
                      f"page {e['page']}: UNPLANNED region(s) measured:"
                      f" {sorted(extra)} - measuring scope you did not plan"
                      " cannot be excused after the fact")
        if not missing and not extra:
            qa = sorted(on_page & recheck_ids)
            audit.add("planned vs completed", "pass",
                      f"page {e['page']}: all {len(expected)} planned region(s)"
                      f" measured" + (f" (+QA rechecks {qa})" if qa else ""))


def audit_schedule(spec, results, audit):
    """Every type/variant measured or disclosed-unresolved; totals
    reconcile; declared evidence conflicts become callouts."""
    sched = spec.get("schedule")
    for problem in spec.get("_schedule_problems") or []:
        audit.add_callout("schedule evidence conflict", problem,
                          blank_fields=[],
                          pages=[sched.get("page") if sched else None])
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
            audit.add_callout(
                f"schedule coverage type {name}",
                f"schedule count {t['count']} but NO standard region measured"
                " - the type's SF stays blank and its count is excluded from"
                " extensions (never defaulted to 1)",
                blank_fields=["area_sf", "extended_sf"],
                pages=[sched.get("page")])
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
            audit.add_callout(
                f"variant coverage {v['name']}",
                f"variant {v['name']} of type {v['type']}: declared count"
                f" {v['count']} but no region measured - its SF stays blank",
                blank_fields=["area_sf", "extended_sf"],
                pages=[sched.get("page")])
        else:
            audit.add("variant coverage", "pass",
                      f"variant {v['name']} of type {v['type']}: count"
                      f" {v['count']}, included_in_parent_total"
                      f" {v['included_in_parent_total']},"
                      f" measured separately (no double-count)")
    piece_regions = {p.get("region_id") for p in spec.get("_pieces") or []}
    extras = [r for r in base if sched is not None
              and r["variant"] is None
              and r["type"] not in {t["type"] for t in sched["types"]}
              and r["region_id"] not in piece_regions]
    if extras:
        audit.add("unplanned types", "fail",
                  "regions reference types outside the schedule (and no"
                  " declared piece covers them): "
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
        audit.add_callout(
            "schedule reconciliation",
            f"allocated unit count {unit_total} != stated project total"
            f" {totals['project']} - resolve from evidence (floor rows, ADA"
            " columns, addenda); the per-row quoted counts stay authoritative"
            " until contradicted, and the disagreement is disclosed here",
            blank_fields=[], pages=[sched.get("page")])
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
                audit.add_callout(
                    f"floor reconciliation {fl}",
                    f"floor {fl!r}: allocated {got} != stated {stated} -"
                    " resolve from the floor rows or withhold the difference",
                    blank_fields=[], pages=[sched.get("page")])
            else:
                audit.add("floor reconciliation", "pass",
                          f"floor {fl!r}: allocated {got} == stated {stated}")
    return unit_total


LEDGER_STATES = {"measured", "package_excluded", "superseded", "unresolved",
                 "included_scope"}


def build_coverage_ledger(spec, results, audit, results_by_id=None,
                          resolved=None):
    """Reconcile EVERY inventoried item to exactly one ledger state (P0.1,
    completed per P0.3):

      measured | package_excluded | superseded | unresolved | included_scope

    Inventory covers the COMPLETE set: schedule types/variants, every
    room in the plan-tag inventory (a room covered by NO assembly - the
    hotel-203 case - is its own unresolved entry), every scope-dispositioned
    page (superseded pages appear here, not just in callouts), assemblies
    and pieces. Entries distinguish measured evidence from included scope:
    variants counted inside a parent total carry included_scope; package-
    excluded GR entries carry package_excluded with their measured-evidence
    detail.
    """
    resolved = resolved or {"assemblies": {}, "pieces": {}}
    ledger = []
    excluded_types = set((spec.get("policy") or {}).get(
        "package_excluded_types") or [])
    by_type = {}
    for r in results:
        if r["kind"] != "base":
            continue
        by_type.setdefault((r.get("type"), r.get("variant")), []).append(r)

    def region_state(r):
        if r.get("status") == "unresolved":
            return "unresolved"
        return "measured"

    if spec.get("mode") == "individual_rooms":
        for r in results:
            if r["kind"] == "base":
                ledger.append({
                    "item": r["region_id"], "kind": "room",
                    "source": {"source_id": r.get("source_id"),
                               "pages": [r["page"]]},
                    "state": region_state(r),
                    "detail": (r.get("unresolved_reason", "")[:120]
                               if r.get("status") == "unresolved"
                               else f"{r['area_sf']:.2f} SF measured"),
                })
    else:
        sched = spec.get("schedule") or {"types": []}
        for t in sched.get("types", []):
            name = t["type"]
            rows = by_type.get((name, None), [])
            measured_rows = [r for r in rows if r.get("status") !=
                             "unresolved"]
            evidence_ok = t.get("_evidence_ok") is not False
            if name in excluded_types:
                state, detail = "package_excluded", (
                    "count known but excluded by policy; reported separately")
            elif not measured_rows:
                state = "unresolved"
                detail = ("schedule count present but no region measured -"
                          " SF blank")
            elif not evidence_ok:
                state = "unresolved"
                detail = ("measured SF but unsupported schedule count -"
                          " extension withheld")
            else:
                state, detail = "measured", (
                    f"{len(measured_rows)} region(s) measured with schedule"
                    " evidence")
            ledger.append({"item": f"type {name} x{t['count']}",
                           "kind": "type",
                           "source": {"pages": [sched.get("page")]},
                           "state": state, "detail": detail})
        for v in sched.get("variants", []):
            key = (v["type"], v["name"])
            rows = by_type.get(key, [])
            measured_rows = [r for r in rows
                             if r.get("status") != "unresolved"]
            if v.get("_evidence_ok") is False:
                state = "unresolved"
                detail = ("variant evidence unsupported - extension"
                          " withheld")
            elif v["included_in_parent_total"]:
                # counted INSIDE the parent total: included scope, not a
                # separate measured count
                state = "included_scope"
                detail = (f"{len(measured_rows)} region(s) measured; count"
                          " included in the parent total (subtracted from"
                          " it), never added again")
            elif measured_rows:
                state, detail = "measured", (
                    f"{len(measured_rows)} region(s) measured")
            else:
                state = "unresolved"
                detail = "declared but no region measured - SF blank"
            ledger.append({
                "item": f"variant {v['type']}:{v['name']} x{v['count']}",
                "kind": "variant",
                "source": {"pages": [sched.get("page")]},
                "state": state, "detail": detail,
            })
        for r in results:
            if r["kind"] != "base":
                continue
            ledger.append({
                "item": r["region_id"], "kind": "region",
                "source": {"source_id": r.get("source_id"),
                           "pages": [r["page"]]},
                "state": region_state(r),
                "detail": (r.get("unresolved_reason", "")[:120]
                           if r.get("status") == "unresolved"
                           else f"{r['area_sf']:.2f} SF"),
            })
    # superseded pages appear in the ledger, not only in callouts (P0.3:
    # the COMPLETE inventory)
    for e in spec.get("scope", {}).get("pages", []):
        if e.get("disposition") == "superseded":
            ledger.append({
                "item": (f"page {e.get('source_id') + ':' if e.get('source_id')
                          else ''}{e['page']}"
                         + (f" ({e.get('sheet')})" if e.get("sheet") else "")),
                "kind": "page",
                "source": {"source_id": e.get("source_id"),
                           "pages": [e["page"]]},
                "state": "superseded",
                "detail": (e.get("reason") or "")[:110],
            })
    # every inventoried ROOM reconciles to the assembly that covers it
    inv = ((spec.get("schedule") or {}).get("room_inventory") or {})
    asm_rooms = {}
    for arow in resolved.get("assemblies", {}).values():
        if arow.get("room"):
            asm_rooms[arow["room"]] = arow
    for room in inv.get("rooms") or []:
        arow = asm_rooms.get(room["room"])
        if arow is None:
            ledger.append({
                "item": f"room {room['room']} ({room['type']})",
                "kind": "room",
                "source": {"pages": [room["page"]]},
                "state": "unresolved",
                "detail": "inventoried but covered by NO assembly -"
                          " quantities blank (never defaulted)",
            })
        else:
            ledger.append({
                "item": f"room {room['room']} ({room['type']})",
                "kind": "room",
                "source": {"pages": [room["page"]]},
                "state": ("package_excluded"
                          if arow["state"] == "package_excluded"
                          else ("measured" if arow.get("ea")
                                else "unresolved")),
                "detail": ("covered by assembly " + arow["assembly_id"]
                           + ("; package-excluded, reported separately"
                              if arow["state"] == "package_excluded"
                              else (f" EA {arow.get('ea')}"
                                    if arow.get("ea") is not None
                                    else " EA withheld"))),
            })
    # assemblies + pieces reconcile into the same ledger from the resolved
    # model (measured evidence vs included scope vs package exclusion)
    for arow in resolved.get("assemblies", {}).values():
        state = arow["state"]
        if state == "package_excluded":
            detail = (("measured evidence present" if arow.get("ea")
                       is not None else "EA unresolved")
                      + "; package rule excludes it from main totals -"
                        " reported separately (included-scope distinction)")
        elif arow.get("ea") is None:
            state = "unresolved"
            detail = arow.get("basis") or "EA withheld"
        else:
            detail = f"{arow.get('basis')} (resolved)"
        ledger.append({"item": f"assembly {arow['assembly_id']}",
                       "kind": "assembly",
                       "source": {"pages": sorted(
                           {s.get("page")
                            for s in arow.get("sources", [])
                            if s.get("page")})},
                       "state": state, "detail": detail})
    for prow in resolved.get("pieces", {}).values():
        state = prow["state"]
        if prow.get("orphan"):
            state = "unresolved"
        elif prow.get("extension_sf") is None and state == "measured":
            state = "unresolved"
        detail = (f"route {prow['route']}; EA {prow.get('ea')}"
                  if prow.get("ea") is not None
                  else f"route {prow['route']}; EA withheld")
        if prow.get("extension_sf") is None:
            detail += "; extension blank"
        ledger.append({"item": f"piece {prow['piece_id']}", "kind": "piece",
                       "source": {"pages": sorted(
                           {l.get("page")
                            for l in (prow.get("source_links") or {}).values()
                            if l.get("page")})},
                       "state": state, "detail": detail})
    bad = [e for e in ledger if e["state"] not in LEDGER_STATES]
    if bad:
        audit.add("coverage ledger", "fail",
                  f"ledger entries with an invalid state: {bad}")
    states = {}
    for e in ledger:
        states[e["state"]] = states.get(e["state"], 0) + 1
    audit.add("coverage ledger", "pass",
              f"every inventoried item reconciled: {states}")
    return ledger


def resolve_assembly_ea(spec, a):
    """Validated EA for ONE assembly, resolved independently (P0.1).

    enumerated            -> 1
    room_type_count       -> the schedule count for its type, MINUS the
                             counts of INCLUDED variants (an ADA room inside
                             the parent type count is SUBTRACTED from the
                             standard EA, never added again on top)
    room_type_count+var   -> that variant's own count

    Returns (ea | None, basis). None = the count is unsupported (evidence
    withheld or reconciliation conflict): the BoQ EA stays blank, never
    guessed. Type-level withholding poisons standard assemblies AND
    variants that are included in the parent total; an ADDITIONAL variant
    with valid evidence of its own keeps its count.
    """
    qb = a["quantity_basis"]
    if qb["mode"] == "enumerated":
        return 1, "enumerated"
    sched = spec.get("schedule")
    if not sched:
        return None, "room_type_count (no schedule declared)"
    vname = qb.get("variant")
    t = next((x for x in sched["types"] if x["type"] == qb.get("type")), None)
    if t is None:
        return None, f"type {qb.get('type')!r} not in the schedule"
    if t.get("_evidence_ok") is False:
        return None, "schedule count unsupported (evidence withheld)"
    if vname:
        v = next((x for x in sched.get("variants", [])
                  if x["type"] == t["type"] and x["name"] == vname), None)
        if v is None:
            return None, f"variant {vname!r} not declared in the schedule"
        if v.get("_evidence_ok") is False:
            return None, "variant count unsupported (evidence withheld)"
        return v["count"], f"variant {vname} count {v['count']} (schedule)"
    incl = sum(v["count"] for v in sched.get("variants", [])
               if v["type"] == t["type"] and v["included_in_parent_total"]
               and v.get("_evidence_ok") is not False)
    count = t["count"] - incl
    if count < 0:
        return None, (f"included variant counts exceed the type count"
                      f" {t['count']}")
    suffix = (f" minus {incl} included variant(s)" if incl else "")
    return count, (f"room-type count {t['count']}{suffix}"
                   " (schedule-validated)")


def resolve_quantities(spec, results, audit, results_by_id=None):
    """ONE resolved quantity model (P0.1).

    Every deliverable total - project SF, type rows, BoQ totals, CSV grand
    total - is DERIVED from the records this function returns, so they
    cannot disagree. Rules:

      - each assembly's EA is resolved independently
        (resolve_assembly_ea); included variants are subtracted from the
        parent count, never added again
      - package scope is applied ONCE per assembly, regardless of
        aggregation branch
      - piece<->assembly membership is bidirectional: orphan pieces,
        pieces claimed by two assemblies, assembly piece-list entries with
        no piece record, and measured regions covered by NO piece are all
        flagged (callouts; the affected extensions stay blank)
      - partial known quantities survive: a piece with measured SF and a
        withheld EA keeps its SF and blanks only the extension
    """
    excluded = spec.get("_excluded_packages") or set()
    assemblies = spec.get("_assemblies") or []
    pieces = spec.get("_pieces") or []
    resolved = {"assemblies": {}, "pieces": {}, "orphans": [],
                "measured_orphans": [], "membership_problems": [],
                "project_total_sf": 0.0, "excluded_total_sf": 0.0}

    # ---- bidirectional membership ------------------------------------
    asm_ids = {a["assembly_id"] for a in assemblies}
    claims = {}
    for p in pieces:
        claims.setdefault(p["assembly_id"], []).append(p["piece_id"])
    for aid, pids in claims.items():
        if aid not in asm_ids:
            resolved["orphans"].extend(pids)
            resolved["membership_problems"].append(
                f"piece(s) {pids} reference assembly {aid!r} which is NOT"
                " declared - their extensions stay blank")
        dupes = sorted({pid for pid in pids if pids.count(pid) > 1})
        if dupes:
            resolved["membership_problems"].append(
                f"assembly {aid!r} lists piece(s) {dupes} more than once")
    seen_claim = {}
    for p in pieces:
        prev = seen_claim.get(p["piece_id"])
        if prev is not None and prev != p["assembly_id"]:
            resolved["membership_problems"].append(
                f"piece {p['piece_id']!r} is claimed by assemblies {prev!r}"
                f" and {p['assembly_id']!r} - one piece cannot belong to two"
                " assemblies")
        seen_claim[p["piece_id"]] = p["assembly_id"]
    for a in assemblies:
        for pid in a.get("pieces") or []:
            if not any(p["piece_id"] == pid for p in pieces):
                resolved["membership_problems"].append(
                    f"assembly {a['assembly_id']!r} lists piece {pid!r} with"
                    " no piece record")
    for problem in resolved["membership_problems"]:
        audit.add_callout("piece/assembly membership", problem,
                          blank_fields=["extension_sf"])

    # ---- measured regions covered by NO piece ------------------------
    if assemblies:
        covered = {p.get("region_id") for p in pieces if p.get("region_id")}
        for r in results:
            if (r["kind"] == "base" and r.get("status") != "unresolved"
                    and r["region_id"] not in covered):
                resolved["measured_orphans"].append(r["region_id"])
                audit.add_callout(
                    f"region {r['region_id']}",
                    "measured but covered by NO assembly/piece - excluded"
                    " from the resolved totals; add it to the job spec or"
                    " exclude it explicitly",
                    blank_fields=["extension_sf"], pages=[r["page"]],
                    source_id=r.get("source_id"))

    # ---- resolve every assembly independently ------------------------
    for a in assemblies:
        aid = a["assembly_id"]
        pkg = a["package"]
        excluded_asm = pkg in excluded
        count, basis = resolve_assembly_ea(spec, a)
        pages = sorted({s.get("page") for s in a.get("sources", [])
                        if s.get("page")})
        if excluded_asm:
            audit.add("package exclusion", "pass",
                      f"assembly {aid} ({a['type']}) is in excluded package"
                      f" {pkg!r} - reported separately, excluded from main"
                      " totals")
        elif count is None:
            audit.add_callout(
                f"assembly {aid}",
                f"quantity basis unresolved: {basis} - EA stays blank",
                blank_fields=["ea"], pages=pages,
                source_id=(a.get("sources") or [{}])[0].get("source_id"))
        resolved["assemblies"][aid] = {
            "assembly_id": aid, "room": a.get("room"), "type": a["type"],
            "variant": a.get("variant"), "package": pkg,
            "finish_tag": a.get("finish_tag"),
            "width_in": a.get("width_in"), "depth_in": a.get("depth_in"),
            "height_in": a.get("height_in"), "handing": a.get("handing"),
            "ea": count, "basis": basis,
            "state": ("package_excluded" if excluded_asm
                      else ("measured" if count else "unresolved")),
            "pieces": list(a.get("pieces") or []),
            "sources": a.get("sources") or [],
            "sf_per_instance": None, "extended_sf": None,
        }

    # ---- resolve every piece from the SAME counts --------------------
    for p in pieces:
        pid = p["piece_id"]
        aid = p["assembly_id"]
        arow = resolved["assemblies"].get(aid)
        orphan = arow is None
        ea = None if orphan else arow["ea"]
        state = "unresolved" if orphan else arow["state"]
        blank = []
        sf = None
        dims = {}
        factor = None
        policy = None
        region_meta = None
        if p["route"] == "geometry":
            r = (results_by_id or {}).get(p.get("region_id"))
            if r is None or r.get("status") == "unresolved":
                blank.append("sf")
            else:
                sf = r["area_sf"]
                factor = r.get("factor_pt_per_ft") or r.get("factor_px_per_ft")
                policy = r.get("gross_area_policy")
                region_meta = {"region_id": r["region_id"],
                               "sheet": r.get("sheet") or "?",
                               "page": r.get("page"),
                               "viewport": r.get("viewport") or "main",
                               "source_id": r.get("source_id"),
                               "factor": factor, "policy": policy}
        else:
            d = p.get("dims_in") or {}
            dims = {k: d.get(k) for k in ("width", "depth", "thickness",
                                          "height")}
            if d.get("width") is None or d.get("depth") is None:
                blank.append("sf")
            else:
                sf = round(d["width"] * d["depth"] / 144.0, 4)
                policy = "stated dims"
                region_meta = {"region_id": None, "sheet": "?", "page": "",
                               "viewport": "stated", "source_id": None,
                               "factor": None, "policy": policy}
        edges = {}
        edge_blank = []
        edge_runs_by_profile = {}
        for run in p.get("edge_runs") or []:
            prof = run["profile"]
            entry = edge_runs_by_profile.setdefault(
                prof, {"lf": 0.0, "complete": True, "exposures": []})
            entry["exposures"].append(run.get("exposure"))
            v = run.get("length_in")
            if v is None:
                # P0.3: an unknown edge blanks ITS profile's LF (never
                # folded into the known length of the same profile)
                entry["complete"] = False
                edge_blank.append(f"edge_lf:{prof}:{run.get('exposure')}")
                continue
            entry["lf"] += v / 12.0
        for prof, entry in edge_runs_by_profile.items():
            edges[prof] = (round(entry["lf"], 3) if entry["complete"]
                           else None)
        splash_lf = 0.0
        splash_sf = 0.0
        splash_lf_ok = True
        splash_sf_ok = True
        splash_detail = []
        for run in p.get("splash_runs") or []:
            ln = run.get("length_in")
            ht = run.get("height_in")
            splash_detail.append({"handing": run.get("handing"),
                                  "returns_in": run.get("returns_in"),
                                  "length_in": ln, "height_in": ht})
            if ln is None:
                splash_lf_ok = False
            else:
                splash_lf += ln / 12.0
            if ln is None or ht is None:
                splash_sf_ok = False   # blank, never a partial zero
            else:
                splash_sf += ln * ht / 144.0
        if not splash_lf_ok:
            blank.append("splash_lf")
        if not splash_sf_ok:
            blank.append("splash_sf")
        cutouts = {}
        for c in p.get("cutouts") or []:
            cutouts[c["kind"]] = cutouts.get(c["kind"], 0) + c["ea"]
        ext = (round(sf * ea, 4)
               if sf is not None and isinstance(ea, (int, float)) else None)
        if ext is None:
            blank.append("extension_sf")
        edge_ext = ({k: round(v * ea, 3) for k, v in edges.items()
                     if v is not None and ea is not None}
                    if ea is not None else None)
        splash_lf_ext = (round(splash_lf * ea, 3)
                         if splash_lf_ok and ea is not None else None)
        splash_sf_ext = (round(splash_sf * ea, 3)
                         if splash_sf_ok and ea is not None else None)
        cutouts_ext = ({k: v * ea for k, v in cutouts.items()}
                       if ea is not None else None)
        if blank:
            audit.add_callout(
                f"piece {pid}",
                "unresolved construction properties - fields stay blank"
                f" ({sorted(set(blank))})",
                blank_fields=sorted(set(blank)),
                pages=sorted({l.get("page")
                              for l in (p.get("source_links") or {}).values()
                              if l.get("page")}),
                source_id=next(iter((p.get("source_links") or {}).values()),
                               {}).get("source_id") if (
                                   p.get("source_links") or {}) else None)
        resolved["pieces"][pid] = {
            "piece_id": pid, "assembly_id": aid,
            "room": None if orphan else arow.get("room"),
            "type": None if orphan else arow.get("type"),
            "package": None if orphan else arow.get("package"),
            "finish_tag": p.get("finish_tag") or (
                None if orphan else arow.get("finish_tag")),
            "route": p["route"], "region_id": p.get("region_id"),
            "dims_in": dims, "sf": sf, "region_meta": region_meta,
            "edge_lf_by_profile": edges,
            "edge_blank_profiles": sorted({b.split(":")[1]
                                           for b in edge_blank}),
            "splash_lf": round(splash_lf, 3) if splash_lf_ok else None,
            "splash_sf": round(splash_sf, 3) if splash_sf_ok else None,
            "splash_detail": splash_detail,
            "cutouts_ea": cutouts or {},
            "ea": ea, "extension_sf": ext,
            "edge_lf_ext": edge_ext, "splash_lf_ext": splash_lf_ext,
            "splash_sf_ext": splash_sf_ext, "cutouts_ea_ext": cutouts_ext,
            "state": state, "blank_fields": sorted(set(blank)),
            "source_links": p.get("source_links") or {},
            "orphan": orphan,
        }

    # ---- assembly SF per instance + extensions (same records) --------
    pieces_by_asm = {}
    for prow in resolved["pieces"].values():
        pieces_by_asm.setdefault(prow["assembly_id"], []).append(prow)
    for arow in resolved["assemblies"].values():
        own = pieces_by_asm.get(arow["assembly_id"], [])
        sfs = [pp["sf"] for pp in own]
        if own and all(v is not None for v in sfs):
            arow["sf_per_instance"] = round(sum(sfs), 4)
            arow["extended_sf"] = (round(arow["sf_per_instance"] * arow["ea"], 4)
                                   if arow["ea"] is not None else None)
        elif own:
            audit.add_callout(
                f"assembly {arow['assembly_id']}",
                "piece SF incomplete - the assembly's SF/extension stays"
                " blank while its other quantities survive",
                blank_fields=["sf", "extension_sf"])

    # ---- totals from the SAME resolved records -----------------------
    for prow in resolved["pieces"].values():
        if prow["orphan"] or prow["state"] == "package_excluded":
            if prow["state"] == "package_excluded" and \
                    prow["extension_sf"] is not None:
                resolved["excluded_total_sf"] += prow["extension_sf"]
            continue
        if prow["extension_sf"] is not None:
            resolved["project_total_sf"] += prow["extension_sf"]
    resolved["project_total_sf"] = round(resolved["project_total_sf"], 4)
    resolved["excluded_total_sf"] = round(resolved["excluded_total_sf"], 4)
    return resolved


def build_assembly_boq(spec, audit, resolved=None):
    """ASSEMBLY BoQ rows: one per assembly with inch descriptions and the
    RESOLVED EA (P0.1). Package-excluded assemblies are reported separately
    (package_excluded), never silently dropped. All rows come from the ONE
    resolved model - they cannot disagree with the piece view."""
    excluded = spec.get("_excluded_packages") or set()
    rows = []
    for a in spec.get("_assemblies") or []:
        aid = a["assembly_id"]
        rrow = (resolved or {}).get("assemblies", {}).get(aid) or {}
        count = rrow.get("ea")
        basis = rrow.get("basis") or "unresolved"
        state = rrow.get("state") or "unresolved"
        rows.append({
            "assembly_id": aid, "room": a.get("room"),
            "type": a["type"], "variant": a.get("variant"),
            "package": a["package"], "finish_tag": a.get("finish_tag"),
            "width_in": a.get("width_in"), "depth_in": a.get("depth_in"),
            "height_in": a.get("height_in"), "handing": a.get("handing"),
            "ea": count, "basis": basis, "state": state,
            "sf_per_instance": rrow.get("sf_per_instance"),
            "extended_sf": rrow.get("extended_sf"),
            "pieces": list(a.get("pieces") or []),
            "sources": a.get("sources") or [],
        })
    if excluded and rows:
        audit.add("package exclusion", "pass",
                  f"excluded packages {sorted(excluded)} are reported"
                  " separately (state package_excluded), excluded from main"
                  " totals in EVERY aggregation branch")
    return rows


def build_piece_boq(spec, audit, resolved=None):
    """PIECE BoQ rows from the ONE resolved model: inch dims, gross/net SF,
    edge LF by profile, splash LF/SF (returns + handing preserved), cutout
    EA - and every extension multiplied by the SAME validated EA (P0.1:
    LF and cutout counts extend with assembly quantities, not just SF).
    Unknown dims keep the affected fields BLANK with a callout naming
    them; a piece with measured SF and a withheld EA keeps its SF."""
    rows = []
    for prow in (resolved or {}).get("pieces", {}).values():
        rows.append(dict(prow))
    return rows


def _box_matches_word(b, w):
    """A recorded evidence box references an actual source word: same text
    and intersection >= 50% of the smaller box."""
    if b.get("t") != w["t"]:
        return False
    ix = max(0.0, min(b["x1"], w["x1"]) - max(b["x0"], w["x0"]))
    iy = max(0.0, min(b["y1"], w["y1"]) - max(b["y0"], w["y0"]))
    inter = ix * iy
    amin = min((b["x1"] - b["x0"]) * (b["y1"] - b["y0"]),
               (w["x1"] - w["x0"]) * (w["y1"] - w["y0"]))
    return amin > 0 and inter / amin >= 0.5


def _withhold_type(audit, sched, name, reason):
    """Mark a type's count unsupported: aggregate_types excludes its
    extension (blank) and the callout names what was withheld."""
    for t in sched["types"]:
        if t["type"] == name:
            t["_evidence_ok"] = False
    audit.add_callout(
        f"schedule count type {name}", reason,
        blank_fields=["count", "extended_sf"], pages=[sched.get("page")])


def audit_schedule_evidence(spec, geometry_map, audit):
    """P0.3 evidence verification.

    text evidence: every recorded word box must reference an ACTUAL source
    word (same text, overlapping box) - quoted rows are not free-form.
    image evidence: the recorded crop hash must match a fresh render of the
    recorded crop bbox at the recorded zoom (proves WHICH pixels were
    read); uncertain cells are disclosed. Unsupported counts are withheld
    (blank) with callouts - never defaulted, never guessed.
    """
    sched = spec.get("schedule")
    if not sched:
        return
    ev = sched.get("evidence") or {"kind": "text"}
    sid = sched.get("source_id") or spec["_sources"][0]["source_id"]
    geo = geometry_map.get(sid) or {"pages": []}
    page = next((p for p in geo["pages"] if p["page"] == sched["page"]),
                None)
    if ev["kind"] == "text":
        if page is None:
            _withhold_all(audit, sched, sid,
                          f"schedule page {sched['page']} has no extracted"
                          " words to verify the quoted rows against")
            return
        words = page["words"]
        for t in sched["types"]:
            boxes = t.get("word_boxes") or []
            missing = [b.get("t") for b in boxes
                       if not any(_box_matches_word(b, w) for w in words)]
            if missing:
                _withhold_type(
                    audit, sched, t["type"],
                    f"evidence boxes {missing} do not reference actual words"
                    f" on source {sid!r} page {sched['page']} - the count is"
                    " unsupported and stays blank (fix the quote or re-read)")
                continue
            ok, why = _count_supported_by_evidence(
                t["count"], [b.get("t") for b in boxes],
                rows=t.get("rows") or [], row_text=t.get("row_text"))
            if not ok:
                # P0.2: a quoted word box containing '3' must not support a
                # count of 30 - numeric correspondence, not word existence
                _withhold_type(audit, sched, t["type"], why)
        for v in sched.get("variants", []):
            boxes = v.get("word_boxes") or []
            missing = [b.get("t") for b in boxes
                       if not any(_box_matches_word(b, w) for w in words)]
            if missing:
                v["_evidence_ok"] = False
                audit.add_callout(
                    f"variant evidence {v['name']}",
                    f"evidence boxes {missing} do not reference actual words"
                    f" on page {sched['page']} - re-read the variant row",
                    blank_fields=["count"], pages=[sched.get("page")])
                continue
            ok, why = _count_supported_by_evidence(
                v["count"], [b.get("t") for b in boxes],
                rows=v.get("rows") or [], row_text=v.get("row_text"))
            if not ok:
                # P0.2: invalid variant evidence -> its SF extension is
                # withheld, not silently added
                v["_evidence_ok"] = False
                audit.add_callout(
                    f"variant evidence {v['name']}", why,
                    blank_fields=["count", "extended_sf"],
                    pages=[sched.get("page")])
    else:  # image evidence
        problems = []
        if page is None:
            problems.append(f"schedule page {sched['page']} not extracted")
        else:
            got = _render_crop_hash(spec, sid, sched["page"], ev)
            if got is None:
                problems.append("crop could not be re-rendered for hash"
                                " verification")
            elif got != ev["crop_sha256"]:
                problems.append(
                    f"crop hash mismatch: recorded {ev['crop_sha256'][:16]}..."
                    f", fresh render {got[:16]}... - the transcription does"
                    " not prove which pixels it read; re-render and"
                    " re-transcribe")
        if ev.get("uncertain_cells"):
            audit.add_callout(
                "schedule image evidence",
                f"uncertain cells disclosed: {ev['uncertain_cells']} -"
                " re-read those cells at higher zoom before relying on them",
                blank_fields=[], pages=[sched.get("page")])
        if problems:
            for t in sched["types"]:
                _withhold_type(audit, sched, t["type"], "; ".join(problems))
        else:
            audit.add("image schedule evidence", "pass",
                      f"crop hash verified on source {sid!r} page"
                      f" {sched['page']} ({len(ev.get('cells') or [])} cells"
                      " transcribed by vision)")
            # P0.2: the count VALUE must be supported by the TRANSCRIBED
            # cells (count_cells); an edited count over verified pixels is
            # still caught
            cell_index = {}
            for c in ev.get("cells") or []:
                cell_index[(c.get("row"), c.get("col"))] = \
                    str(c.get("text", "")).strip()
            for t in sched["types"]:
                refs = t.get("count_cells") or []
                if not refs:
                    _withhold_type(
                        audit, sched, t["type"],
                        "image-evidence count has NO count_cells pointing at"
                        " the transcribed cell(s) that prove it - record"
                        " count_cells (row/col of the transcribed cells) so"
                        " the number is bound to the crop")
                    continue
                vals = []
                bad_refs = []
                for ref in refs:
                    key = (ref.get("row"), ref.get("col"))
                    if key not in cell_index:
                        bad_refs.append(key)
                        continue
                    vals.append(cell_index[key])
                if bad_refs:
                    _withhold_type(
                        audit, sched, t["type"],
                        f"count_cells {bad_refs} do not match any transcribed"
                        " cell - fix the references or re-transcribe")
                    continue
                ok, why = _count_supported_by_evidence(t["count"], vals)
                if not ok:
                    _withhold_type(audit, sched, t["type"], why)


def _withhold_all(audit, sched, sid, reason):
    for t in sched["types"]:
        t["_evidence_ok"] = False
    audit.add_callout("schedule evidence", reason,
                      blank_fields=["count", "extended_sf"],
                      pages=[sched.get("page")], source_id=sid)


def _render_crop_hash(spec, sid, page_no, ev):
    """Re-render the recorded crop and return its sha256 (None on error)."""
    try:
        import pymupdf
        src = next(s for s in spec["_sources"]
                   if s["source_id"] == sid and s["kind"] == "pdf")
        doc = pymupdf.open(src["path"])
        pg = doc[page_no - 1]
        clip = pymupdf.Rect(*ev["crop_bbox"])
        pix = pg.get_pixmap(matrix=pymupdf.Matrix(ev["render_zoom"],
                                                  ev["render_zoom"]),
                            clip=clip)
        data = pix.tobytes("png")
        doc.close()
        import hashlib
        return hashlib.sha256(data).hexdigest()
    except Exception:
        return None


def audit_room_reconciliation(spec, audit):
    """P0.2 cross-validation, rebuilt on the DEDUPED TAG RECORDS: the
    plan-derived per-type count is computed from room_inventory.rooms[],
    NOT taken from the supplied per_type_counts. This catches two traps:
      - a schedule cell edited from 3 to 30 while the plans show 6 (the
        classic invention trap), and
      - an INVENTORY edited to match the edit (per_type_counts changed to
        30 while the recorded tags still show 6 - the supplied count
        contradicting the tag records withholds the type too).
    An unexplained mismatch withholds the affected extension (callout)
    unless the agent recorded an explicit count_resolution with its own
    evidence. NEVER default a missing count to 1."""
    sched = spec.get("schedule")
    inv = (sched or {}).get("room_inventory")
    if not sched:
        return
    if not inv:
        audit.add("room reconciliation", "pass",
                  "plan-tag room inventory not recorded - schedule counts are"
                  " used WITHOUT cross-validation against plan tags; record"
                  " room_inventory.per_type_counts to arm the 3->30 invention"
                  " guard")
        return
    rooms = inv.get("rooms") or []
    supplied = inv.get("per_type_counts") or {}
    resolutions = inv.get("count_resolutions") or {}
    derived = {}
    for r in rooms:
        derived[r["type"]] = derived.get(r["type"], 0) + 1
    seen_types = {t["type"] for t in sched["types"]}
    stray = sorted({r["type"] for r in rooms if r["type"] not in seen_types})
    if stray:
        audit.add_callout(
            "room inventory", f"plan tags reference type(s) {stray} that the"
            " schedule does not declare - the schedule may be incomplete;"
            " inventory them explicitly instead of extending counts",
            blank_fields=["count"], pages=[sched.get("page")])
    for t in sched["types"]:
        name = t["type"]
        got = derived.get(name)
        supplied_ct = supplied.get(name)
        if got is None and supplied_ct is None:
            audit.add_callout(
                f"room reconciliation type {name}",
                "no plan-derived count recorded for this type - the schedule"
                " cell is used as-is; record room_inventory.rooms[] tags for"
                " cross-validation",
                blank_fields=[], pages=[sched.get("page")])
            continue
        if got is not None and supplied_ct is not None \
                and supplied_ct != got:
            _withhold_type(
                audit, sched, name,
                f"room_inventory.per_type_counts says {supplied_ct} but the"
                f" recorded room tags show {got} for type {name} - the"
                " supplied count contradicts the tag records it claims to"
                " summarize (edited inventory?); reconcile the tags first -"
                " the extension is withheld")
            continue
        plan_ct = got if got is not None else supplied_ct
        if got is None:
            audit.add_callout(
                f"room reconciliation type {name}",
                f"no room tags recorded for this type; the supplied"
                f" per_type_counts value {supplied_ct} is used UNVERIFIED",
                blank_fields=[], pages=[sched.get("page")])
        if plan_ct == t["count"]:
            audit.add("room reconciliation", "pass",
                      f"type {name}: schedule cell {t['count']} == plan-derived"
                      f" tag count {plan_ct} ({got or 0} tagged room(s))")
            continue
        res = resolutions.get(name)
        if res and res.get("count") == t["count"]:
            audit.add("room reconciliation", "pass",
                      f"type {name}: schedule {t['count']} != plan tags"
                      f" {plan_ct}, RESOLVED by recorded evidence:"
                      f" {res.get('basis', '')[:90]}")
        else:
            _withhold_type(
                audit, sched, name,
                f"schedule cell {t['count']} disagrees with the plan-derived"
                f" room-tag count {plan_ct} and no valid count_resolution"
                " exists - the extension is withheld (blank) until the"
                " disagreement is resolved from evidence")


def build_piece_boq_legacy(spec, results_by_id, assembly_rows, audit):
    """(superseded V3 builder - kept as a thin alias for older callers;
    the V4 pipeline calls build_piece_boq with the resolved model)."""
    return build_piece_boq(spec, audit, None)


def audit_dual_boq(assembly_rows, piece_rows, audit, project_total=None):
    """Three-way reconciliation (P0.1): the PIECE view, the ASSEMBLY view
    and the PROJECT total are reconciled AGAINST EACH OTHER - not by
    regrouping extensions:

      - assembly view: sum of (resolved EA x resolved per-instance SF)
        over assemblies whose pieces are ALL resolved (independent
        arithmetic path: EA model x SF model)
      - piece view: sum of the per-piece extensions of THOSE SAME
        assemblies (piece-level arithmetic)
      - project total: sum of ALL active piece extensions (including the
        known parts of partially-resolved assemblies - their unknown parts
        stay blank behind callouts)

    The first two MUST agree (any disagreement = EA/SF model inconsistency
    = fail). The project total MUST equal the full piece view. Assemblies
    with partially-blank pieces are excluded from the strict pair and their
    known contributions are disclosed - partial knowledge survives without
    faking a total.
    """
    if not assembly_rows and not piece_rows:
        return 0.0
    pieces_by_asm = {}
    for r in piece_rows:
        pieces_by_asm.setdefault(r["assembly_id"], []).append(r)
    asm_total = 0.0
    piece_subset = 0.0
    partial_asms = []
    for a in assembly_rows:
        if a["state"] == "package_excluded":
            continue
        own = [r for r in pieces_by_asm.get(a["assembly_id"], [])
               if not r.get("orphan")]
        exts = [r.get("extension_sf") for r in own]
        if own and a.get("ea") is not None and a.get("sf_per_instance") \
                is not None and all(e is not None for e in exts):
            asm_total += a["ea"] * a["sf_per_instance"]
            piece_subset += sum(exts)
        else:
            partial_asms.append(a["assembly_id"])
    active = [r for r in piece_rows if r["state"] != "package_excluded"
              and not r.get("orphan")]
    piece_total = round(sum(r["extension_sf"] or 0.0 for r in active), 4)
    pair_ok = abs(round(asm_total, 4) - round(piece_subset, 4)) <= 0.02
    matches_project = True
    if project_total is not None:
        matches_project = abs(piece_total - round(project_total, 4)) <= 0.02
    consistent = pair_ok and matches_project
    if any(r["extension_sf"] is None for r in piece_rows):
        audit.add_callout(
            "dual BoQ reconciliation",
            "some piece extensions are blank (unresolved properties) -"
            " all view totals exclude them and the exclusion is disclosed",
            blank_fields=["extension_sf"])
    detail = (f"piece view total {piece_total:.2f} SF; assembly view"
              f" {round(asm_total, 2):.2f} SF over fully-resolved"
              f" assemblies (their pieces sum to {round(piece_subset, 2):.2f}"
              f" SF); project total"
              + (f" {round(project_total, 2):.2f} SF" if project_total is not None
                 else " n/a")
              + (f"; partial assemblies excluded from the strict pair:"
                 f" {partial_asms}" if partial_asms else "")
              + " - the views are reconciled against each other and never"
                " summed")
    audit.add("dual BoQ reconciliation", "pass" if consistent else "fail",
              detail)
    return piece_total


def audit_room_coverage(spec, audit):
    """P0.7: every inventoried room must reconcile to the coverage ledger.
    A room present in the plan-tag inventory but covered by NO assembly is
    an omitted-room callout (its quantities stay blank) - this is the
    guard that turns 'the plans show 6 rooms, the job measured 5' into a
    named disclosure instead of silence."""
    sched = spec.get("schedule") or {}
    inv = sched.get("room_inventory")
    if not inv or not (spec.get("_assemblies") or []):
        return
    asm_rooms = set()
    asm_types = set()
    for a in spec["_assemblies"]:
        if a.get("room"):
            asm_rooms.add(a["room"])
        else:
            asm_types.add(a["type"])
    covered = set()
    for r in inv.get("rooms") or []:
        if r["room"] in asm_rooms or r["type"] in asm_types:
            covered.add(r["room"])
    missing = sorted({r["room"] for r in (inv.get("rooms") or [])
                      if r["room"] not in covered})
    if missing:
        audit.add_callout(
            "room coverage",
            f"inventoried room(s) {missing} are covered by NO assembly -"
            " omitted from this pass; their quantities stay blank (never"
            " defaulted, never silently dropped)",
            blank_fields=["sf", "edge_lf", "splash_lf"],
            pages=sorted({r["page"] for r in (inv.get("rooms") or [])
                          if r["room"] in missing}))
    else:
        audit.add("room coverage", "pass",
                  f"all {len(asm_rooms) or len(inv.get('rooms') or [])}"
                  " inventoried room(s) reconcile to assemblies")


def audit_region_checks(spec, results, calibrations, audit,
                        recheck_tolerance=RECHECK_TOLERANCE_PCT):
    """Per-region QA: ranges, calibration coverage, recheck deviations,
    duplicate/overlap within counted instances. Regions the recovery path
    marked `unresolved` contribute callouts (blank quantities), not fails."""
    for r in results:
        key = (r.get("source_id"), r["page"], r["viewport"])
        cal = calibrations.get(key)
        if r.get("status") == "unresolved":
            if not r.get("_callout_done"):
                r["_callout_done"] = True
                audit.add_callout(
                    f"region {r['region_id']}", r.get("unresolved_reason",
                    "unresolved"), blank_fields=r.get("blank_fields",
                    ["area_sf"]), pages=[r["page"]],
                    source_id=r.get("source_id"))
            continue
        if r.get("route") == "image":
            if not r.get("expected_range_ok"):
                audit.add("expected range", "fail",
                          f"region {r['region_id']}: image-route"
                          f" {r['area_sf']:.2f} SF outside expected"
                          f" {r['expected_sf_range']} - withheld")
            else:
                audit.add("expected range", "pass",
                          f"region {r['region_id']}: image-route"
                          f" {r['area_sf']:.2f} SF within"
                          f" {r['expected_sf_range']}"
                          f" ({r.get('factor_px_per_ft')} px/ft)")
            continue
        if cal is None:
            audit.add("region calibration", "fail",
                      f"region {r['region_id']}: no calibration for source"
                      f" {r.get('source_id')!r} page {r['page']} viewport"
                      f" {r['viewport']!r}")
        if not r["expected_range_ok"]:
            # V3: a range breach means the number cannot be trusted - the
            # region is downgraded to unresolved (blank) instead of shipping
            # a suspect quantity. The agent fixes the span/boundary and
            # re-runs; the callout names what is withheld.
            r["status"] = "unresolved"
            r["unresolved_reason"] = (
                f"measured {r['area_sf']:.2f} SF outside expected"
                f" {r['expected_sf_range']} - quantity withheld pending"
                " span/boundary investigation")
            r["blank_fields"] = ["area_sf", "edge_lf", "splash_lf"]
            audit.add_callout(
                f"region {r['region_id']}", r["unresolved_reason"],
                blank_fields=r["blank_fields"], pages=[r["page"]],
                source_id=r.get("source_id"))
            continue
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
    base_by_id = {r["region_id"]: r for r in results if r["kind"] == "base"
                  and r.get("status") != "unresolved"}
    unresolved_base_ids = {r["region_id"] for r in results
                           if r["kind"] == "base"
                           and r.get("status") == "unresolved"}
    for r in results:
        if r["kind"] != "recheck":
            continue
        if r.get("status") == "unresolved":
            continue
        if r.get("of") in unresolved_base_ids:
            audit.add_callout(
                f"recheck {r['region_id']}",
                f"base region {r.get('of')!r} is unresolved - the recheck"
                " has nothing to compare against and is excluded from QA",
                blank_fields=["recheck_deviation"], pages=[r["page"]])
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


def aggregate_types(spec, results, audit, resolved=None):
    """Build the per-type totals. Returns (types, project_total_sf).

    V4 (P0.1): when the job declares assemblies, EVERY total comes from the
    ONE resolved model (resolve_quantities) - project total, type rows,
    BoQ totals and CSV totals cannot disagree. The legacy branches (V2
    multiplication without assemblies, individual_rooms) are preserved for
    specs that declare no assemblies; package scope is applied in every
    branch and variant counts with unsupported evidence are withheld
    (blank + callout), never shipped.
    """
    base = [r for r in results if r["kind"] == "base"
            and r.get("status") != "unresolved"]
    unresolved = [r for r in results if r.get("status") == "unresolved"]
    rechecks = [r for r in results if r["kind"] == "recheck"
                and r.get("status") != "unresolved"]
    if unresolved:
        audit.add_callout(
            "totals", f"{len(unresolved)} region(s) unresolved"
            f" ({[r['region_id'] for r in unresolved]}) - excluded from"
            " extensions; their quantities stay blank")
    if spec.get("_assemblies"):
        return aggregate_types_resolved(spec, resolved or {"assemblies": {},
                                                           "pieces": {}},
                                        audit, base)
    if not base:
        audit.add("measured scope", "fail",
                  "no measurable regions completed - nothing to total"
                  " (if calibration exists nowhere in the set this is a"
                  " stop, not a zero)")
        return [], 0.0
    if spec.get("mode") == "individual_rooms":
        groups = {}
        total = 0.0
        for r in sorted(base, key=lambda r: r["region_id"]):
            groups.setdefault(r["type"], []).append(r)
            total += r["area_sf"]
        types = []
        for name in sorted(groups):
            rows = [{"room_type": name, "variant": r["variant"],
                     "region_id": r["region_id"], "sf": r["area_sf"],
                     "count": 1, "extended_sf": round(r["area_sf"], 2),
                     "regions": [r]} for r in groups[name]]
            types.append({"room_type": name, "schedule_count": len(rows),
                          "std_units": len(rows),
                          "sf_per_unit": round(
                              sum(r["area_sf"] for r in groups[name]), 4),
                          "extended_sf": round(
                              sum(r["area_sf"] for r in groups[name]), 2),
                          "rows": rows})
        total = round(total, 2)
        audit.add("totals", "pass",
                  f"individual_rooms: {len(base)} room(s) summed independently"
                  f" = {total:.2f} SF (count 1 each, by mode declaration)")
        return types, total
    sched = spec["schedule"]
    pkg_excluded_types = set((spec.get("policy") or {}).get(
        "package_excluded_types") or [])
    types = []
    total = 0.0
    excluded_total = 0.0
    for t in sched["types"]:
        name = t["type"]
        std = [r for r in base if r["type"] == name and r["variant"] is None]
        incl = [v for v in sched.get("variants", [])
                if v["type"] == name and v["included_in_parent_total"]]
        std_units = t["count"] - sum(v["count"] for v in incl)
        sf_unit = round(sum(r["area_sf"] for r in std), 4)
        ext = sf_unit * std_units
        if t.get("_evidence_ok") is False:
            # unsupported schedule count: the measured per-unit SF is real
            # evidence, but the multiplication is withheld (blank)
            std_units = 0
            ext = 0.0
            audit.add_callout(
                f"totals type {name}",
                "schedule count unsupported - per-unit SF is measured but"
                " the extension (SF x count) is withheld",
                blank_fields=["extended_sf"], pages=[sched.get("page")])
        rows = [{"room_type": name, "variant": None, "region_id": r["region_id"],
                 "assembly": r.get("assembly"),
                 "material_canonical": r.get("material_canonical"),
                 "sf": r["area_sf"], "count": std_units,
                 "extended_sf": round(r["area_sf"] * std_units, 2),
                 "regions": [r]} for r in std]
        for v in sched.get("variants", []):
            if v["type"] != name:
                continue
            vr = [r for r in base if r["type"] == name
                  and r["variant"] == v["name"]]
            vsf = round(sum(r["area_sf"] for r in vr), 4)
            if v.get("_evidence_ok") is False:
                # P0.2: invalid variant evidence -> its SF extension is
                # withheld (blank), not silently added
                audit.add_callout(
                    f"totals variant {name}:{v['name']}",
                    "variant evidence unsupported - its SF extension is"
                    " withheld (blank), not added to the total",
                    blank_fields=["extended_sf"], pages=[sched.get("page")])
            else:
                ext += vsf * v["count"]
            rows += [{"room_type": name, "variant": v["name"],
                      "region_id": r["region_id"],
                      "assembly": r.get("assembly"),
                      "material_canonical": r.get("material_canonical"),
                      "sf": r["area_sf"], "count": v["count"],
                      "extended_sf": round(r["area_sf"] * v["count"], 2),
                      "regions": [r]} for r in vr]
        if name in pkg_excluded_types:
            excluded_total += ext
            ext = 0.0
            audit.add("package exclusion", "pass",
                      f"type {name} is package-excluded by policy - reported"
                      " separately, excluded from the project total")
        types.append({"room_type": name, "schedule_count": t["count"],
                      "std_units": std_units, "sf_per_unit": sf_unit,
                      "extended_sf": round(ext, 2), "rows": rows})
        total += ext
    total = round(total, 2)
    units = sum(t["count"] for t in sched["types"]) + sum(
        v["count"] for v in sched.get("variants", [])
        if not v["included_in_parent_total"])
    audit.add("totals", "pass",
              f"repeated_types: {len(types)} type(s), {units} unit(s),"
              f" project total {total:.2f} SF"
              + (f" (+ {round(excluded_total, 2):.2f} SF package-excluded,"
                 " reported separately)" if excluded_total else ""))
    return types, total


def aggregate_types_resolved(spec, resolved, audit, base):
    """Type rows derived from the ONE resolved model (P0.1). Every row
    carries the assembly's resolved EA and its pieces' resolved SF; the
    project total equals the sum of the ACTIVE type rows by construction."""
    pieces_by_asm = {}
    for prow in resolved.get("pieces", {}).values():
        pieces_by_asm.setdefault(prow["assembly_id"], []).append(prow)
    groups = {}
    order = []
    for arow in resolved.get("assemblies", {}).values():
        name = arow["type"]
        if name not in groups:
            groups[name] = {"extended": 0.0, "excluded": 0.0,
                            "rows": [], "ea": 0, "sf_pi": 0.0}
            order.append(name)
        own = pieces_by_asm.get(arow["assembly_id"], [])
        # P0.1: the type/CSV total carries the KNOWN piece extensions of
        # the assembly (partial knowledge survives); the ASSEMBLY-view
        # extended_sf (EA x per-instance SF) stays blank when any piece is
        # unresolved - the blank lives in the BoQ row, never in the total.
        group_ext = round(sum(p.get("extension_sf") or 0.0
                              for p in own if not p.get("orphan")), 4)
        region_meta = next((p["region_meta"] for p in own
                            if p.get("region_meta")), None)
        first_pid = (own[0]["piece_id"] if own else arow["assembly_id"])
        display = dict(region_meta) if region_meta else {
            "region_id": None, "sheet": "?", "page": "",
            "viewport": "stated", "source_id": None, "factor": None,
            "policy": "stated dims"}
        row = {
            "room_type": name, "variant": arow.get("variant"),
            "region_id": display.get("region_id") or first_pid,
            "assembly": arow["assembly_id"], "assembly_id": arow["assembly_id"],
            "material_canonical": None, "package": arow["package"],
            "sf": arow.get("sf_per_instance"), "count": arow.get("ea"),
            "extended_sf": (arow.get("extended_sf") if arow.get("extended_sf")
                            is not None else group_ext or None),
            "regions": [{
                "region_id": display.get("region_id") or first_pid,
                "type": name, "variant": arow.get("variant"),
                "sheet": display.get("sheet") or "?",
                "page": display.get("page"),
                "viewport": display.get("viewport") or "main",
                "source_id": display.get("source_id"),
                "factor_pt_per_ft": display.get("factor"),
                "gross_area_policy": display.get("policy") or "stated dims",
            }],
        }
        ext = group_ext
        if arow["state"] == "package_excluded":
            groups[name]["excluded"] += ext
            groups[name]["rows"].append(row)
            continue
        groups[name]["extended"] += ext
        groups[name]["ea"] += arow.get("ea") or 0
        groups[name]["sf_pi"] += arow.get("sf_per_instance") or 0.0
        groups[name]["rows"].append(row)
    types = []
    total = 0.0
    sched_types = {t["type"]: t for t in
                   (spec.get("schedule") or {}).get("types", [])}
    for name in sorted(groups):
        g = groups[name]
        sched_count = (sched_types.get(name, {}).get("count")
                       if name in sched_types else g["ea"])
        types.append({
            "room_type": name,
            "schedule_count": sched_count,
            "std_units": g["ea"],
            "sf_per_unit": round(g["sf_pi"], 4),
            "extended_sf": round(g["extended"], 2),
            "excluded_extended_sf": round(g["excluded"], 2),
            "rows": g["rows"],
        })
        total += g["extended"]
    total = round(total, 2)
    excluded_total = round(sum(g["excluded"] for g in groups.values()), 2)
    # P0.1 invariant: the type rows MUST sum to the resolved project total
    # (both derive from the same piece records).
    resolved_total = round(resolved.get("project_total_sf", 0.0), 2)
    if abs(total - resolved_total) > 0.02:
        audit.add("totals", "fail",
                  f"type rows sum to {total:.2f} SF but the resolved project"
                  f" total is {resolved_total:.2f} SF - internal model"
                  " inconsistency")
    unit_count = sum(t["std_units"] for t in types)
    audit.add("totals", "pass",
              f"resolved model: {len(types)} type(s), {unit_count} unit(s),"
              f" project total {total:.2f} SF"
              + (f" (+ {excluded_total:.2f} SF package-excluded, reported"
                 " separately)" if excluded_total else "")
              + " - derived from the same resolved records as both BoQ"
                " views")
    return types, total
