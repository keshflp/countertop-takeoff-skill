"""Job-spec schema validation for the countertop takeoff (V3).

The job spec is an EVIDENCE document: the agent records where every count
came from (row text + word boxes, or an image-schedule crop + cell boxes, on
a page of a hashed source), which pages enter or leave the scope and why,
which dimension spans and boundary segments to use, and the gross-area
policy. Code then measures.

V3 additions over V2 (documented in references/job-spec-v3.md):
  - sources[]: multiple hashed inputs (PDF plan set, DXF exports, rasters),
    each with a stable source_id; pages are keyed (source_id, page_number)
  - tolerant sheet identity evidence (sheet_identity module + audit callouts)
  - bounded viewports (viewport_box) per calibration entry
  - schedule evidence may be text-based (word boxes) or image-based (a
    rendered crop hash + displayed cell boxes transcribed by vision)
  - assemblies[] + pieces[] with edge/splash/cutout runs for the two BoQ
    views; package rules (company profile defaults, job overrides)
  - graduated degradation: audit findings are callouts unless one of the
    three catastrophic stop conditions applies

V2 specs (schema "countertop-takeoff/v2", single source) remain valid: they
run unchanged with an implicit source_id of the first declared source.

Every numeric field is checked finite; every count is a positive integer.
Structural violations raise SpecError (hard stop, exit 2).
"""

import json
import math
import os
import re

SCHEMA_TAG = "countertop-takeoff/v2"
SCHEMA_TAG_V3 = "countertop-takeoff/v3"
SCHEMA_TAGS = {SCHEMA_TAG, SCHEMA_TAG_V3}
DEFAULT_SOURCE_ID = "plans"
SOURCE_KINDS = {"pdf", "cad", "image"}
MODES = {"repeated_types", "individual_rooms"}
DISPOSITIONS = {"measured", "intentionally_skipped", "superseded",
                "unresolved"}
REGION_KINDS = {"base", "recheck"}
GROSS_POLICIES = {"gross", "net_of_declared_cutouts"}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class TakeoffError(Exception):
    """Any hard stop: invalid spec, failed calibration, unclosed boundary,
    failed audit. Never guessed around; maps to exit code 2."""


class SpecError(TakeoffError):
    pass


def finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) \
        and math.isfinite(x)


def require(cond, msg):
    if not cond:
        raise SpecError(msg)


def pos_int(x, what):
    require(isinstance(x, int) and not isinstance(x, bool) and x >= 1,
            f"{what} must be a positive integer, got {x!r}")
    return x


def box(b, what):
    require(isinstance(b, dict), f"{what} must be an object")
    require(isinstance(b.get("t"), str) and b["t"], f"{what}.t must be text")
    for k in ("x0", "y0", "x1", "y1"):
        require(finite(b.get(k)), f"{what}.{k} must be a finite number")
    require(b["x1"] > b["x0"] and b["y1"] > b["y0"],
            f"{what} box must have x1>x0 and y1>y0")


def seg_ids(lst, what):
    require(isinstance(lst, list) and lst, f"{what} must be a non-empty list")
    require(all(isinstance(i, int) and not isinstance(i, bool) and i >= 0
                for i in lst), f"{what} must be segment ids (ints >= 0)")
    return lst


def word_boxes(lst, what):
    require(isinstance(lst, list) and lst,
            f"{what} must be a non-empty list of word boxes (evidence)")
    for i, b in enumerate(lst):
        box(b, f"{what}[{i}]")


def validate_source(spec):
    """Validate sources. V3 allows sources[] (multi-source); V2's single
    `source` object is accepted and normalized to a one-entry sources list
    stored in spec['_sources'] (source_id defaults to 'plans')."""
    sources = spec.get("sources")
    if sources is not None:
        require(isinstance(sources, list) and sources,
                "sources must be a non-empty list when present")
        ids = set()
        norm = []
        for i, s in enumerate(sources):
            require(isinstance(s, dict), f"sources[{i}] must be an object")
            sid = s.get("source_id")
            require(isinstance(sid, str) and sid.strip(),
                    f"sources[{i}].source_id must be a non-empty string")
            require(sid not in ids, f"duplicate source_id {sid!r}")
            ids.add(sid)
            path = s.get("path") or s.get("pdf")
            require(isinstance(path, str) and path,
                    f"sources[{i}] ({sid}): path must name the source file")
            require(isinstance(s.get("sha256"), str)
                    and SHA_RE.match(s["sha256"]),
                    f"sources[{i}] ({sid}): sha256 must be the 64-hex digest")
            kind = s.get("kind") or ("pdf" if path.lower().endswith(".pdf")
                                     else "cad" if path.lower().endswith(
                                         (".dxf", ".dwg")) else "image")
            require(kind in SOURCE_KINDS,
                    f"sources[{i}] ({sid}): kind must be one of"
                    f" {sorted(SOURCE_KINDS)}")
            norm.append({"source_id": sid, "path": path, "sha256": s["sha256"],
                         "kind": kind})
        spec["_sources"] = norm
    else:
        src = spec.get("source")
        require(isinstance(src, dict), "missing 'source' object (or the V3"
                " 'sources' list)")
        require(isinstance(src.get("pdf"), str) and src["pdf"],
                "source.pdf must name the source PDF")
        require(isinstance(src.get("sha256"), str)
                and SHA_RE.match(src["sha256"]),
                "source.sha256 must be the 64-hex digest of the source PDF")
        spec["_sources"] = [{"source_id": DEFAULT_SOURCE_ID,
                             "path": src["pdf"], "sha256": src["sha256"],
                             "kind": "pdf"}]
    require(isinstance(spec.get("geometry"), (str, dict))
            and spec["geometry"],
            "'geometry' must name the extract_geometry.py output (a path, or"
            " a {source_id: path} object for multi-source jobs)")
    geo = spec["geometry"]
    if isinstance(geo, dict):
        ids = {s["source_id"] for s in spec["_sources"]}
        for k, v in geo.items():
            require(k in ids, f"geometry key {k!r} is not a declared"
                    " source_id")
            require(isinstance(v, str) and v, f"geometry[{k!r}] must be a"
                    " path")
    return spec["_sources"]


