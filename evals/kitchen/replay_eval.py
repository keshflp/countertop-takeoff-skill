"""Explicit development-only replay of frozen v1 geometry/financial semantics."""

from copy import deepcopy

import eval as old
from eval import require
import polygon_oracle as poly
import source_eval as current


def expand(job: dict) -> dict:
    require(job["version"] == 1, "geometry replay accepts historical v1 jobs only")
    adapted = deepcopy(job)
    adapted["version"] = 2
    adapted["material"].update(profileId=None, profileProvenance=None, nominalThicknessMm=None)
    settings = old.DEFAULTS | job["settings"]
    adapted["settings"] = {k: settings[k] for k in current.DEFAULTS}
    for installation in adapted["installations"]:
        installation.update(insideCornerRadiusMm=None, sourceArrangement=None, conditions=[])
        for cutout in installation["cutouts"]:
            cutout.update(radiusMm=None, mount=None)
    data = current.expand(adapted)
    data.update(mode="geometry-replay", legacySettings={k: settings[k] for k in ("minSeamToCutoutIn", "minMaterialBesideCutoutIn")})
    return data


def legacy_clearances(data: dict, layout: dict) -> None:
    settings = data["legacySettings"]
    clearance = old.ticks(max(settings.values()))
    for installation in data["installations"]:
        group = [p for identifier, p in current.pieces(layout).values() if identifier == installation["id"]]
        for edge in poly.boundaries(installation["id"], group):
            for index, cutout in enumerate(installation["cutouts"]):
                if old.exempt_join(installation, edge, index):
                    continue
                gap = old.distance2(edge.rect(), old.cutout_rect(cutout))
                require(gap > 0 and gap >= clearance ** 2, "frozen legacy seam/cutout clearance failed")


def replay_label(output: dict, layout_only: bool = False) -> None:
    require(output.get("version") == 2 and (layout_only and output.get("ok") is True or
            output.get("developmentOnly") == "geometry-replay-unassessed"), "missing explicit development replay label")
    assessment = output["assessment"]
    require(assessment["status"] == "unresolved" and assessment["handling"] == "not-evaluated", "replay falsely assessed manufacturer rules")
    require(assessment["profile"] == {"id": None, "provenance": None, "nominalThicknessMm": None}, "replay invented material model facts")
    require(not any(c["source"] is not None or c["status"] == "pass" for c in assessment["checks"]), "replay forged source assessment")
    require(any("replay" in str(s).lower() for s in assessment["limitations"]), "replay scope limitation omitted")


def replay_blanks(job: dict, output: dict) -> None:
    fields = {b["field"] for b in output["blanks"]}
    declared = {u["field"] for u in output["assessment"]["unresolved"]}
    require(fields == set(old.blank_fields(job)) | declared and len(fields) == len(output["blanks"]), "replay blank union omitted or duplicated facts")
    filtered = dict(output, blanks=[b for b in output["blanks"] if b["field"] in old.blank_fields(job)])
    old.check_blanks(job, filtered, {})


def evaluate(case: dict, output: dict, layout_only: bool) -> dict:
    job, expected = case["job"], case.get("expected", {})
    data = expand(job)
    historical = old.expand_job(job)
    layout = output.get("layout")
    checks = {"replayLabel": lambda: replay_label(output, layout_only), "originalGeometry": lambda: current.original_geometry(data)}
    if data["slab"] is not None:
        checks.update({"tiling": lambda: current.tiling(data, layout), "solidAndCutouts": lambda: current.cutouts(data, layout),
                       "pieceFit": lambda: current.fits(data, layout), "pieceCounts": lambda: current.counts(data, layout),
                       "placements": lambda: current.placements(data, layout), "joins": lambda: current.joins(data, layout),
                       "legacyClearances": lambda: legacy_clearances(data, layout),
                       "bounds": lambda: old.check_bounds(data, layout, expected),
                       "warnings": lambda: old.check_warnings(historical, layout, None if layout_only else output)})
    else:
        checks["nullLayout"] = lambda: require(layout is None, "unknown slab replay produced packing")
    if not layout_only:
        checks.update({"quantity": lambda: old.check_quantities(job, historical, output, expected),
                       "pricing": lambda: old.check_pricing(job, historical, output, expected),
                       "blanks": lambda: replay_blanks(job, output), "assumptions": lambda: old.check_assumptions(job, output),
                       "estimates": lambda: old.check_estimates(job, historical, output)})
        if layout is None:
            checks["warnings"] = lambda: old.check_warnings(historical, None, output)
    gates = {name: old.run_gate(check) for name, check in checks.items()}
    lower = None
    if data["slab"] is not None:
        w, h = old.usable(data)
        total = sum(old.area(old.points(i["outline"])) for i in data["installations"])
        lower = (total + w * h - 1) // (w * h)
    count = None if layout is None else layout.get("slabCount")
    return {"gates": gates, "assessmentStatus": "replay-unassessed", "layoutApplicable": data["slab"] is not None,
            "slabs": count, "optimum": expected.get("optimumSlabs"), "lowerBound": lower,
            "provenOptimal": None if layout is None else layout.get("provenOptimal"),
            "excessSlabs": None if count is None else count - expected.get("optimumSlabs", lower)}
