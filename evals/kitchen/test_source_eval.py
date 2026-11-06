"""Hand-built wire witnesses and corruptions; no solver or evidence generator."""

from copy import deepcopy
from decimal import Decimal as D
import json
from pathlib import Path
import unittest
import hashlib
import subprocess
import sys
import tempfile

import assessment_oracle as rules
import source_eval as evaluator

HERE = Path(__file__).parent
NOTE = "Synthetic supplied support evidence for this named scope; not a reinforcement design."
SOURCE = {"id": "S1", "title": "Silestone countertop design and installation", "edition": "REV.03 02/2024",
          "url": "https://assetstools.cosentino.com/api/v1/bynder/doc/0B425745-8BAC-4A87-9D7B54DA7AC39A1D/silestone-installation-manual.pdf",
          "sha256": "56535666e6ed4e33ea1bc452968ea1b7922abd13c57d98fff40312c0aa24794a",
          "filePages": [5, 6, 10, 11], "printedPages": [8, 9, 10, 11, 18, 20],
          "quotation": "Minimum distances and continuous support in the illustrated countertop details.",
          "interpretation": "Only the named dimensional relationship and scoped support detail is assessed."}


def case(prefix):
    return json.loads(next((HERE / "source-cases").glob(prefix + "*.json")).read_text())


def check(rule, actual=None, minimum=None, *, cutout=None, join=None, status="pass", operator=">="):
    return {"id": f"{rule}-{cutout}-{join}", "ruleId": rule,
            "installationId": None if rule in ("profile-selection", "profile-provenance", "nominal-thickness") else "counter",
            "cutoutIndex": cutout, "joinId": join, "status": status, "operator": operator,
            "actual": None if actual is None else {"value": str(actual), "unit": "mm"},
            "required": None if minimum is None else {"value": str(minimum), "unit": "mm"},
            "source": deepcopy(SOURCE),
            "explanation": "Hand-calculated synthetic predicate witness.", "fields": []}


def condition(kind, cutout=None, join=None):
    return {"id": f"{kind}-{cutout}-{join}", "kind": kind, "installationId": "counter",
            "cutoutIndex": cutout, "joinId": join, "status": "satisfied", "source": deepcopy(SOURCE),
            "explanation": "Supplied evidence covers this named support scope.", "evidenceNote": NOTE, "fields": []}


def rect(x, y, w, h):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def piece(identifier, outline, clips=()):
    return {"id": identifier, "installationId": "counter", "outline": outline,
            "cutouts": [{"cutoutIndex": i, "outline": p} for i, p in clips]}