def source_ids(spec):
    return [s["source_id"] for s in spec["_sources"]]


def default_source_id(spec):
    return spec["_sources"][0]["source_id"]


def validate_mode_and_policy(spec):
    require(spec.get("schema") in SCHEMA_TAGS,
            f"schema must be one of {sorted(SCHEMA_TAGS)} (got"
            f" {spec.get('schema')!r}) - V1 job specs are not accepted")
    mode = spec.get("mode")
    require(mode in MODES, f"mode must be one of {sorted(MODES)}"
            " - the takeoff refuses to infer it")
    policy = spec.get("policy")
    require(isinstance(policy, dict),
            "'policy' object is required (gross_area may come from the"
            " company profile, but the block must exist)")
    ga = policy.get("gross_area")
    require(ga is None or ga in GROSS_POLICIES,
            f"policy.gross_area must be one of {sorted(GROSS_POLICIES)} or"
            " omitted to inherit the profile default"
            " - v1 silently subtracted inner loops; v2 requires an explicit"
            " policy")
    decls = policy.get("declarations", [])
    require(isinstance(decls, list), "policy.declarations must be a list")
    for i, d in enumerate(decls):
        require(isinstance(d, dict) and isinstance(d.get("kind"), str)
                and isinstance(d.get("detail"), str) and d["detail"],
                f"policy.declarations[{i}] needs kind + detail")


PROFILE_KEYS = {"profile_version", "company", "material_aliases",
                "gross_net_policy", "required_components",
                "report_preferences", "approved_assumptions",
                "package_defaults", "currency", "rates"}
PACKAGES = {"millwork", "FFE", "public_BOH"}
HANDINGS = {"LH", "RH"}


def validate_rates(profile):
    """Profile v2 pricing schema (P1.1): rates[] price ASSEMBLY EA x an
    exact company-profile rate. Matching requires a stable item code plus
    matching assembly identity/dimensions - NEVER finish alone: a rate
    whose match lacks 'assembly_kind' refuses to load (a finish-only rate
    is exactly how a W laminate vanity gets priced as stone)."""
    rates = profile.get("rates")
    if rates is None:
        return []
    require(isinstance(rates, list) and rates,
            "profile.rates must be a non-empty list when present")
    codes = set()
    profile_currency = profile.get("currency")
    require(profile_currency is None or (isinstance(profile_currency, str)
            and profile_currency.strip()),
            "profile.currency must be a non-empty string (e.g. 'USD')")
    for i, r in enumerate(rates):
        require(isinstance(r, dict), f"rates[{i}] must be an object")
        code = r.get("item_code")
        require(isinstance(code, str) and code.strip(),
                f"rates[{i}].item_code must be a non-empty string (the stable"
                " code every line cites)")
        require(code not in codes, f"rates[{i}]: duplicate item_code {code!r}")
        codes.add(code)
        match = r.get("match")
        require(isinstance(match, dict), f"rates[{i}] ({code}): match must be"
                " an object describing WHICH assemblies the rate prices")
        ak = match.get("assembly_kind")
        require(isinstance(ak, str) and ak.strip(),
                f"rates[{i}] ({code}): match.assembly_kind is REQUIRED - a"
                " rate must pin the assembly identity; NEVER infer price from"
                " finish alone")
        ft = match.get("finish_tag")
        require(ft is None or (isinstance(ft, str) and ft.strip()),
                f"rates[{i}] ({code}): match.finish_tag must be a string")
        for k in ("width_in", "depth_in", "height_in"):
            v = match.get(k)
            require(v is None or (finite(v) and v > 0),
                    f"rates[{i}] ({code}): match.{k} must be a positive"
                    " number")
        h = match.get("handing")
        require(h is None or h in HANDINGS,
                f"rates[{i}] ({code}): match.handing must be LH or RH")
        pkg = match.get("package")
        require(pkg is None or pkg in PACKAGES,
                f"rates[{i}] ({code}): match.package must be one of"
                f" {sorted(PACKAGES)}")
        require(r.get("uom") == "EA",
                f"rates[{i}] ({code}): uom must be 'EA' (v4 prices assembly"
                " EA x exact rate; SF pricing is not built)")
        up = r.get("unit_price")
        require(finite(up) and up >= 0,
                f"rates[{i}] ({code}): unit_price must be a finite number >="
                " 0 (an explicit 0-rate stays distinguishable from a missing"
                " rate)")
        cur = r.get("currency")
        require(cur is None or (isinstance(cur, str) and cur.strip()),
                f"rates[{i}] ({code}): currency must be a string when present")
        if cur and profile_currency and cur != profile_currency:
            raise SpecError(
                f"rates[{i}] ({code}): currency {cur!r} != the profile"
                f" currency {profile_currency!r} - mixed currencies refuse")
        inc = r.get("includes")
        require(inc is None or (isinstance(inc, list)
                and all(isinstance(x, str) and x.strip() for x in inc)),
                f"rates[{i}] ({code}): includes must be a list of strings"
                " (the components the rate already covers)")
    return rates


