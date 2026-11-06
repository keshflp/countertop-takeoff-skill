"""Hand-packed witnesses and single-fault adversarial checks of every gate."""

from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import eval as oracle

CASES = {p.stem: json.loads(p.read_text()) for p in (Path(__file__).parent / "cases").glob("*.json")}


def case(number: int) -> dict:
    return deepcopy(next(value for key, value in CASES.items() if key.startswith(f"{number:02}-")))


def hand_layout(rects: list[tuple], placements: list[tuple], seams: list[tuple] = (),
                lower: int = 1, warnings: list | None = None) -> dict:
    """Coordinates here are explicit witnesses from each case's hand arithmetic."""
    pieces = []
    for index, (installation, x, y, w, h) in enumerate(rects, 1):
        pieces.append({"id": f"p{index}", "installationId": installation,
                       "outline": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]})
    slabs = []
    for index, (slab, x, y, rotated) in enumerate(placements, 1):
        while len(slabs) < slab:
            slabs.append({"index": len(slabs) + 1, "placements": []})
        slabs[slab - 1]["placements"].append({"pieceId": f"p{index}", "x": x, "y": y, "rotated": rotated})
    return {"ok": True, "pieces": pieces, "seams": [dict(zip(("installationId", "x0", "y0", "x1", "y1"), s)) for s in seams],
            "slabs": slabs, "slabCount": len(slabs), "lowerBound": lower, "provenOptimal": True,
            "warnings": warnings or []}


def witness(number: int) -> dict | None:
    one = [(1, 0, 0, False)]
    stack = one + [(1, 0, 25.75, False)]
    if number in (1, 4, 9, 10, 14):
        identifier = "island" if number == 4 else "perimeter"
        warnings = ["perimeter: sink leaves only 1.75 inches at an original edge; confirm with Dad."] if number == 10 else []
        return hand_layout([(identifier, 0, 0, 96, 25.5)], one, warnings=warnings)
    if number in (2, 13):
        placements = one + ([(1, 96.25, 0, False)] if number == 13 else [(1, 0, 25.75, True)])
        return hand_layout([("perimeter", 0, 0, 96, 25.5), ("perimeter", 0, 25.5, 25.5, 46.5)],
                           placements, [("perimeter", 0, 25.5, 25.5, 25.5)])
    if number == 3:
        return hand_layout([("perimeter", 0, 0, 96, 25.5), ("perimeter", 0, 25.5, 25.5, 46.5),
                            ("perimeter", 70.5, 25.5, 25.5, 46.5)],
                           one + [(1, 0, 25.75, True), (1, 46.75, 25.75, True)],
                           [("perimeter", 0, 25.5, 25.5, 25.5), ("perimeter", 70.5, 25.5, 96, 25.5)])
    if number in (5, 6):
        split = 69 if number == 6 else 90
        return hand_layout([("perimeter", 0, 0, split, 25.5), ("perimeter", split, 0, 180 - split, 25.5)],
                           stack, [("perimeter", split, 0, split, 25.5)])
    if number == 7:
        return hand_layout([("perimeter", 0, 0, 96, 25.5), ("perimeter", 70.5, 25.5, 25.5, 46.5),
                            ("island", 0, 0, 60, 25.5)],
                           one + [(1, 0, 25.75, True), (1, 46.75, 25.75, False)],
                           [("perimeter", 70.5, 25.5, 96, 25.5)])
    if number == 8:
        return hand_layout([("perimeter", 0, 0, 101.5, 25.5)], one)
    if number == 11:
        return hand_layout([(identifier, x, 0, 90, 25.5) for identifier in ("perimeter", "island") for x in (0, 90)],
                           stack + [(2, 0, 0, False), (2, 0, 25.75, False)],
                           [(identifier, 90, 0, 90, 25.5) for identifier in ("perimeter", "island")], lower=2)
    if number == 12:
        return hand_layout([("perimeter", 0, 0, 25.5, 96)], [(1, 0, 0, True)])
    if number == 15:
        return None
    if number == 16:
        return hand_layout([("perimeter", 0, 0, 30.0625, 25.5), ("island", 0, 0, 30.0625, 25.5)],
                           one + [(1, 30.3125, 0, False)])
    raise ValueError(number)