def witness(prefix="01"):
    fixture = case(prefix)
    job = fixture["job"]
    profile = job["material"]
    checks = [check("profile-selection", operator="applicable"), check("profile-provenance", operator="documented"),
              check("nominal-thickness", operator="applicable")]
    conditions = [condition("installation-support")]
    joins = []
    if prefix == "09":
        checks += [check("continuous-inside-radius", 10, 10)]
        conditions += [condition(k) for k in ("level-support", "corner-continuous-support", "corner-reinforcement")]
        pieces = [piece("whole", [[0, 0], [72, 0], [72, 24], [24, 24], [24, 60], [0, 60]])]
        placements = [{"pieceId": "whole", "x": 0, "y": 0, "quarterTurns": 0}]
    else:
        conditions += [condition("fixture-support", 0)]
        checks += [check("opening-radius", 10, 10, cutout=0),
                   check("rectangular-run-applicability", cutout=0, operator="applicable")]
        front, rear, start, end = (127, 127, "990.6", "990.6") if prefix == "01" else ("88.9", "101.6", 1397, 1651)
        for rule, actual, minimum in (("original-front-strip", front, 50), ("original-rear-strip", rear, 50 if prefix == "01" else 100),
                                     ("original-start-distance", start, 100), ("original-end-distance", end, 100)):
            checks.append(check(rule, actual, minimum, cutout=0))
        if prefix == "01":
            pieces = [piece("whole", rect(0, 0, 104, 27), [(0, rect(39, 5, 26, 17))])]
            placements = [{"pieceId": "whole", "x": 0, "y": 0, "quarterTurns": 0}]
        else:
            pieces = [piece("left", rect(0, 0, 85, 25.5), [(0, rect(55, 4, 30, 18))]),
                      piece("right", rect(85, 0, 95, 25.5), [(0, rect(85, 4, 30, 18))])]
            joins = [{"id": "join-1", "installationId": "counter", "pieceIds": ["left", "right"],
                      "kind": "inside-opening", "axis": "x", "offsetIn": 85, "startIn": 0, "endIn": 25.5,
                      "segments": [{"x0": 85, "y0": 0, "x1": 85, "y1": 4}, {"x0": 85, "y0": 22, "x1": 85, "y1": 25.5}],
                      "cutoutIndex": 0, "origin": "automatic", "reason": "stock-fit"}]
            checks += [check("inside-opening-centerline", 2159, 2159, cutout=0, join="join-1", operator="=")]
            conditions += [condition("opening-continuous-support", 0, "join-1")]
            placements = [{"pieceId": "left", "x": 0, "y": 0, "quarterTurns": 0},
                          {"pieceId": "right", "x": 0, "y": 25.75, "quarterTurns": 0}]
    layout = {"pieces": pieces, "joins": joins, "slabs": [{"index": 1, "placements": placements}],
              "slabCount": 1, "lowerBound": 1, "provenOptimal": True, "footprintMode": "gross-polygons", "warnings": []}
    assessment = {"status": "assessed", "geometry": "valid",
                  "profile": {"id": profile["profileId"], "provenance": profile["profileProvenance"], "nominalThicknessMm": profile["nominalThicknessMm"]},
                  "checks": checks, "conditions": conditions, "unresolved": [], "handling": "not-evaluated",
                  "limitations": ["Handling, full tap/fixture detailing and reinforcement design are not evaluated."],
                  "installations": [{"id": "counter", "seamNecessity": "stock-fit" if prefix == "02" else "none-required", "explanation": "Hand witness for stock fit or a fitting whole piece."}],
                  "search": {"status": "complete", "candidateFamilies": ["whole", "corner", "stock-fit", "opening-center"],
                             "candidateCount": 2, "qualifyingCount": 1, "packing": "polygon-cells", "optimality": "global-slab-bound", "limits": []}}
    return fixture, {"ok": True, "version": 2, "assessment": assessment, "layout": layout}


def quote_witness(prefix="01"):
    fixture, output = witness(prefix)
    job, key = fixture["job"], fixture["expected"]
    source = deepcopy(job["installations"][0])
    source.update(areaSqIn={"01": "2808", "02": "4590", "09": "2592"}[prefix], sf=key["totalSf"])
    slab = job["material"]["slab"]
    output.update(material=deepcopy(job["material"]), installations=[source], totalSf=key["totalSf"],
                  slabCount=1, slabSf=str(D(slab["lengthIn"]) * D(slab["widthIn"]) / 144), pricing=deepcopy(key["pricing"]),
                  invoice=[{"installation": "Counter", "material": job["material"]["name"], "sf": key["totalSf"],
                            "ratePerSf": key["pricing"]["ratePerSf"], "amount": key["invoiceAmounts"][0]}],
                  blanks=[], geometryEstimates=[], assumptions=[{"setting": k, "value": v, "note": "assumed, confirm with Dad"}
                                                               for k, v in evaluator.DEFAULTS.items()], warnings=[])
    return fixture, output


