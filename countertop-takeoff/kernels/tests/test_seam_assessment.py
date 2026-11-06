"""Source-facing examples are synthetic and checked in exact metric units."""

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seam_model import read_request
from seam_planner import Cut, make_plan, solve_assessment, supplied_cuts


def job(length=96, depth=30, slab=(126, 64), openings=()):
    return {"version": 2, "mode": "assessment", "phase": "plan",
            "material": {"profileId": "silestone-2024-02", "profileProvenance": "Synthetic explicit product match", "nominalThicknessMm": "20"},
            "slab": {"lengthIn": slab[0], "widthIn": slab[1]},
            "settings": {"slabTrimIn": 1, "kerfIn": .25, "allowRotate": True},
            "installations": [{"id": "run", "shapeKind": "rect", "outline": [[0, 0], [length, 0], [length, depth], [0, depth]],
                               "cutouts": list(openings), "insideCornerRadiusMm": None,
                               "sourceArrangement": {"kind": "rectangular-run", "axis": "x", "rear": "min", "provenance": "Synthetic datum"},
                               "conditions": [{"kind": kind, "cutoutIndex": None, "status": "documented", "note": "Synthetic supplied support evidence"}
                                              for kind in ("installation-support", "fixture-support", "opening-continuous-support", "level-support", "corner-continuous-support", "corner-reinforcement")]}]}


def opening(x=36, y=6, w=24, h=18, kind="sink", radius="10"):
    return {"kind": kind, "x": x, "y": y, "w": w, "h": h, "radiusMm": radius, "mount": "under"}


def checks(result, rule):
    return [c for c in result["assessment"]["checks"] if c["ruleId"] == rule]


