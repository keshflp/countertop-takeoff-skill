# /// script
# requires-python = ">=3.12"
# dependencies = ["ortools==9.14.6206"]
# ///
"""Contract checks independent of the optimizer's geometry helpers."""

import copy
from itertools import combinations
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from layout import LayoutError, solve


def job(length=200, depth=25, *, slab=(126, 63), rotate=True, cutouts=()):
    return {"slab": {"lengthIn": slab[0], "widthIn": slab[1]},
            "settings": {"slabTrimIn": 1, "kerfIn": 0.25, "minSeamToCutoutIn": 6,
                         "minMaterialBesideCutoutIn": 3, "allowRotate": rotate},
            "installations": [{"id": "perimeter", "outline": [[0, 0], [length, 0], [length, depth], [0, depth]],
                               "cutouts": list(cutouts)}]}


def box(points):
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def point_inside(x, y, points):
    return sum(a[0] > x and min(a[1], b[1]) < y < max(a[1], b[1])
               for a, b in zip(points, points[1:] + points[:1]) if a[0] == b[0]) % 2 == 1


class LayoutTests(unittest.TestCase):
    def check_layout(self, data, result):
        self.assertTrue(result["ok"])
        sizes = {}
        settings = data["settings"]
        for inst in data["installations"]:
            pieces = [p for p in result["pieces"] if p["installationId"] == inst["id"]]
            xs = sorted({p[0] for r in [inst["outline"]] + [p["outline"] for p in pieces] for p in r})
            ys = sorted({p[1] for r in [inst["outline"]] + [p["outline"] for p in pieces] for p in r})
            for a, b in zip(xs, xs[1:]):
                for c, d in zip(ys, ys[1:]):
                    x, y = (a + b) / 2, (c + d) / 2
                    self.assertEqual(sum(point_inside(x, y, p["outline"]) for p in pieces),
                                     int(point_inside(x, y, inst["outline"])))
            for seam in [s for s in result["seams"] if s["installationId"] == inst["id"]]:
                x0, y0, x1, y1 = box([[seam["x0"], seam["y0"]], [seam["x1"], seam["y1"]]])
                for cut in inst["cutouts"]:
                    dx = max(x0 - cut["x"] - cut["w"], cut["x"] - x1, 0)
                    dy = max(y0 - cut["y"] - cut["h"], cut["y"] - y1, 0)
                    self.assertGreater(dx * dx + dy * dy, 0)
                    self.assertGreaterEqual(dx * dx + dy * dy,
                                            max(settings["minSeamToCutoutIn"], settings["minMaterialBesideCutoutIn"]) ** 2)
            for piece in pieces:
                x0, y0, x1, y1 = box(piece["outline"])
                self.assertEqual(len(piece["outline"]), 4)
                sizes[piece["id"]] = x1 - x0, y1 - y0
        placed = []
        width = data["slab"]["lengthIn"] - 2 * settings["slabTrimIn"]
        height = data["slab"]["widthIn"] - 2 * settings["slabTrimIn"]
        for slab in result["slabs"]:
            rectangles = []
            for p in slab["placements"]:
                placed.append(p["pieceId"])
                w, h = sizes[p["pieceId"]]
                if p["rotated"]:
                    self.assertTrue(settings["allowRotate"])
                    w, h = h, w
                self.assertGreaterEqual(min(p["x"], p["y"]), 0)
                self.assertLessEqual(p["x"] + w, width)
                self.assertLessEqual(p["y"] + h, height)
                rectangles.append((p["x"], p["y"], p["x"] + w, p["y"] + h))
            for a, b in combinations(rectangles, 2):
                k = settings["kerfIn"]
                self.assertTrue(a[2] + k <= b[0] or b[2] + k <= a[0] or a[3] + k <= b[1] or b[3] + k <= a[1])
        self.assertCountEqual(placed, sizes)
        self.assertEqual(result["slabCount"], len(result["slabs"]))

    def test_long_run_shares_one_slab(self):
        data = job()
        result = solve(data)
        self.check_layout(data, result)
        self.assertEqual((result["slabCount"], len(result["pieces"])), (1, 2))

    def test_midpoint_cooktop_moves_seam(self):
        data = job(cutouts=[{"kind": "cooktop", "x": 85, "y": 4, "w": 30, "h": 17}])
        result = solve(data)
        self.check_layout(data, result)
        self.assertEqual(result["slabCount"], 1)
        self.assertEqual(len(result["seams"]), 1)

    def test_material_clearance_and_original_edge_warning(self):
        data = job(cutouts=[{"kind": "sink", "x": 80, "y": 1, "w": 30, "h": 20}])
        data["settings"]["minMaterialBesideCutoutIn"] = 9
        result = solve(data)
        self.check_layout(data, result)
        self.assertTrue(any("original countertop edge" in w for w in result["warnings"]))

    def test_rotation_on_and_off(self):
        data = job(50, 70, slab=(82, 62))
        result = solve(data)
        self.check_layout(data, result)
        self.assertEqual(len(result["pieces"]), 1)
        self.assertTrue(result["slabs"][0]["placements"][0]["rotated"])
        data["settings"]["allowRotate"] = False
        result = solve(data)
        self.check_layout(data, result)
        self.assertEqual(len(result["pieces"]), 2)

    def test_l_and_u_tile_with_corner_seams(self):
        for outline in ([[0, 0], [120, 0], [120, 25], [25, 25], [25, 90], [0, 90]],
                        [[0, 0], [120, 0], [120, 90], [95, 90], [95, 25], [25, 25], [25, 90], [0, 90]]):
            with self.subTest(outline=outline):
                data = job()
                data["installations"][0]["outline"] = outline
                self.check_layout(data, solve(data))

    def test_deterministic(self):
        data = job(cutouts=[{"kind": "sink", "x": 80, "y": 4, "w": 30, "h": 17}])
        self.assertEqual(solve(data), solve(copy.deepcopy(data)))

    def test_budget_keeps_a_safe_layout_without_claiming_proof(self):
        data = job(cutouts=[{"kind": "cooktop", "x": 85, "y": 4, "w": 30, "h": 17}])
        result = solve(data, work_budget=0)
        self.check_layout(data, result)
        self.assertFalse(result["provenOptimal"])
        self.assertEqual(result, solve(data, work_budget=0))

    def test_extra_seams_can_reduce_slab_count(self):
        # Ten 70x25 runs need five slabs if left whole. Two seams suffice:
        # six whole runs on three slabs, plus two lanes of 70+53.75 on slab four;
        # the two 16-inch remainders fit alongside the first six whole runs.
        data = job(70, 25)
        data["installations"] = [dict(data["installations"][0], id=f"run{i}") for i in range(10)]
        result = solve(data)
        self.check_layout(data, result)
        self.assertEqual(result["slabCount"], 4)
        self.assertEqual(len(result["pieces"]), 12)

    def test_corner_cutout_selects_the_other_partition(self):
        data = job()
        data["installations"][0].update(
            outline=[[0, 0], [120, 0], [120, 25], [25, 25], [25, 90], [0, 90]],
            cutouts=[{"kind": "sink", "x": 3, "y": 15, "w": 15, "h": 30}])
        result = solve(data)
        self.check_layout(data, result)
        self.assertTrue(any(s["x0"] == s["x1"] == 25 for s in result["seams"]))

    def test_errors(self):
        cases = [(job(200, 70, rotate=False), "piece_too_wide"),
                 (job(200, 25, cutouts=[{"kind": "sink", "x": 20, "y": 4, "w": 160, "h": 17}]), "no_legal_seam"),
                 (job(slab=(2, 2)), "slab_too_small"),
                 (job(0.1, 25), "invalid_input")]
        for data, tag in cases:
            with self.subTest(tag=tag):
                with self.assertRaises(LayoutError) as error:
                    solve(data)
                self.assertEqual(error.exception.tag, tag)


if __name__ == "__main__":
    unittest.main()