def validate_profile(spec, base_dir):
    """Load + structurally validate the optional company profile."""
    path = spec.get("profile")
    if not path:
        return None
    require(isinstance(path, str) and path,
            "'profile' must name a profile JSON file")
    full = path if os.path.exists(path) else os.path.join(base_dir, path)
    require(os.path.exists(full), f"profile file not found: {path}")
    with open(full, "r", encoding="utf-8") as f:
        profile = json.load(f)
    require(isinstance(profile, dict), "profile must be a JSON object")
    unknown = set(profile) - PROFILE_KEYS
    require(not unknown,
            f"profile has unknown keys {sorted(unknown)} - a typo must not"
            " pass silently (see references/company-profile.md)")
    aliases = profile.get("material_aliases", {})
    require(isinstance(aliases, dict), "material_aliases must be an object")
    for k, v in aliases.items():
        require(isinstance(k, str) and isinstance(v, str) and v,
                "material_aliases must map strings to canonical names")
    gnp = profile.get("gross_net_policy")
    require(gnp is None or gnp in GROSS_POLICIES,
            f"profile gross_net_policy must be one of {sorted(GROSS_POLICIES)}")
    pd = profile.get("package_defaults")
    if pd is not None:
        require(isinstance(pd, dict), "profile package_defaults must be an"
                " object")
        excl = pd.get("exclude")
        require(excl is None or (isinstance(excl, list)
                                 and all(p in PACKAGES for p in excl)),
                f"profile package_defaults.exclude must list packages from"
                f" {sorted(PACKAGES)}")
    for k in ("required_components", "approved_assumptions"):
        v = profile.get(k, [])
        require(isinstance(v, list) and all(isinstance(x, str) for x in v),
                f"profile {k} must be a list of strings")
    require(isinstance(profile.get("report_preferences", {}), dict),
            "report_preferences must be an object")
    validate_rates(profile)
    return profile


def resolve_materials(spec, profile):
    """Resolve region materials via the profile aliases (identity only,
    SF stays the active quantity)."""
    if not profile:
        return
    aliases = profile.get("material_aliases", {})
    canonical = set(aliases.values())
    for r in spec["regions"]:
        mat = r.get("material")
        if not mat:
            continue
        canon = aliases.get(mat)
        if canon is None:
            require(mat in canonical,
                    f"region {r['region_id']}: material {mat!r} resolves via"
                    " neither the profile aliases nor its canonical names")
            canon = mat
        r["material_canonical"] = canon


def validate_scope(spec):
    scope = spec.get("scope")
    require(isinstance(scope, dict), "missing 'scope' object"
            " - every source page must be dispositioned")
    pages = scope.get("pages")
    require(isinstance(pages, list) and pages,
            "scope.pages must list every source page's disposition")
    known = set(source_ids(spec))
    seen = set()
    for entry in pages:
        require(isinstance(entry, dict), "scope entry must be an object")
        pno = pos_int(entry.get("page"), "scope page")
        sid = entry.get("source_id") or default_source_id(spec)
        require(sid in known, f"scope page {pno}: source_id {sid!r} is not a"
                " declared source")
        entry["source_id"] = sid
        key = (sid, pno)
        require(key not in seen,
                f"source {sid!r} page {pno} appears twice in scope.pages")
        seen.add(key)
        disp = entry.get("disposition")
        require(disp in DISPOSITIONS,
                f"page {pno}: disposition must be one of {sorted(DISPOSITIONS)}")
        if disp == "measured":
            regions = entry.get("expected_regions")
            require(isinstance(regions, list) and regions,
                    f"page {pno}: measured pages must list expected_regions"
                    " (an empty measured page is exactly the v1 hole that"
                    " passed deleted scopes at 0 SF)")
            require(len(set(regions)) == len(regions),
                    f"page {pno}: duplicate region ids in expected_regions")
        else:
            require(isinstance(entry.get("reason"), str)
                    and entry["reason"].strip(),
                    f"page {pno}: {disp} pages need a non-empty reason")
    return pages


