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
import statistics

import preflight_lib as pl
import sheet_identity
from regions import check_duplicate_boundaries, check_overlaps
from spec_schema import SpecError, TakeoffError

RECHECK_TOLERANCE_PCT = 2.0


def validate_source_and_geometry(spec, geometry_map):
    """The frozen sources: each source file on disk and its geometry
    payload must both carry the declared digest (integrity mismatch = one
    of the three catastrophic stops)."""
    for src in spec["_sources"]:
        want = src["sha256"]
        path = src["path"]
        if src["kind"] == "pdf" and not os.path.exists(path):
            raise SpecError(f"source file not found: {path}")
        if src["kind"] == "pdf":
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


LEDGER_STATES = {"measured", "package_excluded", "superseded", "unresolved"}


def _assembly_count(spec, a):
    """Validated EA for an assembly: enumerated = 1; room_type_count = the
    validated schedule count for its type/variant (None when the count is
    unsupported - the BoQ EA stays blank, never guessed)."""
    qb = a["quantity_basis"]
    if qb["mode"] == "enumerated":
        return 1, "enumerated"
    sched = spec.get("schedule")
    if not sched:
        return None, "room_type_count (no schedule declared)"
    vname = qb.get("variant")
    for t in sched["types"]:
        if t["type"] != qb.get("type"):
            continue
        if t.get("_evidence_ok") is False:
            return None, "schedule count unsupported (evidence withheld)"
        if vname:
            for v in sched.get("variants", []):
                if v["type"] == t["type"] and v["name"] == vname:
                    return v["count"], f"variant {vname} count (schedule)"
            return None, f"variant {vname!r} not declared in the schedule"
        incl = sum(v["count"] for v in sched.get("variants", [])
                   if v["type"] == t["type"] and v["included_in_parent_total"])
        return t["count"], f"room-type count x{t['count']} (schedule-validated)"
    return None, f"type {qb.get('type')!r} not in the schedule"


def build_assembly_boq(spec, audit):
    """ASSEMBLY BoQ rows: one per assembly with inch descriptions and EA x
    validated count. Package-excluded assemblies are reported separately
    (package_excluded), never silently dropped."""
    excluded = spec.get("_excluded_packages") or set()
    rows = []
    for a in spec.get("_assemblies") or []:
        count, basis = _assembly_count(spec, a)
        pkg = a["package"]
        state = ("package_excluded" if pkg in excluded
                 else ("measured" if count else "unresolved"))
        pages = sorted({s.get("page") for s in a.get("sources", [])
                        if s.get("page")})
        if pkg in excluded:
            audit.add("package exclusion", "pass",
                      f"assembly {a['assembly_id']} ({a['type']}) is in"
                      f" excluded package {pkg!r} - reported separately and"
                      " excluded from main totals")
        elif count is None:
            audit.add_callout(
                f"assembly {a['assembly_id']}",
                f"quantity basis unresolved: {basis} - EA stays blank",
                blank_fields=["ea"], pages=pages,
                source_id=(a.get("sources") or [{}])[0].get("source_id"))
        rows.append({
            "assembly_id": a["assembly_id"], "room": a.get("room"),
            "type": a["type"], "variant": a.get("variant"),
            "package": pkg, "finish_tag": a.get("finish_tag"),
            "width_in": a.get("width_in"), "depth_in": a.get("depth_in"),
            "height_in": a.get("height_in"), "handing": a.get("handing"),
            "ea": count, "basis": basis, "state": state,
            "pieces": list(a.get("pieces") or []),
            "sources": a.get("sources") or [],
        })
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
        for v in sched.get("variants", []):
            boxes = v.get("word_boxes") or []
            missing = [b.get("t") for b in boxes
                       if not any(_box_matches_word(b, w) for w in words)]
            if missing:
                audit.add_callout(
                    f"variant evidence {v['name']}",
                    f"evidence boxes {missing} do not reference actual words"
                    f" on page {sched['page']} - re-read the variant row",
                    blank_fields=["count"], pages=[sched.get("page")])
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
    """P0.3 cross-validation: schedule cells vs plan-derived room-tag
    counts. The real trap this catches: a schedule cell edited from 3 to 30
    passed silently when nothing checked the plan tags. An unexplained
    mismatch withholds the affected extension (callout) unless the agent
    recorded an explicit count_resolution with its own evidence.
    NEVER default a missing count to 1."""
    sched = spec.get("schedule")
    inv = (sched or {}).get("room_inventory")
    if not sched or not inv:
        return
    ptc = inv.get("per_type_counts") or {}
    resolutions = inv.get("count_resolutions") or {}
    rooms = inv.get("rooms") or []
    seen_types = {t["type"] for t in sched["types"]}
    # inventory tags pointing at types the schedule never declares
    stray = sorted({r["type"] for r in rooms if r["type"] not in seen_types})
    if stray:
        audit.add_callout(
            "room inventory", f"plan tags reference type(s) {stray} that the"
            " schedule does not declare - the schedule may be incomplete;"
            " inventory them explicitly instead of extending counts",
            blank_fields=["count"], pages=[sched.get("page")])
    for t in sched["types"]:
        name = t["type"]
        want = ptc.get(name)
        if want is None:
            audit.add_callout(
                f"room reconciliation type {name}",
                "no plan-derived count recorded for this type - the schedule"
                " cell is used as-is; record room_inventory.per_type_counts"
                " for cross-validation",
                blank_fields=[], pages=[sched.get("page")])
            continue
        if want == t["count"]:
            audit.add("room reconciliation", "pass",
                      f"type {name}: schedule cell {t['count']} == plan-derived"
                      f" tag count {want} ({len([r for r in rooms
                                                if r['type'] == name])}"
                      " tagged room(s))")
            continue
        res = resolutions.get(name)
        if res and res.get("count") == t["count"]:
            audit.add("room reconciliation", "pass",
                      f"type {name}: schedule {t['count']} != plan tags"
                      f" {want}, RESOLVED by recorded evidence:"
                      f" {res.get('basis', '')[:90]}")
        else:
            _withhold_type(
                audit, sched, name,
                f"schedule cell {t['count']} disagrees with the plan-derived"
                f" room-tag count {want} and no valid count_resolution"
                " exists - the extension is withheld (blank) until the"
                " disagreement is resolved from evidence")


