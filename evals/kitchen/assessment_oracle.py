"""Recompute physical predicates and verify that explanations/evidence mean them."""

from dataclasses import dataclass
from decimal import Decimal as D
from math import isqrt

import eval as old
from eval import Edge, Rect, require, ticks
import polygon_oracle as poly
from source_predicates import MM_PER_TICK, MSI, SILESTONE, adjacent_gap, applicable, original_run_strips, outside_minimum, radius_minimum

SOURCES = {
    SILESTONE: ("S1", "https://assetstools.cosentino.com/api/v1/bynder/doc/0B425745-8BAC-4A87-9D7B54DA7AC39A1D/silestone-installation-manual.pdf",
                "56535666e6ed4e33ea1bc452968ea1b7922abd13c57d98fff40312c0aa24794a"),
    MSI: ("S2", "https://cdn.msisurfaces.com/files/downloads/quartz-installation-guidelines.pdf",
          "8b9011f17cf55712fc17a4b2aecc40a87cbf2d9f30b6bfe00803c56c425a4074"),
}
STRUCTURAL = {"supplied-piece-count", "supplied-join", "solid-connectivity", "stock-fit"}


def source(source: dict, profile: str, file_page: int | None = None, printed_page: int | None = None) -> None:
    identifier, url, sha = SOURCES[profile]
    require(isinstance(source, dict), "omitted manufacturer source evidence")
    require((source["id"], source["url"], source["sha256"].lower()) == (identifier, url, sha),
            "source id/url/hash does not identify pinned applicable document")
    require(all(isinstance(source[k], str) and bool(source[k].strip()) for k in ("title", "edition", "quotation", "interpretation")),
            "source title/edition/quotation/interpretation missing")
    if profile == SILESTONE:
        require("03" in source["edition"] and "02/2024" in source["edition"], "wrong Silestone edition")
    require(bool(source["filePages"]) and all(type(p) is int and p > 0 for p in source["filePages"]), "invalid source file pages")
    if file_page is not None:
        require(file_page in source["filePages"], "wrong source file page")
    if printed_page is not None:
        require(printed_page in source["printedPages"], "wrong printed source page")


@dataclass(frozen=True)
class Predicate:
    rule: str
    installation: str | None
    cutout: int | None = None
    join: str | None = None
    status: str = "pass"
    actual: D | None = None
    minimum: D | None = None
    page: int | None = None
    printed: int | None = None
    operator: str = ">="


def run_arrangement(installation: dict) -> tuple[Rect, list[Rect]] | None:
    datum = installation["sourceArrangement"]
    p = poly.simple(installation["outline"])
    box = poly.bbox(p)
    if not datum or old.area(p) != box.area or datum["kind"] != "rectangular-run" or not datum["provenance"].strip():
        return None
    holes = [old.cutout_rect(c) for c in installation["cutouts"]]
    if datum["axis"] == "y":
        box = Rect(box.y, box.x, box.h, box.w)
        holes = [Rect(h.y, h.x, h.h, h.w) for h in holes]
    if datum["rear"] == "max":
        holes = [Rect(h.x, 2 * box.y + box.h - h.bottom, h.w, h.h) for h in holes]
    return box, holes


def join_edge(join: dict) -> Edge:
    return Edge(join["installationId"], "v" if join["axis"] == "x" else "h",
                ticks(join["offsetIn"]), ticks(join["startIn"]), ticks(join["endIn"]))


