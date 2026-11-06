import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from draw_assessment import slab_panel, transformed
from draw_layout import render
from seam_planner import solve_assessment
from test_seam_assessment import job, opening


def drawing(data, result):
    return {"version": 2, "slab": data["slab"], "settings": data["settings"],
            "installations": data["installations"], "assessment": result["assessment"],
            "layout": result["layout"], "geometryEstimates": []}


class AssessmentDrawingTests(unittest.TestCase):
    def test_both_exports_retain_estimates_checks_sources_and_conditions(self):
        data = job(openings=[opening(radius=None)])
        data["installations"][0]["conditions"] = []
        data["installations"][0]["seam"] = {"kind": "opening-center", "cutoutIndex": 0}
        payload = drawing(data, solve_assessment(data, work_budget=0))
        payload["geometryEstimates"] = [{"installationId": "run", "cutoutIndex": 0, "fields": ["wIn", "at"],
                                          "note": "Synthetic preliminary estimate", "xIn": 36, "yIn": 6, "wIn": 24, "hIn": 18}]
        original = ImageDraw.ImageDraw.text
        for preview in (True, False):
            seen = []
            def record(draw, xy, text, *args, captured=seen, **kwargs):
                captured.append(text)
                return original(draw, xy, text, *args, **kwargs)
            with tempfile.TemporaryDirectory() as directory, patch.object(ImageDraw.ImageDraw, "text", record):
                path = Path(directory) / "drawing.png"
                render(payload, path, preview=preview)
                with Image.open(path) as image:
                    self.assertEqual(image.width, 1080)
                words = " ".join(seen)
                for text in ("Preliminary: estimated geometry", "width, position estimated", "CONDITIONAL",
                             "opening-radius", "original-rear-strip", "opening-continuous-support",
                             "silestone-2024-02", "file p.5", "assetstools.cosentino.com", "not evaluated"):
                    self.assertIn(text, words)
                if not preview:
                    self.assertIn("run-J1", words)
                    self.assertIn("from installation origin", words)

    def test_unresolved_null_layout_renders_both_modes(self):
        data = job()
        data["material"] = dict.fromkeys(data["material"])
        data["slab"] = None
        payload = drawing(data, solve_assessment(data))
        for preview in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "unknown.png"
                render(payload, path, preview=preview)
                self.assertGreater(path.stat().st_size, 1000)

    def test_rotated_l_is_not_painted_as_bounding_rectangle_and_void_stays_empty(self):
        gross = [[0, 0], [60, 0], [60, 20], [20, 20], [20, 60], [0, 60]]
        clip = [[5, 25], [15, 25], [15, 45], [5, 45]]
        placement = {"pieceId": "L1", "x": 0, "y": 0, "quarterTurns": 2}
        self.assertEqual(transformed([[5, 25]], gross, placement), [[55, 35]])
        payload = {"slab": {"lengthIn": 80, "widthIn": 80}, "settings": {"slabTrimIn": 0},
                   "layout": {"pieces": [{"id": "L1", "outline": gross, "cutouts": [{"cutoutIndex": 0, "outline": clip}]}]}}
        panel = slab_panel({"index": 1, "placements": [placement]}, payload, {"L1": "#76d7ff"})[0]
        # Scale is 700/80. The rotated L occupies right and bottom legs.
        point = lambda x, y: (round(44 + x * 8.75), round(150 + y * 8.75))
        self.assertEqual(panel.getpixel(point(50, 28)), (0, 0, 0))
        self.assertNotEqual(panel.getpixel(point(20, 20)), (118, 215, 255))
        self.assertEqual(panel.getpixel(point(58, 10)), (118, 215, 255))


if __name__ == "__main__":
    unittest.main()