def build_piece_boq(spec, results_by_id, assembly_rows, audit):
    """PIECE BoQ rows: inch dims, gross/net SF, edge LF by profile, splash
    LF/SF, cutouts EA, and extensions using the SAME validated assembly
    counts (the two views are never summed with each other). Unknown dims
    keep the affected fields BLANK with a callout naming them."""
    asm_by_id = {r["assembly_id"]: r for r in assembly_rows}
    excluded = spec.get("_excluded_packages") or set()
    rows = []
    for p in spec.get("_pieces") or []:
        arow = asm_by_id.get(p["assembly_id"]) or {}
        count = arow.get("ea")
        astate = arow.get("state", "unresolved")
        blank = []
        sf = None
        dims = {}
        if p["route"] == "geometry":
            r = results_by_id.get(p.get("region_id"))
            if r is None or r.get("status") == "unresolved":
                blank.append("sf")
            else:
                sf = r["area_sf"]
        else:
            d = p.get("dims_in") or {}
            dims = {k: d.get(k) for k in ("width", "depth", "thickness",
                                          "height")}
            if d.get("width") is None or d.get("depth") is None:
                blank.append("sf")
            else:
                sf = round(d["width"] * d["depth"] / 144.0, 4)
        edges = {}
        splash_lf = 0.0
        splash_sf = 0.0
        splash_blank = False
        for run in p.get("edge_runs") or []:
            v = run.get("length_in")
            if v is None:
                blank.append(f"edge_lf:{run.get('exposure')}")
                continue
            edges[run["profile"]] = round(
                edges.get(run["profile"], 0.0) + v / 12.0, 3)
        for run in p.get("splash_runs") or []:
            ln = run.get("length_in")
            ht = run.get("height_in")
            if ln is None:
                splash_blank = True
                continue
            splash_lf += ln / 12.0
            if ht is not None:
                splash_sf += ln * ht / 144.0
            else:
                blank.append("splash_height")
        cutouts = {}
        for c in p.get("cutouts") or []:
            cutouts[c["kind"]] = cutouts.get(c["kind"], 0) + c["ea"]
        if splash_blank:
            blank.append("splash_lf")
        ext = (round(sf * count, 4)
               if sf is not None and isinstance(count, (int, float))
               else None)
        if ext is None:
            blank.append("extension_sf")
        links = p.get("source_links") or {}
        if blank:
            audit.add_callout(
                f"piece {p['piece_id']}",
                "unresolved construction properties - fields stay blank"
                f" ({sorted(set(blank))})",
                blank_fields=sorted(set(blank)),
                pages=sorted({l.get("page") for l in links.values()
                              if l.get("page")}),
                source_id=next(iter(links.values()), {}).get("source_id"))
        rows.append({
            "piece_id": p["piece_id"], "assembly_id": p["assembly_id"],
            "room": arow.get("room"), "type": arow.get("type"),
            "package": arow.get("package"),
            "finish_tag": p.get("finish_tag") or arow.get("finish_tag"),
            "route": p["route"], "region_id": p.get("region_id"),
            "dims_in": dims, "sf": sf,
            "edge_lf_by_profile": edges,
            "splash_lf": round(splash_lf, 3) if not splash_blank else None,
            "splash_sf": round(splash_sf, 3) if not splash_blank else None,
            "cutouts_ea": cutouts or {},
            "count": count, "extension_sf": ext,
            "state": ("package_excluded"
                      if arow.get("package") in excluded else astate),
            "source_links": links,
        })
    return rows