def hand_quote(number: int) -> dict:
    source = case(number)
    job, expected, layout = source["job"], source["expected"], witness(number)
    areas = {2: ["3633.75"], 3: ["4819.5"], 5: ["4590"], 6: ["4590"], 7: ["3633.75", "1530"],
             8: ["2588.25"], 11: ["4590", "4590"], 13: ["3633.75"], 16: ["766.59375", "766.59375"]}.get(number, ["2448"])
    installations = [{"id": i["id"], "label": i["label"], "areaSqIn": a, "sf": expected["installations"][i["id"]]["sf"]}
                     for i, a in zip(job["installations"], areas)]
    slab = job["material"]["slab"]
    slab_sf = None if slab is None else str(Decimal(slab["lengthIn"]) * Decimal(slab["widthIn"]) / 144)
    invoice = [{"installation": i["label"], "material": job["material"]["name"], "sf": i["sf"],
                "ratePerSf": expected["pricing"]["ratePerSf"], "amount": amount}
               for i, amount in zip(installations, expected["invoiceAmounts"])]
    return {"installations": installations, "totalSf": expected["totalSf"], "layout": layout,
            "slabCount": None if layout is None else layout["slabCount"], "slabSf": slab_sf,
            "pricing": deepcopy(expected["pricing"]), "invoice": invoice,
            "blanks": [{"field": field, "question": f"What is the {field} for this job?"} for field in expected["blanks"]],
            "assumptions": [{"setting": key, "value": str(value).lower(), "note": "assumed, confirm with Dad"}
                            for key, value in oracle.DEFAULTS.items() if key not in job["settings"]],
            "warnings": [] if layout is None else layout["warnings"], "geometryEstimates": []}


def contract_case_and_quote() -> tuple[dict, dict]:
    source = json.loads((Path(__file__).parent / "contract-cases/01-centered-estimates-count.json").read_text())
    layout = hand_layout([("counter", 0, 0, 36, 28), ("counter", 36, 0, 72, 28)],
                         [(1, 0, 0, False), (1, 0, 28.25, False)], [("counter", 36, 0, 36, 28)])
    note = source["job"]["installations"][0]["cutouts"][0]["estimate"]["note"]
    quote = hand_quote(1)
    quote.update(installations=[{"id": "counter", "label": "Counter", "areaSqIn": "3024", "sf": "21.00", "requiredPieceCount": 2}],
                 totalSf="21.00", layout=layout, pricing={"materialCost": "771.75", "materialRatePerSf": "36.75", "laborPerSf": "9.10", "ratePerSf": "45.85"},
                 invoice=[{"installation": "Counter", "material": "Synthetic quartz", "sf": "21.00", "ratePerSf": "45.85", "amount": "962.85"}],
                 geometryEstimates=[{"installationId": "counter", "cutoutIndex": 0, "fields": ["wIn", "hIn", "at"], "note": note,
                                     "xIn": 42, "yIn": 6, "wIn": 24, "hIn": 16}])
    return source, quote


