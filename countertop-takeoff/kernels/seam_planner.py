"""Finite source-admitted seam alternatives, followed by rigid polygon nesting.

Candidate coverage is deliberately explicit: boundary events, balanced cuts,
stock capacities, opening centers and reentrant corners. It is not an exhaustive
enumeration of every grid seam. Every seed and capped incumbent uses the same
admission predicate as the final plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from heapq import heappop, heappush
from itertools import combinations, islice, product
from math import ceil, prod

from layout_geometry import (
    FabricationPolygon,
    Rect,
    connected,
    edges,
    reentrant_vertices,
    solid_cells,
    split_polygon,
    stone_segments,
    tiles,
)
from polygon_pack import Packing, greedy, orientations, pack
from seam_model import (
    MM_PER_TICK,
    S1,
    S2,
    Evidence,
    Facts,
    Request,
    corner_evidence,
    original_evidence,
    profile_evidence,
    read_request,
    source,
)

MAX_PIECES = 12
MAX_STATES = 384
BEAM = 20
MAX_COMBINATIONS = 192
LIMITS = [
    "Finite seam candidates: whole polygons, reentrant corners, balanced/stock-capacity cuts and source boundary/centerline events; not every grid seam.",
    "At most 12 fabrication pieces, 384 states per installation, 20 states per expansion and 192 combined plans.",
    "Rigid polygon-cell nesting with one-worker deterministic CP-SAT; holes stay reserved and internal cells are not cuts.",
]
LIMITATIONS = [
    "Estimator evidence for the named source subset, not fabrication certification or a handling/breakage guarantee.",
    "Handling, dynamic transport, defects, toolpaths, reinforcement design and cabinet/load calculations are not evaluated.",
    "Illustrated sink/tap and cooktop relationships only; full tap, fixture, overhang, thermal and installation-manual detailing is outside this subset.",
]


@dataclass(frozen=True, order=True)
class Cut:
    axis: int
    at: int


@dataclass
class Plan:
    pieces: tuple[FabricationPolygon, ...]
    cuts: tuple[Cut, ...]
    joins: list[dict]
    evidence: Evidence


def partition(inst: Facts, cuts: tuple[Cut, ...]) -> tuple[FabricationPolygon, ...]:
    pieces = (inst.polygon,)
    for cut in cuts:
        pieces = tuple(p for old in pieces for p in split_polygon(old, cut.axis, cut.at))
    return tuple(sorted(pieces, key=lambda p: p.outline))


def common_lines(pieces: tuple[FabricationPolygon, ...], cut: Cut) -> tuple[Rect, ...]:
    intervals = []
    for a, b in combinations(pieces, 2):
        for ea, eb in product(edges(a.outline), edges(b.outline)):
            if cut.axis == 0 and ea.w == eb.w == 0 and ea.x == eb.x == cut.at:
                intervals.append((max(ea.y, eb.y), min(ea.y + ea.h, eb.y + eb.h)))
            if cut.axis == 1 and ea.h == eb.h == 0 and ea.y == eb.y == cut.at:
                intervals.append((max(ea.x, eb.x), min(ea.x + ea.w, eb.x + eb.w)))
    merged = []
    for low, high in sorted(intervals):
        if low >= high:
            continue
        if merged and low <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], high))
        else:
            merged.append((low, high))
    return tuple(Rect(cut.at, a, 0, b - a) if cut.axis == 0 else Rect(a, cut.at, b - a, 0) for a, b in merged)


def touches(piece: FabricationPolygon, lines: tuple[Rect, ...]) -> bool:
    return any((a.w == b.w == 0 and a.x == b.x and max(a.y, b.y) < min(a.y + a.h, b.y + b.h)) or
               (a.h == b.h == 0 and a.y == b.y and max(a.x, b.x) < min(a.x + a.w, b.x + b.w))
               for a, b in product(edges(piece.outline), lines))


def opening_relation(inst: Facts, cut: Cut, index: int, line: Rect) -> tuple[int, bool, bool]:
    r = inst.openings[index].rect
    start, length = (r.x, r.w) if cut.axis == 0 else (r.y, r.h)
    overlaps = (max(r.y, line.y) < min(r.y + r.h, line.y + line.h) if cut.axis == 0 else
                max(r.x, line.x) < min(r.x + r.w, line.x + line.w))
    return (max(start - cut.at, cut.at - start - length, 0),
            overlaps and start < cut.at < start + length, overlaps and cut.at in {start, start + length})


def join_evidence(request: Request, inst: Facts, pieces: tuple[FabricationPolygon, ...], cuts: tuple[Cut, ...],
                  reason: str) -> tuple[list[dict], Evidence]:
    out = Evidence()
    joins = []
    reflex = reentrant_vertices(inst.polygon)
    # Exterior voids separate physical joins. A sink void can split stone
    # segments within one contiguous gross join, but cannot join two U arms.
    for cut, line in ((event, interval) for event in cuts for interval in common_lines(pieces, event)):
        lines = (line,)
        jid = f"{inst.id}-J{len(joins) + 1}"
        crossing = [j for j in range(len(inst.openings)) if opening_relation(inst, cut, j, line)[1]]
        selected = crossing[0] if len(crossing) == 1 else None
        kind = "inside-opening" if crossing else "corner" if any(p[cut.axis] == cut.at for p in reflex) else "outside-opening" if inst.openings else "solid"
        if inst.seam and inst.seam["cutoutIndex"] < len(inst.openings):
            r = inst.openings[inst.seam["cutoutIndex"]].rect
            center2 = 2 * (r.x if cut.axis == 0 else r.y) + (r.w if cut.axis == 0 else r.h)
            supplied_axis = 0 if inst.seam["kind"] == "center-through-cutout" else inst.axis
            supplied = cut.axis == supplied_axis and 2 * cut.at == center2
        else:
            supplied = False
        origin = "supplied" if supplied or inst.required_count is not None else "automatic"
        why = "supplied-join" if supplied else "supplied-count" if inst.required_count is not None else reason
        for j, opening in enumerate(inst.openings):
            gap, crosses, tangent = opening_relation(inst, cut, j, line)
            fields = [f"{inst.path}.cutouts[{j}].at", f"{inst.path}.sourceArrangement"]
            supported = request.profile == S1 and inst.documented_run and cut.axis == inst.axis and opening.kind in {"sink", "cooktop"}
            src = source(request.profile, "join", opening.kind) if request.profile in {S1, S2} else None
            if crosses:
                r = opening.rect
                center2 = 2 * (r.x if cut.axis == 0 else r.y) + (r.w if cut.axis == 0 else r.h)
                valid = supported and selected == j and 2 * cut.at == center2
                out.check("inside-opening-centerline", inst, "pass" if valid else "fail",
                          "Only the selected sink/cooktop centerline has the documented inside-join exception. All other openings retain their clearance checks.",
                          actual=Decimal(cut.at) * MM_PER_TICK, required=Decimal(center2) * MM_PER_TICK / 2,
                          src=src, cut=j, join=jid, fields=fields, operator="=")
            elif tangent:
                out.check("opening-join-applicability", inst, "fail", "Tangent joins are a different detail and are not implemented by this planner.",
                          src=src, cut=j, join=jid, fields=fields, operator="applicable")
            elif supported:
                out.minimum("outside-opening-clearance", inst, Decimal(gap) * MM_PER_TICK, request.gap_mm,
                            "Along-run clearance from this outside join to this opening; the exact metric limit is never rounded down.",
                            src=src, cut=j, join=jid, fields=fields)
            else:
                out.check("opening-join-applicability", inst, "unsupported", "This source/arrangement supplies no inspected numerical outside-join rule; no other profile's distance is substituted.",
                          src=src, cut=j, join=jid, fields=fields, operator="applicable")
            if supported:
                out.obligation("opening-continuous-support", inst,
                               "Provide continuous front/back rail support at this join, including outside-opening joins; independent fixture support is different.",
                               src=src, cut=j, join=jid)
        segments = tuple(s for line in lines for s in stone_segments(inst.polygon, line, inst.cuts))
        if not segments:
            out.check("solid-connectivity", inst, "fail", "This join has no stone connecting its proposed pieces.", join=jid, operator="applicable")
        starts = [r.y if cut.axis == 0 else r.x for r in lines]
        ends = [r.y + r.h if cut.axis == 0 else r.x + r.w for r in lines]
        joins.append({"id": jid, "installationId": inst.id,
                      "pieceIds": [f"{inst.id}-P{i + 1}" for i, piece in enumerate(pieces) if touches(piece, lines)],
                      "kind": kind, "axis": "x" if cut.axis == 0 else "y", "offsetIn": cut.at / 16,
                      "startIn": min(starts) / 16, "endIn": max(ends) / 16,
                      "segments": [{"x0": s.x / 16, "y0": s.y / 16, "x1": (s.x + s.w) / 16,
                                    "y1": (s.y + s.h) / 16} for s in segments], "cutoutIndex": selected,
                      "origin": origin, "reason": why})
    return joins, out


def make_plan(request: Request, inst: Facts, cuts: tuple[Cut, ...], reason: str) -> Plan:
    pieces = partition(inst, cuts)
    joins, evidence = join_evidence(request, inst, pieces, cuts, reason)
    evidence.extend(corner_evidence(request, inst, pieces))
    evidence.check("solid-connectivity", inst, "pass" if tiles(inst.polygon, pieces) and
                   all(connected(solid_cells(p, inst.cuts)) for p in pieces) else "fail",
                   "Gross fabrication polygons tile the installation and every resulting stone piece is connected.",
                   fields=[f"{inst.path}.shape", f"{inst.path}.cutouts"], operator="applicable")
    if inst.required_count is not None:
        evidence.check("supplied-piece-count", inst, "pass" if len(pieces) == inst.required_count else "fail",
                       "The supplied fabrication piece count is exact; it is not a source strength requirement.",
                       actual=len(pieces), required=inst.required_count, unit="count", operator="=",
                       fields=[f"{inst.path}.requiredPieceCount"])
    return Plan(pieces, cuts, joins, evidence)


def supplied_cuts(inst: Facts) -> tuple[tuple[Cut, ...], Evidence, bool]:
    out = Evidence()
    if inst.seam is None:
        return (), out, False
    seam = inst.seam
    index = seam["cutoutIndex"]
    error = None
    unsupported = seam["kind"] == "tangent-cutout"
    axis = 0 if seam["kind"] == "center-through-cutout" else inst.axis
    if index >= len(inst.openings):
        error = "The supplied join refers to an opening that does not exist."
    elif inst.polygon.area != inst.polygon.bounds.area:
        error = "The supplied opening-center join requires a rectangular run."
    elif unsupported:
        error = "Tangent joins are represented but are outside the implemented source detail."
    else:
        r = inst.openings[index].rect
        center2 = 2 * (r.x if axis == 0 else r.y) + (r.w if axis == 0 else r.h)
        length = inst.polygon.bounds.w if axis == 0 else inst.polygon.bounds.h
        if center2 % 2:
            error = "The exact opening center falls between 1/16-inch grid marks."
        elif seam["kind"] == "center-through-cutout" and (center2 != length or inst.required_count not in (None, 2)):
            error = "The equal-halves instruction requires a centered opening and exactly two pieces."
        elif inst.required_count == 1:
            error = "A supplied join cannot make only one fabrication piece."
    out.check("supplied-join", inst, "unsupported" if unsupported else "fail" if error else "pass",
              error or "The supplied opening-center join is retained; it does not waive any source rules.",
              cut=index if index < len(inst.openings) else None, fields=[f"{inst.path}.seam"], operator="applicable")
    if error:
        return (), out, True
    return (Cut(axis, center2 // 2),), out, False


def candidate_events(request: Request, inst: Facts) -> tuple[Cut, ...]:
    b = inst.polygon.bounds
    axes = (inst.axis,) if inst.documented_run and inst.openings else (0, 1)
    events = set()
    for axis in axes:
        length = b.w if axis == 0 else b.h
        for n in range(2, MAX_PIECES + 1):
            for k in range(1, n):
                events.add(Cut(axis, length * k // n))
        if request.usable:
            capacities = {request.usable.w if axis == 0 else request.usable.h}
            if request.rotate:
                capacities |= {request.usable.h if axis == 0 else request.usable.w}
            for capacity in capacities:
                for k in range(1, min(MAX_PIECES, ceil(length / capacity)) + 1):
                    events.update((Cut(axis, k * capacity), Cut(axis, length - k * capacity)))
        gap = int((request.gap_mm / MM_PER_TICK).to_integral_value(rounding=ROUND_CEILING)) if request.gap_mm else 0
        for opening in inst.openings:
            r = opening.rect
            start, size = (r.x, r.w) if axis == 0 else (r.y, r.h)
            events.update((Cut(axis, start - gap), Cut(axis, start + size + gap)))
            if request.profile == S1 and inst.documented_run and opening.kind in {"sink", "cooktop"} and size % 2 == 0:
                events.add(Cut(axis, start + size // 2))
        for vertex in reentrant_vertices(inst.polygon):
            events.add(Cut(axis, vertex[axis]))
    return tuple(sorted(c for c in events if 0 < c.at < (b.w if c.axis == 0 else b.h)))


def fits(request: Request, pieces: tuple[FabricationPolygon, ...]) -> bool:
    return request.usable is not None and all(orientations(p, request.usable, request.rotate) for p in pieces)


def enumerate_plans(request: Request, inst: Facts) -> tuple[list[Plan], int, bool, set[str], Evidence]:
    required, supplied, invalid = supplied_cuts(inst)
    families = {"supplied"} if inst.seam or inst.required_count else set()
    if invalid:
        return [], 0, False, families, supplied
    whole = (inst.polygon,)
    whole_corners = corner_evidence(request, inst, whole)
    reason = "stock-fit" if not fits(request, whole) else "source-rule" if whole_corners.failed else "yield"
    fixed_two = bool(inst.seam and inst.seam["kind"] == "center-through-cutout")
    maximum = 2 if fixed_two else min(inst.required_count or MAX_PIECES, MAX_PIECES)
    events = candidate_events(request, inst)
    initial = make_plan(request, inst, required, reason)
    if required:
        for check in initial.evidence.checks:
            if check["status"] == "fail" and check["ruleId"] not in {"supplied-piece-count", "continuous-inside-radius"}:
                supplied.checks.append({**check, "joinId": None,
                                        "fields": list(dict.fromkeys([*check["fields"], f"{inst.path}.seam"]))})
        if supplied.failed:
            return [], 1, False, families, supplied
    if fixed_two and not fits(request, initial.pieces):
        supplied.check("stock-fit", inst, "fail", "The exact equal-halves instruction leaves a blank that cannot fit the usable slab.",
                       fields=["material.slab", f"{inst.path}.seam"], operator="applicable")
        return [], 1, False, families, supplied
    frontier = [initial]
    seen = {required}
    result = []
    visited = 0
    capped = False
    while frontier:
        following = []
        for plan in frontier:
            visited += 1
            if visited > MAX_STATES:
                capped = True
                break
            physical_fail = any(c["status"] == "fail" and c["ruleId"] not in {"supplied-piece-count", "continuous-inside-radius"}
                                for c in plan.evidence.checks)
            if physical_fail or len(plan.pieces) > maximum:
                continue
            fits_now = fits(request, plan.pieces)
            if not plan.evidence.failed and fits_now and (not fixed_two or len(plan.pieces) == 2):
                result.append(plan)
            if len(plan.pieces) >= maximum or (fixed_two and len(plan.pieces) == 2):
                continue
            # Once a source-admitted stock-fitting plan exists, still compare two
            # extra-piece layers for yield. Larger omitted plans stay a proof limit.
            if inst.required_count is None and result and len(plan.pieces) >= min(len(p.pieces) for p in result) + 2:
                capped = True
                continue
            for event in events:
                cuts = tuple(sorted((*plan.cuts, event)))
                if event in plan.cuts or cuts in seen:
                    continue
                seen.add(cuts)
                candidate = make_plan(request, inst, cuts, reason)
                if len(candidate.pieces) == len(plan.pieces) or len(candidate.pieces) > maximum:
                    continue
                if any(c["status"] == "fail" and c["ruleId"] not in {"supplied-piece-count", "continuous-inside-radius"}
                       for c in candidate.evidence.checks):
                    continue
                following.append(candidate)
        if visited > MAX_STATES:
            break
        if len(following) > BEAM:
            capped = True
        def priority(p: Plan) -> tuple:
            oversized = sum(piece.area for piece in p.pieces if not fits(request, (piece,)))
            bad_corners = any(c["status"] == "fail" and c["ruleId"] == "continuous-inside-radius" for c in p.evidence.checks)
            return oversized, bad_corners, p.evidence.conditional, -min(piece.area for piece in p.pieces), p.cuts
        frontier = sorted(following, key=priority)[:BEAM]
    for plan in result:
        if not plan.cuts:
            families.add("whole")
        for join in plan.joins:
            families.add("opening-center" if join["kind"] == "inside-opening" else "corner" if join["kind"] == "corner" else "stock-fit")
    # The uncut candidate was inspected even if rejected for stock fit or radius.
    families.add("whole")
    result.sort(key=lambda p: (p.evidence.conditional, len(p.joins), sum(j["kind"] == "inside-opening" for j in p.joins),
                               -min(piece.area for piece in p.pieces), p.cuts))
    return result, min(visited, MAX_STATES), capped, families, supplied


def combined_plans(choices: list[list[Plan]]):
    """Visit low-join alternatives across all installations, avoiding product-prefix bias."""
    start = (0,) * len(choices)
    seen = {start}
    queue = [(0, start)]
    while queue:
        _, indices = heappop(queue)
        yield tuple(options[index] for options, index in zip(choices, indices))
        for n in range(len(indices)):
            if indices[n] + 1 >= len(choices[n]):
                continue
            following = indices[:n] + (indices[n] + 1,) + indices[n + 1:]
            if following not in seen:
                seen.add(following)
                heappush(queue, (sum(following), following))


def clipped_openings(piece: FabricationPolygon, inst: Facts) -> list[dict]:
    clips = []
    for j, opening in enumerate(inst.openings):
        r = opening.rect
        for cell in piece.collision_cells:
            x, y = max(cell.x, r.x), max(cell.y, r.y)
            w, h = min(cell.x + cell.w, r.x + r.w) - x, min(cell.y + cell.h, r.y + r.h) - y
            if w > 0 and h > 0:
                clips.append({"cutoutIndex": j, "outline": [[px / 16, py / 16] for px, py in Rect(x, y, w, h).points]})
    return clips


def layout_wire(request: Request, plans: tuple[Plan, ...], packing: Packing, lower: int, capped: bool) -> dict:
    pieces = []
    joins = []
    for inst, plan in zip(request.installations, plans):
        pieces.extend({"id": f"{inst.id}-P{i + 1}", "installationId": inst.id,
                       "outline": [[x / 16, y / 16] for x, y in piece.outline], "cutouts": clipped_openings(piece, inst)}
                      for i, piece in enumerate(plan.pieces))
        joins.extend(plan.joins)
    return {"pieces": pieces, "joins": joins,
            "slabs": [{"index": s + 1, "placements": [
                {"pieceId": piece["id"], "x": pose.x / 16, "y": pose.y / 16, "quarterTurns": pose.turns}
                for piece, pose in zip(pieces, packing.poses) if pose.slab == s]} for s in range(packing.slab_count)],
            "slabCount": packing.slab_count, "lowerBound": lower,
            # This proves slab count only. Candidate coverage and secondary-objective
            # limitations remain explicit in assessment.search even at the area bound.
            "provenOptimal": not capped and packing.slab_count == lower,
            "footprintMode": "gross-polygons", "warnings": [
                "Gross blanks reserve the openings; opening stock is not reused.",
                "Only slab count can be proved by the global area bound; seam-choice coverage is finite.",
            ]}


def necessities(request: Request, plans: tuple[Plan, ...] | None) -> list[dict]:
    results = []
    for i, inst in enumerate(request.installations):
        whole = corner_evidence(request, inst, (inst.polygon,))
        if request.usable is not None and not fits(request, (inst.polygon,)):
            kind, explanation = "stock-fit", "The whole outline cannot fit the usable slab in any permitted quarter-turn."
        elif whole.failed and plans and not plans[i].evidence.failed:
            kind, explanation = "source-rule", "A corner join removes a supplied continuous-corner radius conflict; support requirements remain."
        elif not request.model_known or (inst.openings and not inst.documented_run) or whole.failed:
            kind, explanation = "undetermined", "Missing or unsupported model details prevent a seamless source-rule conclusion."
        else:
            kind, explanation = "none-required", "No seam is required by the evaluated dimensions. Selected yield or supplied-count joins are labelled separately."
        results.append({"id": inst.id, "seamNecessity": kind, "explanation": explanation})
    return results


def assessment_wire(request: Request, evidence: Evidence, status: str, search: dict, plans=None) -> dict:
    return {"status": status, "geometry": "valid", "profile": {
        "id": request.profile, "provenance": request.provenance,
        "nominalThicknessMm": request.raw["material"]["nominalThicknessMm"]},
        "checks": evidence.checks, "conditions": evidence.conditions,
        "unresolved": [{"field": f, "question": q} for f, q in sorted(evidence.questions.items())],
        "handling": "not-evaluated", "limitations": LIMITATIONS + (["MSI Q is a sparse profile; numerical opening seam/rail rules and through-opening permission are not established."] if request.profile == S2 else []),
        "installations": necessities(request, plans), "search": search}


def solve_assessment(data: dict, *, work_budget: float = 0.12) -> dict:
    request = read_request(data)
    if data["mode"] == "geometry-replay":
        return replay(request)
    base = profile_evidence(request)
    originals = [original_evidence(request, inst) for inst in request.installations]
    for evidence in originals:
        base.extend(evidence)
    search = {"status": "not-run", "candidateFamilies": [], "candidateCount": 0, "qualifyingCount": 0,
              "packing": "not-run", "optimality": "not-proven", "limits": list(LIMITS)}
    def reply(evidence, status, layout=None, plans=None):
        return {"ok": True, "version": 2, "assessment": assessment_wire(request, evidence, status, search, plans), "layout": layout}
    if request.usable is None:
        base.ask("material.slab", "What are the supplier slab length and width in inches?")
    if data["phase"] == "assess":
        for inst in request.installations:
            base.extend(corner_evidence(request, inst, (inst.polygon,)))
            _, supplied, _ = supplied_cuts(inst)
            base.extend(supplied)
        status = "conflict" if base.failed else "unresolved" if not request.model_known else "conditional" if base.conditional else "assessed"
        return reply(base, status)
    if base.failed or not request.model_known or request.usable is None:
        for inst in request.installations:
            base.extend(corner_evidence(request, inst, (inst.polygon,)))
        return reply(base, "conflict" if base.failed else "unresolved")
    choices = []
    capped = work_budget <= 0
    families = set()
    for inst in request.installations:
        plans, count, limited, found, supplied = enumerate_plans(request, inst)
        base.extend(supplied)
        search["candidateCount"] += count
        families |= found
        capped |= limited
        choices.append(plans)
        if not plans and inst.required_count == 1:
            whole = make_plan(request, inst, (), "supplied-count")
            base.extend(whole.evidence)
            base.check("stock-fit", inst, "pass" if fits(request, whole.pieces) else "fail",
                       "The exact one-piece constraint requires the whole outline to fit one usable slab.",
                       fields=["material.slab", f"{inst.path}.requiredPieceCount"], operator="applicable")
    search["candidateFamilies"] = sorted(families)
    search["status"] = "capped" if capped else "complete"
    if base.failed:
        return reply(base, "conflict")
    if any(not p for p in choices):
        search["status"] = "capped"
        return reply(base, "unresolved" if any(c["status"] == "unsupported" and c["ruleId"] == "supplied-join" for c in base.checks) else "search-incomplete")
    capped |= prod(map(len, choices)) > MAX_COMBINATIONS
    area = sum(i.polygon.area for i in request.installations)
    lower = (area + request.usable.area - 1) // request.usable.area
    incumbents = []
    for plans in islice(combined_plans(choices), MAX_COMBINATIONS):
        search["candidateCount"] += 1
        pieces = tuple(piece for plan in plans for piece in plan.pieces)
        if len(pieces) > MAX_PIECES:
            capped = True
            continue
        # This is also the timeout fallback path. Never pack a rejected candidate.
        if any(plan.evidence.failed for plan in plans):
            continue
        packing = greedy(pieces, request.usable, request.kerf, request.rotate)
        if packing is None:
            continue
        search["qualifyingCount"] += 1
        rank = (base.conditional or any(p.evidence.conditional for p in plans), packing.slab_count,
                sum(len(p.joins) for p in plans), sum(j["kind"] == "inside-opening" for p in plans for j in p.joins),
                -min(p.area for p in pieces), tuple(p.cuts for p in plans))
        incumbents.append((rank, plans, packing))
    if not incumbents:
        search["status"] = "capped"
        return reply(base, "search-incomplete")
    incumbents.sort(key=lambda p: p[0])
    best = incumbents[0]
    # Refine a bounded shortlist; whole polygons remain candidates even when a
    # corner-decomposed plan happens to have a quick greedy packing.
    for rank, plans, seed in incumbents[:8] if work_budget > 0 else []:
        pieces = tuple(p for plan in plans for p in plan.pieces)
        packed = pack(pieces, request.usable, request.kerf, request.rotate, work_budget / 8)
        if packed is None:
            continue
        candidate = (rank[:1] + (packed.slab_count,) + rank[2:], plans, packed)
        if candidate[0] < best[0]:
            best = candidate
        capped |= not packed.proven
    rank, plans, packing = best
    final = Evidence()
    final.extend(base)
    for plan in plans:
        final.extend(plan.evidence)
    assert not final.failed
    search.update(status="capped" if capped else "complete", packing="polygon-cells",
                  optimality="global-slab-bound" if not capped and packing.slab_count == lower else "not-proven")
    return reply(final, "conditional" if final.conditional else "assessed",
                 layout_wire(request, plans, packing, lower, capped), plans)


def replay(request: Request) -> dict:
    """Explicit developer adapter; the old solver remains byte-frozen internally."""
    from layout import solve
    legacy = {"slab": request.raw["slab"], "settings": {**request.raw["settings"], **request.raw["legacySettings"]},
              "installations": [{"id": i.id, "outline": raw["outline"],
                                 "cutouts": [{k: c[k] for k in ("kind", "x", "y", "w", "h")} for c in raw["cutouts"]],
                                 **({"requiredPieceCount": i.required_count} if i.required_count is not None else {}),
                                 **({"seam": i.seam} if i.seam else {})}
                                for i, raw in zip(request.installations, request.raw["installations"])]}
    evidence = profile_evidence(request)
    search = {"status": "not-run", "candidateFamilies": [], "candidateCount": 0, "qualifyingCount": 0,
              "packing": "not-run", "optimality": "not-proven", "limits": ["Development-only geometry replay; no physical assessment."]}
    assessment = assessment_wire(request, evidence, "unresolved", search)
    assessment["limitations"].append("DEVELOPMENT ONLY: geometry-replay-unassessed; not a normal quote or source-backed seam plan.")
    if request.usable is None or request.raw["phase"] == "assess":
        return {"ok": True, "version": 2, "assessment": assessment, "layout": None}
    old = solve(legacy)
    pieces = []
    joins = []
    for inst in request.installations:
        inst_pieces = [p for p in old["pieces"] if p["installationId"] == inst.id]
        polygons = tuple(FabricationPolygon(tuple((int(x * 16), int(y * 16)) for x, y in p["outline"])) for p in inst_pieces)
        pieces.extend({**p, "cutouts": clipped_openings(poly, inst)} for p, poly in zip(inst_pieces, polygons))
        for n, seam in enumerate(s for s in old["seams"] if s["installationId"] == inst.id):
            line = Rect(int(seam["x0"] * 16), int(seam["y0"] * 16), int((seam["x1"] - seam["x0"]) * 16), int((seam["y1"] - seam["y0"]) * 16))
            selected = inst.seam["cutoutIndex"] if inst.seam else None
            joins.append({"id": f"{inst.id}-J{n + 1}", "installationId": inst.id,
                          "pieceIds": [p["id"] for p, poly in zip(inst_pieces, polygons) if touches(poly, (line,))],
                          "kind": "inside-opening" if selected is not None else "solid", "axis": "x" if line.w == 0 else "y",
                          "offsetIn": (line.x if line.w == 0 else line.y) / 16,
                          "startIn": (line.y if line.w == 0 else line.x) / 16,
                          "endIn": (line.y + line.h if line.w == 0 else line.x + line.w) / 16,
                          "segments": [{"x0": s.x / 16, "y0": s.y / 16, "x1": (s.x + s.w) / 16, "y1": (s.y + s.h) / 16}
                                       for s in stone_segments(inst.polygon, line, inst.cuts)], "cutoutIndex": selected,
                          "origin": "supplied" if inst.seam or inst.required_count else "automatic",
                          "reason": "supplied-join" if inst.seam else "supplied-count" if inst.required_count else "stock-fit"})
    layout = {"pieces": pieces, "joins": joins, "slabs": [{"index": s["index"], "placements": [
        {"pieceId": p["pieceId"], "x": p["x"], "y": p["y"], "quarterTurns": int(p["rotated"])} for p in s["placements"]]} for s in old["slabs"]],
        **{k: old[k] for k in ("slabCount", "lowerBound", "provenOptimal", "warnings")}, "footprintMode": "gross-polygons"}
    return {"ok": True, "version": 2, "assessment": assessment, "layout": layout}