def predicates(data: dict, layout: dict | None) -> list[Predicate]:
    material = data["material"]
    profile, provenance, thickness = (material[k] for k in ("profileId", "profileProvenance", "nominalThicknessMm"))
    checks = [Predicate("profile-selection", None, status="unknown" if profile is None else "pass" if profile in SOURCES else "unsupported", operator="applicable"),
              Predicate("profile-provenance", None, status="unknown" if provenance is None else "pass", operator="documented"),
              Predicate("nominal-thickness", None, status="unknown" if thickness is None else "pass" if D(thickness) > 0 and (profile == MSI or D(thickness) in (12, 20, 30)) else "unsupported", operator="applicable")]
    if not applicable(profile, provenance, thickness):
        return checks
    for installation in data["installations"]:
        identifier = installation["id"]
        cutouts = installation["cutouts"]
        run = run_arrangement(installation)
        for index, cutout in enumerate(cutouts):
            minimum = radius_minimum(profile, cutout["kind"])
            actual = None if cutout["radiusMm"] is None else D(cutout["radiusMm"])
            page, printed = ((5, 8) if cutout["kind"] == "sink" else (6, 10)) if profile == SILESTONE else (2, None)
            checks.append(Predicate("opening-radius", identifier, index, status="unknown" if actual is None else "pass" if actual >= minimum else "fail",
                                    actual=actual, minimum=minimum, page=page, printed=printed))
            if profile != SILESTONE or cutout["kind"] not in ("sink", "cooktop"):
                continue
            if run is None:
                checks.append(Predicate("rectangular-run-applicability", identifier, index, status="unsupported" if installation["sourceArrangement"] else "unknown", operator="applicable"))
                continue
            checks.append(Predicate("rectangular-run-applicability", identifier, index, operator="applicable"))
            box, holes = run
            for relation, measurement in original_run_strips(box, holes[index], cutout["kind"], thickness).items():
                name = {"front": "original-front-strip", "rear": "original-rear-strip", "leftEnd": "original-start-distance", "rightEnd": "original-end-distance"}[relation]
                checks.append(Predicate(name, identifier, index, status="pass" if measurement.passes else "fail",
                                        actual=measurement.actual, minimum=measurement.minimum, page=page, printed=printed))
        if profile == SILESTONE and run is not None:
            for index, a in enumerate(run[1]):
                for b in run[1][index + 1:]:
                    measurement = adjacent_gap(a, b)
                    checks.append(Predicate("adjacent-opening-gap", identifier, index,
                                            status="unsupported" if measurement is None else "pass" if measurement.passes else "fail",
                                            actual=None if measurement is None else measurement.actual,
                                            minimum=D(50), page=5, printed=8))
        original = poly.simple(installation["outline"])
        if installation["shapeKind"] == "U" or len(poly.reentrant(original)) > 1:
            checks.append(Predicate("corner-detail-applicability", identifier, status="unsupported", operator="applicable"))
        current = [original] if layout is None else [poly.simple(p["outline"]) for p in layout["pieces"] if p["installationId"] == identifier]
        if any(poly.reentrant(p) for p in current):
            minimum = radius_minimum(profile, "corner")
            actual = installation["insideCornerRadiusMm"]
            actual = None if actual is None else D(actual)
            checks.append(Predicate("continuous-inside-radius", identifier, status="unknown" if actual is None else "pass" if actual >= minimum else "fail",
                                    actual=actual, minimum=minimum, page=10 if profile == SILESTONE else 2,
                                    printed=18 if profile == SILESTONE else None))
        if layout is None:
            continue
        for join in (j for j in layout["joins"] if j["installationId"] == identifier):
            edge = join_edge(join)
            for index, cutout in enumerate(cutouts):
                if cutout["kind"] not in ("sink", "cooktop"):
                    continue
                page, printed = (5, 9) if cutout["kind"] == "sink" else (6, 11)
                if join["kind"] == "inside-opening" and join["cutoutIndex"] == index:
                    hole = old.cutout_rect(cutout)
                    axis = (installation["sourceArrangement"] or {"axis": "x"})["axis"]
                    center2 = hole.x * 2 + hole.w if axis == "x" else hole.y * 2 + hole.h
                    valid = profile == SILESTONE and join["axis"] == axis and 2 * edge.line == center2
                    checks.append(Predicate("inside-opening-centerline", identifier, index, join["id"],
                                            "pass" if valid else "fail", D(edge.line) * MM_PER_TICK,
                                            D(center2) * MM_PER_TICK / 2, page, printed, "="))
                elif profile == SILESTONE and run is not None:
                    squared = old.distance2(edge.rect(), old.cutout_rect(cutout))
                    # Source-facing transverse joins have an exact axis gap.
                    actual = D(isqrt(squared)) * MM_PER_TICK if isqrt(squared) ** 2 == squared else D(squared).sqrt() * MM_PER_TICK
                    minimum = outside_minimum(thickness)
                    checks.append(Predicate("outside-opening-clearance", identifier, index, join["id"],
                                            "pass" if actual > 0 and actual >= minimum else "fail", actual, minimum, page, printed))
    return checks