def audit_dual_boq(assembly_rows, piece_rows, audit):
    """Cross-check the two views (same records, same validated counts) and
    report both totals SEPARATELY - the piece view and the assembly view
    are never summed together."""
    if not assembly_rows and not piece_rows:
        return 0.0
    active = [r for r in piece_rows if r["state"] != "package_excluded"]
    piece_total = round(sum(r["extension_sf"] or 0.0 for r in active), 4)
    per_asm = {}
    for r in active:
        per_asm.setdefault(r["assembly_id"], 0.0)
        per_asm[r["assembly_id"]] += (r["extension_sf"] or 0.0)
    asm_total = 0.0
    consistent = True
    for a in assembly_rows:
        if a["state"] == "package_excluded":
            continue
        want = per_asm.get(a["assembly_id"])
        if want is None:
            continue
        if a["ea"] is None:
            consistent = False
            continue
        asm_total += want
    if any(r["extension_sf"] is None for r in piece_rows):
        audit.add_callout(
            "dual BoQ reconciliation",
            "some piece extensions are blank (unresolved properties) -"
            " both view totals exclude them and the exclusion is disclosed",
            blank_fields=["extension_sf"])
    audit.add("dual BoQ reconciliation", "pass" if consistent else "fail",
              f"piece view total {piece_total:.2f} SF; assembly view total"
              f" {asm_total:.2f} SF over {len(per_asm)} assembly instance(s)"
              " - the two views describe the SAME records with the SAME"
              " validated counts and are reported separately, never summed")
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