def validate_box_list(lst, what, n=4):
    require(isinstance(lst, list) and len(lst) == n
            and all(finite(v) for v in lst),
            f"{what} must be a list of {n} finite numbers")


def validate_schedule(spec):
    """Validate the schedule evidence block (repeated_types mode only).

    V3 evidence kinds:
      text  - row_text + word_boxes that reference ACTUAL source words
              (audit verifies overlap against the extracted words)
      image - a rendered crop of a bitmap schedule table: crop hash, the
              displayed cell boxes, headers, per-cell text + confidence,
              and uncertain cells listed explicitly (P0.3: the real-world
              schedule was a pasted bitmap under a vector header)
    """
    sched = spec.get("schedule")
    if spec["mode"] == "individual_rooms":
        require(sched is None,
                "individual_rooms mode takes no schedule block - rooms sum"
                " independently, one region each")
        return None
    require(isinstance(sched, dict),
            "repeated_types mode needs a schedule block (the multiplier"
            " evidence) - v1 silently defaulted missing counts to 1")
    pos_int(sched.get("page"), "schedule.page")
    require(isinstance(sched.get("sheet"), str) and sched["sheet"],
            "schedule.sheet must cite the schedule sheet id")
    if sched.get("source_id") is not None:
        require(sched["source_id"] in source_ids(spec),
                f"schedule.source_id {sched['source_id']!r} is not a declared"
                " source")
    else:
        sched["source_id"] = default_source_id(spec)
    ev = sched.get("evidence") or {"kind": "text"}
    require(isinstance(ev, dict) and ev.get("kind") in ("text", "image"),
            "schedule.evidence.kind must be 'text' or 'image'")
    sched["evidence"] = ev
    if ev["kind"] == "image":
        require(isinstance(ev.get("crop_image"), str) and ev["crop_image"],
                "image evidence needs crop_image (path of the rendered crop"
                " the agent read)")
        require(isinstance(ev.get("crop_sha256"), str)
                and SHA_RE.match(ev["crop_sha256"]),
                "image evidence needs crop_sha256 (the 64-hex digest of the"
                " rendered crop PNG) - the audit re-renders and compares")
        require(finite(ev.get("render_zoom")) and ev["render_zoom"] > 0,
                "image evidence needs render_zoom (the zoom used for the"
                " crop render)")
        validate_box_list(ev.get("crop_bbox"),
                          "image evidence crop_bbox (displayed points)")
        require(isinstance(ev.get("headers"), list) and ev["headers"],
                "image evidence must record the transcribed headers")
        cells = ev.get("cells")
        require(isinstance(cells, list) and cells,
                "image evidence must record the transcribed cells")
        for i, c in enumerate(cells):
            require(isinstance(c, dict) and isinstance(c.get("text"), str),
                    f"evidence cell {i} needs text")
            validate_box_list(c.get("box"), f"evidence cell {i} box")
        unc = ev.get("uncertain_cells")
        require(unc is None or isinstance(unc, list),
                "uncertain_cells must be a list of cell indexes")
        for u in unc or []:
            require(isinstance(u, int) and 0 <= u < len(cells),
                    f"uncertain cell {u!r} is not a valid cell index")
    types = sched.get("types")
    require(isinstance(types, list) and types,
            "schedule.types must list every counted type")
    names = set()
    for t in types:
        name = str(t.get("type", "")).strip()
        require(name, "schedule type needs a non-empty 'type' name")
        require(name not in names, f"duplicate schedule type {name!r}")
        names.add(name)
        pos_int(t.get("count"), f"schedule type {name} count")
        require(isinstance(t.get("row_text"), str) and t["row_text"].strip(),
                f"type {name}: row_text must quote the schedule row")
        ev_kind = (sched.get("evidence") or {}).get("kind", "text")
        if ev_kind == "text":
            word_boxes(t.get("word_boxes"), f"type {name} word_boxes")
        else:
            # image evidence: the crop + cells carry the proof; word boxes
            # are optional (the header text on the page is not the table)
            boxes = t.get("word_boxes") or []
            for i, b in enumerate(boxes):
                box(b, f"type {name} word_boxes[{i}]")
        for r in t.get("rows", []) or []:
            pos_int(r.get("count"), f"type {name} row count")
            require(isinstance(r.get("floor"), str) and r["floor"],
                    f"type {name}: each row needs a floor label")
            require(isinstance(r.get("row_text"), str) and r["row_text"],
                    f"type {name}: each row needs row_text")
        for i, ref in enumerate(t.get("count_cells") or []):
            # P0.2 (image evidence): row/col pointers binding the count to
            # transcribed cells so the VALUE is checked against the crop
            require(isinstance(ref, dict) and isinstance(ref.get("row"), int)
                    and not isinstance(ref["row"], bool)
                    and isinstance(ref.get("col"), str) and ref["col"].strip(),
                    f"type {name}: count_cells[{i}] must be {{row: int,"
                    " col: str}} pointing at a transcribed evidence cell")
    variants = sched.get("variants", [])
    require(isinstance(variants, list), "schedule.variants must be a list")
    for v in variants:
        vname = str(v.get("name", "")).strip()
        require(vname, "variant needs a name")
        require(v.get("type") in names,
                f"variant {vname}: parent type {v.get('type')!r} not in types")
        pos_int(v.get("count"), f"variant {vname} count")
        require(isinstance(v.get("included_in_parent_total"), bool),
                f"variant {vname}: included_in_parent_total must be an explicit"
                " bool (true = parent count already contains this variant;"
                " false = the variant row is additional)")
        require(isinstance(v.get("row_text"), str) and v["row_text"].strip(),
                f"variant {vname}: row_text must quote its schedule row")
        word_boxes(v.get("word_boxes"), f"variant {vname} word_boxes")
    totals = sched.get("stated_totals")
    if totals is not None:
        require(isinstance(totals, dict), "stated_totals must be an object")
        per_floor = totals.get("per_floor")
        if per_floor is not None:
            require(isinstance(per_floor, dict) and per_floor,
                    "stated_totals.per_floor must be a non-empty object")
            for k, c in per_floor.items():
                pos_int(c, f"stated_totals.per_floor[{k!r}]")
        if "project" in totals:
            pos_int(totals["project"], "stated_totals.project")
    validate_room_inventory(spec, sched)
    return sched