class AssessmentTests(unittest.TestCase):
    def test_u_arms_are_two_gross_joins_not_a_join_across_exterior_void(self):
        data = job(slab=(130, 100))
        data["installations"][0].update(shapeKind="U", sourceArrangement=None, insideCornerRadiusMm="10",
            outline=[[0, 0], [120, 0], [120, 90], [96, 90], [96, 24], [24, 24], [24, 90], [0, 90]])
        request = read_request(data)
        plan = make_plan(request, request.installations[0], (Cut(1, 40 * 16),), "stock-fit")
        self.assertEqual(len(plan.pieces), 3)
        self.assertEqual([(j["startIn"], j["endIn"]) for j in plan.joins], [(0, 24), (96, 120)])
        self.assertEqual([len(j["pieceIds"]) for j in plan.joins], [2, 2])

    def test_stock_partition_can_use_both_axes_without_openings(self):
        data = job(90, 70, slab=(100, 42))
        data["settings"]["allowRotate"] = False
        result = solve_assessment(data)
        self.assertIsNotNone(result["layout"])
        self.assertEqual(len(result["layout"]["pieces"]), 2)
        self.assertEqual(result["layout"]["joins"][0]["axis"], "y")

    def test_missing_model_and_slab_preserve_assessment_without_layout(self):
        data = job(openings=[opening()])
        data["material"] = dict.fromkeys(data["material"])
        data["slab"] = None
        result = solve_assessment(data)
        self.assertIsNone(result["layout"])
        self.assertEqual(result["assessment"]["status"], "unresolved")
        self.assertEqual({q["field"] for q in result["assessment"]["unresolved"]},
                         {"material.profileId", "material.profileProvenance", "material.nominalThicknessMm", "material.slab"})

    def test_missing_datum_is_a_plain_question_and_null_slab_assess_keeps_rules(self):
        data = job(openings=[opening()])
        data["phase"] = "assess"
        data["slab"] = None
        data["installations"][0]["sourceArrangement"] = None
        result = solve_assessment(data)
        questions = {q["field"]: q["question"] for q in result["assessment"]["unresolved"]}
        self.assertIn("material.slab", questions)
        self.assertIn("installations[0].sourceArrangement", questions)
        self.assertTrue(all(q.endswith("?") for q in questions.values()))
        self.assertTrue(checks(result, "opening-radius"))
        self.assertIsNone(result["layout"])

    def test_exact_original_metric_boundaries_and_zero_radius(self):
        for thickness, boundary in (("12", 5.9375), ("20", 3.9375), ("30", 3.9375)):
            for delta, expected in ((0, "pass"), (-.0625, "fail")):
                data = job(openings=[opening(x=boundary + delta)])
                data["phase"] = "assess"
                data["material"]["nominalThicknessMm"] = thickness
                result = solve_assessment(data)
                self.assertEqual(checks(result, "original-start-distance")[0]["status"], expected)
                self.assertEqual(checks(result, "original-start-distance")[0]["required"]["value"], "150" if thickness == "12" else "100")
        data = job(openings=[opening(radius="0")])
        result = solve_assessment(data)
        self.assertEqual(result["assessment"]["status"], "conflict")
        self.assertEqual(checks(result, "opening-radius")[0]["actual"]["value"], "0")
        self.assertIsNone(result["layout"])

    def test_oriented_sink_rear_and_cooktop_front(self):
        data = job(openings=[opening(y=2)])
        result = solve_assessment(data)
        self.assertEqual(checks(result, "original-front-strip")[0]["status"], "pass")
        self.assertEqual(checks(result, "original-rear-strip")[0]["status"], "fail")
        data["installations"][0]["sourceArrangement"]["rear"] = "max"
        self.assertEqual(solve_assessment(data)["assessment"]["status"], "assessed")
        data["installations"][0]["cutouts"][0]["kind"] = "cooktop"
        data["installations"][0]["sourceArrangement"]["rear"] = "min"
        self.assertEqual(solve_assessment(data)["assessment"]["status"], "assessed")

    def test_original_failure_is_not_fixed_by_supplied_split(self):
        data = job(openings=[opening(y=1)])
        data["installations"][0]["requiredPieceCount"] = 2
        self.assertEqual(solve_assessment(data, work_budget=0)["assessment"]["status"], "conflict")

    def test_missing_radius_and_outside_join_support_are_conditions(self):
        data = job(180, openings=[opening(x=75, radius=None)])
        inst = data["installations"][0]
        inst["conditions"] = [c for c in inst["conditions"] if c["kind"] != "opening-continuous-support"]
        result = solve_assessment(data)
        self.assertEqual(result["assessment"]["status"], "conditional")
        self.assertIsNotNone(result["layout"])
        self.assertTrue(any(c["kind"] == "opening-continuous-support" and c["joinId"] for c in result["assessment"]["conditions"]))
        self.assertTrue(any(c["kind"] == "radius-detail" for c in result["assessment"]["conditions"]))
        self.assertTrue(any(j["kind"] == "outside-opening" for j in result["layout"]["joins"]))

    def test_arbitrary_opening_center_has_two_stone_segments_and_more_cuts_allowed(self):
        data = job(240, slab=(100, 64), openings=[opening(x=48)])
        data["installations"][0]["seam"] = {"kind": "opening-center", "cutoutIndex": 0}
        result = solve_assessment(data, work_budget=0)
        self.assertIsNotNone(result["layout"])
        joins = result["layout"]["joins"]
        selected = next(j for j in joins if j["kind"] == "inside-opening")
        self.assertEqual(selected["offsetIn"], 60)
        self.assertEqual(len(selected["segments"]), 2)
        self.assertGreater(len(result["layout"]["pieces"]), 2)
        self.assertTrue(any(j["origin"] == "automatic" for j in joins))
        self.assertFalse(result["layout"]["provenOptimal"])

    def test_selected_exception_does_not_cover_another_opening(self):
        data = job(160, openings=[opening(x=28), opening(x=54)])
        data["installations"][0]["seam"] = {"kind": "opening-center", "cutoutIndex": 0}
        # Gap=2 inches passes adjacent50. The pinned seam remains >=100 from opening2.
        result = solve_assessment(data)
        self.assertIsNotNone(result["layout"])
        other = [c for c in checks(result, "outside-opening-clearance") if c["cutoutIndex"] == 1]
        self.assertTrue(other)
        data["installations"][0]["cutouts"][1] = opening(x=39, y=25, w=2, h=2, kind="other", radius="5")
        result = solve_assessment(data, work_budget=0)
        self.assertIsNone(result["layout"])

    def test_whole_l_and_corner_radius_alternative(self):
        data = job(slab=(100, 100))
        inst = data["installations"][0]
        inst.update(shapeKind="L", outline=[[0, 0], [90, 0], [90, 25], [25, 25], [25, 80], [0, 80]],
                    sourceArrangement=None, insideCornerRadiusMm="10")
        result = solve_assessment(data)
        self.assertEqual(len(result["layout"]["pieces"]), 1)
        self.assertEqual(result["layout"]["joins"], [])
        inst["insideCornerRadiusMm"] = "0"
        result = solve_assessment(data)
        self.assertEqual(len(result["layout"]["pieces"]), 2)
        self.assertEqual(checks(result, "continuous-inside-radius")[0]["status"], "not-applicable")
        self.assertEqual(result["assessment"]["installations"][0]["seamNecessity"], "source-rule")

    def test_l_openings_never_inherit_rectangle_datum(self):
        data = job(slab=(100, 100), openings=[opening(x=40, y=3, w=24, h=18)])
        inst = data["installations"][0]
        inst.update(shapeKind="L", outline=[[0, 0], [90, 0], [90, 25], [25, 25], [25, 80], [0, 80]], insideCornerRadiusMm="10")
        result = solve_assessment(data)
        self.assertEqual(result["assessment"]["status"], "conditional")
        self.assertFalse(checks(result, "original-rear-strip"))
        self.assertEqual(checks(result, "rectangular-run-applicability")[0]["status"], "unsupported")

    def test_sparse_profile_uses_exact_radius_without_silestone_rails(self):
        data = job(openings=[opening(radius="9.525")])
        data["material"]["profileId"] = "msi-q-pinned"
        result = solve_assessment(data)
        self.assertEqual(result["assessment"]["status"], "conditional")
        self.assertEqual(checks(result, "opening-radius")[0]["status"], "pass")
        self.assertFalse(checks(result, "original-rear-strip"))
        self.assertEqual(checks(result, "opening-radius")[0]["source"]["id"], "S2")

    def test_count_balance_determinism_and_failed_support_fallback(self):
        data = job()
        data["installations"][0]["requiredPieceCount"] = 2
        a = solve_assessment(data, work_budget=0)
        self.assertEqual(a, solve_assessment(copy.deepcopy(data), work_budget=0))
        self.assertEqual(a["layout"]["joins"][0]["offsetIn"], 48)
        data["installations"][0]["conditions"][0]["status"] = "failed"
        self.assertIsNone(solve_assessment(data, work_budget=0)["layout"])

    def test_cap_without_incumbent_is_not_physical_infeasibility(self):
        with patch("seam_planner.MAX_STATES", 0):
            result = solve_assessment(job(200))
        self.assertEqual(result["assessment"]["status"], "search-incomplete")
        self.assertIsNone(result["layout"])

    def test_closed_boundary_and_invalid_supplied_constraints(self):
        data = job(openings=[opening()])
        data["unexpected"] = True
        with self.assertRaises(ValueError):
            read_request(data)
        del data["unexpected"]
        inst = data["installations"][0]
        inst["seam"] = {"kind": "center-through-cutout", "cutoutIndex": 2}
        self.assertEqual(solve_assessment(data)["assessment"]["status"], "conflict")

    def test_legacy_midpoint_stays_x_and_rejected_join_has_no_dangling_id(self):
        data = job(40, 80, openings=[opening(x=12, y=32, w=16, h=16)])
        inst = data["installations"][0]
        inst["sourceArrangement"]["axis"] = "y"
        inst["seam"] = {"kind": "center-through-cutout", "cutoutIndex": 0}
        request = read_request(data)
        cuts, _, _ = supplied_cuts(request.installations[0])
        self.assertEqual(cuts, (Cut(0, 20 * 16),))
        result = solve_assessment(data)
        self.assertEqual(result["assessment"]["status"], "conflict")
        self.assertIsNone(result["layout"])
        self.assertTrue(all(c["joinId"] is None for c in result["assessment"]["checks"]))
        inst["seam"]["cutoutIndex"] = 0
        inst["requiredPieceCount"] = 3
        self.assertEqual(solve_assessment(data)["assessment"]["status"], "conflict")


if __name__ == "__main__":
    unittest.main()
