# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1", "shapely==2.2.0"]
# ///
"""Bounded SIMPLIFY regressions; run with uv run examples/tests_simplify.py."""
import json
import io
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stderr

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import calibrate
import estimate
import image_measure
import intake
import measure
from audit import Audit


class SimplifyRegressions(unittest.TestCase):
    def test_cad_seed_margin_is_physical(self):
        for units, factor in (("in", 12), ("mm", 304.8), ("ft", 1), ("m", .3048)):
            with self.subTest(units=units):
                points = [(0, 0), (factor, 0), (factor, factor), (0, factor)]
                page = {"segments": [dict(id=i, x0=a[0], y0=a[1], x1=b[0], y1=b[1])
                        for i, (a, b) in enumerate(zip(points, points[1:] + points[:1]))]}
                spec = {"_sources": [{"source_id": "cad"}], "policy": {"gross_area": "gross"},
                        "regions": [{"region_id": str(inset), "page": 1, "type": "A",
                                     "seed": [inset * factor, factor / 2],
                                     "boundary": {"seg_ids": [0, 1, 2, 3]},
                                     "expected_sf_range": [.99, 1.01]}
                                    for inset in (-.02, 0, .005, .01, .02)]}
                audit = Audit()
                rows = measure.measure_all_regions(spec, {("cad", 1): page},
                    {("cad", 1, "main"): {"factor_pt_per_ft": factor, "units": units}}, .05, audit, ".")
                self.assertTrue(all(r["area_sf"] is None and r["status"] == "unresolved"
                                    for r in rows[:-1]))
                self.assertEqual(rows[-1]["area_sf"], 1)
                self.assertEqual(len(audit.callouts), 4)
                self.assertFalse(audit.failed)

    def test_seed_margin_withholds_only_affected_regions(self):
        points = [(0, 0), (10, 0), (10, 10), (0, 10)]
        page = {"segments": [{"id": i, "x0": a[0], "y0": a[1], "x1": b[0], "y1": b[1]}
                             for i, (a, b) in enumerate(zip(points, points[1:] + points[:1]))]}
        spec = {"_sources": [{"source_id": "plans"}], "policy": {"gross_area": "gross"}, "regions": [
            {"region_id": str(x), "page": 1, "type": "A", "seed": [x, 5],
             "boundary": {"seg_ids": [0, 1, 2, 3]}, "expected_sf_range": [0.9, 1.1]}
            for x in (0, -0.02, 0.005, 0.01, 0.02)]}
        audit = Audit()
        rows = measure.measure_all_regions(spec, {("plans", 1): page},
            {("plans", 1, "main"): {"factor_pt_per_ft": 10}}, .05, audit, ".")
        for row in rows[:-1]:
            self.assertIsNone(row["area_sf"])
            self.assertEqual(row["status"], "unresolved")
        self.assertEqual(rows[-1]["area_sf"], 1)
        self.assertEqual(len(audit.callouts), 4)
        self.assertFalse(audit.failed)

    def test_intake_legacy_pairing_and_unavailable_inputs(self):
        for flag in ("--name", "--cloud-id", "--cloud-rev"):
            for sources, values in ((["A"], ["A_ID"]), (["A", "B"], ["A_ID", "B_ID"]),
                                    (["A", "B"], ["B_ID"])):
                with self.subTest(flag=flag, sources=sources, values=values), tempfile.TemporaryDirectory() as tmp:
                    job = Path(tmp) / "job"
                    args = ["--job-dir", str(job)] + [a for s in sources for a in ("--source", str(Path(tmp) / s))]
                    args += [a for v in values for a in (flag, v)]
                    if len(sources) != len(values):
                        error = io.StringIO()
                        with redirect_stderr(error), self.assertRaisesRegex(SystemExit, "2"):
                            intake.main(args)
                        self.assertIn(f"sparse {flag} metadata", error.getvalue())
                        self.assertFalse(job.exists())
                        continue
                    args += ["--entry", json.dumps({"requested": "structured", "cloud_id": "S_ID"})]
                    self.assertEqual(intake.main(args), 0)
                    manifest = json.loads((job / "intake_manifest.json").read_text())
                    self.assertIn("unavailable_inputs", manifest["verdict"])
                    self.assertEqual(manifest["sources"][0]["cloud_id"], "S_ID")
                    key = {"--name": "name", "--cloud-id": "cloud_id", "--cloud-rev": "cloud_revision"}[flag]
                    self.assertEqual([e[key] for e in manifest["sources"][1:]], values)

    def test_standalone_rate_codes_are_nonempty_and_unique(self):
        for codes in (["SAME"] * 4, ["", "B", "C", "D"],
                      [" ", "B", "C", "D"], [1, "B", "C", "D"]):
            with self.subTest(codes=codes), tempfile.TemporaryDirectory() as tmp:
                rates = [{"item_code": code, "match": {"assembly_kind": kind},
                          "uom": "EA", "unit_price": "55.55"}
                         for code, kind in zip(codes, ("A", "B", "C", "D"))]
                path = Path(tmp) / "rates.json"
                path.write_text(json.dumps({"currency": "USD", "rates": rates}), encoding="utf-8")
                with self.assertRaisesRegex(SystemExit, "item_code"):
                    estimate.load_profile(path)

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
