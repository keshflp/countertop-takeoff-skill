# /// script
# requires-python = ">=3.12"
# dependencies = ["pymupdf>=1.26,<2", "Pillow>=12,<13", "pillow-heif>=1,<2"]
# ///
"""Focused file-intake contract tests, with synthetic inputs only."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pymupdf
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inspect_input import inspect_file

KERNEL = Path(__file__).resolve().parents[1] / "inspect_input.py"


class InspectInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def test_phone_images_produce_png_previews(self) -> None:
        for extension in ("png", "jpg", "heic"):
            with self.subTest(extension=extension):
                path = self.directory / f"kitchen.{extension}"
                Image.new("RGB", (128, 96), "white").save(path)
                result = inspect_file(path)
                self.assertTrue(result["ok"], result["problem"])
                self.assertEqual(result["kind"], "image")
                self.assertEqual(result["pages"], 1)
                self.assertIsNone(result["problem"])
                with Image.open(result["previews"][0]) as preview:
                    self.assertEqual(preview.format, "PNG")
                    self.assertEqual(preview.size, (128, 96))

    def test_jpeg_orientation_is_applied(self) -> None:
        path = self.directory / "rotated.jpg"
        image = Image.new("RGB", (128, 96), "white")
        exif = image.getexif()
        exif[274] = 6
        image.save(path, exif=exif)
        result = inspect_file(path)
        with Image.open(result["previews"][0]) as preview:
            self.assertEqual(preview.size, (96, 128))

    def test_pdf_renders_each_page_next_to_input(self) -> None:
        path = self.directory / "kitchen.pdf"
        with pymupdf.open() as document:
            for width in (72, 144):
                page = document.new_page(width=width, height=72)
                page.insert_text((10, 30), "Synthetic sketch")
            document.save(path)
        result = inspect_file(path)
        self.assertTrue(result["ok"], result["problem"])
        self.assertEqual(result["kind"], "pdf")
        self.assertEqual(result["pages"], 2)
        self.assertEqual(len(result["previews"]), 2)
        for preview_path, expected_width in zip(result["previews"], (144, 288)):
            preview = Path(preview_path)
            self.assertTrue(preview.is_relative_to(path.parent / "previews"))
            with Image.open(preview) as image:
                self.assertEqual(image.size, (expected_width, 144))

    def test_encrypted_pdf_requires_unlocked_copy(self) -> None:
        for user_password in ("secret", ""):
            with self.subTest(user_password=user_password):
                path = self.directory / f"protected-{len(user_password)}.pdf"
                with pymupdf.open() as document:
                    document.new_page()
                    document.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256,
                                  owner_pw="owner", user_pw=user_password)
                result = inspect_file(path)
                self.assertFalse(result["ok"])
                self.assertIn("unlocked copy", result["problem"])
                self.assertEqual(result["previews"], [])

    def test_missing_empty_corrupt_and_unsupported_files(self) -> None:
        cases = {"missing.png": None, "empty.jpg": b"", "damaged.png": b"bad image",
                 "damaged.pdf": b"%PDF-1.7\nnot a PDF", "damaged.heic": b"bad HEIC"}
        for name, content in cases.items():
            with self.subTest(name=name):
                path = self.directory / name
                if content is not None:
                    path.write_bytes(content)
                result = inspect_file(path)
                self.assertFalse(result["ok"])
                self.assertTrue(result["problem"])
                self.assertEqual(result["pages"], 0)
                self.assertEqual(result["previews"], [])
        gif = self.directory / "animation.gif"
        Image.new("RGB", (10, 10)).save(gif)
        self.assertFalse(inspect_file(gif)["ok"])

    def test_truncated_image_is_not_accepted_from_header_alone(self) -> None:
        path = self.directory / "truncated.jpg"
        Image.new("RGB", (128, 96)).save(path)
        path.write_bytes(path.read_bytes()[:-20])
        result = inspect_file(path)
        self.assertFalse(result["ok"])
        self.assertEqual(result["previews"], [])

    def test_pdf_that_needs_repair_is_reported_as_damaged(self) -> None:
        path = self.directory / "truncated.pdf"
        with pymupdf.open() as document:
            document.new_page()
            document.save(path)
        path.write_bytes(path.read_bytes()[:-40])
        result = inspect_file(path)
        self.assertFalse(result["ok"])
        self.assertIn("damaged", result["problem"])
        self.assertEqual(result["previews"], [])

    def test_cli_returns_all_results_and_selfcheck_is_json(self) -> None:
        image = self.directory / "phone sketch.png"
        Image.new("RGB", (10, 10)).save(image)
        run = subprocess.run([sys.executable, str(KERNEL), str(image),
                              str(self.directory / "absent.pdf")],
                             capture_output=True, text=True, check=True)
        results = json.loads(run.stdout)["files"]
        self.assertEqual([result["ok"] for result in results], [True, False])
        self.assertEqual(results[0]["path"], str(image.resolve()))
        check = subprocess.run([sys.executable, str(KERNEL), "--selfcheck"],
                               capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(check.stdout), {"ok": True})


if __name__ == "__main__":
    unittest.main()
