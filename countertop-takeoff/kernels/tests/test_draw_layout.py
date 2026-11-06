# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow==12.0.0"]
# ///

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from draw_layout import feet_inches, render


class DrawingTests(unittest.TestCase):
    def test_dimensions_keep_sixteenths(self):
        self.assertEqual(feet_inches(25.5), '2\' 1 1/2"')
        self.assertEqual(feet_inches(119.9375), '9\' 11 15/16"')
        self.assertEqual(feet_inches(120), '10\' 0"')

    def test_preview_needs_no_slab_or_layout_and_marks_cutout(self):
        data = {"slab": None, "settings": {}, "installations": [
            {"id": "island", "outline": [[0, 0], [80, 0], [80, 40], [0, 40]],
             "cutouts": [{"kind": "sink", "x": 25, "y": 10, "w": 30, "h": 20}]}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preview.png"
            render(data, path, preview=True)
            with Image.open(path) as image:
                self.assertEqual(image.width, 1080)
                # Same row: countertop fill, then the black sink opening.
                self.assertEqual(image.getpixel((180, 500)), (22, 51, 70))
                self.assertEqual(image.getpixel((420, 500)), (0, 0, 0))

    def test_estimates_are_visible_in_both_exports(self):
        outline = [[0, 0], [80, 0], [80, 40], [0, 40]]
        data = {"slab": {"lengthIn": 126, "widthIn": 63}, "settings": {"slabTrimIn": 1},
                "installations": [{"id": "island", "outline": outline,
                                   "cutouts": [{"kind": "sink", "x": 25, "y": 10, "w": 30, "h": 20}]}],
                "geometryEstimates": [{"installationId": "island", "cutoutIndex": 0,
                                       "fields": ["wIn", "hIn", "at"], "note": "Owner authorized a preliminary placeholder.",
                                       "xIn": 25, "yIn": 10, "wIn": 30, "hIn": 20}],
                "layout": {"ok": True, "slabCount": 1, "seams": [],
                           "pieces": [{"id": "P1", "installationId": "island", "outline": outline}],
                           "slabs": [{"index": 1, "placements": [{"pieceId": "P1", "x": 0, "y": 0, "rotated": False}]}]}}
        original = ImageDraw.ImageDraw.text
        drawn = []

        def record(draw, xy, text, *args, **kwargs):
            drawn.append(text)
            return original(draw, xy, text, *args, **kwargs)

        for preview in (False, True):
            drawn.clear()
            with self.subTest(preview=preview), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "drawing.png"
                with patch.object(ImageDraw.ImageDraw, "text", record):
                    render(data, path, preview=preview)
                self.assertIn("Preliminary: estimated geometry", drawn)
                self.assertIn("island, cutout 1 (sink): width, height, position estimated.", " ".join(drawn))
                with Image.open(path) as image:
                    self.assertIn((255, 211, 110), image.crop((0, 90, 1080, 165)).getdata())

    def test_center_join_shows_stone_front_and_back_with_an_empty_opening(self):
        data = {"slab": {"lengthIn": 126, "widthIn": 63}, "settings": {"slabTrimIn": 1},
                "installations": [{"id": "run", "outline": [[0, 0], [96, 0], [96, 30], [0, 30]],
                                   "seam": {"kind": "center-through-cutout", "cutoutIndex": 0},
                                   "cutouts": [{"kind": "cooktop", "x": 36, "y": 7, "w": 24, "h": 16}]}],
                "layout": {"ok": True, "slabCount": 1,
                           "seams": [{"installationId": "run", "x0": 48, "y0": 0, "x1": 48, "y1": 30}],
                           "pieces": [{"id": "P1", "installationId": "run", "outline": [[0, 0], [48, 0], [48, 30], [0, 30]]},
                                      {"id": "P2", "installationId": "run", "outline": [[48, 0], [96, 0], [96, 30], [48, 30]]}],
                           "slabs": [{"index": 1, "placements": [{"pieceId": "P1", "x": 0, "y": 0, "rotated": False},
                                                                 {"pieceId": "P2", "x": 48.25, "y": 0, "rotated": False}]}]}}
        for preview in (False, True):
            with self.subTest(preview=preview), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "join.png"
                render(data, path, preview=preview)
                with Image.open(path) as image:
                    self.assertEqual(image.getpixel((540, 350)), (255, 255, 255))
                    self.assertEqual(image.getpixel((540, 560)), (255, 255, 255))
                    self.assertEqual(set(image.crop((450, 400, 630, 510)).getdata()), {(0, 0, 0)})
                    self.assertIn((255, 255, 255), image.crop((44, 232, 800, 270)).getdata())


if __name__ == "__main__":
    unittest.main()