class SourceEvaluationTests(unittest.TestCase):
    def assert_passes(self, fixture, output, layout_only=True):
        result = evaluator.evaluate(fixture, output, layout_only)
        self.assertTrue(all(g["pass"] for g in result["gates"].values()), result["gates"])
        return result

    def test_three_complete_hand_witnesses(self):
        for prefix in ("01", "02", "09"):
            with self.subTest(prefix=prefix):
                self.assert_passes(*witness(prefix))
                self.assert_passes(*quote_witness(prefix), layout_only=False)

    def test_whole_l_placement_positive_and_corrupt(self):
        fixture, output = witness("09")
        data = evaluator.expand(fixture["job"])
        evaluator.placements(data, output["layout"])
        output["layout"]["slabs"][0]["placements"][0]["x"] = 27
        with self.assertRaises(ValueError):
            evaluator.placements(data, output["layout"])

    def test_positive_quarterturn_and_disabled_rotation(self):
        fixture, output = witness("09")
        data = evaluator.expand(fixture["job"])
        output["layout"]["slabs"][0]["placements"][0]["quarterTurns"] = 3
        evaluator.placements(data, output["layout"])
        data["settings"]["allowRotate"] = False
        with self.assertRaises(ValueError):
            evaluator.placements(data, output["layout"])

    def test_each_physical_gate_rejects_a_corruption(self):
        for gate, mutate in (
            (evaluator.tiling, lambda l: l["pieces"].pop()),
            (evaluator.cutouts, lambda l: l["pieces"][0]["cutouts"].clear()),
            (evaluator.placements, lambda l: l["slabs"][0]["placements"][1].update(y=25.6875)),
            (evaluator.joins, lambda l: l["joins"][0].update(segments=[{"x0": 85, "y0": 0, "x1": 85, "y1": 25.5}])),
            (evaluator.joins, lambda l: l["joins"][0].update(installationId="invented")),
            (evaluator.joins, lambda l: l["joins"].append(dict(l["joins"][0], id="duplicate-boundary"))),
            (evaluator.counts, lambda l: l["pieces"].pop()),
        ):
            fixture, output = witness("02")
            fixture["job"]["installations"][0]["requiredPieceCount"] = 2
            data, layout = evaluator.expand(fixture["job"]), output["layout"]
            gate(data, layout)
            mutate(layout)
            with self.subTest(gate=gate.__name__), self.assertRaises((ValueError, KeyError)):
                gate(data, layout)

    def test_forged_omitted_duplicate_or_wrong_unit_source_evidence(self):
        for mutation in (lambda a: a["checks"].pop(),
                         lambda a: a["checks"][5]["source"].update(sha256="0" * 64),
                         lambda a: a["checks"][5]["actual"].update(value="128"),
                         lambda a: a["checks"][5]["required"].update(value="1.9685", unit="in"),
                         lambda a: a["checks"].append(dict(a["checks"][5], id="forged-extra", actual={"value": "999", "unit": "mm"})),
                         lambda a: a["checks"].append(dict(a["checks"][5], id="invented", ruleId="magic-strength"))):
            fixture, output = witness()
            data, a = evaluator.expand(fixture["job"]), output["assessment"]
            rules.check_evidence(data, a, output["layout"])
            mutation(a)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                rules.check_evidence(data, a, output["layout"])

    def test_original_rail_failure_cannot_be_repaired_by_opening_join(self):
        fixture, output = witness("02")
        fixture["job"]["installations"][0]["cutouts"][0]["hIn"] = 20
        data = evaluator.expand(fixture["job"])
        self.assertTrue(any(p.rule == "original-front-strip" and p.status == "fail" for p in rules.predicates(data, output["layout"])))
        with self.assertRaises(ValueError):
            rules.check_evidence(data, output["assessment"], output["layout"])

    def test_selected_exemption_does_not_cover_other_opening(self):
        fixture, output = witness("02")
        fixture["job"]["installations"][0]["cutouts"].append({"kind": "cooktop", "wIn": 8, "hIn": 8,
            "at": {"xIn": 86, "yIn": 5}, "radiusMm": "10", "mount": "top"})
        predicates = rules.predicates(evaluator.expand(fixture["job"]), output["layout"])
        self.assertTrue(any(p.rule == "outside-opening-clearance" and p.cutout == 1 and p.status == "fail" for p in predicates))

    def test_moved_join_without_selected_permission_fails(self):
        fixture, output = witness("02")
        data = evaluator.expand(fixture["job"])
        output["layout"]["joins"][0].update(kind="outside-opening", cutoutIndex=None)
        with self.assertRaises(ValueError):
            evaluator.joins(data, output["layout"])

    def test_opening_center_pins_only_one_of_three_pieces(self):
        fixture, output = witness("02")
        installation = fixture["job"]["installations"][0]
        installation["seam"] = {"kind": "opening-center", "cutoutIndex": 0}
        layout = output["layout"]
        layout["pieces"][1] = piece("middle", rect(85, 0, 45, 25.5), [(0, rect(85, 4, 30, 18))])
        layout["pieces"].append(piece("end", rect(130, 0, 50, 25.5)))
        layout["joins"][0].update(pieceIds=["left", "middle"], origin="supplied", reason="supplied-join")
        layout["joins"].append({"id": "join-2", "installationId": "counter", "pieceIds": ["middle", "end"],
            "kind": "outside-opening", "axis": "x", "offsetIn": 130, "startIn": 0, "endIn": 25.5,
            "segments": [{"x0": 130, "y0": 0, "x1": 130, "y1": 25.5}], "cutoutIndex": 0, "origin": "automatic", "reason": "yield"})
        data = evaluator.expand(fixture["job"])
        evaluator.tiling(data, layout)
        evaluator.counts(data, layout)
        evaluator.joins(data, layout)
        rules.check_reasons(data, output["assessment"], layout)
        installation["requiredPieceCount"] = 2
        with self.assertRaises(ValueError):
            evaluator.counts(evaluator.expand(fixture["job"]), layout)

    def test_false_stock_necessity_and_false_supplied_origin(self):
        fixture, output = witness()
        output["assessment"]["installations"][0]["seamNecessity"] = "stock-fit"
        with self.assertRaises(ValueError):
            rules.check_reasons(evaluator.expand(fixture["job"]), output["assessment"], output["layout"])
        fixture, output = witness("02")
        output["layout"]["joins"][0]["origin"] = "supplied"
        with self.assertRaises(ValueError):
            rules.check_reasons(evaluator.expand(fixture["job"]), output["assessment"], output["layout"])

    def test_support_evidence_omission_and_forged_note(self):
        for mutation in (lambda a: a["conditions"].pop(), lambda a: a["conditions"][0].update(evidenceNote="invented")):
            fixture, output = witness("02")
            mutation(output["assessment"])
            with self.assertRaises(ValueError):
                rules.check_conditions(evaluator.expand(fixture["job"]), output["assessment"], output["layout"])

    def test_unknown_radius_is_conditional_not_assessed_or_zero(self):
        fixture, output = witness()
        fixture["job"]["installations"][0]["cutouts"][0]["radiusMm"] = None
        fixture["expected"]["assessmentStatus"] = "conditional"
        a = output["assessment"]
        a["status"] = "conditional"
        a["checks"][3].update(status="unknown", actual=None)
        a["unresolved"] = [{"field": "installations[0].cutouts[0].radiusMm", "question": "What is the supplied opening radius?"}]
        a["conditions"].append(dict(condition("radius-detail", 0), status="required-unverified", evidenceNote=None))
        self.assert_passes(fixture, output)
        self.assertFalse(evaluator.evaluate(fixture, output, True)["layoutApplicable"])
        a["status"] = "assessed"
        with self.assertRaises(ValueError):
            rules.check_assessment(evaluator.expand(fixture["job"]), a, output["layout"], {})
        fixture["job"]["installations"][0]["cutouts"][0]["radiusMm"] = "0"
        self.assertTrue(any(p.rule == "opening-radius" and p.status == "fail" for p in rules.predicates(evaluator.expand(fixture["job"]), None)))

    def test_caps_preserve_incumbent_but_never_claim_proof(self):
        fixture, output = witness()
        a, layout = output["assessment"], output["layout"]
        a["search"].update(status="capped", optimality="not-proven", limits=["Synthetic candidate cap"])
        layout["provenOptimal"] = False
        self.assert_passes(fixture, output)
        layout["provenOptimal"] = True
        with self.assertRaises(ValueError):
            evaluator.bounds(evaluator.expand(fixture["job"]), layout, fixture["expected"], a)
        a["status"] = "search-incomplete"
        a["search"].update(qualifyingCount=0)
        rules.check_assessment(evaluator.expand(fixture["job"]), a, None, {})
        a["status"] = "conflict"
        # A finite search limit is not proof of physical impossibility.
        with self.assertRaises(ValueError):
            rules.check_assessment(evaluator.expand(fixture["job"]), a, None, {})

    def test_missing_material_and_null_prices_preserve_standalone_facts(self):
        fixture, output = quote_witness()
        fixture["job"]["material"]["nominalThicknessMm"] = None
        output["material"]["nominalThicknessMm"] = None
        output["assessment"]["profile"]["nominalThicknessMm"] = None
        output["assessment"].update(status="unresolved", unresolved=[{"field": "material.nominalThicknessMm", "question": "What is the actual nominal thickness?"}])
        output.update(layout=None, slabCount=None)
        output["pricing"].update(materialCost=None, materialCharge=None, materialRatePerSf=None, ratePerSf=None)
        output["invoice"][0].update(ratePerSf=None, amount=None)
        data = evaluator.expand(fixture["job"])
        evaluator.quantity(fixture["job"], data, output, fixture["expected"])
        evaluator.pricing(fixture["job"], data, output, {})
        rules.check_assessment(data, output["assessment"], None, {})
        output["assessment"]["unresolved"].clear()
        with self.assertRaises(ValueError):
            rules.check_assessment(data, output["assessment"], None, {})

    def test_material_class_is_exact_and_never_inferred_from_marketing_name(self):
        fixture, output = witness()
        for thickness, wanted in (("12", "pass"), ("20", "pass"), ("30", "pass"), ("19.999", "unsupported"), (None, "unknown")):
            fixture["job"]["material"]["nominalThicknessMm"] = thickness
            checks = rules.predicates(evaluator.expand(fixture["job"]), None)
            self.assertEqual(next(p.status for p in checks if p.rule == "nominal-thickness"), wanted)
        fixture["job"]["material"].update(profileId=None, nominalThicknessMm="20", name="Silestone", vendor="Cosentino")
        self.assertEqual(rules.predicates(evaluator.expand(fixture["job"]), None)[0].status, "unknown")

    def test_msi_preserves_original_inch_radius_and_never_borrows_s1_support(self):
        fixture, output = witness("09")
        fixture["job"]["material"]["profileId"] = "msi-q-pinned"
        fixture["job"]["installations"][0]["insideCornerRadiusMm"] = "9.525"
        data = evaluator.expand(fixture["job"])
        a = output["assessment"]
        a["checks"][-1].update(actual={"value": "9.525", "unit": "mm"}, required={"value": "0.375", "unit": "in"})
        s2 = dict(SOURCE, id="S2", url="https://cdn.msisurfaces.com/files/downloads/quartz-installation-guidelines.pdf",
                  sha256="8b9011f17cf55712fc17a4b2aecc40a87cbf2d9f30b6bfe00803c56c425a4074", filePages=[2], printedPages=[])
        for record in a["checks"]:
            record["source"] = s2
        a["checks"][-1]["source"] = s2
        rules.check_evidence(data, a, output["layout"])
        a["checks"][-1]["required"] = {"value": "9.525", "unit": "mm"}
        with self.assertRaises(ValueError):
            rules.check_evidence(data, a, output["layout"])
        a["conditions"] = [dict(condition("installation-support"), source=s2)]
        rules.check_conditions(data, a, output["layout"])
        a["conditions"].append(dict(condition("corner-reinforcement"), source=s2))
        with self.assertRaises(ValueError):
            rules.check_conditions(data, a, output["layout"])

    def test_corner_seam_removes_radius_but_retains_support(self):
        fixture, output = witness("09")
        fixture["job"]["installations"][0].update(insideCornerRadiusMm="0", requiredPieceCount=2)
        layout = output["layout"]
        layout["pieces"] = [piece("top", rect(0, 0, 72, 24)), piece("leg", rect(0, 24, 24, 36))]
        layout["joins"] = [{"id": "corner", "installationId": "counter", "pieceIds": ["top", "leg"], "kind": "corner",
                            "axis": "y", "offsetIn": 24, "startIn": 0, "endIn": 24, "segments": [{"x0": 0, "y0": 24, "x1": 24, "y1": 24}],
                            "cutoutIndex": None, "origin": "supplied", "reason": "supplied-count"}]
        layout["slabs"][0]["placements"] = [{"pieceId": "top", "x": 0, "y": 0, "quarterTurns": 0},
                                                {"pieceId": "leg", "x": 0, "y": 24.25, "quarterTurns": 0}]
        output["assessment"]["checks"].pop()
        self.assert_passes(fixture, output)
        output["assessment"]["conditions"].pop()
        with self.assertRaises(ValueError):
            rules.check_conditions(evaluator.expand(fixture["job"]), output["assessment"], layout)

    def test_missing_datum_and_support_paths_are_exact_questions(self):
        fixture, output = witness("02")
        installation = fixture["job"]["installations"][0]
        installation["sourceArrangement"] = None
        installation["conditions"] = []
        data = evaluator.expand(fixture["job"])
        self.assertEqual(rules.missing_fields(data, output["layout"]),
                         {"installations[0].sourceArrangement", "installations[0].conditions"})
        installation["conditions"] = [{"kind": "installation-support", "cutoutIndex": None, "status": "unknown", "note": None}]
        self.assertIn("installations[0].conditions[0].status", rules.missing_fields(evaluator.expand(fixture["job"]), output["layout"]))
        fixture, output = witness()
        output["assessment"]["unresolved"] = [{"field": "fabricated.path", "question": "A fabricated missing fact?"}]
        with self.assertRaises(ValueError):
            rules.check_assessment(evaluator.expand(fixture["job"]), output["assessment"], output["layout"], {})

    def test_exact_synthetic_answer_keys_and_frozen_fixture_bytes(self):
        for path in (HERE / "source-cases").glob("*.json"):
            fixture = json.loads(path.read_text())
            data = evaluator.expand(fixture["job"])
            evaluator.original_geometry(data)
            key = fixture["expected"]
            areas = evaluator.old.exact_areas(data)
            self.assertEqual(key["totalSf"], evaluator.old.money(sum(areas.values()) / 144), path.name)
            if "optimumSlabs" in key:
                self.assertEqual(key["pricing"], evaluator.old.expected_pricing(fixture["job"], data, key["optimumSlabs"]), path.name)
        frozen = json.loads((HERE / "historical-baseline.json").read_text())
        for path, sha in frozen["fixtures"].items():
            self.assertEqual(hashlib.sha256((HERE.parents[1] / path).read_bytes()).hexdigest(), sha)

    def test_v2_runner_does_not_skip_null_slab_or_score_conditional(self):
        fixture, output = witness()
        fixture["job"]["material"]["slab"] = None
        fixture["expected"]["assessmentStatus"] = "unresolved"
        a = output["assessment"]
        a.update(status="unresolved", unresolved=[{"field": "material.slab", "question": "What is the nominal slab size?"}])
        a["search"].update(status="not-run", candidateCount=0, qualifyingCount=0, packing="not-run", optimality="not-proven")
        output["layout"] = None
        with tempfile.TemporaryDirectory(prefix="source eval ") as directory:
            root = Path(directory)
            (root / "case.json").write_text(json.dumps(fixture))
            responder = root / "respond.py"
            responder.write_text("import json\nprint(json.dumps(" + repr(output) + "))\n")
            completed = subprocess.run([sys.executable, str(HERE / "eval.py"), "--json", "--layout-only", "--cases", str(root),
                                        "--layout-cmd", f'"{sys.executable}" "{responder}"'], text=True, capture_output=True, timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            report = json.loads(completed.stdout)
            self.assertEqual(report["evaluatedCases"], 1)
            self.assertEqual(report["skippedCases"], 0)
            self.assertEqual(report["assessmentCounts"], {"unresolved": 1})
            self.assertFalse(report["scoreAvailable"])

    def test_assess_phase_keeps_one_stock_question_without_claiming_packing(self):
        fixture, output = witness()
        fixture["job"]["material"]["slab"] = None
        data = evaluator.expand(fixture["job"])
        data["phase"] = "assess"
        a = output["assessment"]
        a["unresolved"] = [{"field": "material.slab", "question": "What is the nominal slab size?"}]
        a["search"].update(status="not-run", candidateCount=0, qualifyingCount=0, packing="not-run", optimality="not-proven")
        rules.check_assessment(data, a, None, {})
        with self.assertRaises(ValueError):
            rules.check_assessment(data, a, output["layout"], {})
        a["unresolved"].append(deepcopy(a["unresolved"][0]))
        with self.assertRaises(ValueError):
            rules.check_assessment(data, a, None, {})


if __name__ == "__main__":
    unittest.main()