def validate_room_inventory(spec, sched):
    """V3 room-tag inventory (P0.3): the agent dedupes rooms appearing in
    both overall and enlarged plans, then records per-type plan-derived
    counts. The audit reconciles them against the schedule cells; an
    unexplained mismatch withholds the affected extension (callout).
    NEVER default a missing count to 1."""
    inv = sched.get("room_inventory")
    if inv is None:
        return None
    require(isinstance(inv, dict), "room_inventory must be an object")
    rooms = inv.get("rooms")
    require(isinstance(rooms, list) and rooms,
            "room_inventory.rooms must list the tagged rooms")
    for i, r in enumerate(rooms):
        require(isinstance(r, dict), f"room_inventory.rooms[{i}] must be an"
                " object")
        require(isinstance(r.get("room"), str) and r["room"],
                f"room_inventory.rooms[{i}].room must be a label")
        require(isinstance(r.get("type"), str) and r["type"],
                f"room_inventory.rooms[{i}].type must be a type tag")
        pos_int(r.get("page"), f"room_inventory.rooms[{i}].page")
    ptc = inv.get("per_type_counts")
    require(isinstance(ptc, dict) and ptc,
            "room_inventory.per_type_counts must map type -> plan-derived"
            " count")
    for k, c in ptc.items():
        pos_int(c, f"room_inventory.per_type_counts[{k!r}]")
    notes = inv.get("dedupe_notes")
    require(notes is None or isinstance(notes, list),
            "room_inventory.dedupe_notes must be a list of strings")
    for n in notes or []:
        require(isinstance(n, str) and n.strip(),
                "room_inventory.dedupe_notes entries must be non-empty")
    res = inv.get("count_resolutions") or {}
    require(isinstance(res, dict),
            "count_resolutions must map type -> resolution")
    for k, r in res.items():
        require(isinstance(r, dict) and isinstance(r.get("count"), int)
                and not isinstance(r["count"], bool) and r["count"] >= 1,
                f"count_resolutions[{k!r}] must carry an explicit integer"
                " count with its evidence")
        require(isinstance(r.get("basis"), str) and r["basis"].strip(),
                f"count_resolutions[{k!r}] needs a basis (which evidence"
                " wins and why)")
    return inv


def validate_schedule_consistency(sched):
    """Self-consistency of stated evidence (no measurement involved)."""
    problems = []
    for t in sched["types"]:
        rows = t.get("rows") or []
        if rows:
            s = sum(r["count"] for r in rows)
            if s != t["count"]:
                problems.append(
                    f"type {t['type']}: count {t['count']} != sum of its"
                    f" floor rows {s} ({[r['count'] for r in rows]})")
        floors = {}
        for r in rows:
            floors[r["floor"]] = floors.get(r["floor"], 0) + r["count"]
        t["_floor_counts"] = floors
    for v in sched.get("variants", []):
        parent = next(t for t in sched["types"] if t["type"] == v["type"])
        if v["included_in_parent_total"] and v["count"] > parent["count"]:
            problems.append(
                f"variant {v['name']}: count {v['count']} exceeds parent type"
                f" {v['type']} count {parent['count']} while claiming to be"
                " included in it")
    totals = sched.get("stated_totals") or {}
    per_floor = totals.get("per_floor") or {}
    if per_floor and "project" in totals:
        s = sum(per_floor.values())
        if s != totals["project"]:
            problems.append(
                f"stated_totals: floors sum to {s} but project total is"
                f" {totals['project']}")
    return problems


