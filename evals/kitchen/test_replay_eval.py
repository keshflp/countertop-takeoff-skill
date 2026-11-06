"""Replay is an explicit historical workload, never a material assessment."""

from copy import deepcopy
import unittest

import replay_eval
import test_eval as historical


def witness():
    fixture, output = historical.case(9), historical.hand_quote(9)
    layout = output["layout"]
    layout.pop("ok")
    layout.pop("seams")
    layout.update(joins=[], footprintMode="gross-polygons")
    layout["pieces"][0]["cutouts"] = []
    placement = layout["slabs"][0]["placements"][0]
    placement.pop("rotated")
    placement["quarterTurns"] = 0
    unresolved = [{"field": "material." + field, "question": "What is the actual supplied model fact?"}
                  for field in ("profileId", "profileProvenance", "nominalThicknessMm")]
    output.update(version=2, developmentOnly="geometry-replay-unassessed", assessment={
        "status": "unresolved", "profile": {"id": None, "provenance": None, "nominalThicknessMm": None},
        "checks": [], "handling": "not-evaluated", "limitations": ["Development geometry replay; source rules unassessed."],
        "unresolved": unresolved})
    output["blanks"] += deepcopy(unresolved)
    return fixture, output


class ReplayTests(unittest.TestCase):
    def test_positive_historical_quote_and_corrupted_label_price_or_placement(self):
        for mutation, gate in ((lambda o: o.update(developmentOnly=None), "replayLabel"),
                               (lambda o: o["pricing"].update(materialCost="0.00"), "pricing"),
                               (lambda o: o["layout"]["slabs"][0]["placements"][0].update(x=100), "placements")):
            fixture, output = witness()
            result = replay_eval.evaluate(fixture, output, False)
            self.assertTrue(all(g["pass"] for g in result["gates"].values()), result)
            self.assertEqual(result["assessmentStatus"], "replay-unassessed")
            mutation(output)
            self.assertFalse(replay_eval.evaluate(fixture, output, False)["gates"][gate]["pass"])

    def test_expansion_never_adds_material_facts_to_original_fixture(self):
        fixture, _ = witness()
        before = deepcopy(fixture)
        data = replay_eval.expand(fixture["job"])
        self.assertEqual(fixture, before)
        self.assertEqual(data["mode"], "geometry-replay")
        self.assertEqual(data["legacySettings"], {"minSeamToCutoutIn": 6, "minMaterialBesideCutoutIn": 3})
        self.assertTrue(all(v is None for v in data["material"].values()))

    def test_replay_cannot_claim_source_assessment(self):
        _, output = witness()
        output["assessment"]["status"] = "assessed"
        with self.assertRaises(ValueError):
            replay_eval.replay_label(output)


if __name__ == "__main__":
    unittest.main()
