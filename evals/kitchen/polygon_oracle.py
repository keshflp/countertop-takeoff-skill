"""Exact independent polygon checks; computational cells never become seams."""

from collections import deque

from eval import Edge, Point, Rect, area, inside, merge_edges, points, require

Polygon = list[Point]


def edges(poly: Polygon) -> list[tuple[Point, Point]]:
    return list(zip(poly, poly[1:] + poly[:1]))


def simple(raw: list) -> Polygon:
    poly = points(raw)
    area(poly)
    sides = edges(poly)
    for index, (a, b) in enumerate(sides):
        for other, (c, d) in enumerate(sides[index + 1:], index + 1):
            if other == index + 1 or index == 0 and other == len(sides) - 1:
                continue
            ax, bx = sorted((a[0], b[0]))
            ay, by = sorted((a[1], b[1]))
            cx, dx = sorted((c[0], d[0]))
            cy, dy = sorted((c[1], d[1]))
            require(bx < cx or dx < ax or by < cy or dy < ay,
                    "polygon has crossing or touching nonadjacent edges")
    return poly


def bbox(poly: Polygon) -> Rect:
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def cells(poly: Polygon, holes: list[Rect] = ()) -> list[Rect]:
    """Coordinate compression covers the gross polygon or its actual remaining solid."""
    box = bbox(poly)
    xs = sorted({x for x, _ in poly} | {x for h in holes for x in (h.x, h.right) if box.x < x < box.right})
    ys = sorted({y for _, y in poly} | {y for h in holes for y in (h.y, h.bottom) if box.y < y < box.bottom})
    return [Rect(x0, y0, x1 - x0, y1 - y0)
            for x0, x1 in zip(xs, xs[1:]) for y0, y1 in zip(ys, ys[1:])
            if inside(poly, x0 + x1, y0 + y1)
            and not any(h.contains_center(x0 + x1, y0 + y1) for h in holes)]


def connected(poly: Polygon, holes: list[Rect] = ()) -> None:
    solid = cells(poly, holes)
    require(bool(solid), "fabrication piece has no positive solid area")
    reached, queue = {0}, deque([0])
    while queue:
        a = solid[queue.popleft()]
        for index, b in enumerate(solid):
            if index in reached:
                continue
            horizontal = (a.right == b.x or b.right == a.x) and min(a.bottom, b.bottom) > max(a.y, b.y)
            vertical = (a.bottom == b.y or b.bottom == a.y) and min(a.right, b.right) > max(a.x, b.x)
            if horizontal or vertical:
                reached.add(index)
                queue.append(index)
    require(len(reached) == len(solid), "opening leaves a disconnected fabrication piece")


def tile(outline: Polygon, pieces: list[Polygon]) -> None:
    polys = [outline] + pieces
    xs = sorted({x for p in polys for x, _ in p})
    ys = sorted({y for p in polys for _, y in p})
    for x0, x1 in zip(xs, xs[1:]):
        for y0, y1 in zip(ys, ys[1:]):
            count = sum(inside(p, x0 + x1, y0 + y1) for p in pieces)
            require(count == int(inside(outline, x0 + x1, y0 + y1)),
                    "gross polygons do not tile original outline exactly once")


def turn(poly: Polygon, quarter_turns: int) -> Polygon:
    require(type(quarter_turns) is int and quarter_turns in range(4), "quarterTurns must be 0/1/2/3")
    rotated = list(poly)
    for _ in range(quarter_turns):
        rotated = [(-y, x) for x, y in rotated]
    box = bbox(rotated)
    return [(x - box.x, y - box.y) for x, y in rotated]


def separated(a: Rect, b: Rect, kerf: int) -> bool:
    return a.right + kerf <= b.x or b.right + kerf <= a.x or a.bottom + kerf <= b.y or b.bottom + kerf <= a.y


def no_collision(a: Polygon, b: Polygon, kerf: int) -> None:
    # Holes remain reserved gross stock. Only exterior concavities can interlock.
    require(all(separated(c, d, kerf) for c in cells(a) for d in cells(b)),
            "polygon overlap or insufficient orthogonal-axis kerf")


def boundaries(identifier: str, pieces: list[Polygon]) -> list[Edge]:
    shared = []
    for index, a in enumerate(pieces):
        for b in pieces[index + 1:]:
            for p, q in edges(a):
                for r, s in edges(b):
                    if p[0] == q[0] == r[0] == s[0]:
                        start, end = max(min(p[1], q[1]), min(r[1], s[1])), min(max(p[1], q[1]), max(r[1], s[1]))
                        if start < end:
                            shared.append(Edge(identifier, "v", p[0], start, end))
                    if p[1] == q[1] == r[1] == s[1]:
                        start, end = max(min(p[0], q[0]), min(r[0], s[0])), min(max(p[0], q[0]), max(r[0], s[0]))
                        if start < end:
                            shared.append(Edge(identifier, "h", p[1], start, end))
    return merge_edges(shared)


def stone_segments(edge: Edge, holes: list[Rect]) -> list[Edge]:
    intervals = [(edge.start, edge.end)]
    for hole in holes:
        lo, hi = (hole.y, hole.bottom) if edge.axis == "v" else (hole.x, hole.right)
        intersects = hole.x < edge.line < hole.right if edge.axis == "v" else hole.y < edge.line < hole.bottom
        if not intersects:
            continue
        intervals = [(a, min(b, lo)) for a, b in intervals if a < min(b, lo)] + [
            (max(a, hi), b) for a, b in intervals if max(a, hi) < b]
    return [Edge(edge.installation, edge.axis, edge.line, a, b) for a, b in sorted(intervals)]


def reentrant(poly: Polygon) -> list[Point]:
    result = []
    for index, (x, y) in enumerate(poly):
        px, py = poly[index - 1]
        nx, ny = poly[(index + 1) % len(poly)]
        if (x - px) * (ny - y) - (y - py) * (nx - x) < 0:
            result.append((x, y))
    return result