def validate_regions(spec, sched):
    regions = spec.get("regions")
    require(isinstance(regions, list) and regions,
            "regions must be a non-empty list - nothing to measure")
    ids = set()
    for r in regions:
        rid = str(r.get("region_id", "")).strip()
        require(rid, "every region needs a non-empty region_id")
        require(rid not in ids, f"duplicate region_id {rid!r}")
        ids.add(rid)
    for r in regions:
        rid = r["region_id"]
        for k in ("assembly", "material", "piece"):
            require(k not in r or isinstance(r[k], str),
                    f"{rid}: {k} must be a string")
    pieces = spec.get("pieces") or []
    piece_regions = {p.get("region_id") for p in pieces}
    for r in regions:
        rid = r["region_id"]
        kind = r.get("kind", "base")
        require(kind in REGION_KINDS, f"{rid}: kind must be one of"
                f" {sorted(REGION_KINDS)}")
        rtype = str(r.get("type", "")).strip()
        require(rtype, f"{rid}: region needs a 'type'")
        if kind == "base" and sched is not None:
            names = {t["type"] for t in sched["types"]}
            if rtype not in names and rid not in piece_regions:
                require(False,
                        f"{rid}: type {rtype!r} is not in the approved"
                        " schedule and no declared piece covers it -"
                        " unplanned scope must go through scope planning"
                        " first (or declare an out-of-series assembly +"
                        " piece for it)")
        if kind == "recheck":
            require(r.get("of") in ids,
                    f"{rid}: recheck 'of' must reference a base region_id")
        v = r.get("variant")
        if v is not None and sched is not None:
            names = {x["name"] for x in sched.get("variants", [])
                     if x["type"] == rtype}
            require(v in names, f"{rid}: variant {v!r} not declared for type"
                    f" {rtype!r} in the schedule")
        pos_int(r.get("page"), f"{rid}: page")
        if r.get("route") == "image":
            # P0.6 route 3: calibrated image-space measurement produced by
            # scripts/image_measure.py; no vector boundary is selected
            require(isinstance(r.get("image_measurement"), str)
                    and r["image_measurement"],
                    f"{rid}: route 'image' needs image_measurement (path to"
                    " the image_measure.py result JSON)")
            rng = r.get("expected_sf_range")
            require(isinstance(rng, list) and len(rng) == 2
                    and all(finite(x) for x in rng) and rng[0] < rng[1],
                    f"{rid}: expected_sf_range [min, max] is required")
            if r.get("source_id") is None:
                r["source_id"] = default_source_id(spec)
            continue
        if r.get("source_id") is not None:
            require(r["source_id"] in source_ids(spec),
                    f"{rid}: source_id {r['source_id']!r} is not a declared"
                    " source")
        else:
            r["source_id"] = default_source_id(spec)
        seg_ids((r.get("boundary") or {}).get("seg_ids"),
                f"{rid}: boundary.seg_ids")
        seed = r.get("seed")
        require(isinstance(seed, list) and len(seed) == 2
                and all(finite(x) for x in seed),
                f"{rid}: seed must be [x, y] in displayed page points")
        rng = r.get("expected_sf_range")
        require(isinstance(rng, list) and len(rng) == 2
                and all(finite(x) for x in rng) and rng[0] < rng[1],
                f"{rid}: expected_sf_range [min, max] is required (the sanity"
                " guard that catches wrong calibration)")
        for c in r.get("cutouts", []) or []:
            require(isinstance(c.get("label"), str) and c["label"],
                    f"{rid}: each cutout needs a label")
            seg_ids(c.get("seg_ids"), f"{rid}: cutout {c['label']} seg_ids")
    return regions


def validate_source_link(link, what):
    """Property-specific provenance: length from the plan/elevation, depth/
    thickness/material/profile from the section/spec sheet (the real set
    joins A504 sections to A450/A452 lengths)."""
    require(isinstance(link, dict), f"{what} must be an object")
    pos_int(link.get("page"), f"{what}.page")
    require(link.get("kind") in {"plan", "elevation", "section", "spec",
                                "schedule", "detail", "other"},
            f"{what}.kind must be one of plan|elevation|section|spec|"
            "schedule|detail|other")
    if link.get("note") is not None:
        require(isinstance(link["note"], str), f"{what}.note must be a"
                " string")


