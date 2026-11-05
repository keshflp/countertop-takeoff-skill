# /// script
# requires-python = ">=3.13"
# dependencies = ["pymupdf==2.1", "shapely==2.2.0"]
# ///
"""Evidence navigation and supplied-rate contracts; no recognition benchmark."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import unquote

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import audit_pack
import estimate
import measure
import proposal
import pymupdf
import spec_schema
from test_support import sh, sha256


class ApplicationViewTests(unittest.TestCase):
    def test_measured_prototypes_keep_earned_ea_and_selection_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf, geo, job, out = [root / n for n in ("plans (issued).pdf", "geometry.json", "job.json", "results.json")]
            sh(str(SKILL / "examples/make_fixture.py"), "--out", str(pdf))
            sh(str(SKILL / "scripts/extract_geometry.py"), str(pdf), "--pages", "all", "--out", str(geo))
            spec = json.loads((SKILL / "examples/fixture.jobs.json").read_text())
            spec["source"]["pdf"], spec["geometry"] = str(pdf), str(geo)
            spec["assemblies"], spec["pieces"] = [], []
            for name in ("A", "B"):
                ids = [r["region_id"] for r in spec["regions"] if r["type"] == name]
                spec["assemblies"].append({"assembly_id": name, "type": name, "package": "millwork",
                    "quantity_basis": {"mode": "room_type_count", "type": name},
                    "pieces": ids})
                spec["pieces"] += [{"piece_id": rid, "assembly_id": name, "route": "geometry", "region_id": rid}
                                   for rid in ids]
            job.write_text(json.dumps(spec), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(measure.main([str(job), "--json", str(out)]), 0)
            result = json.loads(out.read_text())
            self.assertEqual(result["totals"]["known_subtotal_sf"], 168.75)
            self.assertEqual([a["ea"] for a in result["assembly_boq"]], [3, 2])
            self.assertEqual(result["assembly_boq"][0]["quantity_basis"], spec["assemblies"][0]["quantity_basis"])
            result["_results_path"] = str(out)
            before, original = copy.deepcopy(result), out.read_bytes()
            pack = root / "review pack"
            with redirect_stdout(io.StringIO()):
                audit_pack.render_pack(result, str(pack), 1, base_dir=str(root))
            md = (pack / "index.md").read_text(encoding="utf-8")
            for text in ("Detail application and count evidence", "room_type_count", "A:kitchen", "selected word boxes in results",
                         "seg_ids", "104", "112", "Recorded room tags", "| 3 | measured; EA resolved"):
                self.assertIn(text, md)
            self.assertIn(sha256(pdf), md)
            self.assertIn("plans%20%28issued%29.pdf", md)
            self.assertIn("property quantities complete: False", md)
            self.assertEqual(result, before)
            self.assertEqual(out.read_bytes(), original)
            links = [s.split("](", 1)[1].split(")", 1)[0] for s in md.split("[")[1:] if "](" in s]
            self.assertTrue(links)
            self.assertTrue(all((pack / unquote(target)).exists() for target in links))

    def result(self):
        return {"sources": [{"source_id": "plans", "path": "plan one.pdf", "sha256": "a" * 64},
                            {"source_id": "specs", "path": "spec.pdf", "sha256": "b" * 64}],
                "schedule": {"source_id": "plans", "page": 1, "types": [{"type": "A", "count": 12, "row_text": "A | 12"}],
                    "variants": [{"type": "A", "name": "ADA", "count": 2, "row_text": "ADA 2", "included_in_parent_total": True,
                                  "count_cells": [{"row": 2, "col": "TOTAL"}]}],
                    "room_inventory": {"rooms": [{"room": "101", "type": "A", "page": 2},
                        {"room": "102", "type": "A", "variant": "ADA", "page": 2}],
                        "dedupe_notes": ["101 also appears in the enlargement; one inventory entry."]}},
                "assembly_boq": [{"assembly_id": "typical", "type": "A", "variant": None, "handing": "RH", "room": None,
                    "quantity_basis": {"mode": "room_type_count", "type": "A"}, "ea": None, "ea_state": "unresolved",
                    "basis": "schedule count unsupported", "state": "unresolved", "pieces": ["top"], "quantity_complete": False},
                    {"assembly_id": "ADA", "type": "A", "variant": "ADA", "room": "102", "ea": 1,
                     "quantity_basis": {"mode": "enumerated"}, "state": "measured", "pieces": ["stated"]},
                    {"assembly_id": "excluded", "type": "GR", "ea": 1, "state": "package_excluded", "pieces": ["missing"]}],
                "piece_boq": [{"piece_id": "top", "route": "geometry", "region_id": "crop", "source_links": {}},
                    {"piece_id": "stated", "route": "stated", "source_links": {"depth": {"source_id": "specs", "page": 2,
                        "word_ids": [37], "quoted_text": "25.5 in"}}}],
                "regions": [{"region_id": "crop", "source_id": "plans", "page": 2, "viewport": "detail", "route": "image",
                             "overlay": "crop proof.png"}, {"region_id": "unadopted-contour"}],
                "coverage_ledger": [{"item": "variant A:ADA missing detail", "state": "unresolved", "detail": "construction BLANK"}]}

    def test_withheld_count_and_unknown_room_variant_are_not_inferred(self):
        result = self.result()
        before = copy.deepcopy(result)
        md = "\n".join(audit_pack.application_lines(result, ".", {}))
        typical = next(line for line in md.splitlines() if line.startswith("| typical /"))
        self.assertIn("| BLANK | unresolved; EA unresolved; schedule count unsupported", typical)
        self.assertIn("| A / parent | 12 | parent total", md)
        self.assertIn("| A / ADA | 2 | included in parent", md)
        self.assertIn('count_cells=[{"col": "TOTAL", "row": 2}]', md)
        self.assertIn("| 101 | A | BLANK | plans p.2 |", md)
        self.assertIn("| 102 | A | ADA | plans p.2 |", md)
        self.assertIn("variant A:ADA missing detail: construction BLANK", md)
        self.assertNotIn("unadopted-contour", md)
        self.assertEqual(result, before)

    def test_sources_image_proof_exclusions_and_stated_selectors_are_visible(self):
        md = "\n".join(audit_pack.application_lines(self.result(), ".", {"crop": ["marker.png"]}))
        for text in ("a" * 64, "b" * 64, "original-pixel overlay unavailable", "specs p.2 word_ids=[37]",
                     "quoted_text=25.5 in", "package_excluded", "missing: BLANK", "typical / A / BLANK / RH"):
            self.assertIn(text, md)
        self.assertIn("source unavailable: plan one.pdf", md)

    def test_legacy_result_does_not_invent_a_quantity_basis(self):
        result = self.result()
        result["assembly_boq"][0].pop("quantity_basis")
        md = "\n".join(audit_pack.application_lines(result, ".", {}))
        self.assertIn("| room BLANK; BLANK |", md)
        result["assembly_boq"] = []
        self.assertIn("No assembly application records", "\n".join(audit_pack.application_lines(result, ".", {})))

    def test_image_schedule_preserves_crop_transform_and_source_identity(self):
        result = self.result()
        result["schedule"]["evidence"] = {"kind": "image", "crop_image": "schedule crop.png",
            "crop_sha256": "c" * 64, "crop_bbox": [10, 20, 310, 420], "render_zoom": 3, "render_rotation": 90}
        md = "\n".join(audit_pack.application_lines(result, ".", {}))
        for text in ("recorded schedule crop unavailable: schedule crop.png", "c" * 64,
                     "crop bbox [10, 20, 310, 420]", "zoom 3", "rotation 90"):
            self.assertIn(text, md)

    def test_relocated_bitmap_results_keep_the_original_schedule_crop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf, geo, job = [root / n for n in ("hotel.pdf", "hotel.geometry.json", "hotel.jobs.json")]
            sh(str(SKILL / "examples/make_fixture.py"), "--case", "hotel", "--out", str(pdf))
            sh(str(SKILL / "scripts/extract_geometry.py"), str(pdf), "--pages", "all", "--out", str(geo))
            sh(str(SKILL / "examples/make_hotel_jobs.py"), "--pdf", str(pdf), "--geometry", str(geo),
               "--out", str(job), "--workdir", str(root / "evidence"))
            original = job.read_bytes()
            out = root / "elsewhere/results.json"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(measure.main([str(job), "--json", str(out)]), 0)
            result = json.loads(out.read_text())
            evidence = result["schedule"]["evidence"]
            crop = root / "evidence/schedule_crop.png"
            self.assertEqual(Path(evidence["crop_image"]), crop)
            self.assertEqual(evidence["crop_sha256"], sha256(crop))
            result["_results_path"] = str(out)
            md = "\n".join(audit_pack.application_lines(result, str(root / "elsewhere/pack"), {}))
            self.assertIn("[recorded schedule crop](../../evidence/schedule_crop.png)", md)
            self.assertEqual(job.read_bytes(), original)
            self.assertEqual(result["totals"]["known_subtotal_sf"], 146.98)


class RateBasisTests(unittest.TestCase):
    def profile(self):
        return {"company": "Test shop", "currency": "USD", "rates": [
            {"item_code": "A", "match": {"assembly_kind": "A"}, "uom": "EA", "unit_price": 55.555,
             "rate_basis": {"source": "Shop supplied rate sheet", "date": "2026-11-04", "quote_reference": "QUOTE-42"},
             "includes": ["top", "edge"]},
            {"item_code": "ZERO", "match": {"assembly_kind": "ZERO"}, "uom": "EA", "unit_price": 0},
            *[{"item_code": code, "match": {"assembly_kind": "AMB"}, "uom": "EA", "unit_price": 10,
               "rate_basis": {"source": code}} for code in ("AMB1", "AMB2")]]}

    def results(self):
        return {"run_status": "complete_with_callouts", "assembly_boq": [
            {"assembly_id": kind, "type": kind, "ea": qty, "basis": "known count", "state": "measured"}
            for kind, qty in (("A", 3), ("ZERO", 1), ("MISSING", 2), ("AMB", 1))]}

    def test_json_markdown_pdf_and_proposal_preserve_basis_exact_rates_and_blanks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rates, results, est_json = [root / name for name in ("rates.json", "results.json", "estimate.json")]
            rates.write_text(json.dumps(self.profile()), encoding="utf-8")
            results.write_text(json.dumps(self.results()), encoding="utf-8")
            protected = {p: p.read_bytes() for p in (rates, results)}
            with redirect_stdout(io.StringIO()):
                est = estimate.build_estimate(str(results), str(rates), out_json=str(est_json),
                    out_md=str(root / "estimate.md"), out_pdf=str(root / "estimate.pdf"))
                prop = proposal.build_proposal(str(results), str(est_json), str(rates),
                    out_json=str(root / "proposal.json"), out_md=str(root / "proposal.md"), out_pdf=str(root / "proposal.pdf"))
            self.assertEqual(est["lines"], prop["lines"])
            self.assertEqual(est["lines"][0]["rate_reference"]["rate_basis"], self.profile()["rates"][0]["rate_basis"])
            self.assertEqual(est["lines"][0]["unit_price_exact"], "55.555")
            self.assertEqual([l["line_total"] for l in est["lines"]], [166.67, 0.0, None, None])
            self.assertEqual(est["priced_subtotal"], 166.67)
            self.assertIsNone(est["grand_total"])
            self.assertFalse(prop["scope_complete"])
            self.assertEqual(est["profile_sha256"], sha256(rates))
            for line in est["lines"][1:]:
                self.assertIsNone(line["rate_reference"]["rate_basis"])
            for name in ("estimate", "proposal"):
                payload = json.loads((root / (name + ".json")).read_text())
                self.assertEqual(payload["lines"], est["lines"])
                md = (root / (name + ".md")).read_text()
                with pymupdf.open(root / (name + ".pdf")) as doc:
                    pdf_text = " ".join(" ".join(p.get_text().split()) for p in doc)
                for text in ("Shop supplied rate sheet", "2026-11-04", "QUOTE-42", "55.555", "166.67", "0.00"):
                    self.assertIn(text, md)
                    self.assertIn(text, pdf_text)
                self.assertIn("source: __blank__", md)
                self.assertIn("source: BLANK", pdf_text)
                self.assertIn("top; edge", pdf_text)
            self.assertTrue(all(p.read_bytes() == content for p, content in protected.items()))

    def test_metadata_cannot_select_a_rate_or_resolve_withheld_ea(self):
        results = self.results()
        results["assembly_boq"][0]["ea"] = None
        lines, _, _, _ = estimate.build_lines(results, self.profile()["rates"])
        self.assertIsNone(lines[0]["line_total"])
        self.assertEqual(lines[0]["rate_reference"]["rate_basis"]["quote_reference"], "QUOTE-42")
        self.assertIsNone(lines[3]["item_code"])
        self.assertIsNone(lines[3]["rate_reference"]["rate_basis"])

    def test_metadata_does_not_change_a_complete_total_or_expire_an_old_rate(self):
        results = self.results()
        results["assembly_boq"] = results["assembly_boq"][:2]
        rates = self.profile()["rates"]
        baseline = estimate.build_lines(results, rates)[0]
        rates[0]["rate_basis"]["date"] = "2000-01-01"
        changed = estimate.build_lines(results, rates)[0]
        self.assertEqual(estimate.summarize(baseline), estimate.summarize(changed))
        self.assertEqual(str(estimate.summarize(changed)[1]), "166.67")
        repeat = dict(changed[0], assembly_ids=["second-room"])
        md = "\n".join(estimate.rate_basis_lines([changed[0], repeat]))
        self.assertEqual(md.count("source: Shop supplied rate sheet"), 1)

    def test_includes_display_rejects_malformed_lists_in_both_loaders(self):
        with tempfile.TemporaryDirectory() as tmp:
            for invalid in ("top", [False], [""]):
                profile = self.profile()
                profile["rates"][0]["includes"] = invalid
                with self.assertRaises(spec_schema.SpecError):
                    spec_schema.validate_rates(profile)
                path = Path(tmp) / "rates.json"
                path.write_text(json.dumps(profile), encoding="utf-8")
                with self.assertRaisesRegex(SystemExit, "includes"):
                    estimate.load_profile(str(path))

    def test_pdf_final_total_stays_with_its_qualification_and_no_trailing_blank_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            for suffix in ("123.00", "BLANK - " + "scope unresolved " * 12):
                text = "\n".join(["detail line"] * (estimate.PDF_MAX_LINES - 1)
                                 + ["GRAND TOTAL: " + suffix]) + "\n"
                path = str(Path(tmp) / "estimate.pdf")
                estimate.render_pdf(text, path)
                with pymupdf.open(path) as doc:
                    self.assertEqual(doc.page_count, 1 if suffix == "123.00" else 2)
                    self.assertIn("GRAND TOTAL:", doc[-1].get_text())

    def test_optional_null_partial_and_absent_metadata_in_both_validators(self):
        for basis in (None, {}, {"source": None}, {"quote_reference": "shop email supplied locally"}, {"date": "2024-02-29"}):
            with self.subTest(basis=basis), tempfile.TemporaryDirectory() as tmp:
                profile = self.profile()
                profile["rates"][0]["rate_basis"] = basis
                spec_schema.validate_rates(profile)
                path = Path(tmp) / "rates.json"
                path.write_text(json.dumps(profile), encoding="utf-8")
                loaded, _, _ = estimate.load_profile(str(path))
                self.assertEqual(loaded["rates"][0]["rate_basis"], basis)

    def test_malformed_metadata_refuses_consistently_without_expiry_policy(self):
        invalid = ([], "shop", {"sources": "typo"}, {"source": ""}, {"date": "2026-02-30"},
                   {"date": "20261104"}, {"date": 2026}, {"quote_reference": False})
        for basis in invalid:
            with self.subTest(basis=basis), tempfile.TemporaryDirectory() as tmp:
                profile = self.profile()
                profile["rates"][0]["rate_basis"] = basis
                with self.assertRaises(spec_schema.SpecError):
                    spec_schema.validate_rates(profile)
                path = Path(tmp) / "rates.json"
                path.write_text(json.dumps(profile), encoding="utf-8")
                with self.assertRaisesRegex(SystemExit, "rate_basis"):
                    estimate.load_profile(str(path))


if __name__ == "__main__":
    unittest.main()
