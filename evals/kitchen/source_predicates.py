"""Independent, narrow manufacturer predicates in exact metric units.

These calculations consume original installation geometry. They never infer
profile applicability from a name or reinterpret splitting as a rail repair.
Wire evidence/status verification is separate from these arithmetic predicates.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING

from eval import Edge, Rect, distance2, require

D = Decimal
MM_PER_TICK = D("1.5875")
SILESTONE = "silestone-2024-02"
MSI = "msi-q-pinned"


def minimum_ticks(mm: Decimal | str | int) -> int:
    return int((D(mm) / MM_PER_TICK).to_integral_value(rounding=ROUND_CEILING))


def applicable(profile: str | None, provenance: str | None, thickness: object) -> bool:
    return (profile in (SILESTONE, MSI) and isinstance(provenance, str) and bool(provenance.strip())
            and thickness is not None and D(str(thickness)) > 0
            and (profile == MSI or D(str(thickness)) in (12, 20, 30)))


def radius_minimum(profile: str, kind: str) -> Decimal:
    require(profile in (SILESTONE, MSI), "unsupported fabrication profile")
    return D("9.525") if profile == MSI else D(10 if kind in ("sink", "cooktop", "corner") else 5)


def outside_minimum(thickness: object) -> Decimal:
    require(D(str(thickness)) in (12, 20, 30), "unsupported nominal thickness class")
    return D(150 if D(str(thickness)) == 12 else 100)


@dataclass(frozen=True)
class Measurement:
    actual: Decimal
    minimum: Decimal

    @property
    def passes(self) -> bool:
        return self.actual >= self.minimum


def original_run_strips(run: Rect, opening: Rect, kind: str, thickness: object) -> dict[str, Measurement]:
    """Named original edges for the documented horizontal rectangular arrangement."""
    require(kind in ("sink", "cooktop"), "strip detail not established for this opening kind")
    end = outside_minimum(thickness)
    return {
        "front": Measurement((run.bottom - opening.bottom) * MM_PER_TICK, D(50)),
        "rear": Measurement((opening.y - run.y) * MM_PER_TICK, D(100 if kind == "sink" else 50)),
        "leftEnd": Measurement((opening.x - run.x) * MM_PER_TICK, end),
        "rightEnd": Measurement((run.right - opening.right) * MM_PER_TICK, end),
    }


def adjacent_gap(a: Rect, b: Rect) -> Measurement | None:
    # The source's side-by-side detail does not justify arbitrary diagonal gaps.
    if min(a.bottom, b.bottom) <= max(a.y, b.y):
        return None
    return Measurement(max(b.x - a.right, a.x - b.right) * MM_PER_TICK, D(50))


def opening_center(edge: Edge, opening: Rect) -> bool:
    return edge.axis == "v" and edge.line * 2 == 2 * opening.x + opening.w


def seam_clearance(edge: Edge, opening: Rect, thickness: object, selected: bool = False) -> bool:
    if selected and opening_center(edge, opening):
        return True
    squared_mm = D(distance2(edge.rect(), opening)) * MM_PER_TICK ** 2
    return squared_mm > 0 and squared_mm >= outside_minimum(thickness) ** 2
