# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1", "shapely==2.2.0"]
# ///
"""Bounded SIMPLIFY regressions; run with uv run examples/tests_simplify.py."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import calibrate
import image_measure
import measure
from audit import Audit


class SimplifyRegressions(unittest.TestCase):
    def test_vector_zero_label_withholds_locally(self):
        page = {"words": [{"id": i, "t": t} for i, t in enumerate(['0"', "2'", "3'"])],
                "segments": [{"id": i, "x0": 0, "y0": i, "x1": n, "y1": i}
                             for i, n in enumerate([100, 100, 150])]}
        span = lambda i: {"word_ids": [i], "seg_ids": [i]}
        for override in (None, 2.0):
            with self.subTest(real_ft=override):
                zero = span(0)
                if override is not None:
                    zero["real_ft"] = override
                entries = [{"page": 1, "viewport": "bad", "spans": [zero, span(1)]},
                           {"page": 1, "viewport": "good", "spans": [span(1), span(2)]}]
                callouts = []
                cals, errors = calibrate.build_calibrations(
                    entries, {("plans", 1): page}, "plans",
                    on_error=lambda key, msg: callouts.append((key, msg)))
                self.assertEqual(set(cals), {("plans", 1, "good")})
                self.assertEqual(cals[("plans", 1, "good")]["factor_pt_per_ft"], 50)
                self.assertEqual(errors, callouts)
                self.assertEqual(len(errors), 1)
                spec = {"_sources": [{"source_id": "plans"}], "regions": [
                    {"region_id": "bad", "page": 1, "viewport": "bad", "type": "A"}]}
                rows = measure.measure_all_regions(spec, {("plans", 1): page}, cals, .05, Audit(), ".")
                self.assertEqual(rows[0]["status"], "unresolved")
                self.assertIsNone(rows[0]["area_sf"])

    def test_image_zero_label_is_unusable(self):
        for override in (None, 2.0):
            with self.subTest(real_ft=override):
                zero = {"label": '0"', "p1": [0, 0], "p2": [100, 0]}
                if override is not None:
                    zero["real_ft"] = override
                result = image_measure.measure_from_points(
                    [zero, {"label": "3'", "p1": [0, 10], "p2": [150, 10]}],
                    [{"px": p} for p in ([0, 0], [100, 0], [100, 100], [0, 100])])
                self.assertFalse(result["quality"]["usable"])
                self.assertEqual(result["anchor_independence"]["usable_anchors"], 1)
                self.assertTrue(result["warnings"])


if __name__ == "__main__":
    unittest.main()
