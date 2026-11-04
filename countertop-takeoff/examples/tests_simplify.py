# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1", "shapely==2.2.0"]
# ///
"""Bounded SIMPLIFY regressions; run with uv run examples/tests_simplify.py."""
import json
import io
import hashlib
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from shapely.geometry import Polygon

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import calibrate
import cad_input
import audit_pack
import estimate
import image_measure
import intake
import measure
import proposal
import pymupdf
from audit import Audit, audit_region_checks


class SimplifyRegressions(unittest.TestCase):
    def test_pricing_manifest_aliases_preserve_inputs(self):
        for command in ("estimate", "proposal"):
            for linked in (False, True):
                with self.subTest(command=command, linked=linked), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    results, rates, est, out = [root / name for name in
                                              ("results.json", "rates.json", "estimate.json", "out.json")]
                    results.write_text(json.dumps({"run_status": "complete", "assembly_boq": [
                        {"assembly_id": "counter", "type": "A", "ea": 2}]}), encoding="utf-8")
                    rates.write_text(json.dumps({"currency": "USD", "rates": [{"item_code": "A", "match": {"assembly_kind": "A"},
                                                           "uom": "EA", "unit_price": 10}]}), encoding="utf-8")
                    if command == "proposal":
                        with redirect_stdout(io.StringIO()):
                            estimate.build_estimate(str(results), str(rates), out_json=str(est))
                    manifest = Path(str(results) + ".artifacts.json")
                    manifest.unlink(missing_ok=True)
                    if linked:
                        os.link(rates, manifest)
                        profile = rates
                    else:
                        manifest.write_bytes(rates.read_bytes())
                        profile = manifest
                    protected = {p: p.read_bytes() for p in (results, rates, manifest)}
                    out.write_text("previous output", encoding="utf-8")
                    with redirect_stdout(io.StringIO()), self.assertRaisesRegex(SystemExit, "artifact manifest.*aliases"):
                        if command == "estimate":
                            estimate.build_estimate(str(results), str(profile), out_json=str(out))
                        else:
                            proposal.build_proposal(str(results), str(est), str(profile), out_json=str(out))
                    self.assertTrue(all(p.read_bytes() == content for p, content in protected.items()))
                    self.assertEqual(out.read_text(), "previous output")

    def test_receipt_manifest_aliases_preserve_evidence(self):
        for target in ("results", "receipt"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                results = Path(tmp) / "results.json"
                receipt = Path(str(results) + ".receipt.json")
                payload = {"run_status": "complete"}
                results.write_text(json.dumps(payload), encoding="utf-8")
                receipt.write_text("previous receipt", encoding="utf-8")
                os.link(results if target == "results" else receipt, str(results) + ".artifacts.json")
                original = {p: p.read_bytes() for p in (results, receipt)}
                with self.assertRaisesRegex(SystemExit, "artifact manifest.*aliases"):
                    audit_pack.record_receipt(payload, str(results), "human:test", "approved", "", tmp)
                self.assertTrue(all(p.read_bytes() == content for p, content in original.items()))

    def test_audit_pack_prefers_results_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job, other, pack = root / "job", root / "other", root / "pack"
            job.mkdir()
            other.mkdir()
            for folder, width in ((job, 160), (other, 240)):
                with pymupdf.open() as doc:
                    doc.new_page(width=width, height=100)
                    doc.save(str(folder / "plans.pdf"))
            result = {"sources": [{"source_id": "plans", "path": "plans.pdf"}], "regions": [
                {"region_id": "counter", "source_id": "plans", "page": 1, "viewport": "main",
                 "status": "unresolved", "unresolved_reason": "boundary unavailable"}]}
            previous = os.getcwd()
            try:
                os.chdir(other)
                with redirect_stdout(io.StringIO()):
                    audit_pack.render_pack(result, str(pack), 1, base_dir=str(job))
                png, = pack.glob("*_full.png")
                self.assertEqual(pymupdf.Pixmap(str(png)).width, 160)
                self.assertEqual(audit_pack.resolve_from("plans.pdf", str(root / "missing")), "plans.pdf")
            finally:
                os.chdir(previous)

    def test_proposal_package_unknown_ea_stays_blank(self):
        cases = (((None,), None), ((2, None), None), ((None, 2), None), ((0,), 0), ((2, 3), 5))
        for quantities, expected in cases:
            with self.subTest(quantities=quantities), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                results, rates, est = [root / name for name in ("results.json", "rates.json", "estimate.json")]
                results.write_text(json.dumps({"run_status": "complete_with_callouts", "assembly_boq": [
                    {"assembly_id": str(i), "type": "A", "ea": qty, "package": "millwork"}
                    for i, qty in enumerate(quantities)]}), encoding="utf-8")
                rates.write_text(json.dumps({"currency": "USD", "rates": [{"item_code": "A", "match": {"assembly_kind": "A"},
                                                       "uom": "EA", "unit_price": 10}]}), encoding="utf-8")
                with redirect_stdout(io.StringIO()):
                    estimate.build_estimate(str(results), str(rates), out_json=str(est))
                    payload = proposal.build_proposal(str(results), str(est), str(rates),
                        out_json=str(root / "proposal.json"), out_md=str(root / "proposal.md"),
                        out_pdf=str(root / "proposal.pdf"))
                self.assertEqual(payload["packages"][0]["ea_total"], expected)
                self.assertEqual(json.loads((root / "proposal.json").read_text())["packages"][0]["ea_total"], expected)
                shown = estimate.BLANK if expected is None else str(expected)
                md = (root / "proposal.md").read_text(encoding="utf-8")
                self.assertIn(f"| millwork | {len(quantities)} | {shown} |", md)
                with pymupdf.open(str(root / "proposal.pdf")) as doc:
                    text = "".join(page.get_text() for page in doc)
                self.assertIn(f"millwork | {len(quantities)} | {estimate.plain_text(shown)} |", " ".join(text.split()))

    def test_repeated_calibration_segments_withhold_locally(self):
        page = {"words": [{"id": 0, "t": "10'"}, {"id": 1, "t": "20'"}],
                "segments": [dict(id=i, x0=0, y0=i * 20, x1=length, y1=i * 20)
                             for i, length in enumerate((100, 200))]}
        for repeated in ((True, False), (True, True)):
            with self.subTest(repeated=repeated):
                entries = [{"page": 1, "viewport": viewport, "spans": [
                    {"word_ids": [i], "seg_ids": [i, i] if duplicate else [i]}
                    for i, duplicate in enumerate(repeated if viewport == "bad" else (False, False))]}
                    for viewport in ("bad", "good")]
                cals, errors = calibrate.build_calibrations(entries, {("plans", 1): page}, "plans")
                self.assertEqual(set(cals), {("plans", 1, "good")})
                self.assertEqual(cals[("plans", 1, "good")]["factor_pt_per_ft"], 10)
                self.assertEqual(len(errors), 1)
                self.assertIn("repeated segment ids", errors[0][1])

    def test_survey_feet_preserve_physical_area(self):
        name, factor, verified, warning = cad_input.resolve_units(
            SimpleNamespace(header={"$INSUNITS": 20}), None)
        self.assertEqual(name, "us_survey_ft")
        self.assertTrue(verified)
        self.assertIsNone(warning)
        # A five-survey-foot square, independently converted through metres.
        expected = (5 * (1200 / 3937) / .3048) ** 2
        self.assertAlmostEqual(25 / factor ** 2, expected, places=9)
        self.assertLess(abs(25 / factor ** 2 - 25), .001)

    def test_cad_full_circles_and_wrapped_arcs(self):
        for start, end, ccw, sweep in ((0, 2 * math.pi, True, 2 * math.pi),
                                     (1, 1 - 2 * math.pi, False, -2 * math.pi),
                                     (3 * math.pi / 2, math.pi / 2, True, math.pi),
                                     (math.pi / 2, 0, False, -math.pi / 2)):
            with self.subTest(start=start, end=end, ccw=ccw):
                edges = []
                cad_input.arc_segments((0, 0), 2, start, end, None,
                                       lambda a, b: edges.append((a, b)), ccw=ccw)
                self.assertTrue(all(math.dist(a, b) > 0 for a, b in edges))
                area = sum(a[0] * b[1] - b[0] * a[1] for a, b in edges) / 2
                self.assertLessEqual(abs(area - 2 * sweep) / abs(2 * sweep), cad_input.ARC_AREA_TOL)
                if abs(sweep) == 2 * math.pi:
                    ring = Polygon([a for a, b in edges])
                    self.assertTrue(ring.is_valid)
                    self.assertLessEqual(abs(ring.area - 4 * math.pi) / (4 * math.pi), cad_input.ARC_AREA_TOL)

    def test_recheck_a_then_b_withholds_locally(self):
        self._assert_multiple_rechecks_complete(("A", "B"))

    def test_recheck_b_then_a_withholds_locally(self):
        self._assert_multiple_rechecks_complete(("B", "A"))

    def _assert_multiple_rechecks_complete(self, order):
        for b_area in (10, 14):
            with self.subTest(order=order, b_area=b_area), tempfile.TemporaryDirectory() as tmp:
                areas = {"base": 10, "healthy": 5, "A": 12, "B": b_area}
                rows = []
                for i, rid in enumerate(("base", "healthy", *order)):
                    x = i * 20
                    rows.append({"region_id": rid, "source_id": "plans", "page": 1,
                                 "viewport": "main", "kind": "base" if i < 2 else "recheck",
                                 "of": "base" if i >= 2 else None, "type": "A", "variant": None,
                                 "area_sf": areas[rid], "expected_sf_range": [0, 20],
                                 "expected_range_ok": True, "gross_area_policy": "gross",
                                 "factor_pt_per_ft": 1,
                                 "polygon": [(x, 0), (x + 10, 0), (x + 10, 1), (x, 1)],
                                 "boundary_seg_ids": list(range(4 * i, 4 * i + 4))})
                bases = rows[:2]
                spec = {"_sources": [{"source_id": "plans", "path": "plans.pdf", "sha256": "0" * 64}],
                        "geometry": {}, "mode": "individual_rooms", "policy": {"gross_area": "gross"},
                        "scope": {"pages": [{"page": 1, "disposition": "measured",
                                             "expected_regions": [r["region_id"] for r in bases]}]},
                        "_assemblies": [{"assembly_id": r["region_id"], "type": "A", "package": "base",
                                         "pieces": [r["region_id"]], "quantity_basis": {"mode": "enumerated"}}
                                        for r in bases],
                        "_pieces": [{"piece_id": r["region_id"], "assembly_id": r["region_id"],
                                     "region_id": r["region_id"], "route": "geometry"} for r in bases]}
                audit = Audit()
                audit_region_checks(spec, rows, {("plans", 1, "main"): {"factor_pt_per_ft": 1}}, audit)
                self.assertEqual(rows[0]["status"], "unresolved")
                self.assertIsNone(rows[0]["area_sf"])
                self.assertEqual(rows[0]["measured_area_sf"], 10)
                self.assertTrue(any(c["scope"] == "region base" for c in audit.callouts))
                if areas[order[0]] != 10:
                    dependent = [c for c in audit.callouts if c["scope"] == f"recheck {order[1]}"]
                    self.assertEqual(len(dependent), 1)
                    self.assertEqual(dependent[0]["blank_fields"], ["recheck_deviation"])
                    self.assertIn("excluded from QA", dependent[0]["reason"])
                output = Path(tmp) / "results.json"
                args = measure.parse_args(["unused.json", "--json", str(output)])
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(measure.finish(spec, {}, {}, audit, rows, 2, args, None), 0)
                result = json.loads(output.read_text(encoding="utf-8"))
                regions = {r["region_id"]: r for r in result["regions"]}
                pieces = {p["piece_id"]: p for p in result["piece_boq"]}
                assemblies = {a["assembly_id"]: a for a in result["assembly_boq"]}
                self.assertIsNone(regions["base"]["area_sf"])
                self.assertIsNone(pieces["base"]["extension_sf"])
                self.assertIsNone(assemblies["base"]["extended_sf"])
                self.assertEqual(regions["healthy"]["area_sf"], 5)
                self.assertEqual(pieces["healthy"]["extension_sf"], 5)
                self.assertEqual(assemblies["healthy"]["extended_sf"], 5)
                self.assertEqual(result["totals"]["project_sf"], 5)
                self.assertFalse(result["totals"]["project_sf_complete"])
                self.assertEqual(result["run_status"], "complete_with_callouts")
                self.assertFalse(audit.failed)

    def test_conflict_ids_withhold_only_affected_regions(self):
        id_pairs = [("left", "right"), ("men's vanity", "women's vanity"),
                    ("kitchen and bath", "pantry and sink")]
        for route in ("vector", "image"):
            for conflict, offset in (("duplicate", 0), ("overlap", .5), ("separate", 1.5)):
                for ids in id_pairs:
                    with self.subTest(route=route, conflict=conflict, ids=ids), tempfile.TemporaryDirectory() as tmp:
                        rows = []
                        for i, (rid, x) in enumerate(zip((*ids, "healthy"), (0, offset, 3))):
                            polygon = [(x, 0), (x + 1, 0), (x + 1, 1), (x, 1)]
                            rows.append({"region_id": rid, "source_id": "plans", "page": 1,
                                         "viewport": "main", "kind": "base", "type": "A", "variant": None,
                                         "route": route, "area_sf": 1, "expected_sf_range": [.9, 1.1],
                                         "expected_range_ok": True, "gross_area_policy": "gross",
                                         "factor_pt_per_ft": 1, "polygon": polygon,
                                         "boundary_seg_ids": list(range(4 * i, 4 * i + 4))})
                            if route == "image":
                                rows[-1].update(polygon=[(a * 2, b * 2) for a, b in polygon],
                                                factor_px_per_ft=2, image_quality={"usable": True},
                                                provenance={"crop_bbox": [0, 0, 10, 10], "render_zoom": 2})
                        if conflict == "duplicate":
                            rows[1]["boundary_seg_ids"] = rows[0]["boundary_seg_ids"][:]
                        spec = {"_sources": [{"source_id": "plans", "path": "plans.pdf", "sha256": "0" * 64}],
                                "geometry": {}, "mode": "individual_rooms", "policy": {"gross_area": "gross"},
                                "scope": {"pages": [{"page": 1, "disposition": "measured",
                                                     "expected_regions": [r["region_id"] for r in rows]}]},
                                "_assemblies": [{"assembly_id": r["region_id"], "type": "A", "package": "base",
                                                 "pieces": [r["region_id"]], "quantity_basis": {"mode": "enumerated"}}
                                                for r in rows],
                                "_pieces": [{"piece_id": r["region_id"], "assembly_id": r["region_id"],
                                             "region_id": r["region_id"], "route": "geometry"} for r in rows]}
                        audit = Audit()
                        audit_region_checks(spec, rows, {("plans", 1, "main"): {"factor_pt_per_ft": 1}}, audit)
                        output = Path(tmp) / "results.json"
                        args = measure.parse_args(["unused.json", "--json", str(output)])
                        with redirect_stdout(io.StringIO()):
                            self.assertEqual(measure.finish(spec, {}, {}, audit, rows, 3, args, None), 0)
                        result = json.loads(output.read_text(encoding="utf-8"))
                        withheld = conflict != "separate"
                        pieces = {p["piece_id"]: p for p in result["piece_boq"]}
                        assemblies = {a["assembly_id"]: a for a in result["assembly_boq"]}
                        for row in result["regions"]:
                            piece, assembly = pieces[row["region_id"]], assemblies[row["region_id"]]
                            affected = withheld and row["region_id"] in ids
                            self.assertEqual(row["area_sf"], None if affected else 1)
                            self.assertEqual(piece["sf"], None if affected else 1)
                            self.assertEqual(piece["extension_sf"], None if affected else 1)
                            self.assertEqual(assembly["extended_sf"], None if affected else 1)
                            if affected:
                                self.assertEqual(row["status"], "unresolved")
                                self.assertEqual(row["measured_area_sf"], 1)
                                self.assertTrue(row["blank_fields"])
                        self.assertEqual(result["totals"]["project_sf"], 1 if withheld else 3)
                        self.assertEqual(result["totals"]["known_subtotal_sf"], 1 if withheld else 3)
                        self.assertEqual(result["totals"]["piece_view_sf"], 1 if withheld else 3)
                        self.assertEqual(result["totals"]["assembly_view_sf"], 1 if withheld else 3)
                        self.assertEqual(result["totals"]["project_sf_complete"], not withheld)
                        self.assertEqual(result["run_status"], "complete_with_callouts" if withheld else "complete")
                        self.assertFalse(audit.failed)

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
