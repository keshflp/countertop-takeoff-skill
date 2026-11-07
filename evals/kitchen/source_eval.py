"""V2 evaluator boundary; no runtime manufacturer or geometry implementation imported."""

from collections import Counter
from copy import deepcopy
from decimal import Decimal as D

import eval as old
from eval import Edge, Rect, require, ticks
import polygon_oracle as poly

DEFAULTS = {key: old.DEFAULTS[key] for key in ("slabTrimIn", "kerfIn", "allowRotate")}


def expand(job: dict) -> dict:
    require(job["version"] == 2, "normal source assessment requires job v2")
    copy = deepcopy(job)
    for installation in copy["installations"]:
        installation.pop("seam", None)
    data = old.expand_job(copy)
    data.update(version=2, mode="assessment", phase="plan",
                material={k: job["material"][k] for k in ("profileId", "profileProvenance", "nominalThicknessMm")},
                settings=DEFAULTS | job["settings"])
    require(set(data["settings"]) == set(DEFAULTS), "generic legacy cutout settings are not v2 source rules")
    for source, target in zip(job["installations"], data["installations"]):
        target["shapeKind"] = source["shape"]["kind"]
        for key in ("insideCornerRadiusMm", "sourceArrangement", "conditions"):
            target[key] = deepcopy(source[key])
        if "seam" in source:
            target["seam"] = deepcopy(source["seam"])
        for a, b in zip(source["cutouts"], target["cutouts"]):
            b.update(radiusMm=a["radiusMm"], mount=a["mount"])
    return data


def pieces(layout: dict) -> dict[str, tuple[str, poly.Polygon]]:
    result = {}
    for piece in layout["pieces"]:
        require(piece["id"] not in result, "duplicate fabrication piece id")
        result[piece["id"]] = piece["installationId"], poly.simple(piece["outline"])
    require(0 < len(result) <= 12, "expected one to twelve physical pieces")
    return result


def original_geometry(data: dict) -> None:
    for installation in data["installations"]:
        outline = poly.simple(installation["outline"])
        holes = [old.cutout_rect(c) for c in installation["cutouts"]]
        poly.contained_openings(outline, holes)
        poly.connected(outline, holes)


def tiling(data: dict, layout: dict) -> None:
    available = pieces(layout)
    ids = {i["id"] for i in data["installations"]}
    require(all(i in ids for i, _ in available.values()), "piece references unknown installation")
    for installation in data["installations"]:
        group = [p for i, p in available.values() if i == installation["id"]]
        poly.tile(poly.simple(installation["outline"]), group)


def same_coverage(expected: list[Rect], actual: list[poly.Polygon]) -> None:
    xs = sorted({x for r in expected for x in (r.x, r.right)} | {x for p in actual for x, _ in p})
    ys = sorted({y for r in expected for y in (r.y, r.bottom)} | {y for p in actual for _, y in p})
    for x0, x1 in zip(xs, xs[1:]):
        for y0, y1 in zip(ys, ys[1:]):
            require(sum(r.contains_center(x0 + x1, y0 + y1) for r in expected) ==
                    sum(old.inside(p, x0 + x1, y0 + y1) for p in actual),
                    "attributed cutout does not equal original opening clipped to this piece")


def cutouts(data: dict, layout: dict) -> None:
    originals = {i["id"]: i for i in data["installations"]}
    for piece in layout["pieces"]:
        p = poly.simple(piece["outline"])
        holes = [old.cutout_rect(c) for c in originals[piece["installationId"]]["cutouts"]]
        by_index: dict[int, list[poly.Polygon]] = {}
        for clip in piece["cutouts"]:
            index = clip["cutoutIndex"]
            require(type(index) is int and index in range(len(holes)), "invalid attributed opening index")
            by_index.setdefault(index, []).append(poly.simple(clip["outline"]))
        for index, hole in enumerate(holes):
            same_coverage(poly.clipped_opening(p, hole), by_index.get(index, []))
        poly.connected(p, holes)


def fits(data: dict, layout: dict) -> None:
    w, h = old.usable(data)
    for _, p in pieces(layout).values():
        box = poly.bbox(p)
        require(box.w <= w and box.h <= h or data["settings"]["allowRotate"] and box.h <= w and box.w <= h,
                "whole fabrication polygon cannot fit usable slab")


