"""Gross orthogonal fabrication footprints, in integer sixteenth-inch units.

A polygon is one connected piece, regardless of its collision-cell count.
Openings remain reserved within the gross footprint. These geometric checks
make no claim about material strength, cutting access or fabrication approval.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from itertools import combinations, pairwise

Point = tuple[int, int]


@dataclass(frozen=True, order=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def area(self) -> int:
        return self.w * self.h

    @property
    def points(self) -> tuple[Point, ...]:
        return ((self.x, self.y), (self.x + self.w, self.y),
                (self.x + self.w, self.y + self.h), (self.x, self.y + self.h))


def distance2(a: Rect, b: Rect) -> int:
    dx = max(a.x - b.x - b.w, b.x - a.x - a.w, 0)
    dy = max(a.y - b.y - b.h, b.y - a.y - a.h, 0)
    return dx * dx + dy * dy


def edges(outline: tuple[Point, ...]) -> list[Rect]:
    return [Rect(min(a[0], b[0]), min(a[1], b[1]), abs(a[0] - b[0]), abs(a[1] - b[1]))
            for a, b in zip(outline, outline[1:] + outline[:1])]


class InvalidPolygon(ValueError):
    pass


@dataclass(frozen=True)
class FabricationPolygon:
    """One simple outer ring; multiple islands, holes and self-touch are rejected.

    A simple closed ring guarantees a connected interior. Cell decomposition
    is derived geometry, never a fabrication partition or a source of seams.
    """

    outline: tuple[Point, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.outline, (tuple, list)) or any(
            not isinstance(p, (tuple, list)) or len(p) != 2 or any(type(v) is not int for v in p)
            for p in self.outline
        ):
            raise InvalidPolygon("Outline coordinates must be pairs of whole sixteenth-inch units.")
        outline = tuple((p[0], p[1]) for p in self.outline)
        if outline and outline[0] == outline[-1]:
            outline = outline[:-1]
        if len(outline) < 4 or any((a[0] == b[0]) == (a[1] == b[1])
                                   for a, b in zip(outline, outline[1:] + outline[:1])):
            raise InvalidPolygon("draw a closed outline with horizontal and vertical edges.")
        boundary = edges(outline)
        for i, a in enumerate(boundary):
            for j in range(i + 1, len(boundary)):
                b = boundary[j]
                adjacent = j == i + 1 or (i == 0 and j == len(boundary) - 1)
                # Adjacent edges may share only their endpoint, including when
                # collinear. Backtracking along the previous edge is invalid.
                overlap = (min(a.x + a.w, b.x + b.w) > max(a.x, b.x)
                           or min(a.y + a.h, b.y + b.h) > max(a.y, b.y))
                if distance2(a, b) == 0 and (not adjacent or overlap):
                    raise InvalidPolygon("the outline crosses or touches itself.")
        object.__setattr__(self, "outline", outline)

    @cached_property
    def bounds(self) -> Rect:
        xs, ys = zip(*self.outline)
        return Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    @cached_property
    def area(self) -> int:
        return abs(sum(a[0] * b[1] - b[0] * a[1]
                       for a, b in zip(self.outline, self.outline[1:] + self.outline[:1]))) // 2

    @cached_property
    def collision_cells(self) -> tuple[Rect, ...]:
        """Disjoint horizontal bands covering the exact gross polygon."""
        boundary = edges(self.outline)
        cells: list[Rect] = []
        for top, bottom in pairwise(sorted({y for _, y in self.outline})):
            # Doubled midpoints avoid floats, including for large coordinates.
            crossings = sorted(e.x for e in boundary
                               if e.w == 0 and 2 * e.y < top + bottom < 2 * (e.y + e.h))
            cells.extend(Rect(left, top, right - left, bottom - top)
                         for left, right in zip(crossings[::2], crossings[1::2]))
        return tuple(cells)

    def placed(self, x: int, y: int, quarter_turns: int = 0) -> FabricationPolygon:
        """Rotate clockwise in x-right/y-down coordinates; set bbox origin to x,y.

        Only rigid quarter turns are supported, with no reflection. The ring's
        vertex order is retained so the transform is unambiguous for callers.
        """
        if type(x) is not int or type(y) is not int or type(quarter_turns) is not int or not 0 <= quarter_turns < 4:
            raise ValueError("Placement needs integer coordinates and 0, 1, 2 or 3 quarter turns.")
        bounds = self.bounds
        points = []
        for px, py in self.outline:
            u, v = px - bounds.x, py - bounds.y
            if quarter_turns == 1:
                u, v = bounds.h - v, u
            elif quarter_turns == 2:
                u, v = bounds.w - u, bounds.h - v
            elif quarter_turns == 3:
                u, v = v, bounds.w - u
            points.append((x + u, y + v))
        return FabricationPolygon(tuple(points))


def _separated(a: FabricationPolygon, b: FabricationPolygon, gap: int) -> bool:
    # Check distinct fabrication pieces only. Internal cells touch by design.
    return all(left.x + left.w + gap <= right.x or right.x + right.w + gap <= left.x
               or left.y + left.h + gap <= right.y or right.y + right.h + gap <= left.y
               for left in a.collision_cells for right in b.collision_cells)


def tiles(whole: FabricationPolygon, pieces: Sequence[FabricationPolygon]) -> bool:
    """Exact gross coverage: no overlap, missing region or protrusion."""
    if sum(p.area for p in pieces) != whole.area or any(
        not _separated(a, b, 0) for a, b in combinations(pieces, 2)
    ):
        return False
    # Both decompositions have disjoint cells, so intersection areas add exactly.
    return all(sum(max(0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
                   * max(0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
                   for b in whole.collision_cells) == a.area
               for piece in pieces for a in piece.collision_cells)


def packing_fits(pieces: Sequence[FabricationPolygon], usable: Rect, kerf: int) -> bool:
    """Check one slab using the existing orthogonal axis-gap kerf convention.

    Each input polygon is one already-transformed piece. No kerf is applied
    between its own cells; even identical polygons listed twice are two pieces.
    """
    if type(kerf) is not int or kerf < 0 or usable.w <= 0 or usable.h <= 0:
        raise ValueError("Use a nonnegative integer kerf and a positive usable slab size.")
    return all(usable.x <= p.bounds.x and usable.y <= p.bounds.y
               and p.bounds.x + p.bounds.w <= usable.x + usable.w
               and p.bounds.y + p.bounds.h <= usable.y + usable.h for p in pieces) and all(
        _separated(a, b, kerf) for a, b in combinations(pieces, 2)
    )


def solid_cells(polygon: FabricationPolygon, openings: Sequence[Rect]) -> tuple[Rect, ...]:
    """Subtract opening envelopes for connectivity/drawing, never stock reuse."""
    cells = list(polygon.collision_cells)
    for cut in openings:
        remaining = []
        for cell in cells:
            left, top = max(cell.x, cut.x), max(cell.y, cut.y)
            right, bottom = min(cell.x + cell.w, cut.x + cut.w), min(cell.y + cell.h, cut.y + cut.h)
            if left >= right or top >= bottom:
                remaining.append(cell)
                continue
            remaining.extend(r for r in (
                Rect(cell.x, cell.y, cell.w, top - cell.y),
                Rect(cell.x, bottom, cell.w, cell.y + cell.h - bottom),
                Rect(cell.x, top, left - cell.x, bottom - top),
                Rect(right, top, cell.x + cell.w - right, bottom - top),
            ) if r.area > 0)
        cells = remaining
    return tuple(cells)


def connected(cells: Sequence[Rect]) -> bool:
    """Solid regions must share an edge with positive length, not just a point."""
    if not cells:
        return False
    unseen = set(range(1, len(cells)))
    queue = [0]
    while queue:
        a = cells[queue.pop()]
        adjacent = {i for i in unseen if (
            (a.x + a.w == cells[i].x or cells[i].x + cells[i].w == a.x)
            and max(a.y, cells[i].y) < min(a.y + a.h, cells[i].y + cells[i].h)
        ) or (
            (a.y + a.h == cells[i].y or cells[i].y + cells[i].h == a.y)
            and max(a.x, cells[i].x) < min(a.x + a.w, cells[i].x + cells[i].w)
        )}
        unseen -= adjacent
        queue.extend(sorted(adjacent))
    return not unseen


def reentrant_vertices(polygon: FabricationPolygon) -> tuple[Point, ...]:
    ring = polygon.outline
    clockwise = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1])) > 0
    return tuple(b for a, b, c in zip(ring[-1:] + ring[:-1], ring, ring[1:] + ring[:1])
                 if ((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
                 * (1 if clockwise else -1) < 0)


def place_rect(rect: Rect, bounds: Rect, x: int, y: int, turns: int) -> Rect:
    """Apply the parent piece's rigid transform to a collision cell or opening."""
    u, v, w, h = rect.x - bounds.x, rect.y - bounds.y, rect.w, rect.h
    if turns == 1:
        u, v, w, h = bounds.h - v - h, u, h, w
    elif turns == 2:
        u, v = bounds.w - u - w, bounds.h - v - h
    elif turns == 3:
        u, v, w, h = v, bounds.w - u - w, h, w
    return Rect(x + u, y + v, w, h)


