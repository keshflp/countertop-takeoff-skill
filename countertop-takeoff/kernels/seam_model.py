"""Pinned manufacturer rule subset and strict numeric v2 intake.

Geometry uses sixteenth-inch integers. Source distances are compared in exact
millimetres; supplied radii stay metric. Evidence is serialized only at the edge.
This module assesses installation details, not handling strength or toolpaths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import combinations

from layout_geometry import (
    FabricationPolygon,
    Rect,
    connected,
    reentrant_vertices,
    solid_cells,
)

MM_PER_TICK = Decimal("1.5875")
S1 = "silestone-2024-02"
S2 = "msi-q-pinned"
CONDITION_KINDS = {"level-support", "corner-continuous-support", "corner-reinforcement",
                   "opening-continuous-support", "fixture-support", "installation-support"}


def closed(value: object, required: str, optional: str = "") -> dict:
    needed, allowed = set(required.split()), set((required + " " + optional).split())
    if not isinstance(value, dict) or not needed <= value.keys() or not value.keys() <= allowed:
        raise ValueError("A layout record has missing or unrecognized fields.")
    return value


def text_value(value: object, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Names and evidence notes must contain words.")
    return value


def enum(value: object, choices: set[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ValueError("A layout option is not recognized.")
    return value


def count(value: object, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= 9007199254740991:
        raise ValueError("Piece counts and opening numbers must be whole numbers.")
    return value


def ticks(value: object, positive: bool = False) -> int:
    if type(value) not in (int, float) or not 0 <= value <= 1000000 or value * 16 != int(value * 16):
        raise ValueError("Lengths must be nonnegative inches in steps of 1/16 inch.")
    result = int(value * 16)
    if positive and result == 0:
        raise ValueError("Lengths and widths must be greater than zero.")
    return result


def metric(value: object, positive: bool = False) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d+)?", value):
        raise ValueError("Millimetres must be a decimal string or null when unknown.")
    result = Decimal(value)
    if positive and result <= 0:
        raise ValueError("Material thickness must be greater than zero.")
    return result


def sequence(value: object) -> list:
    if not isinstance(value, list):
        raise TypeError("Outlines, openings and conditions must be lists.")
    return value


@dataclass(frozen=True)
class Opening:
    kind: str
    rect: Rect
    radius: Decimal | None
    mount: str | None


@dataclass(frozen=True)
class Facts:
    id: str
    path: str
    shape_kind: str
    polygon: FabricationPolygon
    openings: tuple[Opening, ...]
    radius: Decimal | None
    arrangement: dict | None
    conditions: tuple[dict, ...]
    required_count: int | None
    seam: dict | None

    @property
    def cuts(self) -> tuple[Rect, ...]:
        return tuple(o.rect for o in self.openings)

    @property
    def documented_run(self) -> bool:
        return self.arrangement is not None and self.polygon.area == self.polygon.bounds.area

    @property
    def axis(self) -> int:
        if self.documented_run:
            return 0 if self.arrangement["axis"] == "x" else 1
        return 0 if self.polygon.bounds.w >= self.polygon.bounds.h else 1


@dataclass(frozen=True)
class Request:
    raw: dict
    profile: str | None
    provenance: str | None
    thickness: Decimal | None
    usable: Rect | None
    kerf: int
    rotate: bool
    installations: tuple[Facts, ...]

    @property
    def model_known(self) -> bool:
        return bool(self.provenance) and ((self.profile == S1 and self.thickness in (12, 20, 30))
                                         or (self.profile == S2 and self.thickness is not None))

    @property
    def gap_mm(self) -> Decimal | None:
        if self.profile == S1 and self.thickness in (12, 20, 30):
            return Decimal(150 if self.thickness == 12 else 100)
        return None


def read_request(value: object) -> Request:
    raw = closed(value, "version mode phase material slab settings installations", "legacySettings")
    if type(raw["version"]) is not int or raw["version"] != 2:
        raise ValueError("Use the version 2 layout request.")
    mode = enum(raw["mode"], {"assessment", "geometry-replay"})
    enum(raw["phase"], {"assess", "plan"})
    if (mode == "geometry-replay") != ("legacySettings" in raw):
        raise ValueError("Legacy seam distances are only for development geometry replay.")
    if mode == "geometry-replay":
        old = closed(raw["legacySettings"], "minSeamToCutoutIn minMaterialBesideCutoutIn")
        for number in old.values():
            ticks(number)
    material = closed(raw["material"], "profileId profileProvenance nominalThicknessMm")
    profile = text_value(material["profileId"], True)
    provenance = text_value(material["profileProvenance"], True)
    thickness = metric(material["nominalThicknessMm"], True)
    settings = closed(raw["settings"], "slabTrimIn kerfIn allowRotate")
    trim, kerf = ticks(settings["slabTrimIn"]), ticks(settings["kerfIn"])
    if type(settings["allowRotate"]) is not bool:
        raise ValueError("Allow rotation must be true or false.")
    usable = None
    if raw["slab"] is not None:
        slab = closed(raw["slab"], "lengthIn widthIn")
        usable = Rect(0, 0, ticks(slab["lengthIn"], True) - 2 * trim, ticks(slab["widthIn"], True) - 2 * trim)
        if min(usable.w, usable.h) <= 0:
            raise ValueError("The slab trim leaves no usable material.")
    installations = []
    for i, item in enumerate(sequence(raw["installations"])):
        item = closed(item, "id shapeKind outline cutouts insideCornerRadiusMm sourceArrangement conditions",
                      "requiredPieceCount seam")
        identity = text_value(item["id"])
        shape_kind = enum(item["shapeKind"], {"rect", "L", "U", "outline"})
        ring = []
        for point in sequence(item["outline"]):
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError("Every outline point needs x and y inches.")
            ring.append((ticks(point[0]), ticks(point[1])))
        if ring and ring[0] == ring[-1]:
            raise ValueError("Do not repeat the first outline point at the end.")
        polygon = FabricationPolygon(tuple(ring))
        if sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1])) <= 0:
            raise ValueError("List outline points clockwise, with y increasing down the page.")
        if polygon.bounds.x != 0 or polygon.bounds.y != 0:
            raise ValueError("Start the installation's outer bounds at x=0 and y=0.")
        if shape_kind == "rect" and polygon.area != polygon.bounds.area:
            raise ValueError("A rectangular installation must have a rectangular outline.")
        openings = []
        for cut in sequence(item["cutouts"]):
            cut = closed(cut, "kind x y w h radiusMm mount")
            rect = Rect(ticks(cut["x"]), ticks(cut["y"]), ticks(cut["w"], True), ticks(cut["h"], True))
            if polygon.area - sum(c.area for c in solid_cells(polygon, (rect,))) != rect.area:
                raise ValueError(f"{identity}: an opening extends outside the countertop.")
            openings.append(Opening(enum(cut["kind"], {"sink", "cooktop", "other"}), rect,
                                    metric(cut["radiusMm"]), None if cut["mount"] is None else
                                    enum(cut["mount"], {"top", "under", "flush", "other"})))
        for a, b in combinations(openings, 2):
            if max(a.rect.x, b.rect.x) < min(a.rect.x + a.rect.w, b.rect.x + b.rect.w) and \
               max(a.rect.y, b.rect.y) < min(a.rect.y + a.rect.h, b.rect.y + b.rect.h):
                raise ValueError(f"{identity}: two openings overlap.")
        arrangement = item["sourceArrangement"]
        if arrangement is not None:
            closed(arrangement, "kind axis rear provenance")
            enum(arrangement["kind"], {"rectangular-run"})
            enum(arrangement["axis"], {"x", "y"})
            enum(arrangement["rear"], {"min", "max"})
            text_value(arrangement["provenance"])
        conditions = sequence(item["conditions"])
        scopes = set()
        for condition in conditions:
            closed(condition, "kind cutoutIndex status note")
            enum(condition["kind"], CONDITION_KINDS)
            enum(condition["status"], {"documented", "failed", "unknown"})
            if condition["cutoutIndex"] is not None and count(condition["cutoutIndex"]) >= len(openings):
                raise ValueError("A support condition refers to an opening that does not exist.")
            text_value(condition["note"], condition["status"] == "unknown")
            scope = (condition["kind"], condition["cutoutIndex"])
            if scope in scopes:
                raise ValueError("Supply one evidence record per condition and opening scope.")
            scopes.add(scope)
        seam = item.get("seam")
        if seam is not None:
            closed(seam, "kind cutoutIndex", "side")
            kind = enum(seam["kind"], {"center-through-cutout", "opening-center", "tangent-cutout"})
            if (kind == "tangent-cutout") != ("side" in seam):
                raise ValueError("Only a tangent join has a start or end side.")
            if "side" in seam:
                enum(seam["side"], {"start", "end"})
            count(seam["cutoutIndex"])
        installations.append(Facts(identity, f"installations[{i}]", shape_kind, polygon, tuple(openings),
                                   metric(item["insideCornerRadiusMm"]), arrangement, tuple(conditions),
                                   count(item["requiredPieceCount"], 1) if "requiredPieceCount" in item else None, seam))
    if not installations or len({i.id for i in installations}) != len(installations):
        raise ValueError("Supply installations with distinct names.")
    return Request(raw, profile, provenance, thickness, usable, kerf, settings["allowRotate"], tuple(installations))


def source(profile: str, detail: str, kind: str = "sink") -> dict:
    """Small source register. Diagram dimensions are identified as diagram labels."""
    if profile == S2:
        page = 2 if detail == "radius" else (4 if detail == "fixture" else 3)
        quote = {"radius": 'All corners on the countertop must be rounded to a minimum 3/8" radius.',
                 "fixture": "independent of the Q top"}.get(detail, "Provide perimeter support of full deck.")
        return {"id": "S2", "title": "MSI Q Installation Guidelines", "edition": "Pinned guide; no edition shown",
                "url": "https://cdn.msisurfaces.com/files/downloads/quartz-installation-guidelines.pdf",
                "sha256": "8b9011f17cf55712fc17a4b2aecc40a87cbf2d9f30b6bfe00803c56c425a4074",
                "filePages": [page], "printedPages": [page], "quotation": quote,
                "interpretation": "Sparse Q subset; no opening seam permission or numerical rail rule established."}
    page, printed = (5, 8) if kind == "sink" else (6, 10)
    quote = "Diagram labels: front >=50 mm; sink rear >=100 mm; cooktop rear >=50 mm; adjacent gap >=50 mm."
    interpretation = "Illustrated rectangular run with explicit front/rear datum; full tap and fixture detailing excluded."
    if detail == "radius":
        quote = 'minimum radius of 10 mm [3/8"]' if kind in {"sink", "cooktop"} else 'minimum radius of 5 mm [3/16"]'
    elif detail == "join":
        printed += 1
        quote = "Cosentino does not recommend leaving joints in the cut-out area. Ensure continuous, seamless support in this area."
        interpretation = "Outside D >=150 mm at 12 mm, >=100 mm at 20/30 mm; illustrated centerline alternative. Rail support applies to outside and inside details."
    elif detail == "corner":
        page, printed = 10, 18
        quote = "R >=10 mm. Fixing corner reinforcements and supports in place."
        interpretation = "One-piece and multiple-piece L details. A corner seam removes only the continuous corner radius."
    elif detail in {"support", "fixture"}:
        page, printed = 11, 20 if detail == "support" else 21
        quote = "The countertop must always rest completely on the cabinet structure" if detail == "support" else "large (> 600 mm [24\"]) or particularly heavy cooktops/sinks"
        interpretation = "Supplied support evidence is retained; support geometry, loads and reinforcement design are not calculated."
    elif detail == "thickness":
        page, printed = 5, 8
        quote = "12 mm; 20 mm and 30 mm."
        interpretation = "Exact nominal classes in the illustrated opening/end-distance table; no interpolation."
    return {"id": "S1", "title": "Silestone Countertops: Design & Installation", "edition": "REV.03 02/2024",
            "url": "https://assetstools.cosentino.com/api/v1/bynder/doc/0B425745-8BAC-4A87-9D7B54DA7AC39A1D/silestone-installation-manual.pdf",
            "sha256": "56535666e6ed4e33ea1bc452968ea1b7922abd13c57d98fff40312c0aa24794a",
            "filePages": [page], "printedPages": [printed], "quotation": quote, "interpretation": interpretation}


def measure(value: Decimal | int | None, unit: str = "mm") -> dict | None:
    return None if value is None else {"value": format(Decimal(value), "f"), "unit": unit}


@dataclass
class Evidence:
    checks: list[dict] = field(default_factory=list)
    conditions: list[dict] = field(default_factory=list)
    questions: dict[str, str] = field(default_factory=dict)

    def ask(self, path: str, question: str) -> None:
        self.questions.setdefault(path, question)

    def check(self, rule: str, inst: Facts | None, status: str, explanation: str, *, actual=None,
              required=None, unit="mm", src=None, cut=None, join=None, fields=(), operator=">=") -> None:
        identity = f"{inst.id if inst else 'material'}:{rule}:{cut if cut is not None else '-'}:{join or '-'}"
        # Pairwise predicates share the first cutout; the field list distinguishes the second.
        suffix = sum(c["id"].startswith(identity) for c in self.checks)
        self.checks.append({"id": identity + (f":{suffix}" if suffix else ""), "ruleId": rule,
                            "installationId": inst.id if inst else None, "cutoutIndex": cut, "joinId": join,
                            "status": status, "operator": operator, "actual": measure(actual, unit),
                            "required": measure(required, unit), "source": src, "explanation": explanation,
                            "fields": list(fields)})

    def minimum(self, rule: str, inst: Facts, actual: Decimal | None, required: Decimal | None,
                explanation: str, **kw) -> None:
        status = "unknown" if actual is None or required is None else "pass" if actual >= required else "fail"
        self.check(rule, inst, status, explanation, actual=actual, required=required, **kw)

    def obligation(self, kind: str, inst: Facts, explanation: str, *, src=None, cut=None, join=None,
                   status: str | None = None, fields=()) -> None:
        supplied = [(i, c) for i, c in enumerate(inst.conditions) if c["kind"] == kind and
                    (c["cutoutIndex"] is None or c["cutoutIndex"] == cut)]
        # A failed whole-installation fact cannot be overridden by a narrower positive note.
        supplied.sort(key=lambda v: ({"failed": 0, "documented": 1, "unknown": 2}[v[1]["status"]],
                                     v[1]["cutoutIndex"] is None, v[0]))
        note = None
        paths = list(fields)
        if status is None:
            if supplied:
                index, fact = supplied[0]
                status = {"documented": "satisfied", "failed": "failed", "unknown": "required-unverified"}[fact["status"]]
                note = fact["note"]
                paths.append(f"{inst.path}.conditions[{index}].status")
            else:
                status = "required-unverified"
                paths.append(f"{inst.path}.conditions")
        if status == "required-unverified" and paths:
            detail = {"installation-support": "the required installed countertop supports",
                      "level-support": "level support at the corner",
                      "corner-continuous-support": "continuous support through the corner",
                      "corner-reinforcement": "the required corner reinforcement",
                      "opening-continuous-support": "continuous front/back rail support at the opening joins",
                      "fixture-support": "the fixture's required independent or large/heavy-fixture support",
                      "radius-detail": "the actual minimum inside radius"}.get(kind, "this source condition")
            self.ask(paths[-1], f"{inst.id}: what evidence confirms {detail}?")
        self.conditions.append({"id": f"{inst.id}:{kind}:{cut if cut is not None else '-'}:{join or '-'}",
                                "kind": kind, "installationId": inst.id, "cutoutIndex": cut, "joinId": join,
                                "status": status, "source": src, "explanation": explanation,
                                "evidenceNote": note, "fields": paths})

    @property
    def failed(self) -> bool:
        return any(c["status"] == "fail" for c in self.checks) or any(c["status"] == "failed" for c in self.conditions)

    @property
    def conditional(self) -> bool:
        return any(c["status"] in {"unknown", "unsupported"} for c in self.checks) or any(
            c["status"] != "satisfied" for c in self.conditions)

    def extend(self, other: Evidence) -> None:
        for target, records in ((self.checks, other.checks), (self.conditions, other.conditions)):
            ids = {record["id"] for record in target}
            for record in records:
                identity = record["id"]
                n = 1
                while identity in ids:
                    identity = f"{record['id']}:{n}"
                    n += 1
                target.append({**record, "id": identity})
                ids.add(identity)
        self.questions.update(other.questions)


def profile_evidence(request: Request) -> Evidence:
    out = Evidence()
    for field_name, value, question in (
        ("profileId", request.profile, "Which documented material profile applies to this product?"),
        ("profileProvenance", request.provenance, "What product/source evidence confirms this profile?"),
        ("nominalThicknessMm", request.thickness, "What is the actual nominal slab thickness in millimetres?"),
    ):
        path = f"material.{field_name}"
        if value is None:
            out.ask(path, question)
    out.check("profile-selection", None, "unknown" if request.profile is None else
              "pass" if request.profile in {S1, S2} else "unsupported",
              "Use an explicitly selected, documented product profile; trade names do not establish applicability.",
              fields=["material.profileId"], operator="applicable")
    out.check("profile-provenance", None, "pass" if request.provenance else "unknown",
              "The supplied provenance records why this product is matched to the selected profile.",
              fields=["material.profileProvenance"], operator="documented")
    known = request.profile == S1 and request.thickness in (12, 20, 30)
    out.check("nominal-thickness", None, "unknown" if request.thickness is None else "pass" if known else "unsupported",
              "Silestone uses exact nominal 12, 20 or 30 mm classes. Other classes are not interpolated; the sparse MSI profile supplies no thickness table.",
              actual=request.thickness, src=source(S1, "thickness") if request.profile == S1 else None,
              fields=["material.nominalThicknessMm"], operator="applicable")
    return out


def original_evidence(request: Request, inst: Facts) -> Evidence:
    out = Evidence()
    out.check("solid-connectivity", inst, "pass" if connected(solid_cells(inst.polygon, inst.cuts)) else "fail",
              "The original countertop must remain connected after subtracting its openings.", operator="applicable",
              fields=[f"{inst.path}.shape", f"{inst.path}.cutouts"])
    # Preserve negative supplied facts even if no candidate happens to invoke that detail.
    for index, fact in enumerate(inst.conditions):
        if fact["status"] == "failed":
            out.obligation(fact["kind"], inst, "Supplied support evidence reports a failed installation condition.",
                           cut=fact["cutoutIndex"])
            out.conditions[-1]["id"] += f":input-{index}"
    if request.profile not in {S1, S2}:
        return out
    profile = request.profile
    out.obligation("installation-support", inst, "Confirm the applicable installed supports; loads, cabinet geometry and reinforcement design are outside this calculation.",
                   src=source(profile, "support"))
    corners = reentrant_vertices(inst.polygon)
    if corners:
        if profile == S1:
            for kind in ("level-support", "corner-continuous-support", "corner-reinforcement"):
                out.obligation(kind, inst, "Corner joins do not remove the required level support, continuous corner support or reinforcement.",
                               src=source(profile, "corner" if kind != "corner-continuous-support" else "support"))
        else:
            out.obligation("unsupported-detail", inst, "The sparse Q guide establishes the corner radius/seam exception and general supports, not the inspected Silestone corner reinforcement detail.",
                           status="unsupported", src=source(S2, "radius"), fields=[f"{inst.path}.shape"])
        if inst.shape_kind not in {"L", "rect"} or len(corners) != 1:
            out.check("corner-detail-applicability", inst, "unsupported", "The inspected L detail does not establish all U/general-outline conditions.",
                      src=source(profile, "corner"), fields=[f"{inst.path}.shape"], operator="applicable")
            out.obligation("unsupported-detail", inst, "U/general corner detailing needs separate source review.", status="unsupported",
                           src=source(profile, "corner"), fields=[f"{inst.path}.shape"])
    for j, opening in enumerate(inst.openings):
        minimum = Decimal("9.525") if profile == S2 else Decimal(10 if opening.kind in {"sink", "cooktop"} else 5)
        path = f"{inst.path}.cutouts[{j}].radiusMm"
        out.minimum("opening-radius", inst, opening.radius, minimum, "Check the supplied minimum inside radius; the drawn rectangle is only the opening envelope.",
                    cut=j, src=source(profile, "radius", opening.kind), fields=[path])
        if profile == S2:
            out.checks[-1]["required"] = measure(Decimal("0.375"), "in")
        if opening.radius is None:
            out.ask(path, f"{inst.id}, opening {j + 1}: what is its minimum inside radius in millimetres?")
            out.obligation("radius-detail", inst, f"Provide an inside opening radius of at least {minimum} mm; this is a proposed detail, not a supplied fact.",
                           cut=j, src=source(profile, "radius", opening.kind), status="required-unverified", fields=[path])
        if opening.kind == "sink" or (profile == S1 and opening.kind == "cooktop"):
            out.obligation("fixture-support", inst, "Confirm fixture support and the source's large/heavy-fixture requirements; fixture support alone does not support a countertop join.",
                           src=source(profile, "fixture"), cut=j)
        elif profile == S2 and opening.kind == "cooktop":
            out.obligation("unsupported-detail", inst, "The Q sink-support passage does not establish this cooktop's support detail.",
                           status="unsupported", cut=j, fields=[f"{inst.path}.cutouts[{j}]"])
        supported = profile == S1 and inst.documented_run and opening.kind in {"sink", "cooktop"}
        out.check("rectangular-run-applicability", inst, "pass" if supported else "unknown" if profile == S1 and inst.arrangement is None and inst.polygon.area == inst.polygon.bounds.area else "unsupported",
                  "Named rails and original end distances apply only to the illustrated sink/cooktop rectangle with an explicit axis and rear datum. L/U leg envelopes are not that arrangement.",
                  cut=j, src=source(profile, "rails", opening.kind), fields=[f"{inst.path}.sourceArrangement"], operator="applicable")
        if not supported:
            if inst.arrangement is None and inst.polygon.area == inst.polygon.bounds.area:
                out.ask(f"{inst.path}.sourceArrangement", f"{inst.id}: confirm the rectangular run axis, rear edge and source-arrangement evidence.")
            out.obligation("unsupported-detail", inst, "Opening strip/end rules are not established for this profile or arrangement; no limits from another profile are substituted.",
                           cut=j, status="unsupported", src=source(profile, "rails", opening.kind), fields=[f"{inst.path}.sourceArrangement"])
            continue
        b, r, axis = inst.polygon.bounds, opening.rect, inst.axis
        low, high = ((r.y - b.y, b.y + b.h - r.y - r.h) if axis == 0 else
                     (r.x - b.x, b.x + b.w - r.x - r.w))
        rear, front = (low, high) if inst.arrangement["rear"] == "min" else (high, low)
        start, end = (r.x - b.x, b.x + b.w - r.x - r.w) if axis == 0 else (r.y - b.y, b.y + b.h - r.y - r.h)
        for rule, actual, minimum in (("original-front-strip", front, Decimal(50)),
                                      ("original-rear-strip", rear, Decimal(100 if opening.kind == "sink" else 50)),
                                      ("original-start-distance", start, request.gap_mm),
                                      ("original-end-distance", end, request.gap_mm)):
            out.minimum(rule, inst, Decimal(actual) * MM_PER_TICK, minimum,
                        "Measured on the original oriented installation. A new seam cannot cure an original strip or end-distance defect.",
                        cut=j, src=source(S1, "rails", opening.kind), fields=[f"{inst.path}.cutouts[{j}].at", f"{inst.path}.sourceArrangement"])
    if profile == S1 and inst.documented_run:
        for (j, a), (k, b) in combinations(enumerate(inst.openings), 2):
            if a.kind not in {"sink", "cooktop"} or b.kind not in {"sink", "cooktop"}:
                continue
            axis = inst.axis
            a0, al, at, ad = (a.rect.x, a.rect.w, a.rect.y, a.rect.h) if axis == 0 else (a.rect.y, a.rect.h, a.rect.x, a.rect.w)
            b0, bl, bt, bd = (b.rect.x, b.rect.w, b.rect.y, b.rect.h) if axis == 0 else (b.rect.y, b.rect.h, b.rect.x, b.rect.w)
            fields = [f"{inst.path}.cutouts[{j}].at", f"{inst.path}.cutouts[{k}].at"]
            if max(at, bt) < min(at + ad, bt + bd) and (a0 + al <= b0 or b0 + bl <= a0):
                gap = max(b0 - a0 - al, a0 - b0 - bl)
                out.minimum("adjacent-opening-gap", inst, Decimal(gap) * MM_PER_TICK, Decimal(50),
                            f"Clear along-run material between openings {j + 1} and {k + 1}; the diagram requires 50 mm, not 100 mm.",
                            cut=j, src=source(S1, "rails", a.kind), fields=fields)
            else:
                out.check("adjacent-opening-gap", inst, "unsupported", "This is not the illustrated side-by-side opening arrangement.",
                          cut=j, src=source(S1, "rails", a.kind), fields=fields, operator="applicable")
    return out


def corner_evidence(request: Request, inst: Facts, pieces: tuple[FabricationPolygon, ...]) -> Evidence:
    out = Evidence()
    if request.profile not in {S1, S2} or not reentrant_vertices(inst.polygon):
        return out
    remaining = any(reentrant_vertices(piece) for piece in pieces)
    minimum = Decimal(10) if request.profile == S1 else Decimal("9.525")
    path = f"{inst.path}.insideCornerRadiusMm"
    src = source(request.profile, "corner" if request.profile == S1 else "radius")
    if not remaining:
        out.check("continuous-inside-radius", inst, "not-applicable", "Corner seams remove the continuous reentrant corners; support and reinforcement conditions remain.",
                  src=src, fields=[path], operator="applicable")
    else:
        out.minimum("continuous-inside-radius", inst, inst.radius, minimum, "Continuous reentrant corners retain the source radius requirement.",
                    src=src, fields=[path])
        if request.profile == S2:
            out.checks[-1]["required"] = measure(Decimal("0.375"), "in")
        if inst.radius is None:
            out.ask(path, f"{inst.id}: what is the minimum continuous inside-corner radius in millimetres?")
            out.obligation("radius-detail", inst, f"Provide continuous inside corners with radius at least {minimum} mm.",
                           src=src, status="required-unverified", fields=[path])
    return out