def counts(data: dict, layout: dict) -> None:
    counter = Counter(i for i, _ in pieces(layout).values())
    for installation in data["installations"]:
        requested = installation.get("requiredPieceCount")
        if installation.get("seam", {}).get("kind") == "center-through-cutout":
            requested = 2
        if requested is not None:
            require(counter[installation["id"]] == requested, "wrong requested fabrication-piece count")


def placements(data: dict, layout: dict) -> None:
    available, placed = pieces(layout), []
    w, h = old.usable(data)
    require(layout["footprintMode"] in ("gross-polygons", "bounding-box"), "unknown packing footprint mode")
    for index, slab in enumerate(layout["slabs"], 1):
        require(slab["index"] == index and bool(slab["placements"]), "empty or noncontiguous slab")
        transformed = []
        for placement in slab["placements"]:
            identifier, q = placement["pieceId"], placement["quarterTurns"]
            require(data["settings"]["allowRotate"] or q == 0, "rotation disabled")
            _, p = available[identifier]
            x, y = ticks(placement["x"]), ticks(placement["y"])
            transformed_piece = [(px + x, py + y) for px, py in poly.turn(p, q)]
            box = poly.bbox(transformed_piece)
            require(box.x >= 0 and box.y >= 0 and box.right <= w and box.bottom <= h,
                    "rigid polygon placement outside usable slab")
            for other in transformed:
                if layout["footprintMode"] == "bounding-box":
                    require(poly.separated(box, poly.bbox(other), ticks(data["settings"]["kerfIn"])), "bbox fallback kerf violation")
                else:
                    poly.no_collision(transformed_piece, other, ticks(data["settings"]["kerfIn"]))
            transformed.append(transformed_piece)
            placed.append(identifier)
    require(Counter(placed) == Counter(available.keys()), "piece placement omitted, duplicated or invented")


def join_edge(join: dict) -> Edge:
    require(join["axis"] in ("x", "y"), "invalid logical join axis")
    edge = Edge(join["installationId"], "v" if join["axis"] == "x" else "h",
                ticks(join["offsetIn"]), ticks(join["startIn"]), ticks(join["endIn"]))
    require(edge.end > edge.start, "logical join must have positive length")
    return edge


def joins(data: dict, layout: dict) -> None:
    available = pieces(layout)
    require(len({j["id"] for j in layout["joins"]}) == len(layout["joins"]), "duplicate logical join id")
    require(all(j["installationId"] in {i["id"] for i in data["installations"]} for j in layout["joins"]), "join references unknown installation")
    for installation in data["installations"]:
        group = {k: p for k, (i, p) in available.items() if i == installation["id"]}
        actual = poly.boundaries(installation["id"], list(group.values()))
        reported = [j for j in layout["joins"] if j["installationId"] == installation["id"]]
        declared = [join_edge(j) for j in reported]
        require(not any(a.axis == b.axis and a.line == b.line and min(a.end, b.end) > max(a.start, b.start)
                        for n, a in enumerate(declared) for b in declared[n + 1:]), "logical join boundary reported twice")
        require(old.merge_edges(declared) == actual,
                "logical joins differ from physical piece boundaries")
        holes = [old.cutout_rect(c) for c in installation["cutouts"]]
        for join in reported:
            edge = join_edge(join)
            require(join["cutoutIndex"] is None or type(join["cutoutIndex"]) is int and join["cutoutIndex"] in range(len(holes)), "invalid join opening index")
            for index, hole in enumerate(holes):
                if old.distance2(edge.rect(), hole) == 0:
                    if data["mode"] == "geometry-replay":
                        continue  # Explicit replay checks the frozen legacy rules separately.
                    selected = join["kind"] == "inside-opening" and join["cutoutIndex"] == index
                    require(selected and installation["cutouts"][index]["kind"] in ("sink", "cooktop")
                            and data["material"]["profileId"] == "silestone-2024-02",
                            "join crossing/tangency has no selected applicable opening exemption")
            expected_segments = poly.stone_segments(edge, holes)
            raw = {"seams": [dict(s, installationId=installation["id"]) for s in join["segments"]]}
            require(sorted(old.declared_edges(raw)) == sorted(expected_segments),
                    "join stone segments omit stone or bridge an opening void")
            participants = []
            for identifier, p in group.items():
                if any(e.axis == edge.axis and e.line == edge.line and min(e.end, edge.end) > max(e.start, edge.start)
                       for e in polygon_edges(installation["id"], p)):
                    participants.append(identifier)
            require(Counter(join["pieceIds"]) == Counter(participants), "join has wrong participating pieces")
        request = installation.get("seam")
        if request and request["kind"] != "tangent-cutout":
            if request["kind"] == "center-through-cutout":
                require(len(reported) == 1, "legacy equal-halves request needs one exact physical join")
            selected = holes[request["cutoutIndex"]]
            axis = "x" if request["kind"] == "center-through-cutout" else (installation["sourceArrangement"] or {"axis": "x"})["axis"]
            center = 2 * selected.x + selected.w if axis == "x" else 2 * selected.y + selected.h
            selected_joins = [j for j in reported if j["cutoutIndex"] == request["cutoutIndex"] and
                              join_edge(j).axis == ("v" if axis == "x" else "h") and 2 * join_edge(j).line == center]
            require(bool(selected_joins), "supplied opening join moved away from exact selected center")
            if request["kind"] == "center-through-cutout":
                edge = join_edge(selected_joins[0])
                box = old.rectangle(installation["outline"])
                require(2 * edge.line == box.x * 2 + box.w, "equal-halves join is not at exact run midpoint")
                require(all(old.area(p) * 2 == box.area for p in group.values()), "supplied equal blanks differ")