def validate_assemblies(spec):
    """V3 assemblies[]: one record per room-instance prototype with its
    package, finish tag, dimensions, handing, and quantity basis."""
    asms = spec.get("assemblies")
    if asms is None:
        spec["_assemblies"] = []
        return []
    require(isinstance(asms, list), "assemblies must be a list")
    known_sources = set(source_ids(spec))
    ids = set()
    for i, a in enumerate(asms):
        require(isinstance(a, dict), f"assemblies[{i}] must be an object")
        aid = a.get("assembly_id")
        require(isinstance(aid, str) and aid.strip(),
                f"assemblies[{i}].assembly_id must be a non-empty string")
        require(aid not in ids, f"duplicate assembly_id {aid!r}")
        ids.add(aid)
        require(isinstance(a.get("type"), str) and a["type"],
                f"assembly {aid}: type is required")
        require(a.get("package") in PACKAGES,
                f"assembly {aid}: package must be one of {sorted(PACKAGES)}")
        if a.get("finish_tag") is not None:
            require(isinstance(a["finish_tag"], str) and a["finish_tag"],
                    f"assembly {aid}: finish_tag must be a string (ST/PL/W)"
                    " when present")
        if a.get("handing") is not None:
            require(a["handing"] in HANDINGS,
                    f"assembly {aid}: handing must be LH or RH when present")
        for k in ("width_in", "depth_in", "height_in"):
            v = a.get(k)
            require(v is None or (finite(v) and v > 0),
                    f"assembly {aid}: {k} must be a positive number or null"
                    " (unknown stays blank, never 0)")
        qb = a.get("quantity_basis")
        require(isinstance(qb, dict)
                and qb.get("mode") in {"room_type_count", "enumerated"},
                f"assembly {aid}: quantity_basis.mode must be"
                " 'room_type_count' or 'enumerated'")
        if qb["mode"] == "room_type_count":
            require(isinstance(qb.get("type"), str) and qb["type"],
                    f"assembly {aid}: room_type_count basis needs the type")
        pieces = a.get("pieces")
        require(isinstance(pieces, list),
                f"assembly {aid}: pieces must list piece_id strings")
        srcs = a.get("sources") or []
        require(isinstance(srcs, list), f"assembly {aid}: sources must be a"
                " list")
        for j, s in enumerate(srcs):
            require(isinstance(s, dict), f"assembly {aid} sources[{j}]")
            sid = s.get("source_id") or default_source_id(spec)
            require(sid in known_sources,
                    f"assembly {aid}: sources[{j}] source_id {sid!r} is not"
                    " declared")
            s["source_id"] = sid
            pos_int(s.get("page"), f"assembly {aid} sources[{j}].page")
    spec["_assemblies"] = asms
    return asms


def validate_pieces(spec, region_ids):
    """V3 pieces[]: geometry (measured region) or dimensioned construction;
    edge/splash/cutout runs; blank dims stay blank (never zero)."""
    pieces = spec.get("pieces")
    if pieces is None:
        spec["_pieces"] = []
        return []
    require(isinstance(pieces, list), "pieces must be a list")
    asm_ids = {a["assembly_id"] for a in spec["_assemblies"]}
    ids = set()
    for i, p in enumerate(pieces):
        require(isinstance(p, dict), f"pieces[{i}] must be an object")
        pid = p.get("piece_id")
        require(isinstance(pid, str) and pid.strip(),
                f"pieces[{i}].piece_id must be a non-empty string")
        require(pid not in ids, f"duplicate piece_id {pid!r}")
        ids.add(pid)
        require(p.get("assembly_id") in asm_ids,
                f"piece {pid}: assembly_id must reference a declared"
                " assembly")
        route = p.get("route")
        require(route in {"geometry", "stated"},
                f"piece {pid}: route must be 'geometry' or 'stated'")
        if route == "geometry":
            require(p.get("region_id") in region_ids,
                    f"piece {pid}: region_id must reference a region in"
                    " spec.regions")
        else:
            dims = p.get("dims_in")
            require(isinstance(dims, dict),
                    f"piece {pid}: stated route needs dims_in")
            for k in ("width", "depth", "thickness", "height"):
                v = dims.get(k)
                require(v is None or (finite(v) and v > 0),
                        f"piece {pid}: dims_in.{k} must be positive or null"
                        " (unknown stays blank, never 0)")
        for run in p.get("edge_runs") or []:
            require(isinstance(run, dict), f"piece {pid}: edge_runs entries")
            require(isinstance(run.get("profile"), str) and run["profile"],
                    f"piece {pid}: edge run needs a profile")
            require(isinstance(run.get("exposure"), str)
                    and run["exposure"],
                    f"piece {pid}: edge run needs an exposure (front/side/)")
            v = run.get("length_in")
            require(v is None or (finite(v) and v > 0),
                    f"piece {pid}: edge run length_in must be positive or"
                    " null (blank when unmeasurable)")
            if run.get("source") is not None:
                validate_source_link(run["source"], f"piece {pid} edge run"
                                     " source")
        for run in p.get("splash_runs") or []:
            require(isinstance(run, dict), f"piece {pid}: splash_runs entries")
            for k in ("height_in", "length_in", "returns_in"):
                v = run.get(k)
                require(v is None or (finite(v) and v > 0),
                        f"piece {pid}: splash {k} must be positive or null")
            if run.get("handing") is not None:
                require(run["handing"] in HANDINGS,
                        f"piece {pid}: splash handing must be LH or RH")
            if run.get("source") is not None:
                validate_source_link(run["source"], f"piece {pid} splash run"
                                     " source")
        for c in p.get("cutouts") or []:
            require(isinstance(c, dict) and isinstance(c.get("kind"), str)
                    and c["kind"], f"piece {pid}: cutouts need a kind")
            pos_int(c.get("ea"), f"piece {pid}: cutout ea")
            if c.get("source") is not None:
                validate_source_link(c["source"], f"piece {pid} cutout"
                                     " source")
        links = p.get("source_links") or {}
        require(isinstance(links, dict), f"piece {pid}: source_links must be"
                " an object")
        for prop, link in links.items():
            validate_source_link(link, f"piece {pid} source_links.{prop}")
    spec["_pieces"] = pieces
    validate_piece_geometry_reuse(spec, pieces)
    return pieces


