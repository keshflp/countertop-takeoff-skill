# /// script
# requires-python = ">=3.10"
# dependencies = ["opencv-python-headless==4.12.0.88", "numpy==2.2.6", "pymupdf==2.1", "shapely==2.2.0"]
# ///
"""Observable contracts for optional scan assistance; run sequentially with acceptance."""
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pymupdf
from shapely.geometry import Polygon

from evaluate_scan_detail import SKILL, prepare, evaluate, MATCH_IOU
sys.path.insert(0, str(SKILL / "scripts"))
import image_measure
import regions
import scan_detail


class ScanDetailContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        prepare(cls.root)
        cls.truth = json.loads((cls.root / "truth.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def case(self, name):
        return next(c for c in self.truth["cases"] if c["name"] == name)

    def suggest(self, case, tag):
        provenance = {k: case[k] for k in ("page", "crop_bbox", "render_zoom")}
        provenance["source_id"] = "generated-scans"
        return scan_detail.suggest_detail(self.root / case["crop"], self.root / tag, provenance)

    def adopted(self, name, tag):
        case = self.case(name)
        suggestions = self.suggest(case, tag)
        expected = Polygon(case["outline"])
        def iou(s):
            p = Polygon([p["px"] for p in s["points"]])
            return p.intersection(expected).area / p.union(expected).area
        # Test-only oracle chooses an outline. Production requires agent
        # inspection and explicit selection; there is no automatic adopter.
        choice = max(suggestions["suggestions"], key=iou)
        self.assertGreaterEqual(iou(choice), MATCH_IOU)
        measured = image_measure.measure_from_points(case["anchors"], choice["points"])
        crop = self.root / case["crop"]
        measured.update(crop=str(crop), crop_sha256=case["crop_sha256"],
                        provenance=suggestions["provenance"], overlay=str(self.root / f"{tag}.png"))
        image_measure.render_overlay(str(crop), measured, measured["overlay"])
        path = self.root / f"{tag}.json"
        path.write_text(json.dumps(measured), encoding="utf-8")
        region = {"region_id": tag, "source_id": "generated-scans", "page": case["page"],
                  "image_measurement": str(path), "expected_sf_range": [1, 100]}
        return measured, region, path

    def test_frozen_generated_outline_and_cleanup_contract(self):
        result = evaluate(self.root, "contract", False)
        self.assertEqual((result["eligible_details"], result["missed"], result["spurious"]), (8, 0, 3))
        for row in result["cases"]:
            with self.subTest(case=row["case"]):
                if row["eligible"]:
                    self.assertLess(abs(row["area_error_pct"]), 3)  # This workload only.
                    self.assertLess(row["boundary_error_px"], 3.2)
                self.assertEqual(row["mapping_error_px_or_pt"], 0)
                if row["case"] in ("gradient", "gradient-ell"):
                    self.assertEqual(row["background_darkness_pct"], 0)
                    self.assertEqual(row["ink_retained_pct"], 100)
        self.assertLess(next(r for r in result["cases"] if r["case"] == "speckle")["background_darkness_pct"], .01)

    def test_unadopted_suggestions_cannot_be_measured(self):
        for case in self.truth["cases"]:
            with self.subTest(case=case["name"]):
                out = self.root / "unadopted" / case["name"]
                result = scan_detail.suggest_detail(self.root / case["crop"], out)
                self.assertTrue(result["review_required"])
                self.assertFalse(result["provenance_verified"])
                self.assertIsNone(result["original_to_page"])
                region = {"region_id": "unadopted", "page": case["page"], "source_id": "generated-scans",
                          "image_measurement": str(out / "suggestions.json"), "expected_sf_range": [1, 100]}
                refused = regions.measure_region_image(region, str(self.root))
                self.assertEqual(refused["status"], "unresolved")
                self.assertIsNone(refused["area_sf"])
                self.assertNotIn("totals", result)
                self.assertNotIn("run_status", result)

    def test_explicit_adoption_and_arithmetic_are_separate(self):
        for name in ("rectangle", "ell", "notch", "skew"):
            with self.subTest(case=name):
                case = self.case(name)
                # Baseline with exact independent oracle points verifies math,
                # rather than crediting recognition with oracle geometry.
                exact = image_measure.measure_from_points(case["anchors"], [{"px": p} for p in case["outline"]])
                true_area = Polygon(case["outline"]).area / 40 ** 2
                self.assertAlmostEqual(exact["area_sf"], true_area, places=4)
                measured, region, path = self.adopted(name, f"adopt-{name}")
                accepted = regions.measure_region_image(region, str(self.root))
                self.assertEqual(accepted["status"], "measured")
                self.assertLess(abs(accepted["area_sf"] / true_area - 1), .03)
                self.assertEqual(measured["selections"]["anchors"], case["anchors"])

    def test_independent_anchors_overlay_and_source_binding_still_required(self):
        measured, region, path = self.adopted("rectangle", "guards")
        for label, mutate in [
            ("duplicate-anchor", lambda m: m["selections"].update(anchors=[m["selections"]["anchors"][0]] * 2)),
            ("wrong-page", lambda m: m["provenance"].update(page=999)),
            ("wrong-source", lambda m: m["provenance"].update(source_id="other")),
            ("missing-overlay", lambda m: m.update(overlay=None)),
            ("edited-result", lambda m: m.update(area_sf=99)),
            ("wrong-pixels", lambda m: m.update(crop_sha256="0" * 64)),
        ]:
            with self.subTest(case=label):
                bad = copy.deepcopy(measured)
                mutate(bad)
                path.write_text(json.dumps(bad), encoding="utf-8")
                refused = regions.measure_region_image(region, str(self.root))
                self.assertEqual(refused["status"], "unresolved")
                self.assertIsNone(refused["area_sf"])

    def test_mapping_agrees_with_source_render_and_existing_measurement_route(self):
        bbox, zoom = [40, 60, 840, 580], 1.5
        with pymupdf.open(str(self.root / "scans.pdf")) as source:
            pix = source[0].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=pymupdf.Rect(*bbox))
        crop = self.root / "zoomed.png"
        pix.save(str(crop))
        prov = {"source_id": "generated-scans", "page": 1, "crop_bbox": bbox, "render_zoom": zoom}
        result = scan_detail.suggest_detail(crop, self.root / "zoomed", prov)
        original_pts = np.array([[0, 0, 1], [720, 150, 1], [1200, 780, 1]])
        mapped = original_pts @ np.array(result["original_to_page"]).T
        np.testing.assert_allclose(mapped, [[40, 60, 1], [520, 160, 1], [840, 580, 1]])
        poly = [[210, 270], [930, 270], [930, 420], [210, 420]]
        page_poly = regions._page_polygon({"route": "image", "polygon": poly, "provenance": prov})
        self.assertTrue(page_poly.equals(Polygon([(180, 240), (660, 240), (660, 340), (180, 340)])))
        self.assertEqual(hashlib.sha256(crop.read_bytes()).hexdigest(), result["original_crop"]["sha256"])

    def test_invalid_or_fractional_provenance_refuses_without_outputs(self):
        good = {"source_id": "s", "page": 1, "crop_bbox": [40, 60, 840, 580], "render_zoom": 1}
        for bad in ([good], {}, dict(good, page=True), dict(good, render_zoom=float("nan")),
                    dict(good, crop_bbox=[40.25, 60, 840.25, 580]), dict(good, render_zoom=2)):
            with self.subTest(provenance=bad):
                out = self.root / "invalid-provenance"
                with self.assertRaises(ValueError):
                    scan_detail.suggest_detail(self.root / "rectangle.png", out, bad)
                self.assertFalse(out.exists())

    def test_aliases_cannot_overwrite_original_or_other_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / "cleaned.png"
            original.write_bytes((self.root / "rectangle.png").read_bytes())
            before = original.read_bytes()
            with self.assertRaises(SystemExit):
                scan_detail.suggest_detail(original, root)
            self.assertEqual(original.read_bytes(), before)
            out = root / "hardlink"
            out.mkdir()
            os.link(original, out / "cleaned.png")
            with self.assertRaises(SystemExit):
                scan_detail.suggest_detail(original, out)
            self.assertEqual(original.read_bytes(), before)
            other = root / "linked-outputs"
            other.mkdir()
            (other / "cleaned.png").write_bytes(before)
            os.link(other / "cleaned.png", other / "suggestions.png")
            with self.assertRaises(SystemExit):
                scan_detail.suggest_detail(original, other)
            self.assertEqual((other / "cleaned.png").read_bytes(), before)
            protected = root / "protected-provenance"
            protected.mkdir()
            provenance = protected / "suggestions.json"
            content = '{"source_id": "s", "page": 1, "crop_bbox": [0, 0, 800, 520], "render_zoom": 1}'
            provenance.write_text(content, encoding="utf-8")
            with self.assertRaises(SystemExit):
                scan_detail.main(["--crop", str(original), "--out-dir", str(protected),
                                  "--provenance", str(provenance)])
            self.assertEqual(provenance.read_text(encoding="utf-8"), content)

    def test_cli_supports_unicode_and_leaves_original_unchanged(self):
        root = self.root / "détails space"
        root.mkdir()
        original = root / "counter.png"
        original.write_bytes((self.root / "rectangle.png").read_bytes())
        run = subprocess.run([sys.executable, str(SKILL / "scripts" / "scan_detail.py"),
            "--crop", str(original), "--out-dir", str(root / "output")], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("unreviewed", run.stdout)
        self.assertEqual(original.read_bytes(), (self.root / "rectangle.png").read_bytes())

    def test_unreadable_file_refuses_without_outputs(self):
        bad = self.root / "not-an-image.png"
        bad.write_text("not an image", encoding="utf-8")
        out = self.root / "bad-image-output"
        with self.assertRaises(ValueError):
            scan_detail.suggest_detail(bad, out)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