def polygon_edges(identifier: str, p: poly.Polygon) -> list[Edge]:
    return [Edge(identifier, "v" if a[0] == b[0] else "h", a[0] if a[0] == b[0] else a[1],
                 min(a[1], b[1]) if a[0] == b[0] else min(a[0], b[0]),
                 max(a[1], b[1]) if a[0] == b[0] else max(a[0], b[0])) for a, b in poly.edges(p)]


def bounds(data: dict, layout: dict, expected: dict, assessment: dict) -> None:
    old.check_bounds(data, dict(layout, ok=True), expected)
    search = assessment["search"]
    if search["status"] == "capped":
        require(layout["provenOptimal"] is False, "capped search cannot claim provenOptimal")
    if search["optimality"] == "global-slab-bound":
        require(layout["slabCount"] == layout["lowerBound"], "global slab proof does not meet independent area bound")
    if layout["provenOptimal"]:
        require(layout["slabCount"] == layout["lowerBound"] and search["optimality"] == "global-slab-bound",
                "global optimality lacks exact area-bound evidence")
    if layout["footprintMode"] == "bounding-box":
        require(search["packing"] == "bounding-box" and bool(search["limits"]), "bbox coverage limitation hidden")


def quantity(job: dict, data: dict, quote: dict, expected: dict) -> None:
    old.check_quantities(job, data, quote, expected)
    for source, actual in zip(job["installations"], quote["installations"]):
        require({k: v for k, v in actual.items() if k not in ("sf", "areaSqIn")} == source,
                "standalone quote lost or invented original installation facts")
    require(quote["material"] == job["material"], "standalone quote changed material applicability or financial facts")