def validate_piece_geometry_reuse(spec, pieces):
    """V5 (P0.2): optional explicit declarations of LEGITIMATE piece reuse
    across assemblies - `piece_geometry_reuse: [{region_id, pieces[],
    reason}]`. Every declared piece must be a geometry-route piece bound to
    the named region; an undeclared duplicate geometry claim is a defect
    (the audit withholds the duplicate extension)."""
    reuse = spec.get("piece_geometry_reuse")
    if reuse is None:
        return
    require(isinstance(reuse, list) and reuse,
            "piece_geometry_reuse must be a non-empty list when present")
    by_id = {p["piece_id"]: p for p in pieces}
    for i, d in enumerate(reuse):
        require(isinstance(d, dict),
                f"piece_geometry_reuse[{i}] must be an object")
        rid = d.get("region_id")
        require(isinstance(rid, str) and rid.strip(),
                f"piece_geometry_reuse[{i}].region_id must name the measured"
                " region")
        pids = d.get("pieces")
        require(isinstance(pids, list) and pids
                and all(isinstance(x, str) and x.strip() for x in pids),
                f"piece_geometry_reuse[{i}] ({rid}): pieces must list the"
                " piece ids that legitimately share the region")
        require(len(pids) >= 2,
                f"piece_geometry_reuse[{i}] ({rid}): reuse needs at least two"
                " pieces")
        require(isinstance(d.get("reason"), str) and d["reason"].strip(),
                f"piece_geometry_reuse[{i}] ({rid}): a non-empty reason is"
                " required (the auditor reads it)")
        for pid in pids:
            p = by_id.get(pid)
            require(p is not None,
                    f"piece_geometry_reuse[{i}] ({rid}): piece {pid!r} is not"
                    " declared in spec.pieces")
            require(p.get("route") == "geometry"
                    and p.get("region_id") == rid,
                    f"piece_geometry_reuse[{i}] ({rid}): piece {pid!r} is not"
                    f" a geometry piece of region {rid!r}")


def excluded_packages(spec, profile):
    """Package scope rules: company profile defaults, job policy override
    (GR guestroom FF&E excluded by default in the example profile, reported
    separately as package_excluded)."""
    if (spec.get("policy") or {}).get("packages"):
        excl = spec["policy"]["packages"].get("exclude") or []
        require(isinstance(excl, list)
                and all(p in PACKAGES for p in excl),
                f"policy.packages.exclude must list packages from"
                f" {sorted(PACKAGES)}")
        return set(excl)
    if profile and profile.get("package_defaults"):
        return set(profile["package_defaults"].get("exclude") or [])
    return set()


def validate_spec(spec):
    """Validate everything structural EXCEPT the optional profile (which the
    pipeline loads with the job file's folder for relative paths).
    Returns {scope, schedule, regions}."""
    validate_source(spec)
    validate_mode_and_policy(spec)
    scope = validate_scope(spec)
    sched = validate_schedule(spec)
    # V3: internal evidence conflicts (rows vs counts, floors vs project
    # totals) are real drawing conflicts - disclosed as callouts by the
    # audit, not spec refusals. Structurally MALFORMED evidence (counts
    # that are not positive integers, missing row quotes) still refuses.
    spec["_schedule_problems"] = (validate_schedule_consistency(sched)
                                  if sched is not None else [])
    regions = validate_regions(spec, sched)
    validate_assemblies(spec)
    validate_pieces(spec, {r["region_id"] for r in regions})
    return {"scope": scope, "schedule": sched, "regions": regions}