class GateTests(unittest.TestCase):
    def assert_gate(self, number: int, gate: str, corrupt, *, prepare=None):
        source, quote = case(number), hand_quote(number)
        if prepare:
            prepare(source, quote)
        good = oracle.evaluate(source, quote, False)["gates"][gate]
        self.assertTrue(good["pass"], good["errors"])
        corrupt(source, quote)
        bad = oracle.evaluate(source, quote, False)["gates"][gate]
        self.assertFalse(bad["pass"], f"{gate} accepted the corrupted fixture")

    def test_all_hand_optima_and_prices(self):
        for number in range(1, 17):
            with self.subTest(number=number):
                result = oracle.evaluate(case(number), hand_quote(number), False)
                self.assertTrue(all(g["pass"] for g in result["gates"].values()), result)

    def test_centered_estimated_exact_count_witness(self):
        source, quote = contract_case_and_quote()
        result = oracle.evaluate(source, quote, False)
        self.assertTrue(all(g["pass"] for g in result["gates"].values()), result)

    def test_piece_count_is_exact_not_minimum_or_preference(self):
        source, quote = contract_case_and_quote()
        data = oracle.expand_job(source["job"])
        oracle.check_piece_counts(data, quote["layout"])
        for rects in ([('counter', 0, 0, 108, 28)],
                      [('counter', x, 0, 36, 28) for x in (0, 36, 72)]):
            corrupted = hand_layout(rects, [(i, 0, 0, False) for i in range(1, len(rects) + 1)])
            with self.subTest(count=len(rects)), self.assertRaises(ValueError):
                oracle.check_piece_counts(data, corrupted)

    def test_requested_count_survives_quantity_output_without_slab(self):
        source, quote = contract_case_and_quote()
        data = oracle.expand_job(source["job"])
        oracle.check_quantities(source["job"], data, quote, source["expected"])
        quote["installations"][0].pop("requiredPieceCount")
        with self.assertRaises(ValueError):
            oracle.check_quantities(source["job"], data, quote, source["expected"])

    def test_estimates_preserve_fields_note_identity_and_resolved_rectangle(self):
        source, quote = contract_case_and_quote()
        data = oracle.expand_job(source["job"])
        oracle.check_estimates(source["job"], data, quote)
        for key, wrong in {"fields": ["wIn"], "note": "No authorization.", "installationId": "other", "cutoutIndex": 1,
                           "xIn": 43, "yIn": 7, "wIn": 25, "hIn": 17}.items():
            bad = deepcopy(quote)
            bad["geometryEstimates"][0][key] = wrong
            with self.subTest(key=key), self.assertRaises(ValueError):
                oracle.check_estimates(source["job"], data, bad)
        quote["geometryEstimates"] = []
        with self.assertRaises(ValueError):
            oracle.check_estimates(source["job"], data, quote)

    def test_center_does_not_invent_an_estimate(self):
        source, quote = contract_case_and_quote()
        source["job"]["installations"][0]["cutouts"][0].pop("estimate")
        quote["geometryEstimates"] = []
        oracle.check_estimates(source["job"], oracle.expand_job(source["job"]), quote)
        quote.pop("geometryEstimates")
        with self.assertRaises(KeyError):
            oracle.check_estimates(source["job"], oracle.expand_job(source["job"]), quote)

    def test_numeric_and_center_geometry_agree_on_every_supported_leg(self):
        for number, legs in ((1, {"main": 48}), (2, {"back": 48, "left": 36}),
                             (7, {"back": 48, "right": 36}), (3, {"back": 48, "left": 36, "right": 36})):
            for leg, center in legs.items():
                source = case(number)["job"]
                source["installations"][0]["cutouts"] = [{"kind": "other", "wIn": 12, "hIn": 12,
                                                           "at": {"leg": leg, "centerFromStartIn": "center"}}]
                centered = oracle.expand_job(source)
                source["installations"][0]["cutouts"][0]["at"]["centerFromStartIn"] = center
                with self.subTest(shape=number, leg=leg):
                    self.assertEqual(centered, oracle.expand_job(source))

    def test_invalid_center_leg_and_off_grid_resolution_are_errors(self):
        source, _ = contract_case_and_quote()
        job = source["job"]
        job["installations"][0]["cutouts"][0]["at"]["leg"] = "left"
        with self.assertRaises(ValueError):
            oracle.expand_job(job)
        job["installations"][0]["cutouts"][0]["at"]["leg"] = "main"
        job["installations"][0]["shape"]["lengthIn"] = 108.0625
        with self.assertRaises(ValueError):
            oracle.expand_job(job)

    def test_contract_workload_does_not_turn_naive_count_failure_into_a_gain(self):
        completed = subprocess.run([sys.executable, str(Path(oracle.__file__)), "--layout-only", "--json",
                                    "--cases", str(Path(__file__).parent / "contract-cases"), "--layout-cmd",
                                    f'"{sys.executable}" "{Path(__file__).parent / "naive_layout.py"}"'],
                                   text=True, capture_output=True, timeout=10)
        self.assertEqual(completed.returncode, 1, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertFalse(report["scoreAvailable"])
        self.assertIsNone(report["score"])
        self.assertFalse(report["cases"][0]["gates"]["pieceCounts"]["pass"])

    def test_response(self):
        self.assert_gate(1, "response", lambda c, q: q["layout"].update(ok=False))

    def test_tiling(self):
        self.assert_gate(1, "tiling", lambda c, q: q["layout"]["pieces"][0].update(outline=[[0, 0], [95, 0], [95, 25.5], [0, 25.5]]))

    def test_piece_fit(self):
        self.assert_gate(1, "pieceFit", lambda c, q: q["layout"]["pieces"][0].update(outline=[[0, 0], [125, 0], [125, 62], [0, 62]]))

    def test_piece_fit_rotation_disabled(self):
        self.assert_gate(12, "pieceFit", lambda c, q: c["job"]["settings"].update(allowRotate=False))

    def test_placements_kerf(self):
        self.assert_gate(5, "placements", lambda c, q: q["layout"]["slabs"][0]["placements"][1].update(y=25.6875))

    def test_placements_bounds(self):
        self.assert_gate(1, "placements", lambda c, q: q["layout"]["slabs"][0]["placements"][0].update(x=-0.0625))

    def test_placements_rotation_disabled(self):
        self.assert_gate(13, "placements", lambda c, q: q["layout"]["slabs"][0]["placements"][1].update(rotated=True))

    def test_placements_missing_piece(self):
        self.assert_gate(5, "placements", lambda c, q: q["layout"]["slabs"][0]["placements"].pop())

    def test_seams_cutout(self):
        self.assert_gate(6, "seams", lambda c, q: q["layout"].update(
            witness(5)))

    def test_seams_threshold(self):
        self.assert_gate(6, "seams", lambda c, q: c["job"]["settings"].update(minSeamToCutoutIn=6.0625))

    def test_hidden_seam(self):
        self.assert_gate(6, "seams", lambda c, q: q["layout"].update(seams=[]))

    def test_seam_material_independent_of_seam_gate(self):
        self.assert_gate(6, "seamMaterial", lambda c, q: c["job"]["settings"].update(minMaterialBesideCutoutIn=6.0625))

    def test_warnings(self):
        self.assert_gate(10, "warnings", lambda c, q: q["layout"].update(warnings=[]))

    def test_unrelated_warning_does_not_hide_original_edge_violation(self):
        self.assert_gate(10, "warnings", lambda c, q: q["layout"].update(warnings=["Search has not proved optimality."]))

    def test_bounds(self):
        self.assert_gate(11, "bounds", lambda c, q: q["layout"].update(lowerBound=1))

    def test_false_optimality(self):
        def prepare(c, q):
            import naive_layout
            q["layout"] = naive_layout.run(oracle.expand_job(c["job"]))
        self.assert_gate(5, "bounds", lambda c, q: q["layout"].update(provenOptimal=True), prepare=prepare)

    def test_quantity(self):
        self.assert_gate(8, "quantity", lambda c, q: q["installations"][0].update(sf="17.98"))

    def test_quantity_round_total_once(self):
        self.assert_gate(16, "quantity", lambda c, q: q.update(totalSf="10.64"))

    def test_pricing(self):
        self.assert_gate(8, "pricing", lambda c, q: q["pricing"].update(materialCost="565.82"))

    def test_pricing_invoice_amount(self):
        self.assert_gate(8, "pricing", lambda c, q: q["invoice"][0].update(amount="695.97"))

    def test_repeating_slab_sf_preserves_half_cent_ties(self):
        source, quote = case(8), hand_quote(8)
        source.pop("expected")
        source["job"]["material"]["pricePerSf"] = "0.21"
        # 120*55*0.21/144 = 9.625 exactly; dividing slab SF first can produce 9.624999...
        quote["pricing"].update(materialCost="9.63", materialRatePerSf="0.54", ratePerSf="7.79")
        quote["invoice"][0].update(ratePerSf="7.79", amount="139.99")
        result = oracle.evaluate(source, quote, False)
        self.assertTrue(result["gates"]["pricing"]["pass"], result)

    def test_blanks_invented_labor(self):
        self.assert_gate(9, "blanks", lambda c, q: q["pricing"].update(laborPerSf="0.00"))

    def test_blanks_duplicate(self):
        self.assert_gate(9, "blanks", lambda c, q: q["blanks"].append(q["blanks"][0]))

    def test_assumptions(self):
        self.assert_gate(1, "assumptions", lambda c, q: q["assumptions"].pop())

    def test_each_gate_runs_after_another_fails(self):
        source, quote = case(9), hand_quote(9)
        quote["layout"]["pieces"] = []
        quote["totalSf"] = "999.00"
        quote["pricing"]["materialCost"] = "0.00"
        quote["blanks"] = []
        quote["assumptions"] = []
        result = oracle.evaluate(source, quote, False)
        for gate in ("tiling", "quantity", "pricing", "blanks", "assumptions"):
            self.assertFalse(result["gates"][gate]["pass"], gate)

    def test_malformed_layout_does_not_skip_quote_gates(self):
        quote = hand_quote(1)
        quote["layout"] = None
        result = oracle.evaluate(case(1), quote, False)
        self.assertFalse(result["gates"]["response"]["pass"])
        self.assertTrue(result["gates"]["quantity"]["pass"])
        self.assertTrue(result["gates"]["assumptions"]["pass"])

    def test_partial_answer_key(self):
        source = {"job": case(5)["job"]}
        result = oracle.evaluate(source, witness(5), True)
        self.assertIsNone(result["optimum"])
        self.assertEqual(result["excessSlabs"], 0)
        self.assertTrue(all(g["pass"] for g in result["gates"].values()))
        source = {"job": case(1)["job"], "expected": {"installations": {"perimeter": {}}}}
        result = oracle.evaluate(source, hand_quote(1), False)
        self.assertTrue(all(g["pass"] for g in result["gates"].values()))

    def test_l_u_cutout_expansion(self):
        for side, expected in (("left", {"x": 3.75, "y": 36}), ("right", {"x": 74.25, "y": 36})):
            source = case(7)["job"]
            source["installations"][0]["shape"]["side"] = side
            source["installations"][0]["cutouts"] = [{"kind": "sink", "wIn": 18, "hIn": 24,
                                                       "at": {"leg": side, "centerFromStartIn": 48}}]
            expanded = oracle.expand_job(source)["installations"][0]
            self.assertEqual(expanded["cutouts"], [{"kind": "sink", "w": 18, "h": 24, **expected}])
        source = case(3)["job"]
        source["installations"][0]["cutouts"] = [{"kind": "sink", "wIn": 30, "hIn": 18,
                                                   "at": {"leg": "back", "centerFromStartIn": 48}}]
        self.assertEqual(oracle.expand_job(source)["installations"][0]["cutouts"][0],
                         {"kind": "sink", "x": 33, "y": 3.75, "w": 30, "h": 18})

    def test_grid_is_exact(self):
        self.assertEqual(oracle.ticks(0.0625), 1)
        with self.assertRaises(ValueError):
            oracle.ticks(0.06250001)

    def test_line_count_excludes_bundle_and_node_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in {"a.py": "one\ntwo\n", "b.md": "three", "cli/takeoff.js": "ignored\n",
                                  "node_modules/dep/a.ts": "ignored\n", "cli/a.ts": "four\n", "a.json": "five\n"}.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            self.assertEqual(oracle.line_count(root), 5)

    def test_cli_json_private_partial_cases_and_failure_exit(self):
        with tempfile.TemporaryDirectory(prefix="kitchen eval ") as directory:
            root = Path(directory)
            cases = root / "cases"
            cases.mkdir()
            (cases / "private.json").write_text(json.dumps({"job": case(9)["job"]}))
            responder = root / "quote.py"
            for corrupt in (False, True):
                quote = hand_quote(9)
                if corrupt:
                    quote["totalSf"] = "100.00"
                    quote["blanks"] = []
                responder.write_text("import json\nprint(json.dumps(" + repr(quote) + "))\n")
                completed = subprocess.run([sys.executable, str(Path(oracle.__file__)), "--json",
                                            "--cases", str(cases), "--cases", str(cases), "--quote-cmd",
                                            f'"{sys.executable}" "{responder}"'],
                                           text=True, capture_output=True, timeout=10)
                self.assertEqual(completed.returncode, int(corrupt), completed.stderr)
                report = json.loads(completed.stdout)
                self.assertEqual(len(report["cases"]), 1)
                self.assertEqual(report["pass"], not corrupt)
                self.assertEqual(report["scoreAvailable"], not corrupt)
                if corrupt:
                    gates = report["cases"][0]["gates"]
                    self.assertFalse(gates["quantity"]["pass"])
                    self.assertFalse(gates["blanks"]["pass"])

    def test_pending_intake_never_runs_a_command_or_numeric_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "pending-source"
            folder.mkdir()
            (folder / "INTAKE.md").write_text("Unconfirmed source; do not calculate.")
            # An unrelated inspection result is not a case wrapper.
            (folder / "inspection.json").write_text('{"files":[]}')
            for selected in (root, folder):
                completed = subprocess.run([sys.executable, str(Path(oracle.__file__)), "--json",
                                            "--cases", str(selected), "--quote-cmd", "command-must-never-run"],
                                           text=True, capture_output=True, timeout=10)
                self.assertEqual(completed.returncode, 2, completed.stderr)
                report = json.loads(completed.stdout)
                self.assertFalse(report["pass"])
                self.assertFalse(report["scoreAvailable"])
                self.assertIsNone(report["score"])
                self.assertEqual(report["evaluatedCases"], 0)
                self.assertEqual(report["pendingCases"], 1)
                self.assertEqual(report["cases"][0]["gates"], {})
            (root / "explicit.json").write_text('{"status":"pending","reason":"facts unknown"}')
            self.assertEqual(len(oracle.discover_cases([root])), 2)

    def test_null_slab_and_pending_do_not_disqualify_valid_numeric_subset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = root / "cases"
            cases.mkdir()
            for number in (1, 15):
                (cases / f"{number}.json").write_text(json.dumps(case(number)))
            (cases / "pending.json").write_text('{"status":"pending"}')
            responder = root / "quote.py"
            responder.write_text("import json,sys\nj=json.load(sys.stdin)\nprint(json.dumps(" +
                                 repr(hand_quote(15)) + " if j['material']['slab'] is None else " +
                                 repr(hand_quote(1)) + "))\n")
            completed = subprocess.run([sys.executable, str(Path(oracle.__file__)), "--json",
                                        "--cases", str(cases), "--quote-cmd", f'"{sys.executable}" "{responder}"'],
                                       text=True, capture_output=True, timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertTrue(report["scoreAvailable"])
            self.assertEqual(report["score"], 0)
            self.assertEqual(report["evaluatedCases"], 2)
            self.assertEqual(report["pendingCases"], 1)


if __name__ == "__main__":
    unittest.main()