def pricing(job: dict, data: dict, quote: dict, expected: dict) -> None:
    layout = quote["layout"]
    count = None if layout is None else layout["slabCount"]
    require(quote["slabCount"] == count, "quote slab count differs from final layout")
    slab = job["material"]["slab"]
    nominal = None if slab is None else D(str(slab["lengthIn"])) * D(str(slab["widthIn"])) / 144
    require(quote["slabSf"] is None if nominal is None else isinstance(quote["slabSf"], str)
            and abs(D(quote["slabSf"]) - nominal) <= D("1e-12"), "nominal slab SF changed")
    wanted = old.expected_pricing(job, data, count)
    require(quote["pricing"] == wanted, "exact supplier cost/markup/rate/labor arithmetic differs")
    require(len(quote["invoice"]) == len(job["installations"]), "wrong invoice line count")
    for source, line in zip(job["installations"], quote["invoice"]):
        sf = old.money(old.exact_areas(data)[source["id"]] / 144)
        amount = None if wanted["ratePerSf"] is None else old.money(D(sf) * D(wanted["ratePerSf"]))
        require(line == {"installation": source["label"], "material": job["material"]["name"], "sf": sf,
                         "ratePerSf": wanted["ratePerSf"], "amount": amount}, "wrong rounded invoice line")
    if count is not None and count == expected.get("optimumSlabs"):
        for key, value in expected.get("pricing", {}).items():
            require(wanted[key] == value, f"source-case hand price key inconsistent: {key}")
        if "invoiceAmounts" in expected:
            require([line["amount"] for line in quote["invoice"]] == expected["invoiceAmounts"], "source-case hand invoice key inconsistent")


def blanks(job: dict, quote: dict) -> None:
    fields = set(old.blank_fields(job)) | {u["field"] for u in quote["assessment"]["unresolved"]}
    require(Counter(b["field"] for b in quote["blanks"]) == Counter(fields), "one blank per actual unresolved/null fact required")
    require(all(isinstance(b["question"], str) and len(b["question"].strip()) >= 8 and "?" in b["question"]
                for b in quote["blanks"]), "missing plain question")


def assumptions(job: dict, quote: dict) -> None:
    adapted = deepcopy(job)
    adapted["settings"] = {"minSeamToCutoutIn": 0, "minMaterialBesideCutoutIn": 0} | job["settings"]
    old.check_assumptions(adapted, quote)
    require(not any(a["setting"] in ("minSeamToCutoutIn", "minMaterialBesideCutoutIn") for a in quote["assumptions"]),
            "retired generic clearances masquerade as source rules")


def evaluate(case: dict, output: dict, layout_only: bool) -> dict:
    from assessment_oracle import check_assessment, check_evidence, check_reasons, check_conditions

    job, expected = case["job"], case.get("expected", {})
    data = expand(job)
    layout, assessment = output.get("layout"), output.get("assessment")
    checks = {
        "response": lambda: require(output.get("version") == 2 and (not layout_only or output.get("ok") is True), "expected successful v2 protocol"),
        "originalGeometry": lambda: original_geometry(data),
        "assessment": lambda: check_assessment(data, assessment, layout, expected),
        "sourceRules": lambda: check_evidence(data, assessment, layout),
        "conditions": lambda: check_conditions(data, assessment, layout),
        "reasons": lambda: check_reasons(data, assessment, layout),
    }
    if layout is not None:
        checks.update({"tiling": lambda: tiling(data, layout), "solidAndCutouts": lambda: cutouts(data, layout),
                       "pieceFit": lambda: fits(data, layout), "pieceCounts": lambda: counts(data, layout),
                       "placements": lambda: placements(data, layout), "joins": lambda: joins(data, layout),
                       "bounds": lambda: bounds(data, layout, expected, assessment)})
    if not layout_only:
        checks.update({"quantity": lambda: quantity(job, data, output, expected),
                       "pricing": lambda: pricing(job, data, output, expected), "blanks": lambda: blanks(job, output),
                       "assumptions": lambda: assumptions(job, output),
                       "estimates": lambda: old.check_estimates(job, data, output)})
    gates = {name: old.run_gate(check) for name, check in checks.items()}
    count = None if layout is None else layout.get("slabCount")
    lower = None
    if data["slab"] is not None:
        w, h = old.usable(data)
        total = sum(old.area(old.points(i["outline"])) for i in data["installations"])
        lower = (total + w * h - 1) // (w * h)
    status = assessment.get("status") if isinstance(assessment, dict) else None
    # Only fully assessed outputs enter this new workload's objective.
    scored = status == "assessed" and count is not None
    return {"gates": gates, "assessmentStatus": status, "layoutApplicable": scored,
            "slabs": count, "optimum": expected.get("optimumSlabs"), "lowerBound": lower,
            "provenOptimal": None if layout is None else layout.get("provenOptimal"),
            "excessSlabs": count - expected.get("optimumSlabs", lower) if scored and lower is not None else None}