def check_evidence(data: dict, assessment: dict, layout: dict | None) -> None:
    records = assessment["checks"]
    require(len({c["id"] for c in records}) == len(records), "duplicate rule evidence id")
    expected = predicates(data, layout)
    profile = data["material"]["profileId"]
    def matches(record: dict, wanted: Predicate) -> bool:
        return ((record["ruleId"], record["installationId"], record["cutoutIndex"], record["joinId"], record["status"]) ==
                (wanted.rule, wanted.installation, wanted.cutout, wanted.join, wanted.status) and
                (record["actual"] is None if wanted.actual is None else record["actual"] is not None and measure_mm(record["actual"]) == wanted.actual))

    for wanted in expected:
        candidates = [c for c in records if (c["ruleId"], c["installationId"], c["cutoutIndex"], c["joinId"]) ==
                      (wanted.rule, wanted.installation, wanted.cutout, wanted.join)]
        require(any(matches(c, wanted) for c in candidates),
                f"missing or forged {wanted.rule} evidence for {wanted.installation}/{wanted.cutout}/{wanted.join}")
    expected_rules = {p.rule for p in expected}
    for record in records:
        require(isinstance(record["explanation"], str) and bool(record["explanation"].strip()), "rule explanation missing")
        if record["ruleId"] in STRUCTURAL:
            require(record["source"] is None, "structural constraint was presented as manufacturer authority")
        elif record["status"] in ("pass", "fail"):
            source(record["source"], profile)
        if record["source"] is not None:
            source(record["source"], profile)
        if record["ruleId"] in expected_rules:
            compatible = [p for p in expected if matches(record, p)]
            require(bool(compatible), "extra contradictory or fabricated rule evidence")
            wanted = compatible[0]
            require(record["operator"] == wanted.operator, "wrong rule comparison operator")
            if wanted.minimum is not None:
                require(record["required"] is not None and measure_mm(record["required"]) == wanted.minimum, "wrong exact source minimum")
                unit, value = ("in", D("0.375")) if profile == MSI else ("mm", wanted.minimum)
                require(record["required"] == {"value": str(value), "unit": unit} or
                        record["required"]["unit"] == unit and D(record["required"]["value"]) == value,
                        "source minimum lost its exact original units")
                source(record["source"], profile, wanted.page, wanted.printed)
        else:
            require(record["ruleId"] in {"opening-join-applicability", "supplied-piece-count", "supplied-join", "solid-connectivity", "stock-fit"},
                    "unknown or fabricated rule evidence")


def measure_mm(measure: dict) -> D:
    require(isinstance(measure["value"], str), "metric evidence must be a decimal string")
    require(measure["unit"] in ("mm", "in"), "wrong dimensional evidence unit")
    return D(measure["value"]) * (D("25.4") if measure["unit"] == "in" else 1)


def required_conditions(data: dict, layout: dict | None) -> list[tuple[str, str, int | None, str | None]]:
    required = []
    if not applicable(*(data["material"][k] for k in ("profileId", "profileProvenance", "nominalThicknessMm"))):
        return required
    for installation in data["installations"]:
        identifier = installation["id"]
        required.append((identifier, "installation-support", None, None))
        if data["material"]["profileId"] == SILESTONE and poly.reentrant(poly.simple(installation["outline"])):
            for kind in ("level-support", "corner-continuous-support", "corner-reinforcement"):
                required.append((identifier, kind, None, None))
        for index, cutout in enumerate(installation["cutouts"]):
            if cutout["kind"] == "sink" or data["material"]["profileId"] == SILESTONE and cutout["kind"] == "cooktop":
                required.append((identifier, "fixture-support", index, None))
                if layout and data["material"]["profileId"] == SILESTONE:
                    for join in (j for j in layout["joins"] if j["installationId"] == identifier):
                        required.append((identifier, "opening-continuous-support", index, join["id"]))
    return required


def check_conditions(data: dict, assessment: dict, layout: dict | None) -> None:
    conditions = assessment["conditions"]
    require(len({c["id"] for c in conditions}) == len(conditions), "duplicate condition id")
    originals = {i["id"]: i for i in data["installations"]}
    profile = data["material"]["profileId"]
    for identifier, kind, index, join in required_conditions(data, layout):
        require(any((c["installationId"], c["kind"], c["cutoutIndex"], c["joinId"]) == (identifier, kind, index, join)
                    for c in conditions), f"omitted source condition {identifier}/{kind}/{index}/{join}")
    for condition in conditions:
        installation = originals[condition["installationId"]]
        if profile == MSI:
            require(condition["kind"] not in ("level-support", "corner-continuous-support", "corner-reinforcement", "opening-continuous-support"),
                    "sparse MSI evidence cannot inherit Silestone support obligations")
            if condition["kind"] == "fixture-support":
                index = condition["cutoutIndex"]
                require(type(index) is int and installation["cutouts"][index]["kind"] == "sink", "MSI fixture support applies to sink, not an invented cooktop rule")
        if condition["source"] is not None:
            source(condition["source"], profile)
        if condition["kind"] in ("radius-detail", "unsupported-detail"):
            require(condition["status"] != "satisfied", "missing radius or unsupported detail cannot be documented satisfied")
            continue
        records = [c for c in installation["conditions"] if c["kind"] == condition["kind"]
                   and c["cutoutIndex"] in (None, condition["cutoutIndex"])]
        failed = [c for c in records if c["status"] == "failed"]
        documented = [c for c in records if c["status"] == "documented"]
        wanted = "failed" if failed else "satisfied" if documented else "required-unverified"
        require(condition["status"] == wanted, "source condition status contradicts supplied scoped support facts")
        if wanted in ("failed", "satisfied"):
            require(condition["evidenceNote"] in [c["note"] for c in failed or documented], "support evidence note was forged or lost")
        else:
            require(condition["evidenceNote"] is None or condition["evidenceNote"] in [c["note"] for c in records], "unknown support gained evidence")
        require(condition["source"] is not None, "source-required support lacks source evidence")
    for predicate in predicates(data, layout):
        if predicate.status == "unknown" and predicate.rule in ("opening-radius", "continuous-inside-radius"):
            require(any(c["kind"] == "radius-detail" and c["installationId"] == predicate.installation and c["cutoutIndex"] == predicate.cutout
                        for c in conditions), "missing radius needs an explicit proposed radius-detail condition")


