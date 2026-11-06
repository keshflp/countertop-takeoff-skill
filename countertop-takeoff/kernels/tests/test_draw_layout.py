# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow==12.0.0"]
# ///

from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

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


if __name__ == "__main__":
    unittest.main()
