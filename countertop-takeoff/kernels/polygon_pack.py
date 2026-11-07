"""Deterministic orthogonal polygon nesting; cells of a piece move together."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, islice, product

from layout_geometry import FabricationPolygon, Rect, packing_fits, place_rect
from ortools.sat.python import cp_model


@dataclass(frozen=True)
class Pose:
    slab: int
    x: int
    y: int
    turns: int


@dataclass(frozen=True)
class Packing:
    poses: tuple[Pose, ...]
    slab_count: int
    proven: bool


def orientations(piece: FabricationPolygon, usable: Rect, rotate: bool) -> tuple[int, ...]:
    result = []
    seen = set()
    for turns in range(4 if rotate else 1):
        rotated = piece.placed(0, 0, turns)
        key = tuple(sorted(rotated.collision_cells))
        if key not in seen and rotated.bounds.w <= usable.w and rotated.bounds.h <= usable.h:
            seen.add(key)
            result.append(turns)
    return tuple(result)


def greedy(pieces: tuple[FabricationPolygon, ...], usable: Rect, kerf: int, rotate: bool) -> Packing | None:
    poses: dict[int, Pose] = {}
    slabs: list[list[FabricationPolygon]] = []
    for index in sorted(range(len(pieces)), key=lambda i: (-pieces[i].area, i)):
        piece = pieces[index]
        rotations = orientations(piece, usable, rotate)
        if not rotations:
            return None
        placed = False
        for slab in range(len(slabs) + 1):
            existing = slabs[slab] if slab < len(slabs) else []
            for turns in rotations:
                rotated = piece.placed(0, 0, turns)
                xs, ys = {0}, {0}
                for other in existing:
                    for a in other.collision_cells:
                        for b in rotated.collision_cells:
                            xs.update((a.x + a.w + kerf - b.x, a.x - kerf - b.x - b.w))
                            ys.update((a.y + a.h + kerf - b.y, a.y - kerf - b.y - b.h))
                xs = {x for x in xs if 0 <= x <= usable.w - rotated.bounds.w}
                ys = {y for y in ys if 0 <= y <= usable.h - rotated.bounds.h}
                for y, x in islice(product(sorted(ys), sorted(xs)), 1024):
                    candidate = piece.placed(x, y, turns)
                    if packing_fits([*existing, candidate], usable, kerf):
                        if slab == len(slabs):
                            slabs.append([])
                        slabs[slab].append(candidate)
                        poses[index] = Pose(slab, x, y, turns)
                        placed = True
                        break
                if placed:
                    break
            if placed:
                break
    return Packing(tuple(poses[i] for i in range(len(pieces))), len(slabs), False)


def pack(pieces: tuple[FabricationPolygon, ...], usable: Rect, kerf: int, rotate: bool,
         budget: float = 0.15) -> Packing | None:
    seed = greedy(pieces, usable, kerf, rotate)
    if seed is None or budget <= 0:
        return seed
    lower = (sum(p.area for p in pieces) + usable.area - 1) // usable.area
    if seed.slab_count == lower:
        return Packing(seed.poses, seed.slab_count, True)
    model = cp_model.CpModel()
    count = model.new_int_var(lower, seed.slab_count, "slabs")
    variables = []
    cells = []
    for index, piece in enumerate(pieces):
        rotation = model.new_int_var_from_domain(cp_model.Domain.from_values(orientations(piece, usable, rotate)), "turns")
        slab = model.new_int_var(0, seed.slab_count - 1, "slab")
        x, y = model.new_int_var(0, usable.w, "x"), model.new_int_var(0, usable.h, "y")
        model.add(slab < count)
        component = []
        for cell in piece.collision_cells:
            options = [place_rect(cell, piece.bounds, 0, 0, q) for q in range(4)]
            offsets = []
            for values in ([r.x for r in options], [r.y for r in options],
                           [r.w for r in options], [r.h for r in options]):
                variable = model.new_int_var(min(values), max(values), "cell_geometry")
                model.add_element(rotation, values, variable)
                offsets.append(variable)
            dx, dy, width, height = offsets
            model.add(x + dx + width <= usable.w)
            model.add(y + dy + height <= usable.h)
            component.append((x + dx, y + dy, width, height))
        cells.append(component)
        variables.append((slab, x, y, rotation))
        for variable, value in zip(variables[-1], (seed.poses[index].slab, seed.poses[index].x,
                                                  seed.poses[index].y, seed.poses[index].turns)):
            model.add_hint(variable, value)
    for i, j in combinations(range(len(pieces)), 2):
        different = model.new_bool_var("different_slabs")
        model.add(variables[i][0] != variables[j][0]).only_enforce_if(different)
        for a, b in product(cells[i], cells[j]):
            alternatives = []
            for relation in (a[0] + a[2] + kerf <= b[0], b[0] + b[2] + kerf <= a[0],
                             a[1] + a[3] + kerf <= b[1], b[1] + b[3] + kerf <= a[1]):
                separated = model.new_bool_var("separated")
                model.add(relation).only_enforce_if(separated)
                alternatives.append(separated)
            model.add_bool_or([different, *alternatives])
    model.minimize(count)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_deterministic_time = budget
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return seed
    poses = tuple(Pose(*(solver.value(v) for v in values)) for values in variables)
    labels = {label: i for i, label in enumerate(sorted({p.slab for p in poses}))}
    poses = tuple(Pose(labels[p.slab], p.x, p.y, p.turns) for p in poses)
    for slab in labels.values():
        assert packing_fits([piece.placed(p.x, p.y, p.turns) for piece, p in zip(pieces, poses)
                             if p.slab == slab], usable, kerf)
    return Packing(poses, len(labels), status == cp_model.OPTIMAL)