def check_assessment(data: dict, assessment: dict, layout: dict | None, expected: dict) -> None:
    require(assessment["profile"] == {"id": data["material"]["profileId"], "provenance": data["material"]["profileProvenance"],
                                      "nominalThicknessMm": data["material"]["nominalThicknessMm"]}, "assessment changed profile applicability facts")
    require(assessment["handling"] == "not-evaluated" and bool(assessment["limitations"]), "omitted handling/scope limitations")
    require(assessment["geometry"] == "valid", "valid source-case geometry was falsely labelled invalid")
    status, search = assessment["status"], assessment["search"]
    require(status in ("unresolved", "conditional", "assessed", "conflict", "search-incomplete"), "unknown assessment outcome")
    missing = [f"material.{k}" for k, v in data["material"].items() if v is None]
    if data["slab"] is None:
        missing.append("material.slab")
    unresolved = assessment["unresolved"]
    require(len({u["field"] for u in unresolved}) == len(unresolved), "duplicate missing-fact question")
    wanted_missing = missing_fields(data, layout)
    require(wanted_missing == {u["field"] for u in unresolved}, "missing-fact paths were omitted or invented")
    require(all(isinstance(u["question"], str) and "?" in u["question"] for u in unresolved), "plain unresolved question missing")
    computed = predicates(data, layout)
    failed = any(c.status == "fail" for c in computed) or any(c["status"] == "failed" for c in assessment["conditions"])
    uncertain = any(c.status in ("unknown", "unsupported") for c in computed) or any(c["status"] in ("required-unverified", "unsupported") for c in assessment["conditions"])
    if status == "assessed":
        stock_only = data["phase"] == "assess" and {u["field"] for u in unresolved} <= {"material.slab"}
        require(not failed and not uncertain and (not unresolved or stock_only), "conditional/unknown/failed facts labelled assessed")
        require(assessment["geometry"] == "valid" and all(c["status"] in ("pass", "not-applicable") for c in assessment["checks"]),
                "assessed output contains unresolved or invalid returned checks")
        require(data["material"]["profileId"] != MSI, "sparse MSI profile cannot be fully assessed")
    if any(i.get("seam", {}).get("kind") == "tangent-cutout" for i in data["installations"]):
        require(layout is None and status in ("conflict", "unresolved"), "unsupported tangent request received a qualifying layout")
    if layout is not None:
        require(status in ("assessed", "conditional") and not failed and not missing, "unqualified layout escaped admission gate")
        require(all(c["status"] != "fail" for c in assessment["checks"]), "layout admitted despite returned failed check")
        require(search["status"] in ("complete", "capped") and search["packing"] != "not-run", "layout claims search/packing never ran")
        require(applicable(*(data["material"][k] for k in ("profileId", "profileProvenance", "nominalThicknessMm"))), "layout used unsupported material/thickness")
        require(search["qualifyingCount"] > 0, "layout without qualifying candidate")
        if status == "conditional":
            require(uncertain or bool(unresolved), "conditional label hides no actual outstanding condition")
    elif data["phase"] != "assess":
        require(status in ("unresolved", "conflict", "search-incomplete"), "normal plan outcome omitted promised layout")
    if failed:
        require(status == "conflict" and layout is None, "known source failure did not produce conflict")
    if missing and not failed and not (data["phase"] == "assess" and set(missing) == {"material.slab"}):
        require(status == "unresolved", "missing profile/thickness/slab was not unresolved")
    if data["phase"] == "assess":
        require(layout is None and search["status"] == "not-run" and search["packing"] == "not-run", "assessment phase pretends to solve stock layout")
    if status == "search-incomplete":
        require(search["status"] == "capped" and layout is None, "no-incumbent cap was misrepresented")
    if status == "conflict" and search["status"] == "capped":
        require(failed, "capped search without independent failure cannot prove a conflict")
    if search["status"] == "capped":
        require(bool(search["limits"]), "cap limits omitted")
    require(search["qualifyingCount"] <= search["candidateCount"], "qualifying count exceeds searched candidates")
    require("whole" in search["candidateFamilies"] or search["status"] == "not-run", "whole-piece candidate family omitted")
    require(expected.get("assessmentStatus", status) == status, "case expected a different independently hand-checked outcome")


