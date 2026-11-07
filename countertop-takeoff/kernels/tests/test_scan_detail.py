# /// script
# requires-python = ">=3.10"
# dependencies = ["opencv-python-headless==4.12.0.88", "numpy==2.2.6"]
# ///
"""Synthetic contract tests for optional selected scan-detail suggestions."""

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scan_detail import IDENTITY, encode_png, suggest_detail, suggest_preview

KERNEL = Path(__file__).resolve().parents[1] / "scan_detail.py"


class ScanDetailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def fixture(self, name: str | Path = "preview.png", width: int = 96, height: int = 72) -> tuple[Path, np.ndarray]:
        image = np.full((height, width, 3), 255, np.uint8)
        cv2.rectangle(image, (15, 15), (75, 55), (0, 0, 0), 2)
        path = Path(name)
        if not path.is_absolute():
            path = self.directory / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encode_png(image))
        return path, image

    def test_output_contract_has_inspection_only_keys(self) -> None:
        crop = self.directory / "selected.png"
        crop.write_bytes(encode_png(self.fixture()[1]))
        result = suggest_detail(crop, self.directory / "output")
        self.assertEqual(result["kind"], "scan_detail_suggestions")
        self.assertEqual(result["status"], "requires_inspection")
        self.assertTrue(result["review_required"])
        self.assertEqual(result["suggestion_space"], "original_crop_pixels")
        self.assertEqual(result["cleaned_to_original"], IDENTITY)
        self.assertIsNone(result["original_to_page"])
        self.assertEqual(result["original_crop"]["size_px"], [96, 72])
        self.assertEqual(result["original_crop"]["sha256"], hashlib.sha256(crop.read_bytes()).hexdigest())
        required = {"kind", "status", "review_required", "original_crop", "provenance",
                    "suggestion_space", "cleaned_to_original", "original_to_page",
                    "cleaned", "overlay", "suggestions"}
        self.assertTrue(required.issubset(result))
        forbidden = ("quantity", "area", "scale", "price", "material", "confirmation", "px_per_ft")
        def keys(value: object) -> set[str]:
            if isinstance(value, dict):
                return {key for child in value.values() for key in keys(child)} | set(value)
            if isinstance(value, list):
                return {key for child in value for key in keys(child)}
            return set()

        all_keys = keys(result)
        for suggestion in result["suggestions"]:
            self.assertEqual(suggestion["status"], "requires_inspection")
        self.assertFalse(any(word in key.lower() for word in forbidden for key in all_keys))

    def test_input_crop_bytes_are_unchanged(self) -> None:
        crop = self.directory / "selected.png"
        crop.write_bytes(encode_png(self.fixture()[1]))
        original_bytes = crop.read_bytes()
        suggest_detail(crop, self.directory / "output")
        self.assertEqual(crop.read_bytes(), original_bytes)

    def test_exact_preview_crop_and_pdf_page_round_trip(self) -> None:
        source = self.directory / "plan.pdf"
        source.write_bytes(b"synthetic source marker")
        preview, pixels = self.fixture(source.parent / "previews" / source.name / "page-2.png")
        preview_bytes, source_bytes = preview.read_bytes(), source.read_bytes()
        box = (7, 9, 67, 59)
        output = self.directory / "suggestions"
        result = suggest_preview(preview, source, output, box, page=2)

        crop = cv2.imdecode(np.frombuffer((output / "crop.png").read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
        np.testing.assert_array_equal(crop, pixels[box[1]:box[3], box[0]:box[2]])
        self.assertEqual(crop.shape[:2], (box[3] - box[1], box[2] - box[0]))
        self.assertEqual(preview.read_bytes(), preview_bytes)
        self.assertEqual(source.read_bytes(), source_bytes)
        self.assertEqual(result["original_crop"]["sha256"], hashlib.sha256((output / "crop.png").read_bytes()).hexdigest())
        self.assertEqual(result["provenance"]["source"], str(source.resolve()))
        self.assertEqual(result["provenance"]["page"], 2)
        self.assertEqual(result["provenance"]["crop_box_px"], list(box))
        self.assertEqual(result["original_to_page"], [[0.5, 0, 3.5], [0, 0.5, 4.5], [0, 0, 1]])

        points = np.array([[0, 0, 1], [59, 49, 1], [11.25, 20.5, 1]], dtype=np.float64)
        page_points = points @ np.array(result["original_to_page"], dtype=np.float64).T
        crop_points = page_points.copy()
        crop_points[:, :2] = crop_points[:, :2] * 2 - [box[0], box[1]]
        np.testing.assert_allclose(crop_points, points, atol=1e-12)

    def test_image_preview_keeps_image_pixels_without_page_scale(self) -> None:
        source = self.directory / "photo.jpg"
        source.write_bytes(b"synthetic image source")
        preview, _ = self.fixture(source.parent / "previews" / source.name / "page-1.png")
        result = suggest_preview(preview, source, self.directory / "image-output", (4, 6, 50, 45))
        self.assertIsNone(result["original_to_page"])
        self.assertIsNone(result["provenance"]["page"])
        self.assertEqual(result["provenance"]["source_space"], "image_preview_pixels")
        self.assertEqual(result["provenance"]["crop_to_preview"], [[1, 0, 4], [0, 1, 6], [0, 0, 1]])

    def test_bad_boxes_are_refused_before_output(self) -> None:
        source = self.directory / "plan.pdf"
        source.write_bytes(b"synthetic source marker")
        preview, _ = self.fixture(source.parent / "previews" / source.name / "page-1.png")
        bad_boxes = [(-1, 0, 10, 10), (0, 0, 0, 10), (0, 0, 97, 10), (0, 0, 10.5, 10), (False, 0, 10, 10)]
        for index, box in enumerate(bad_boxes):
            with self.subTest(box=box):
                output = self.directory / f"bad-{index}"
                with self.assertRaises(ValueError):
                    suggest_preview(preview, source, output, box, page=1)
                self.assertFalse(output.exists())

    def test_mismatched_page_and_preview_are_refused(self) -> None:
        source = self.directory / "plan.pdf"
        source.write_bytes(b"synthetic source marker")
        preview, _ = self.fixture(source.parent / "previews" / source.name / "page-1.png")
        output = self.directory / "wrong-page"
        with self.assertRaisesRegex(ValueError, "inspect_input"):
            suggest_preview(preview, source, output, (1, 1, 50, 50), page=2)
        self.assertFalse(output.exists())

    def test_output_aliasing_preview_is_refused_without_writing(self) -> None:
        source = self.directory / "plan.pdf"
        source.write_bytes(b"synthetic source marker")
        preview, _ = self.fixture(source.parent / "previews" / source.name / "page-1.png")
        output = self.directory / "aliased-output"
        output.mkdir()
        os.link(preview, output / "crop.png")
        original = preview.read_bytes()
        with self.assertRaisesRegex(ValueError, "aliases"):
            suggest_preview(preview, source, output, (1, 1, 50, 50), page=1)
        self.assertEqual(preview.read_bytes(), original)

    def test_cli_selfcheck_is_json(self) -> None:
        run = subprocess.run([sys.executable, str(KERNEL), "--selfcheck"],
                             capture_output=True, text=True, check=True)
        self.assertEqual(run.stdout.strip(), '{"ok":true}')


if __name__ == "__main__":
    unittest.main()
