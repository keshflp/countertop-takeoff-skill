# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Independent kitchen oracle. Geometry uses integer sixteenths, never floats."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = {
    "slabTrimIn": 1,
    "kerfIn": 0.25,
    "minSeamToCutoutIn": 6,
    "minMaterialBesideCutoutIn": 3,
    "allowRotate": True,
}
D = Decimal
Point = tuple[int, int]


def ticks(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("a length cannot be boolean")
    scaled = D(str(value)) * 16
    if not scaled.is_finite() or scaled != scaled.to_integral_value():
        raise ValueError(f"{value!r} is not a finite multiple of 1/16 inch")
    return int(scaled)


def money(value: Decimal) -> str:
    return str(value.quantize(D("0.01"), rounding=ROUND_HALF_UP))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def area(self) -> int:
        return self.w * self.h

    def contains_center(self, x2: int, y2: int) -> bool:
        return 2 * self.x < x2 < 2 * self.right and 2 * self.y < y2 < 2 * self.bottom


@dataclass(frozen=True, order=True)
class Edge:
    installation: str
    axis: str
    line: int
    start: int
    end: int

    def rect(self) -> Rect:
        if self.axis == "h":
            return Rect(self.start, self.line, self.end - self.start, 0)
        return Rect(self.line, self.start, 0, self.end - self.start)


def points(raw: list) -> list[Point]:
    result = [(ticks(x), ticks(y)) for x, y in raw]
    if len(result) > 1 and result[0] == result[-1]:
        result.pop()
    require(len(result) >= 4, "outline needs at least four vertices")
    for a, b in zip(result, result[1:] + result[:1]):
        require(a != b and ((a[0] == b[0]) != (a[1] == b[1])), "non-orthogonal edge")
    return result


def area(poly: list[Point]) -> int:
    twice = sum(x * ny - nx * y for (x, y), (nx, ny) in zip(poly, poly[1:] + poly[:1]))
    require(twice > 0 and twice % 2 == 0, "outline must be clockwise in y-down coordinates")
    return twice // 2


def inside(poly: list[Point], x2: int, y2: int) -> bool:
    # Ray casting on doubled coordinates avoids fractions at cell centers.
    crossings = 0
    for (x, y), (nx, ny) in zip(poly, poly[1:] + poly[:1]):
        if x == nx and min(y, ny) * 2 < y2 < max(y, ny) * 2 and x * 2 > x2:
            crossings += 1
    return crossings % 2 == 1


def rectangle(raw: list) -> Rect:
    poly = points(raw)
    xs, ys = sorted({x for x, _ in poly}), sorted({y for _, y in poly})
    require(len(poly) == 4 and len(xs) == len(ys) == 2, "pieces must be rectangles")
    result = Rect(xs[0], ys[0], xs[1] - xs[0], ys[1] - ys[0])
    require(area(poly) == result.area, "invalid piece rectangle")
    return result


def shape_outline(shape: dict) -> list[list]:
    kind = shape["kind"]
    if kind == "outline":
        return shape["points"]
    d = shape["depthIn"]
    if kind == "rect":
        length = shape["lengthIn"]
        return [[0, 0], [length, 0], [length, d], [0, d]]
    back = shape["backIn"]
    if kind == "L":
        side = shape["sideIn"]
        if shape["side"] == "left":
            return [[0, 0], [back, 0], [back, d], [d, d], [d, side], [0, side]]
        return [[0, 0], [back, 0], [back, side], [back - d, side], [back - d, d], [0, d]]
    require(kind == "U", f"unknown shape {kind}")
    left, right = shape["leftIn"], shape["rightIn"]
    return [[0, 0], [back, 0], [back, right], [back - d, right], [back - d, d],
            [d, d], [d, left], [0, left]]


def expand_job(job: dict) -> dict:
    """Recreate the contract's shape and cutout rules without calling CLI code."""
    installations = []
    for installation in job["installations"]:
        shape = installation["shape"]
        cutouts = []
        for cutout in installation["cutouts"]:
            w, h, at = cutout["wIn"], cutout["hIn"], cutout["at"]
            if "xIn" in at:
                require("yIn" in at, "explicit cutout needs xIn and yIn")
                x, y = at["xIn"], at["yIn"]
            else:
                d, center, leg = shape["depthIn"], at["centerFromStartIn"], at["leg"]
                allowed = {"rect": {"main"}, "L": {"back", shape.get("side")}, "U": {"back", "left", "right"}}
                require(leg in allowed.get(shape["kind"], set()), "invalid cutout leg for this shape")
                if center == "center":
                    length_key = "lengthIn" if leg == "main" else "backIn" if leg == "back" else (
                        "sideIn" if shape["kind"] == "L" else f"{leg}In")
                    center = shape[length_key] / 2
                if leg in ("main", "back"):
                    x, y = center - w / 2, (d - h) / 2
                else:
                    x = (d - w) / 2 if leg == "left" else shape["backIn"] - (d + w) / 2
                    y = center - h / 2
            for value in (x, y, w, h):
                ticks(value)
            cutouts.append({"kind": cutout["kind"], "x": x, "y": y, "w": w, "h": h})
        expanded = {"id": installation["id"], "outline": shape_outline(shape), "cutouts": cutouts}
        if "requiredPieceCount" in installation:
            count = installation["requiredPieceCount"]
            require(type(count) is int and count > 0, "requiredPieceCount must be a positive integer")
            expanded["requiredPieceCount"] = count
        installations.append(expanded)
    return {"slab": job["material"]["slab"], "settings": DEFAULTS | job.get("settings", {}),
            "installations": installations}


def cutout_rect(cutout: dict) -> Rect:
    return Rect(*(ticks(cutout[key]) for key in ("x", "y", "w", "h")))


def pieces(layout: dict) -> dict[str, tuple[str, Rect]]:
    result = {}
    for piece in layout["pieces"]:
        require(isinstance(piece["id"], str) and piece["id"] not in result, "duplicate/invalid piece id")
        result[piece["id"]] = (piece["installationId"], rectangle(piece["outline"]))
    require(bool(result), "layout contains no pieces")
    return result


def tiled(poly: list[Point], rects: list[Rect]) -> None:
    xs = sorted({x for x, _ in poly} | {x for r in rects for x in (r.x, r.right)})
    ys = sorted({y for _, y in poly} | {y for r in rects for y in (r.y, r.bottom)})
    for x0, x1 in zip(xs, xs[1:]):
        for y0, y1 in zip(ys, ys[1:]):
            coverage = sum(r.contains_center(x0 + x1, y0 + y1) for r in rects)
            require(coverage == int(inside(poly, x0 + x1, y0 + y1)),
                    f"outline coverage {coverage} at ({x0 / 16:g},{y0 / 16:g})")


def usable(data: dict) -> tuple[int, int]:
    trim = ticks(data["settings"]["slabTrimIn"])
    w, h = (ticks(data["slab"][key]) - 2 * trim for key in ("lengthIn", "widthIn"))
    require(w > 0 and h > 0, "trim leaves no usable slab")
    return w, h


def distance2(a: Rect, b: Rect) -> int:
    dx, dy = max(a.x - b.right, b.x - a.right, 0), max(a.y - b.bottom, b.y - a.bottom, 0)
    return dx * dx + dy * dy


def shared_edges(layout: dict) -> list[Edge]:
    items = list(pieces(layout).values())
    result = []
    for i, (installation, a) in enumerate(items):
        for other, b in items[i + 1:]:
            if installation != other:
                continue
            if a.right == b.x or b.right == a.x:
                start, end = max(a.y, b.y), min(a.bottom, b.bottom)
                if end > start:
                    result.append(Edge(installation, "v", max(a.x, b.x), start, end))
            if a.bottom == b.y or b.bottom == a.y:
                start, end = max(a.x, b.x), min(a.right, b.right)
                if end > start:
                    result.append(Edge(installation, "h", max(a.y, b.y), start, end))
    return result


def merge_edges(edges: list[Edge]) -> list[Edge]:
    merged: list[Edge] = []
    for edge in sorted(edges):
        if (merged and (edge.installation, edge.axis, edge.line) ==
                (merged[-1].installation, merged[-1].axis, merged[-1].line) and edge.start <= merged[-1].end):
            last = merged.pop()
            edge = Edge(last.installation, last.axis, last.line, last.start, max(last.end, edge.end))
        merged.append(edge)
    return merged


def declared_edges(layout: dict) -> list[Edge]:
    result = []
    for seam in layout["seams"]:
        x0, y0, x1, y1 = (ticks(seam[key]) for key in ("x0", "y0", "x1", "y1"))
        require((x0 == x1) != (y0 == y1), "seam must be a nonzero axis-aligned segment")
        if x0 == x1:
            result.append(Edge(seam["installationId"], "v", x0, min(y0, y1), max(y0, y1)))
        else:
            result.append(Edge(seam["installationId"], "h", y0, min(x0, x1), max(x0, x1)))
    return result


def check_tiling(data: dict, layout: dict) -> None:
    by_installation = defaultdict(list)
    for installation, rect in pieces(layout).values():
        by_installation[installation].append(rect)
    require(set(by_installation) == {i["id"] for i in data["installations"]}, "installation ids differ")
    for installation in data["installations"]:
        tiled(points(installation["outline"]), by_installation[installation["id"]])


def check_piece_fit(data: dict, layout: dict) -> None:
    w, h = usable(data)
    for piece_id, (_, r) in pieces(layout).items():
        fits = r.w <= w and r.h <= h
        turned = data["settings"]["allowRotate"] and r.h <= w and r.w <= h
        require(fits or turned, f"piece {piece_id} exceeds usable slab")


def check_piece_counts(data: dict, layout: dict) -> None:
    counts = Counter(installation for installation, _ in pieces(layout).values())
    for installation in data["installations"]:
        if "requiredPieceCount" in installation:
            require(counts[installation["id"]] == installation["requiredPieceCount"],
                    f"{installation['id']} requires exactly {installation['requiredPieceCount']} fabrication pieces")


def check_placements(data: dict, layout: dict) -> None:
    available, placed = pieces(layout), []
    w, h = usable(data)
    kerf = ticks(data["settings"]["kerfIn"])
    require(kerf >= 0, "negative kerf")
    indices = []
    for slab in layout["slabs"]:
        indices.append(slab["index"])
        require(bool(slab["placements"]), "empty slab")
        rects = []
        for placement in slab["placements"]:
            piece_id = placement["pieceId"]
            _, rect = available[piece_id]
            rotated = placement["rotated"]
            require(type(rotated) is bool, "rotated must be boolean")
            require(not rotated or data["settings"]["allowRotate"], "rotation is disabled")
            pw, ph = (rect.h, rect.w) if rotated else (rect.w, rect.h)
            r = Rect(ticks(placement["x"]), ticks(placement["y"]), pw, ph)
            require(r.x >= 0 and r.y >= 0 and r.right <= w and r.bottom <= h, "placement outside usable slab")
            for other in rects:
                separate = (r.right + kerf <= other.x or other.right + kerf <= r.x or
                            r.bottom + kerf <= other.y or other.bottom + kerf <= r.y)
                require(separate, f"overlap or insufficient kerf on slab {slab['index']}")
            rects.append(r)
            placed.append(piece_id)
    require(Counter(placed) == Counter(available.keys()), "pieces missing, repeated, or unknown in placements")
    require(all(type(i) is int for i in indices) and sorted(indices) == list(range(1, len(indices) + 1)),
            "slab indices must be unique and start at 1")


def check_seams(data: dict, layout: dict) -> None:
    actual = shared_edges(layout)
    require(merge_edges(actual) == merge_edges(declared_edges(layout)), "seams do not match piece boundaries")
    minimum = ticks(data["settings"]["minSeamToCutoutIn"])
    for edge in actual:
        for installation in data["installations"]:
            if installation["id"] == edge.installation:
                for cutout in installation["cutouts"]:
                    gap = distance2(edge.rect(), cutout_rect(cutout))
                    require(gap > 0 and gap >= minimum * minimum, "seam crosses or is too close to cutout")


def check_seam_material(data: dict, layout: dict) -> None:
    minimum = ticks(data["settings"]["minMaterialBesideCutoutIn"])
    for edge in shared_edges(layout):
        for installation in data["installations"]:
            if installation["id"] == edge.installation:
                for cutout in installation["cutouts"]:
                    require(distance2(edge.rect(), cutout_rect(cutout)) >= minimum * minimum,
                            "seam-made edge leaves too little material beside cutout")


def original_edge_violations(data: dict) -> list[str]:
    minimum = ticks(data["settings"]["minMaterialBesideCutoutIn"])
    violations = []
    for installation in data["installations"]:
        poly = points(installation["outline"])
        for cutout in installation["cutouts"]:
            rect = cutout_rect(cutout)
            for (x, y), (nx, ny) in zip(poly, poly[1:] + poly[:1]):
                edge = Rect(min(x, nx), min(y, ny), abs(x - nx), abs(y - ny))
                if distance2(edge, rect) < minimum * minimum:
                    violations.append(installation["id"])
                    break
    return violations


def check_warnings(data: dict, layout: dict, quote: dict | None = None) -> None:
    require(isinstance(layout["warnings"], list), "warnings must be an array")
    if original_edge_violations(data):
        for warnings in (layout["warnings"],) if quote is None else (layout["warnings"], quote["warnings"]):
            relevant = []
            for warning in warnings:
                text = str(warning).lower()
                relevant.append(any(word in text for word in ("cutout", "sink", "cooktop")) and
                                any(word in text for word in ("material", "edge", "thin", "clearance", "margin")))
            require(any(relevant), "original edge needs a material-beside-cutout warning; unrelated warnings do not count")


def check_bounds(data: dict, layout: dict, expected: dict) -> None:
    w, h = usable(data)
    total = sum(area(points(i["outline"])) for i in data["installations"])
    lower = (total + w * h - 1) // (w * h)
    require(type(layout["slabCount"]) is int and layout["slabCount"] == len(layout["slabs"]), "wrong slab count")
    require(type(layout["lowerBound"]) is int and layout["lowerBound"] == lower, "wrong area lower bound")
    require(layout["slabCount"] >= lower, "slab count below area bound")
    require(type(layout["provenOptimal"]) is bool, "provenOptimal must be boolean")
    optimum = expected.get("optimumSlabs")
    if optimum is not None:
        require(layout["slabCount"] >= optimum, "layout contradicts hand-proved optimum")
        require(not layout["provenOptimal"] or layout["slabCount"] == optimum, "false optimality claim")


def exact_areas(data: dict) -> dict[str, Decimal]:
    return {i["id"]: D(area(points(i["outline"]))) / 256 for i in data["installations"]}


def check_quantities(job: dict, data: dict, quote: dict, expected: dict) -> None:
    areas = exact_areas(data)
    entries = quote["installations"]
    require(len(entries) == len(areas) and {i["id"] for i in entries} == set(areas), "quantity installation ids differ")
    labels = {i["id"]: i["label"] for i in job["installations"]}
    required_counts = {i["id"]: i.get("requiredPieceCount") for i in job["installations"]}
    for installation in entries:
        identifier = installation["id"]
        require(installation["label"] == labels[identifier], "wrong installation label")
        require(installation.get("requiredPieceCount") == required_counts[identifier], "quote lost or invented requiredPieceCount")
        if required_counts[identifier] is not None:
            require(type(installation["requiredPieceCount"]) is int, "requiredPieceCount must remain an integer")
        require(isinstance(installation["areaSqIn"], str) and D(installation["areaSqIn"]) == areas[identifier], "wrong exact area")
        sf = money(areas[identifier] / 144)
        require(installation["sf"] == sf, f"wrong sf for {identifier}")
        answer = expected.get("installations", {}).get(identifier, {})
        require(answer.get("sf", sf) == sf, "answer key sf is inconsistent")
    total = money(sum(areas.values()) / 144)
    require(quote["totalSf"] == total, "totalSf must round the exact total, not sum rounded lines")
    require(expected.get("totalSf", total) == total, "answer key totalSf is inconsistent")


def expected_pricing(job: dict, data: dict, slab_count: int | None) -> dict:
    slab, material = job["material"]["slab"], job["material"]["pricePerSf"]
    labor = None if job["laborPerSf"] is None else money(D(job["laborPerSf"]))
    cost = rate = None
    if slab is not None and slab_count is not None and material is not None:
        numerator = slab_count * D(str(slab["lengthIn"])) * D(str(slab["widthIn"])) * D(material)
        cost = money(numerator / 144)
        # Cancel the common /144 before division; repeating slab SF must not spoil half-cent ties.
        rate = money(numerator / sum(exact_areas(data).values()))
    return {"materialCost": cost, "materialRatePerSf": rate, "laborPerSf": labor,
            "ratePerSf": None if rate is None or labor is None else money(D(rate) + D(labor))}


def check_pricing(job: dict, data: dict, quote: dict, expected: dict) -> None:
    count = quote["slabCount"]
    require(count is None or type(count) is int, "quote slabCount must be integer or null")
    if job["material"]["slab"] is None:
        require(count is None and quote["slabSf"] is None and quote["layout"] is None,
                "unknown slab must propagate null")
    else:
        require(count == quote["layout"]["slabCount"], "quote and layout slab counts differ")
        slab = job["material"]["slab"]
        nominal = D(str(slab["lengthIn"])) * D(str(slab["widthIn"])) / 144
        require(isinstance(quote["slabSf"], str) and abs(D(quote["slabSf"]) - nominal) <= D("1e-12"),
                "slabSf must use nominal dimensions")
    pricing = expected_pricing(job, data, count)
    require(quote["pricing"] == pricing, f"pricing differs: expected {pricing}")
    if count == expected.get("optimumSlabs"):
        for key, value in expected.get("pricing", {}).items():
            require(pricing[key] == value, f"answer key pricing is inconsistent: {key}")
    invoice = quote["invoice"]
    require(len(invoice) == len(job["installations"]), "one invoice line required per installation")
    areas = exact_areas(data)
    for source, line in zip(job["installations"], invoice):
        sf = money(areas[source["id"]] / 144)
        amount = None if pricing["ratePerSf"] is None else money(D(sf) * D(pricing["ratePerSf"]))
        require(line == {"installation": source["label"], "material": job["material"]["name"], "sf": sf,
                         "ratePerSf": pricing["ratePerSf"], "amount": amount}, "wrong invoice line")
    if count == expected.get("optimumSlabs") and "invoiceAmounts" in expected:
        require([i["amount"] for i in invoice] == expected["invoiceAmounts"], "answer key invoice amounts are inconsistent")


def blank_fields(job: dict) -> list[str]:
    result = [f"material.{key}" for key in ("name", "vendor", "pricePerSf", "slab") if job["material"][key] is None]
    if job["laborPerSf"] is None:
        result.append("laborPerSf")
    return result


def check_blanks(job: dict, quote: dict, expected: dict) -> None:
    blanks = quote["blanks"]
    fields = blank_fields(job)
    require(Counter(b["field"] for b in blanks) == Counter(fields), "exactly one blank per null input required")
    for blank in blanks:
        question = blank["question"]
        require(isinstance(question, str) and len(question.strip()) >= 8 and "?" in question,
                "blank needs a plain-words question")
    if "blanks" in expected:
        require(sorted(expected["blanks"]) == sorted(fields), "answer key blanks are inconsistent")
    pricing = quote["pricing"]
    if job["laborPerSf"] is None:
        require(pricing["laborPerSf"] is None and pricing["ratePerSf"] is None, "unknown labor produced a rate")
        require(all(i["ratePerSf"] is None and i["amount"] is None for i in quote["invoice"]), "unknown labor produced invoice amounts")
    if job["material"]["pricePerSf"] is None or job["material"]["slab"] is None:
        require(all(pricing[k] is None for k in ("materialCost", "materialRatePerSf", "ratePerSf")), "unknown material input produced pricing")


def check_assumptions(job: dict, quote: dict) -> None:
    assumptions = quote["assumptions"]
    for key, default in DEFAULTS.items():
        if key in job.get("settings", {}):
            continue
        matches = [a for a in assumptions if a["setting"] == key]
        require(len(matches) == 1, f"defaulted {key} must appear once in assumptions")
        value = matches[0]["value"]
        if isinstance(default, bool):
            require(value is default or value == "true", f"wrong assumed {key}")
        else:
            require(D(str(value)) == D(str(default)), f"wrong assumed {key}")
        note = matches[0]["note"].lower()
        require(all(word in note for word in ("assum", "confirm", "dad")), "default must ask Dad to confirm")


def geometry_estimates(job: dict, data: dict) -> list[dict]:
    result = []
    for source, installation in zip(job["installations"], data["installations"]):
        for index, (cutout, resolved) in enumerate(zip(source["cutouts"], installation["cutouts"])):
            if "estimate" not in cutout:
                continue
            estimate = cutout["estimate"]
            fields, note = estimate["fields"], estimate["note"]
            require(isinstance(fields, list) and bool(fields) and len(fields) == len(set(fields)) and
                    set(fields) <= {"wIn", "hIn", "at"}, "estimate fields must be nonempty, unique, and named")
            require(isinstance(note, str) and bool(note.strip()), "estimate needs its authorization note")
            result.append({"installationId": source["id"], "cutoutIndex": index, "fields": fields, "note": note,
                           "xIn": resolved["x"], "yIn": resolved["y"], "wIn": resolved["w"], "hIn": resolved["h"]})
    return result


def check_estimates(job: dict, data: dict, quote: dict) -> None:
    require(isinstance(quote["geometryEstimates"], list), "geometryEstimates must be an array, including when empty")
    for estimate in quote["geometryEstimates"]:
        require(type(estimate["cutoutIndex"]) is int, "cutoutIndex must remain an integer")
        for key in ("xIn", "yIn", "wIn", "hIn"):
            require(type(estimate[key]) in (int, float), "estimate rectangle must contain numeric inches")
            ticks(estimate[key])
    require(quote["geometryEstimates"] == geometry_estimates(job, data),
            "geometryEstimates must preserve authorized fields/notes and actual resolved cutout rectangles")


def run_gate(check: Callable[[], None]) -> dict:
    try:
        check()
        return {"pass": True, "errors": []}
    except (ValueError, KeyError, TypeError, IndexError, AttributeError, ArithmeticError) as error:
        return {"pass": False, "errors": [str(error)]}


def check_response(layout: dict) -> None:
    require(isinstance(layout, dict), "layout must be an object")
    require(layout.get("ok") is True, f"layout failed: {layout.get('error')}")


def evaluate(case: dict, output: dict, layout_only: bool) -> dict:
    job, expected = case["job"], case.get("expected", {})
    data = expand_job(job)
    layout = output if layout_only else output.get("layout")
    gates = {}
    if data["slab"] is not None:
        gates["response"] = run_gate(lambda: check_response(layout))
        checks = {"tiling": check_tiling, "pieceFit": check_piece_fit, "pieceCounts": check_piece_counts, "placements": check_placements,
                  "seams": check_seams, "seamMaterial": check_seam_material}
        for name, check in checks.items():
            gates[name] = run_gate(lambda check=check: check(data, layout))
        gates["warnings"] = run_gate(lambda: check_warnings(data, layout, None if layout_only else output))
        gates["bounds"] = run_gate(lambda: check_bounds(data, layout, expected))
    if not layout_only:
        gates["quantity"] = run_gate(lambda: check_quantities(job, data, output, expected))
        gates["pricing"] = run_gate(lambda: check_pricing(job, data, output, expected))
        gates["blanks"] = run_gate(lambda: check_blanks(job, output, expected))
        gates["assumptions"] = run_gate(lambda: check_assumptions(job, output))
        gates["estimates"] = run_gate(lambda: check_estimates(job, data, output))
    count = layout.get("slabCount") if isinstance(layout, dict) else None
    lower = None
    if data["slab"] is not None:
        w, h = usable(data)
        total = sum(area(points(i["outline"])) for i in data["installations"])
        lower = (total + w * h - 1) // (w * h)
    target = expected.get("optimumSlabs", lower)
    return {"gates": gates, "layoutApplicable": data["slab"] is not None,
            "slabs": count, "optimum": expected.get("optimumSlabs"), "lowerBound": lower,
            "provenOptimal": layout.get("provenOptimal") if isinstance(layout, dict) else None,
            "excessSlabs": count - target if type(count) is int and target is not None else None}


def line_count(root: Path = ROOT / "countertop-takeoff") -> int:
    return sum(len(path.read_bytes().splitlines()) for path in root.rglob("*")
               if path.is_file() and path.suffix in (".py", ".md", ".ts", ".json")
               and "node_modules" not in path.parts and path.relative_to(root).as_posix() != "cli/takeoff.js")


def command_argv(command: str) -> list[str]:
    # shlex's POSIX parser eats Windows backslashes. Non-POSIX retains quoted paths.
    return [part[1:-1] if len(part) > 1 and part[0] == part[-1] and part[0] in "\"'" else part
            for part in shlex.split(command, posix=False)]


def discover_cases(directories: list[Path]) -> dict[Path, str | None]:
    """An intake folder needs an explicit case.json before any numeric work can run."""
    found: dict[Path, str | None] = {}

    def intake(folder: Path) -> None:
        wrapper = folder / "case.json"
        found[wrapper.resolve() if wrapper.is_file() else folder.resolve()] = (
            None if wrapper.is_file() else "intake awaits confirmed facts; no case.json")

    for directory in directories:
        if (directory / "INTAKE.md").is_file():
            intake(directory)
            continue
        for path in directory.glob("*.json"):
            found[path.resolve()] = None
        for record in directory.glob("*/INTAKE.md"):
            intake(record.parent)
    return dict(sorted(found.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", action="append", type=Path, help="repeatable; replaces the default public directory")
    parser.add_argument("--layout-only", action="store_true")
    parser.add_argument("--layout-cmd", default="uv run countertop-takeoff/kernels/layout.py")
    parser.add_argument("--quote-cmd", default="bun countertop-takeoff/cli/src/eval.ts")
    parser.add_argument("--timeout", type=float, default=60, help="seconds per case")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    directories = args.cases or [Path(__file__).parent / "cases"]
    sources = discover_cases(directories)
    if not sources:
        parser.error("no case JSON files or intake folders found")
    results = []
    for path, pending in sources.items():
        result = {"case": path.stem}
        try:
            if pending is not None:
                result.update({"pending": pending, "gates": {}})
                results.append(result)
                continue
            case = json.loads(path.read_text(encoding="utf-8-sig"))
            if case.get("status") == "pending":
                result.update({"pending": case.get("reason", "awaiting confirmed facts"), "gates": {}})
                results.append(result)
                continue
            data = expand_job(case["job"])
            if args.layout_only and data["slab"] is None:
                result.update({"skipped": "slab dimensions unknown", "gates": {}})
            else:
                payload = data if args.layout_only else case["job"]
                command = args.layout_cmd if args.layout_only else args.quote_cmd
                completed = subprocess.run(command_argv(command), input=json.dumps(payload), text=True,
                                           encoding="utf-8", capture_output=True, timeout=args.timeout, cwd=ROOT)
                require(completed.returncode == 0, f"command exited {completed.returncode}: {completed.stderr.strip()[:600]}")
                output = json.loads(completed.stdout)
                require(isinstance(output, dict), "command must return a JSON object")
                result.update(evaluate(case, output, args.layout_only))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, ArithmeticError, subprocess.TimeoutExpired) as error:
            result["gates"] = {"execution": {"pass": False, "errors": [str(error)]}}
        results.append(result)
    evaluated = sum(bool(r["gates"]) for r in results)
    passed = evaluated > 0 and all(g["pass"] for r in results for g in r["gates"].values())
    scored = [r for r in results if r.get("excessSlabs") is not None]
    summary = {"mode": "layout" if args.layout_only else "quote", "pass": passed, "cases": results,
               "score": sum(r["excessSlabs"] for r in scored) if scored and passed else None,
               "scoreAvailable": passed and bool(scored) and all(
                   "pending" in r or "skipped" in r or r.get("layoutApplicable") is False or
                   r.get("excessSlabs") is not None for r in results),
               "evaluatedCases": evaluated, "pendingCases": sum("pending" in r for r in results),
               "skippedCases": sum("skipped" in r for r in results),
               "skillLines": line_count()}
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print("case                         gates                         slabs/optimum/lowerBound  provenOptimal")
        for r in results:
            if "pending" in r:
                print(f"{r['case']:<28} PENDING {r['pending']}")
                continue
            if "skipped" in r:
                print(f"{r['case']:<28} SKIP {r['skipped']}")
                continue
            failed = [name for name, gate in r["gates"].items() if not gate["pass"]]
            status = "PASS" if not failed else "FAIL " + ",".join(failed)
            numbers = "/".join(str(r.get(k)) if r.get(k) is not None else "?" for k in ("slabs", "optimum", "lowerBound"))
            print(f"{r['case']:<28} {status:<29} {numbers:<25} {r.get('provenOptimal', '?')}")
            for name in failed:
                for error in r["gates"][name]["errors"]:
                    print(f"  {name}: {error}")
        score = summary["score"] if summary["scoreAvailable"] else "unavailable (failed gates or no scored layouts)"
        print(f"excess slabs: {score}; skill lines: {summary['skillLines']}")
        print(f"evaluated: {evaluated}; pending: {summary['pendingCases']}; skipped: {summary['skippedCases']}")
    if evaluated == 0:
        return 2
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