def missing_fields(data: dict, layout: dict | None) -> set[str]:
    missing = {f"material.{k}" for k, v in data["material"].items() if v is None}
    if data["slab"] is None:
        missing.add("material.slab")
    if not applicable(*(data["material"][k] for k in ("profileId", "profileProvenance", "nominalThicknessMm"))):
        return missing
    for n, installation in enumerate(data["installations"]):
        root = f"installations[{n}]"
        relevant = [p for p in predicates(data, layout) if p.installation == installation["id"] and p.status == "unknown"]
        for p in relevant:
            if p.rule == "opening-radius":
                missing.add(f"{root}.cutouts[{p.cutout}].radiusMm")
            elif p.rule == "continuous-inside-radius":
                missing.add(f"{root}.insideCornerRadiusMm")
            elif p.rule == "rectangular-run-applicability":
                missing.add(f"{root}.sourceArrangement")
        for identifier, kind, index, _ in required_conditions(data, layout):
            if identifier != installation["id"]:
                continue
            records = [(k, c) for k, c in enumerate(installation["conditions"]) if c["kind"] == kind and c["cutoutIndex"] in (None, index)]
            if not records:
                missing.add(f"{root}.conditions")
            elif not any(c["status"] in ("documented", "failed") for _, c in records):
                missing.update(f"{root}.conditions[{k}].status" for k, c in records if c["status"] == "unknown")
    return missing


def check_reasons(data: dict, assessment: dict, layout: dict | None) -> None:
    reports = assessment["installations"]
    require({r["id"] for r in reports} == {i["id"] for i in data["installations"]} and len(reports) == len(data["installations"]), "missing installation seam explanation")
    for installation in data["installations"]:
        report = next(r for r in reports if r["id"] == installation["id"])
        require(bool(report["explanation"].strip()), "empty necessity explanation")
        if not layout:
            require(report["seamNecessity"] != "stock-fit" or data["slab"] is not None, "unknown stock invented seam necessity")
            continue
        w, h = old.usable(data)
        box = poly.bbox(poly.simple(installation["outline"]))
        whole_fits = box.w <= w and box.h <= h or data["settings"]["allowRotate"] and box.h <= w and box.w <= h
        if report["seamNecessity"] == "none-required":
            require(whole_fits, "stock-infeasible whole piece was reported to need no seam")
        if report["seamNecessity"] == "stock-fit":
            require(not whole_fits, "a whole polygon that fits was falsely declared stock-infeasible")
        if report["seamNecessity"] == "source-rule":
            require(any(c.status == "fail" and c.installation == installation["id"] for c in predicates(data, None)), "source necessity has no failing whole-plan source predicate")
        for join in (j for j in layout["joins"] if j["installationId"] == installation["id"]):
            request = installation.get("seam")
            pinned = False
            if request and join["cutoutIndex"] == request["cutoutIndex"]:
                hole = old.cutout_rect(installation["cutouts"][request["cutoutIndex"]])
                axis = "x" if request["kind"] == "center-through-cutout" else (installation["sourceArrangement"] or {"axis": "x"})["axis"]
                center2 = 2 * hole.x + hole.w if axis == "x" else 2 * hole.y + hole.h
                pinned = join["axis"] == axis and 2 * ticks(join["offsetIn"]) == center2
            if pinned:
                require((join["origin"], join["reason"]) == ("supplied", "supplied-join"), "supplied join called automatic/physical necessity")
            elif "requiredPieceCount" in installation:
                require((join["origin"], join["reason"]) == ("supplied", "supplied-count"), "supplied count called an automatic strength requirement")
            else:
                require(join["origin"] == "automatic" and join["reason"] not in ("supplied-count", "supplied-join"), "automatic plan invented a supplied constraint")
                if join["reason"] == "stock-fit":
                    require(not whole_fits, "yield seam misrepresented as stock requirement")
