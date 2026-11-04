# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1", "shapely==2.2.0"]
# ///
"""Bounded SIMPLIFY regressions; run with uv run examples/tests_simplify.py."""
import json
import io
import hashlib
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
import pymupdf
from audit import Audit, audit_region_checks


class SimplifyRegressions(unittest.TestCase):
    def test_image_route_recovery_and_qa(self):
        with tempfile.TemporaryDirectory() as tmp:
            crop = Path(tmp) / "crop.png"
            doc = pymupdf.open()
            doc.new_page(width=300, height=300).get_pixmap().save(str(crop))
            doc.close()
            def region(rid, x, zoom, edit):
                points = [{"px": [a * zoom, b * zoom]} for a, b in
                          ((0, 0), (50, 0), (50, 50), (0, 50))]
                if edit == "collinear":
                    points = [{"px": [n, n]} for n in (0, 50, 100)]
                m = image_measure.measure_from_points([
                    {"label": "1'", "p1": [0, 0], "p2": [50 * zoom, 0]},
                    {"label": "2'", "p1": [0, 10], "p2": [100 * zoom, 10]}], points)
                m.update(crop=str(crop), crop_sha256=hashlib.sha256(crop.read_bytes()).hexdigest(),
                         overlay=str(Path(tmp) / f"{rid}.overlay.png"), provenance={"source_id": "plans", "page": 1,
                         "crop_bbox": [x, 0, x + 300, 300], "render_zoom": zoom})
                image_measure.render_overlay(str(crop), m, m["overlay"])
                if edit == "collinear":
                    self.assertIsNone(m["area_sf"])
                    self.assertTrue(m["warnings"])
                    m.update(area_sf=0, warnings=[])  # also reject old zero-area artifacts
                if isinstance(edit, dict):
                    m.update(edit)
                path = Path(tmp) / f"{rid}.json"
                path.write_text(edit if edit in ("{", "[]") else json.dumps(m), encoding="utf-8")
                return {"region_id": rid, "route": "image", "source_id": "plans", "page": 1,
                        "type": "A", "image_measurement": str(path), "expected_sf_range": [0, 2]}
            cases = [("separate", 100, 2, None, 0), ("duplicate", 0, 2, None, 2),
                     ("overlap", 25, 2, None, 2), ("json", 100, 1, "{", 1),
                     ("shape", 100, 1, "[]", 1), ("collinear", 100, 1, "collinear", 1)]
            cases += [(str(v), 100, 1, {"area_sf": v}, 1) for v in (None, 0, -1, "bad", float("nan"))]
            for name, x, zoom, edit, blanks in cases:
                with self.subTest(case=name):
                    spec = {"_sources": [{"source_id": "plans"}], "regions": [
                        region("healthy", 0, 1, None), region("affected", x, zoom, edit)]}
                    audit = Audit()
                    rows = measure.measure_all_regions(spec, {("plans", 1): {}}, {}, .05, audit, tmp)
                    audit_region_checks(spec, rows, {}, audit)
                    self.assertEqual(sum(r["area_sf"] is None for r in rows), blanks)
                    self.assertEqual(len(audit.callouts), blanks)
                    self.assertTrue(all(r["status"] == "unresolved" and r["blank_fields"]
                                        for r in rows if r["area_sf"] is None))
                    if blanks < 2:
                        self.assertEqual(rows[0]["area_sf"], 1)
                    self.assertFalse(audit.failed)
                    if name == "separate":
                        for bad in (dict(area_sf=0), dict(image_quality={"usable": False})):
                            broken, qa = dict(rows[1], **bad), Audit()
                            audit_region_checks(spec, [broken], {}, qa)
                            self.assertIsNone(broken["area_sf"])
                            self.assertEqual(len(qa.callouts), 1)

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
