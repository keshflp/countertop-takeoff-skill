# /// script
# requires-python = ">=3.12"
# dependencies = ["ortools==9.14.6206"]
# ///
"""Joint seam selection and slab packing on an exact 1/16-inch grid.

Corner partitions use the outline's vertex grid. Each rectangular run can then
split across its length at any legal sixteenth inch. CP-SAT chooses those cuts,
rotations and placements together. One worker and a deterministic work budget
make capped searches reproducible. No drawings or private job files are read.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations, islice, product
from math import ceil, isqrt
from typing import NamedTuple, TypedDict

from ortools.sat.python import cp_model

GRID = 16
MAX_PIECES = 12
MAX_PARTITIONS = 128
WORK_BUDGET = 1.0
Point = tuple[int, int]


class LayoutError(ValueError):
    def __init__(self, tag: str, message: str):
        self.tag = tag
        super().__init__(message)


class Piece(TypedDict):
    id: str
    installationId: str
    outline: list[list[float]]


class Seam(TypedDict):
    installationId: str
    x0: float
    y0: float
    x1: float
    y1: float


class Placement(TypedDict):
    pieceId: str
    x: float
    y: float
    rotated: bool


class Slab(TypedDict):
    index: int
    placements: list[Placement]


class Layout(TypedDict):
    ok: bool
    pieces: list[Piece]
    seams: list[Seam]
    slabs: list[Slab]
    slabCount: int
    lowerBound: int
    provenOptimal: bool
    warnings: list[str]


def ticks(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LayoutError("invalid_input", f"{name} must be a number in inches.")
    scaled = Fraction(str(value)) * GRID
    if scaled.denominator != 1 or scaled < 0:
        raise LayoutError("invalid_input", f"{name} must be a nonnegative multiple of 1/16 inch.")
    return int(scaled)


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
    def points(self) -> list[list[float]]:
        return [[x / GRID, y / GRID] for x, y in (
            (self.x, self.y), (self.x + self.w, self.y),
            (self.x + self.w, self.y + self.h), (self.x, self.y + self.h))]


@dataclass(frozen=True)
class Installation:
    id: str
    outline: tuple[Point, ...]
    cutouts: tuple[Rect, ...]
    required_pieces: int | None = None


@dataclass(frozen=True)
class Job:
    width: int
    height: int
    kerf: int
    clearance: int
    material: int
    rotate: bool
    installations: tuple[Installation, ...]


def inside(x: float, y: float, outline: tuple[Point, ...]) -> bool:
    return sum(a[0] > x and min(a[1], b[1]) < y < max(a[1], b[1])
               for a, b in zip(outline, outline[1:] + outline[:1]) if a[0] == b[0]) % 2 == 1


def distance2(a: Rect, b: Rect) -> int:
    dx = max(a.x - b.x - b.w, b.x - a.x - a.w, 0)
    dy = max(a.y - b.y - b.h, b.y - a.y - a.h, 0)
    return dx * dx + dy * dy


def edges(outline: tuple[Point, ...]) -> list[Rect]:
    return [Rect(min(a[0], b[0]), min(a[1], b[1]), abs(a[0] - b[0]), abs(a[1] - b[1]))
            for a, b in zip(outline, outline[1:] + outline[:1])]


def read_job(data: dict) -> Job:
    try:
        settings = data["settings"]
        trim = ticks(settings["slabTrimIn"], "Slab trim")
        width = ticks(data["slab"]["lengthIn"], "Slab length") - 2 * trim
        height = ticks(data["slab"]["widthIn"], "Slab width") - 2 * trim
        if min(width, height) <= 0:
            raise LayoutError("slab_too_small", "The slab has no usable space after trimming its edges.")
        rotate = settings["allowRotate"]
        if not isinstance(rotate, bool):
            raise LayoutError("invalid_input", "Allow rotation must be true or false.")
        installations = []
        ids: set[str] = set()
        for item in data["installations"]:
            identity = item["id"]
            if not isinstance(identity, str) or not identity or identity in ids:
                raise LayoutError("invalid_input", "Give each installation a different, nonempty name.")
            ids.add(identity)
            required = item.get("requiredPieceCount")
            if "requiredPieceCount" in item and (type(required) is not int or required <= 0):
                raise LayoutError("invalid_input", f"{identity}: the requested piece count must be a positive whole number.")
            if required is not None and required > MAX_PIECES:
                raise LayoutError("too_many_pieces", f"{identity}: this layout tool supports up to 12 pieces per job.")
            outline = tuple((ticks(p[0], "Outline x"), ticks(p[1], "Outline y")) for p in item["outline"])
            if outline and outline[0] == outline[-1]:
                outline = outline[:-1]
            if len(outline) < 4 or any((a[0] == b[0]) == (a[1] == b[1])
                                       for a, b in zip(outline, outline[1:] + outline[:1])):
                raise LayoutError("invalid_outline", f"{identity}: draw a closed outline with horizontal and vertical edges.")
            boundary = edges(outline)
            for i, a in enumerate(boundary):
                for j in range(i + 1, len(boundary)):
                    if j not in (i + 1, len(boundary) - 1 if i == 0 else -1) and distance2(a, boundary[j]) == 0:
                        raise LayoutError("invalid_outline", f"{identity}: the outline crosses or touches itself.")
            cutouts = tuple(Rect(*(ticks(c[k], f"Cutout {k}") for k in ("x", "y", "w", "h")))
                            for c in item["cutouts"])
            for c in cutouts:
                if not c.area or not inside(c.x + c.w / 2, c.y + c.h / 2, outline) or any(
                    e.w == 0 and c.x < e.x < c.x + c.w and max(c.y, e.y) < min(c.y + c.h, e.y + e.h)
                    or e.h == 0 and c.y < e.y < c.y + c.h and max(c.x, e.x) < min(c.x + c.w, e.x + e.w)
                    for e in boundary
                ):
                    raise LayoutError("invalid_cutout", f"{identity}: a cutout extends outside the countertop or has no size.")
            if any(distance2(a, b) == 0 for a, b in combinations(cutouts, 2)):
                raise LayoutError("invalid_cutout", f"{identity}: two cutouts touch or overlap. Check their positions.")
            installations.append(Installation(identity, outline, cutouts, required))
        if not installations:
            raise LayoutError("invalid_input", "Add at least one countertop installation.")
        return Job(width, height, ticks(settings["kerfIn"], "Saw gap"),
                   ticks(settings["minSeamToCutoutIn"], "Seam clearance"),
                   ticks(settings["minMaterialBesideCutoutIn"], "Material beside cutouts"),
                   rotate, tuple(installations))
    except (KeyError, TypeError, IndexError) as exc:
        raise LayoutError("invalid_input", "The layout is missing a slab size, setting, outline, or cutout measurement.") from exc


def shared_edge(a: Rect, b: Rect) -> Rect | None:
    if a.x + a.w == b.x or b.x + b.w == a.x:
        lo, hi = max(a.y, b.y), min(a.y + a.h, b.y + b.h)
        if lo < hi:
            return Rect(max(a.x, b.x), lo, 0, hi - lo)
    if a.y + a.h == b.y or b.y + b.h == a.y:
        lo, hi = max(a.x, b.x), min(a.x + a.w, b.x + b.w)
        if lo < hi:
            return Rect(lo, max(a.y, b.y), hi - lo, 0)
    return None


def corner_seams(rects: tuple[Rect, ...]) -> list[Rect]:
    return [edge for a, b in combinations(rects, 2) if (edge := shared_edge(a, b)) is not None]


def partitions(inst: Installation, clearance: int) -> tuple[list[tuple[Rect, ...]], bool]:
    """Enumerate irreducible rectangular covers on the outline's corner grid.

    Mergeable rectangles are excluded: a straight run's movable cuts belong in
    the solver, not in the corner partition. L/U corners retain both directions.
    """
    xs, ys = sorted({p[0] for p in inst.outline}), sorted({p[1] for p in inst.outline})
    cells = {(x, y) for x in range(len(xs) - 1) for y in range(len(ys) - 1)
             if inside((xs[x] + xs[x + 1]) / 2, (ys[y] + ys[y + 1]) / 2, inst.outline)}
    if len(cells) > 64:
        raise LayoutError("outline_too_complex", f"{inst.id}: simplify this outline into a few separate countertop runs.")
    covers: list[tuple[Rect, ...]] = []
    visits, complete = 0, True

    def visit(remaining: set[tuple[int, int]], chosen: tuple[Rect, ...]) -> None:
        nonlocal visits, complete
        if visits >= 10_000 or len(covers) >= MAX_PARTITIONS:
            complete = False
            return
        visits += 1
        if not remaining:
            covers.append(chosen)
            return
        x, y = min(remaining)
        for x1 in range(x + 1, len(xs)):
            for y1 in range(y + 1, len(ys)):
                occupied = set(product(range(x, x1), range(y, y1)))
                if not occupied <= remaining:
                    continue
                rect = Rect(xs[x], ys[y], xs[x1] - xs[x], ys[y1] - ys[y])
                if any((rect.x == old.x and rect.w == old.w or rect.y == old.y and rect.h == old.h)
                       and shared_edge(rect, old) is not None for old in chosen):
                    continue
                seams = [e for old in chosen if (e := shared_edge(rect, old)) is not None]
                if any(distance2(e, c) < clearance * clearance or distance2(e, c) == 0
                       for e in seams for c in inst.cutouts):
                    continue
                visit(remaining - occupied, chosen + (rect,))
                if not complete:
                    return

    visit(cells, ())
    return sorted(covers, key=lambda p: (len(p), p)), complete


@dataclass(frozen=True)
class Run:
    installation: Installation
    rect: Rect
    horizontal: bool

    @property
    def length(self) -> int:
        return self.rect.w if self.horizontal else self.rect.h

    @property
    def depth(self) -> int:
        return self.rect.h if self.horizontal else self.rect.w

    @property
    def start(self) -> int:
        return self.rect.x if self.horizontal else self.rect.y

    def cutout_axes(self, cutout: Rect) -> tuple[int, int, int]:
        r = self.rect
        if self.horizontal:
            return cutout.x, cutout.x + cutout.w, max(cutout.y - r.y - r.h, r.y - cutout.y - cutout.h, 0)
        return cutout.y, cutout.y + cutout.h, max(cutout.x - r.x - r.w, r.x - cutout.x - cutout.w, 0)

    def legal_cuts(self, clearance: int) -> cp_model.Domain:
        allowed = cp_model.Domain(self.start + 1, self.start + self.length - 1)
        for cutout in self.installation.cutouts:
            lo, hi, gap = self.cutout_axes(cutout)
            square = clearance * clearance - gap * gap
            if square > 0 or gap == 0:
                reach = max(1, isqrt(max(0, square)) + (isqrt(max(0, square)) ** 2 < square))
                forbidden = cp_model.Domain(lo - reach + 1, hi + reach - 1)
                allowed = allowed.intersection_with(forbidden.complement())
        return allowed


@dataclass
class Slot:
    run: Run
    start: cp_model.IntVar
    length: cp_model.IntVar
    active: cp_model.IntVar
    bin: cp_model.IntVar
    x: cp_model.IntVar
    y: cp_model.IntVar
    rotated: cp_model.IntVar


class PackedPiece(NamedTuple):
    run: Run
    start: int
    length: int
    bin: int
    x: int
    y: int
    rotated: bool


def run_direction(rect: Rect, partition: tuple[Rect, ...]) -> bool:
    # A short end of a side leg still runs vertically. Its full-width corner
    # connection identifies the direction even when it is shorter than deep.
    contacts = [e for other in partition if other != rect and (e := shared_edge(rect, other)) is not None]
    if contacts and all(e.w == rect.w for e in contacts):
        return False
    if contacts and all(e.h == rect.h for e in contacts):
        return True
    return rect.w >= rect.h


def build_model(job: Job, runs: list[Run], fixed: list[tuple[str, Rect]], lower: int,
                piece_limit: int, incumbent: int | None = None) -> tuple[cp_model.CpModel, list[Slot]]:
    model = cp_model.CpModel()
    max_bins = piece_limit
    count = model.new_int_var(lower, max_bins, "slabs")
    if incumbent is not None:
        model.add(count <= incumbent)
    far = max(max(p) for inst in job.installations for p in inst.outline) + max(job.width, job.height)
    clearance2 = model.new_int_var(0, far * far, "clearance_squared")
    for identity, seam in fixed:
        inst = next(i for i in job.installations if i.id == identity)
        for c in inst.cutouts:
            model.add(clearance2 <= distance2(seam, c))
    slots: list[Slot] = []
    x_intervals, y_intervals = [], []
    min_counts = [len(run_lengths(job, run)) for run in runs]
    if sum(min_counts) > piece_limit:
        raise LayoutError("too_many_pieces", "This job needs more than 12 pieces. Split it into smaller jobs or choose a larger slab.")
    for run, minimum in zip(runs, min_counts):
        previous = None
        end = model.new_int_var(run.start, run.start, "run_start")
        for j in range(minimum + piece_limit - sum(min_counts)):
            active = model.new_bool_var("piece")
            length = model.new_int_var(0, run.length, "length")
            model.add(length >= 1).only_enforce_if(active)
            model.add(length == 0).only_enforce_if(active.Not())
            if previous is None:
                model.add(active == 1)
            else:
                model.add(active <= previous)
                model.add_linear_expression_in_domain(end, run.legal_cuts(max(job.clearance, job.material))).only_enforce_if(active)
                for c in run.installation.cutouts:
                    lo, hi, gap = run.cutout_axes(c)
                    along = model.new_int_var(0, far, "cutout_distance")
                    model.add_max_equality(along, [0, lo - end, end - hi])
                    square = model.new_int_var(0, far * far, "distance_squared")
                    model.add_multiplication_equality(square, [along, along])
                    model.add(clearance2 <= square + gap * gap).only_enforce_if(active)
            rotate = model.new_bool_var("rotated")
            if not job.rotate:
                model.add(rotate == 0)
            model.add(rotate <= active)
            w = model.new_int_var(0, max(run.length, run.depth), "width")
            h = model.new_int_var(0, max(run.length, run.depth), "height")
            normal = (length, run.depth) if run.horizontal else (run.depth, length)
            model.add(w == normal[0]).only_enforce_if(rotate.Not())
            model.add(h == normal[1]).only_enforce_if(rotate.Not())
            model.add(w == normal[1]).only_enforce_if(rotate)
            model.add(h == normal[0]).only_enforce_if(rotate)
            bin_id = model.new_int_var(0, max_bins - 1, "slab")
            x = model.new_int_var(0, job.width, "x")
            y = model.new_int_var(0, job.height, "y")
            model.add(x + w <= job.width).only_enforce_if(active)
            model.add(y + h <= job.height).only_enforce_if(active)
            model.add(bin_id < count).only_enforce_if(active)
            for v in (bin_id, x, y):
                model.add(v == 0).only_enforce_if(active.Not())
            global_x = model.new_int_var(0, max_bins * (job.width + job.kerf), "global_x")
            model.add(global_x == bin_id * (job.width + job.kerf) + x)
            x_end = model.new_int_var(0, (max_bins + 1) * (job.width + job.kerf) + run.length, "x_end")
            y_end = model.new_int_var(0, job.height + run.length + run.depth + job.kerf, "y_end")
            x_intervals.append(model.new_optional_interval_var(global_x, w + job.kerf, x_end, active, "piece_x"))
            y_intervals.append(model.new_optional_interval_var(y, h + job.kerf, y_end, active, "piece_y"))
            slots.append(Slot(run, end, length, active, bin_id, x, y, rotate))
            next_end = model.new_int_var(run.start, run.start + run.length, "cut")
            model.add(next_end == end + length)
            end, previous = next_end, active
        model.add(end == run.start + run.length)
    model.add_no_overlap_2d(x_intervals, y_intervals)
    # Number slabs in first-use order to remove equivalent bin permutations.
    maximum = model.new_int_var(0, 0, "first_slab")
    for index, slot in enumerate(slots):
        model.add(slot.bin <= maximum + (index != 0))
        next_maximum = model.new_int_var(0, max_bins - 1, "used_slabs")
        model.add_max_equality(next_maximum, [maximum, slot.bin])
        maximum = next_maximum
    piece_count = sum(s.active for s in slots)
    model.add(piece_count <= piece_limit)
    for inst in job.installations:
        if inst.required_pieces is not None:
            model.add(sum(s.active for s in slots if s.run.installation == inst) == inst.required_pieces)
    # These weights preserve the three priorities exactly, including corners.
    unit = far * far + 1
    model.minimize(count * (piece_limit + 1) * unit + piece_count * unit - clearance2)
    return model, slots


def split_run(run: Run, capacity: int, clearance: int) -> list[int]:
    """Farthest legal cuts give the minimum number of segments in one run."""
    intervals = run.legal_cuts(clearance).flattened_intervals()
    start, end = run.start, run.start + run.length
    lengths = []
    while start + capacity < end:
        reachable = [min(b, start + capacity) for a, b in zip(intervals[::2], intervals[1::2])
                     if a <= start + capacity and b > start]
        if not reachable:
            raise LayoutError("no_legal_seam", f"{run.installation.id}: no safe seam can make this run fit the slab. Move the cutout or choose a larger slab.")
        cut = max(reachable)
        lengths.append(cut - start)
        start = cut
    return lengths + [end - start]


def run_lengths(job: Job, run: Run) -> list[int]:
    capacities = []
    if run.depth <= (job.height if run.horizontal else job.width):
        capacities.append(job.width if run.horizontal else job.height)
    if job.rotate and run.depth <= (job.width if run.horizontal else job.height):
        capacities.append(job.height if run.horizontal else job.width)
    if not capacities:
        raise LayoutError("piece_too_wide", f"{run.installation.id}: the countertop is wider than the usable slab. Choose a wider slab or allow rotation.")
    return split_run(run, max(capacities), max(job.clearance, job.material))


def requested_splits(job: Job, runs: list[Run]) -> list[list[int]]:
    """Refine safe shortest splits to exact owner counts before any search.

    Inserting a legal cut preserves fit. If every legal grid point is already
    used, no alternative split can supply another piece in this partition.
    """
    lengths = [run_lengths(job, run) for run in runs]
    for inst in job.installations:
        if inst.required_pieces is None:
            continue
        indices = [i for i, run in enumerate(runs) if run.installation == inst]
        count = sum(len(lengths[i]) for i in indices)
        if count > inst.required_pieces:
            raise LayoutError("piece_count_conflict", f"{inst.id}: this shape needs at least {count} pieces to fit safely, but you requested exactly {inst.required_pieces}. Choose a larger slab or change the requested count.")
        while count < inst.required_pieces:
            options = []
            for i in indices:
                intervals = runs[i].legal_cuts(max(job.clearance, job.material)).flattened_intervals()
                start = runs[i].start
                for j, length in enumerate(lengths[i]):
                    for a, b in zip(intervals[::2], intervals[1::2]):
                        lo, hi = max(a, start + 1), min(b, start + length - 1)
                        if lo <= hi:
                            cut = max(lo, min(hi, start + length // 2))
                            options.append((-length, abs(2 * (cut - start) - length), i, j, cut - start))
                    start += length
            if not options:
                raise LayoutError("piece_count_conflict", f"{inst.id}: exactly {inst.required_pieces} pieces would need a seam too close to a cutout. Change the requested count or the cutout position.")
            _, _, i, j, first = min(options)
            lengths[i][j:j + 1] = [first, lengths[i][j] - first]
            count += 1
    return lengths


def make_layout(packed: list[PackedPiece], fixed: list[tuple[str, Rect]], lower: int, warnings: list[str]) -> Layout:
    pieces: list[Piece] = []
    seams: list[Seam] = []
    bins: dict[int, list[Placement]] = {}
    all_seams = list(fixed)
    for s in packed:
        r, start, length = s.run.rect, s.start, s.length
        rect = Rect(start, r.y, length, r.h) if s.run.horizontal else Rect(r.x, start, r.w, length)
        identity = f"P{len(pieces) + 1}"
        pieces.append({"id": identity, "installationId": s.run.installation.id, "outline": rect.points})
        bins.setdefault(s.bin, []).append({"pieceId": identity, "x": s.x / GRID,
                                          "y": s.y / GRID, "rotated": s.rotated})
        if start != s.run.start:
            all_seams.append((s.run.installation.id, Rect(start, r.y, 0, r.h) if s.run.horizontal else Rect(r.x, start, r.w, 0)))
    for identity, s in sorted(all_seams):
        seams.append({"installationId": identity, "x0": s.x / GRID, "y0": s.y / GRID,
                      "x1": (s.x + s.w) / GRID, "y1": (s.y + s.h) / GRID})
    slabs: list[Slab] = [{"index": i + 1, "placements": bins[b]} for i, b in enumerate(sorted(bins))]
    return {"ok": True, "pieces": pieces, "seams": seams, "slabs": slabs, "slabCount": len(slabs),
            "lowerBound": lower, "provenOptimal": False, "warnings": list(warnings)}


def greedy_pack(job: Job, runs: list[Run], lengths: list[list[int]]) -> list[PackedPiece]:
    """Seed every search with a legal layout, even with a zero search budget."""
    packed: list[PackedPiece] = []
    bins: list[list[Rect]] = []
    for run, segments in zip(runs, lengths):
        start = run.start
        for length in segments:
            w, h = (length, run.depth) if run.horizontal else (run.depth, length)
            options = [(False, w, h)] + ([(True, h, w)] if job.rotate else [])
            placed = False
            for index in range(len(bins) + 1):
                existing = bins[index] if index < len(bins) else []
                xs = sorted({0} | {r.x + r.w + job.kerf for r in existing})
                ys = sorted({0} | {r.y + r.h + job.kerf for r in existing})
                for rotated, pw, ph in options:
                    for y, x in product(ys, xs):
                        if x + pw > job.width or y + ph > job.height:
                            continue
                        if all(x + pw + job.kerf <= r.x or r.x + r.w + job.kerf <= x or
                               y + ph + job.kerf <= r.y or r.y + r.h + job.kerf <= y for r in existing):
                            if index == len(bins):
                                bins.append([])
                            bins[index].append(Rect(x, y, pw, ph))
                            packed.append(PackedPiece(run, start, length, index, x, y, rotated))
                            placed = True
                            break
                    if placed:
                        break
                if placed:
                    break
            start += length
    return packed


def layout_score(layout: Layout, job: Job) -> tuple[int, int, int]:
    gaps = [distance2(Rect(round(s["x0"] * GRID), round(s["y0"] * GRID),
                          round((s["x1"] - s["x0"]) * GRID), round((s["y1"] - s["y0"]) * GRID)), c)
            for s in layout["seams"] for inst in job.installations if inst.id == s["installationId"] for c in inst.cutouts]
    return layout["slabCount"], len(layout["seams"]), -min(gaps, default=sys.maxsize)


def solve(data: dict, *, work_budget: float = WORK_BUDGET) -> Layout:
    job = read_job(data)
    warnings = []
    choices = []
    complete = True
    for inst in job.installations:
        for n, cutout in enumerate(inst.cutouts, 1):
            if any(distance2(e, cutout) < job.material * job.material for e in edges(inst.outline)):
                warnings.append(f"{inst.id}: cutout {n} leaves less than {job.material / GRID:g} inches of material at an original countertop edge. Confirm this with the fabricator.")
        covers, exhausted = partitions(inst, max(job.clearance, job.material))
        choices.append(covers)
        complete &= exhausted
        if not choices[-1]:
            if not exhausted:
                raise LayoutError("search_limit", f"{inst.id}: this outline has too many corners to check in one search. Separate it into simpler installations.")
            raise LayoutError("no_legal_seam", f"{inst.id}: no corner seam can stay far enough from the cutouts. Move a cutout or change the countertop shape.")
    area = sum(r.area for group in choices for r in group[0])
    lower = ceil(area / (job.width * job.height))
    combinations_count = 1
    for choice in choices:
        combinations_count *= len(choice)
    complete &= combinations_count <= MAX_PARTITIONS
    combinations_count = min(combinations_count, MAX_PARTITIONS)
    best: Layout | None = None
    best_score: tuple[int, int, int] | None = None
    last_error: LayoutError | None = None
    for selected in islice(product(*choices), MAX_PARTITIONS):
        runs = [Run(inst, r, run_direction(r, partition))
                for inst, partition in zip(job.installations, selected) for r in partition]
        fixed = [(inst.id, s) for inst, partition in zip(job.installations, selected) for s in corner_seams(partition)]
        try:
            lengths = requested_splits(job, runs)
            minimum = sum(map(len, lengths))
            if minimum > MAX_PIECES:
                raise LayoutError("too_many_pieces", "This job needs more than 12 pieces. Split it into smaller jobs or choose a larger slab.")
        except LayoutError as exc:
            last_error = exc
            continue
        seed = greedy_pack(job, runs, lengths)
        candidate = make_layout(seed, fixed, lower, warnings)
        score = layout_score(candidate, job)
        if best_score is None or score < best_score:
            best, best_score = candidate, score
        # First solve the smallest possible piece count. It is both much easier
        # and a proof for all piece counts when it attains the area lower bound.
        maximum = minimum if all(i.required_pieces is not None for i in job.installations) else MAX_PIECES
        for limit in dict.fromkeys((minimum, maximum)):
            model, slots = build_model(job, runs, fixed, lower, limit, best["slabCount"] if best else None)
            for run in runs:
                parts = [p for p in seed if p.run == run]
                for index, slot in enumerate(s for s in slots if s.run == run):
                    active = index < len(parts)
                    p = parts[index] if active else PackedPiece(run, run.start + run.length, 0, 0, 0, 0, False)
                    for variable, value in ((slot.active, active), (slot.start, p.start), (slot.length, p.length),
                                            (slot.bin, p.bin), (slot.x, p.x), (slot.y, p.y), (slot.rotated, p.rotated)):
                        model.add_hint(variable, int(value))
            solver = cp_model.CpSolver()
            solver.parameters.num_search_workers = 1
            solver.parameters.random_seed = 0
            solver.parameters.max_deterministic_time = work_budget / (2 * combinations_count)
            status = solver.solve(model)
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                packed = [PackedPiece(s.run, solver.value(s.start), solver.value(s.length), solver.value(s.bin),
                                      solver.value(s.x), solver.value(s.y), bool(solver.value(s.rotated)))
                          for s in slots if solver.value(s.active)]
                candidate = make_layout(packed, fixed, lower, warnings)
                score = layout_score(candidate, job)
                if best_score is None or score < best_score:
                    best, best_score = candidate, score
                if candidate["slabCount"] == lower:
                    break
        complete &= status in (cp_model.OPTIMAL, cp_model.INFEASIBLE)
    if best is None:
        if not complete:
            raise LayoutError("search_limit", "The layout search ran out of time before finding a safe arrangement. Try a larger slab or separate this job into smaller runs.")
        if last_error is not None:
            raise last_error
        raise LayoutError("no_legal_seam", "No safe seam arrangement fits the slab. A cutout may be too close to every possible seam; try a larger slab or move the cutout.")
    # Reaching the area bound proves slab count globally. A complete search
    # then proves the secondary objectives too: >12 pieces cannot use fewer
    # seams than this <=12-piece solution. Never claim proof from a timeout.
    best["provenOptimal"] = complete and best["slabCount"] == lower
    if not best["provenOptimal"]:
        best["warnings"].append("This is the best safe layout found; the search has not proved that it is the best possible layout.")
    return best


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selfcheck", action="store_true")
    args = parser.parse_args()
    if args.selfcheck:
        print('{"ok":true}')
        return
    try:
        result = solve(json.load(sys.stdin))
    except LayoutError as exc:
        result = {"ok": False, "error": {"tag": exc.tag, "message": str(exc)}}
    except (ValueError, OverflowError):
        result = {"ok": False, "error": {"tag": "invalid_input", "message": "Check the layout measurements and send valid JSON numbers."}}
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