def split_polygon(polygon: FabricationPolygon, axis: int, at: int) -> tuple[FabricationPolygon, ...]:
    """Split along an axis line; each connected gross component is one piece."""
    xs = sorted({x for x, _ in polygon.outline} | ({at} if axis == 0 else set()))
    ys = sorted({y for _, y in polygon.outline} | ({at} if axis == 1 else set()))
    cells = {(i, j) for i, (left, right) in enumerate(pairwise(xs))
             for j, (top, bottom) in enumerate(pairwise(ys))
             if any(2 * c.x < left + right < 2 * (c.x + c.w)
                    and 2 * c.y < top + bottom < 2 * (c.y + c.h) for c in polygon.collision_cells)}
    pieces = []
    for side in (False, True):
        todo = {cell for cell in cells if ((xs[cell[0]] if axis == 0 else ys[cell[1]]) >= at) == side}
        while todo:
            component = {min(todo)}
            queue = list(component)
            todo -= component
            while queue:
                i, j = queue.pop()
                adjacent = {(i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1)} & todo
                todo -= adjacent
                component |= adjacent
                queue.extend(sorted(adjacent))
            boundary: set[tuple[Point, Point]] = set()
            for i, j in sorted(component):
                ring = ((xs[i], ys[j]), (xs[i + 1], ys[j]),
                        (xs[i + 1], ys[j + 1]), (xs[i], ys[j + 1]))
                for a, b in zip(ring, ring[1:] + ring[:1]):
                    if (b, a) in boundary:
                        boundary.remove((b, a))
                    else:
                        boundary.add((a, b))
            following = dict(boundary)
            start = min(following)
            traced = [start]
            point = following.pop(start)
            while point != start:
                traced.append(point)
                point = following.pop(point)
            if following:
                raise InvalidPolygon("A split produced a hole or touching boundary.")
            simplified = tuple(b for a, b, c in zip(traced[-1:] + traced[:-1], traced, traced[1:] + traced[:1])
                               if not (a[0] == b[0] == c[0] or a[1] == b[1] == c[1]))
            pieces.append(FabricationPolygon(simplified))
    return tuple(sorted(pieces, key=lambda p: p.outline))


def stone_segments(polygon: FabricationPolygon, line: Rect, openings: Sequence[Rect]) -> tuple[Rect, ...]:
    """Intersect a logical join with stone; join geometry never bridges a void."""
    horizontal = line.h == 0
    intervals = []
    for cell in solid_cells(polygon, openings):
        if horizontal and cell.y <= line.y <= cell.y + cell.h:
            intervals.append((max(line.x, cell.x), min(line.x + line.w, cell.x + cell.w)))
        elif not horizontal and cell.x <= line.x <= cell.x + cell.w:
            intervals.append((max(line.y, cell.y), min(line.y + line.h, cell.y + cell.h)))
    merged: list[tuple[int, int]] = []
    for lo, hi in sorted(intervals):
        if lo >= hi:
            continue
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(hi, merged[-1][1]))
        else:
            merged.append((lo, hi))
    return tuple(Rect(lo, line.y, hi - lo, 0) if horizontal else Rect(line.x, lo, 0, hi - lo)
                 for lo, hi in merged)