def build_coverage_ledger(spec, results, audit, results_by_id=None):
    """Reconcile EVERY inventoried item to exactly one ledger state:
    measured | package_excluded | superseded | unresolved (P0.1).

    Inventory: schedule types/variants (repeated mode), individual rooms
    (individual mode), and the region/page level. Assemblies and pieces
    extend this in the V3 schema; package exclusion comes from the profile
    or job policy.
    """
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
        seen = set()
        for t in sched.get("types", []):
            name = t["type"]
            if name in excluded_types:
                ledger.append({"item": f"type {name}", "kind": "type",
                               "state": "package_excluded",
                               "source": {"pages": [sched.get("page")]},
                               "detail": "count known but excluded by the"
                                         " package rules; reported separately"})
            else:
                rows = by_type.get((name, None), [])
                measured_rows = [r for r in rows if r.get("status") !=
                                 "unresolved"]
                evidence_ok = t.get("_evidence_ok") is not False
                if not measured_rows:
                    state = "unresolved"
                elif not evidence_ok:
                    state = "unresolved"
                else:
                    state = "measured"
                ledger.append({"item": f"type {name} x{t['count']}",
                               "kind": "type",
                               "source": {"pages": [sched.get("page")]},
                               "state": state,
                               "detail": (f"{len(measured_rows)} region(s)"
                                          " measured with schedule evidence"
                                          if measured_rows and evidence_ok
                                          else ("measured SF but unsupported"
                                                " schedule count"
                                                if measured_rows else
                                                "schedule count present but"
                                                " no region measured - SF"
                                                " blank"))})
            seen.add((name, None))
        for v in sched.get("variants", []):
            key = (v["type"], v["name"])
            rows = by_type.get(key, [])
            measured_rows = [r for r in rows
                             if r.get("status") != "unresolved"]
            ledger.append({
                "item": f"variant {v['type']}:{v['name']} x{v['count']}",
                "kind": "variant",
                "source": {"pages": [sched.get("page")]},
                "state": ("measured" if measured_rows else "unresolved"),
                "detail": (f"{len(measured_rows)} region(s) measured"
                           if measured_rows else
                           "declared but no region measured - SF blank"),
            })
            seen.add(key)
        for r in results:
            if r["kind"] != "base":
                continue
            key = (r.get("type"), r.get("variant"))
            ledger.append({
                "item": r["region_id"], "kind": "region",
                "source": {"source_id": r.get("source_id"),
                           "pages": [r["page"]]},
                "state": region_state(r),
                "detail": (r.get("unresolved_reason", "")[:120]
                           if r.get("status") == "unresolved"
                           else f"{r['area_sf']:.2f} SF"),
            })
    # V3 assemblies + pieces reconcile into the same ledger
    for a in spec.get("_assemblies") or []:
        excluded = a["package"] in (spec.get("_excluded_packages") or set())
        if excluded:
            state, detail = "package_excluded", ("package " + a["package"]
                                                 + " excluded; reported"
                                                 " separately")
        else:
            count, basis = _assembly_count(spec, a)
            state = "measured" if count else "unresolved"
            detail = basis
        ledger.append({"item": f"assembly {a['assembly_id']}",
                       "kind": "assembly",
                       "source": {"pages": sorted({s.get("page")
                                                  for s in a.get("sources", [])
                                                  if s.get("page")})},
                       "state": state, "detail": detail})
    for p in spec.get("_pieces") or []:
        asm = next((x for x in ledger
                    if x["item"] == f"assembly {p['assembly_id']}"), {})
        state = asm.get("state", "unresolved")
        if p.get("route") == "geometry":
            r = results_by_id.get(p.get("region_id")) if results_by_id \
                else None
            if r is not None and r.get("status") == "unresolved":
                state = "unresolved"
        ledger.append({"item": f"piece {p['piece_id']}", "kind": "piece",
                       "source": {"pages": sorted({l.get("page")
                                                  for l in
                                                  (p.get("source_links")
                                                   or {}).values()
                                                  if l.get("page")})},
                       "state": state,
                       "detail": ("route " + p["route"] + "; "
                                  + str(p.get("finish_tag") or ""))})
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


def aggregate_types(spec, results, audit):
    """Build the per-type totals. Returns (types, project_total_sf).

    V3 fixes the individual_rooms crash (reporting expected grouped rows
    with a 'rows' key; V2's flat list raised KeyError 'rows') and excludes
    unresolved regions from extensions (their SF is blank + callout).
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
    # V3: when the spec declares individually-enumerated assemblies, every
    # measured instance counts ONCE (no schedule multiplication - the
    # schedule counts cross-validate the room inventory instead). Package
    # exclusions still remove their regions from the main total.
    enumerated = bool(spec.get("_assemblies")) and all(
        a["quantity_basis"]["mode"] == "enumerated"
        for a in spec["_assemblies"])
    if enumerated:
        excluded = spec.get("_excluded_packages") or set()
        asm_by_id = {a["assembly_id"]: a for a in spec["_assemblies"]}
        excluded_regions = {
            p.get("region_id") for p in spec.get("_pieces") or []
            if (asm_by_id.get(p.get("assembly_id")) or {}).get("package")
            in excluded}
        total = round(sum(
            r["area_sf"] or 0.0 for r in base
            if r["region_id"] not in excluded_regions), 2)
        exc_sf = round(sum(r["area_sf"] or 0.0 for r in base
                           if r["region_id"] in excluded_regions), 2)
        audit.add("totals", "pass",
                  f"individually enumerated assemblies: {len(base)} measured"
                  f" instance(s) sum to {total:.2f} SF"
                  + (f" (+ {exc_sf:.2f} SF in excluded packages, reported"
                     " separately)" if exc_sf else "")
                  + " - schedule counts cross-validate the inventory and do"
                    " NOT multiply here")
        return [], total
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
            ext += vsf * v["count"]
            rows += [{"room_type": name, "variant": v["name"],
                      "region_id": r["region_id"],
                      "assembly": r.get("assembly"),
                      "material_canonical": r.get("material_canonical"),
                      "sf": r["area_sf"], "count": v["count"],
                      "extended_sf": round(r["area_sf"] * v["count"], 2),
                      "regions": [r]} for r in vr]
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
              f" project total {total:.2f} SF")
    return types, total
