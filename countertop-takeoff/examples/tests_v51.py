"""5.1 correctness regressions, run by tests_v5 after its original checks."""
import copy
import json
import os


def refused(fn):
    try:
        fn()
    except (SystemExit, Exception) as exc:
        return "alias" in str(exc).lower()
    return False


def measurement_tests(t):
    from estimate import build_estimate
    from proposal import build_proposal
    import pymupdf
    profile = os.path.join(t.BUILD, "v51.rates.json")
    json.dump(t.HOTEL_ALLMATCH_PROFILE, open(profile, "w", encoding="utf-8"))

    def hotel():
        return json.load(open(t.HOTEL_JOBS, encoding="utf-8"))

    def run_hotel(spec, tag):
        return t.run_measure(spec, tag, jobs_path=os.path.join(
            t.BUILD, "hotel", tag + ".jobs.json"))[1]

    spec = hotel()
    for a in spec["assemblies"]:
        if a["type"] == "A":
            a["quantity_basis"] = {"mode": "room_type_count", "type": "A"}
    spec["schedule"]["evidence"]["uncertain_cells"] = [1]
    res = run_hotel(spec, "v51_uncertain")
    affected = [a for a in res["assembly_boq"] if a["type"] == "A"]
    t.check("P0.1 bitmap uncertain referenced TYPE A cell withholds EA + ledger",
            affected and all(a["ea"] is None for a in affected)
            and any(e["state"] == "unresolved" and "type A" in e["item"]
                    for e in res["coverage_ledger"]))
    spec = hotel()
    for a in spec["assemblies"]:
        if a["type"] == "A":
            a["quantity_basis"] = {"mode": "room_type_count", "type": "A"}
    spec["schedule"]["variants"] = [{"type": "A", "name": "ADA", "count": 2,
        "included_in_parent_total": True, "row_text": "fabricated ADA 2",
        "word_boxes": [{"t": "2", "x0": 1, "x1": 3, "y0": 1, "y1": 3}]}]
    ada = copy.deepcopy(spec["assemblies"][0])
    ada.update(assembly_id="fake-ada", variant="ADA", pieces=[])
    ada["quantity_basis"] = {"mode": "room_type_count", "type": "A", "variant": "ADA"}
    spec["assemblies"].append(ada)
    res = run_hotel(spec, "v51_fabricated")
    t.check("P0.1 bitmap fabricated ADA evidence withholds variant + standard allocation",
            all(a["ea"] is None for a in res["assembly_boq"] if a["type"] == "A")
            and any(e["kind"] == "variant" and e["state"] == "unresolved"
                    for e in res["coverage_ledger"]))
    # Image variants may cite cells without fabricated text-word evidence.
    spec["schedule"]["variants"][0]["word_boxes"] = []
    spec["schedule"]["variants"][0]["count_cells"] = [{"row": 2, "col": "TYPE B"}]
    spec["schedule"]["evidence"]["uncertain_cells"] = [7]
    for tag, refs in (("uncertain", [{"row": 2, "col": "TYPE B"}]),
                      ("unsupported", [{"row": 99, "col": "missing ADA cell"}])):
        spec["schedule"]["variants"][0]["count_cells"] = refs
        res = run_hotel(spec, "v51_variant_" + tag)
        t.check("P0.1 image variant " + tag + " cell withholds variant + standard EA",
                res["run_status"] == "complete_with_callouts"
                and all(a["ea"] is None for a in res["assembly_boq"] if a["type"] == "A")
                and any(e["kind"] == "variant" and e["state"] == "unresolved"
                        for e in res["coverage_ledger"]))
    ev = hotel()["schedule"]["evidence"]
    crop = os.path.join(os.path.dirname(t.HOTEL_JOBS), ev["crop_image"])
    pix = pymupdf.Pixmap(crop)
    box = ev["cells"][1]["box"]
    # Inset boxes exclude grid lines: nonwhite pixels must be the cell glyph.
    dark = sum(1 for y in range(int(box[1]), int(box[3]))
               for x in range(int(box[0]), int(box[2])) if min(pix.pixel(x, y)) < 150)
    t.check("P0.1 upright crop TYPE A box contains ink; hash proves pixels only",
            dark > 5 and ev["render_rotation"] == 90 and "pixel identity only" in ev["note"])

    spec = t.mixed_v5_spec()
    spec["assemblies"][0]["pieces"].remove("p:k")
    _, res, _ = t.run_measure(spec, "v51_membership")
    p = next(p for p in res["piece_boq"] if p["piece_id"] == "p:k")
    a = next(a for a in res["assembly_boq"] if a["assembly_id"] == "fl1-a")
    rp = os.path.join(t.BUILD, "v51_membership.results.json")
    est = build_estimate(rp, profile)
    t.check("P0.2 reciprocal membership withholds SF/edges/cutouts/EA/pricing",
            all(p[k] is None for k in ("sf", "extension_sf", "edge_lf_ext", "cutouts_ea_ext"))
            and a["ea"] is None and res["totals"]["project_sf"] == 602
            and not res["totals"]["project_sf_complete"]
            and next(l for l in est["lines"] if "fl1-a" in l["assembly_ids"])["line_total"] is None)

    spec = t.mixed_v5_spec()
    spec["assemblies"] = [a for a in spec["assemblies"] if a["assembly_id"] != "fl1-a"]
    spec["pieces"] = [p for p in spec["pieces"] if p["piece_id"] != "p:k"]
    _, res, _ = t.run_measure(spec, "v51_omission")
    rp = os.path.join(t.BUILD, "v51_omission.results.json")
    ep = os.path.join(t.BUILD, "v51_omission.estimate.json")
    est = build_estimate(rp, profile, out_json=ep)
    prop = build_proposal(rp, ep, profile)
    t.check("P0.3 measured orphan region blanks grand total; proposal inherits reason",
            res["totals"]["project_sf"] == 602 and not res["totals"]["project_sf_complete"]
            and est["priced_subtotal"] > 0 and est["grand_total"] is None
            and prop["grand_total"] is None and "A:kitchen" in json.dumps(prop["callouts"]))
    for name, entries in (("unavailable input", {"unavailable_inputs": [
            {"item": "missing specifications", "detail": "source unavailable"}]}),
            ("generic unresolved ledger", {"coverage_ledger": [
                {"item": "unread scope", "kind": "region", "state": "unresolved",
                 "detail": "unknown contribution, no special room phrase"}]}),
            ("legacy unavailable source callout", {"callouts": [{"scope": "missing input",
                "reason": "source unavailable", "blank_fields": ["all quantities from this source"]}]})):
        source = copy.deepcopy(res)
        source.update(scope_incomplete=[], coverage_ledger=[], unavailable_inputs=[])
        source.update(entries)
        json.dump(source, open(rp, "w", encoding="utf-8"))
        est = build_estimate(rp, profile, out_json=ep)
        prop = build_proposal(rp, ep, profile)
        t.check("P0.3 " + name + " structurally propagates to estimate + proposal",
                est["grand_total"] is None and est["priced_subtotal"] > 0
                and not prop["scope_complete"] and prop["open_items"]
                and all("fully priced" not in p["note"] for p in prop["packages"]))
    spec["mode"] = "individual_rooms"
    spec.pop("schedule", None)
    for a in spec["assemblies"]:
        a["quantity_basis"] = {"mode": "enumerated"}
    _, res, _ = t.run_measure(spec, "v51_individual_omission")
    t.check("P0.3 individual-room orphan scope also makes project incomplete",
            not res["totals"]["project_sf_complete"]
            and any(e["item"] == "A:kitchen" and e["state"] == "unresolved"
                    for e in res["coverage_ledger"]))


def run(t):
    measurement_tests(t)
    publishing_tests(t)
    import tests_v51_documents
    tests_v51_documents.run(t)
    documentation_tests(t)


def documentation_tests(t):
    import re
    from pathlib import Path
    root = Path(t.SKILL)
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    readme = (root.parent / "README.md").read_text(encoding="utf-8")
    refs = root / "references"
    checklist = (refs / "first-run-checklist.md").read_text(encoding="utf-8")
    t.check("P1.5 first-run checklist covers supervision + a drawings-only blind exercise",
            all(term in checklist for term in ("headers", "floor totals", "zeros", "ADA",
                "Deduplicate", "Shells are countertops", "viewport", "report -> estimate ->",
                "Receipt/hash consistency", "Output paths", "only drawings", "upright",
                "transform", "cell-box preview", "independent count-cell reading")))
    t.check("P1.2/P1.5 workflow places audit/receipt before pricing/proposal + delivery",
            skill.index("### Step 5.") < skill.index("### Step 6.") < skill.index("### Step 7.")
            < skill.index("### Step 7b.") < skill.index("### Step 8.")
            and "NEVER modifies results.json" in skill)
    text = "\n".join(p.read_text(encoding="utf-8") for p in refs.glob("*.md"))
    t.check("P1.6 secondary references contain current run statuses",
            not re.search(r"`(?:ready|warning|failed)`|Overall: READY", text, re.I)
            and "complete_with_callouts" in text)
    t.check("P1.6 public total claims distinguish resolved subset from full known subtotal",
            all("123.00" in doc and "146.98" in doc for doc in (skill, readme,
                (refs / "method.md").read_text(encoding="utf-8"),
                (refs / "output-format.md").read_text(encoding="utf-8"))))
    # Replace the published URL: the former placeholder is no longer in README.
    # Check the clone command too, so each owner exercises its own URL.
    for owner in ("keshflp", "example-org", "Another.Owner"):
        url = f"https://github.com/{owner}/countertop-takeoff-skill.git"
        swapped = readme.replace("https://github.com/keshflp/countertop-takeoff-skill.git", url)
        t.check("P1.6 transfer URL assertion accepts owner " + owner,
                f"git clone {url}" in swapped and t.install_docs_ok(swapped))
    t.check("P1.6 turnkey transfer keeps clone-vs-copy and ff-only guidance",
            all(term in readme for term in ("git remote set-url origin $repoUrl",
                "WriteAllText", "git pull --ff-only", "Separately-copied skill folder",
                "does NOT update itself")))
    t.check("release version is 5.1.0", "Version **5.1.0**" in readme)


def publishing_tests(t):
    import measure
    import estimate
    import proposal
    import audit_pack
    from publish_safety import dependent_paths, aliases
    profile = os.path.join(t.BUILD, "v51.rates.json")
    jobs = os.path.join(t.BUILD, "v51_safety.jobs.json")
    rp = os.path.join(t.BUILD, "v51_safety.results.json")
    ep = os.path.join(t.BUILD, "v51_safety.estimate.json")
    json.dump(t.mixed_v5_spec(), open(jobs, "w", encoding="utf-8"))
    before = t.sha256(jobs)
    for name, output in (("same job file", jobs), ("case-insensitive job file", jobs.upper())):
        t.check("P1.1 measure rejects " + name + " without mutating input",
                refused(lambda: measure.main([jobs, "--json", output])) and t.sha256(jobs) == before)
    t.check("P1.1 canonical identity resolves dot segments and case",
            aliases(os.path.join(t.BUILD, "sub", "..", "FILE.JSON"),
                    os.path.join(t.BUILD, "file.json")))
    rc = measure.main([jobs, "--json", rp])
    estimate.build_estimate(rp, profile, out_json=ep)
    for output in ("out_md", "out_json", "out_pdf"):
        t.check("P1.1 proposal " + output + " cannot alias estimate input (case-insensitive)",
                refused(lambda: proposal.build_proposal(rp, ep, profile, **{output: ep.upper()})))
    t.check("P1.1 estimate output/output case alias rejected",
            refused(lambda: estimate.build_estimate(rp, profile, out_md=ep + ".MD",
                                                     out_pdf=ep + ".md")))
    copied_results = rp + ".copy.json"
    with open(rp, "rb") as src, open(copied_results, "wb") as dst:
        dst.write(src.read())
    t.check("P1.1 proposal cannot overwrite estimate's original results when given a copy",
            refused(lambda: proposal.build_proposal(copied_results, ep, profile, out_md=rp.upper())))
    t.check("P1.1 measure output/output case alias rejected",
            refused(lambda: measure.main([jobs, "--json", rp, "--report", rp.upper()])))
    t.check("P1.1 measure output cannot alias geometry input",
            refused(lambda: measure.main([jobs, "--json", t.mixed_v5_spec()["geometry"].upper()])))
    out = os.path.join(t.BUILD, "external-output", "proposal")
    proposal.build_proposal(rp, ep, profile, out_json=out + ".json", out_md=out + ".md",
                            out_pdf=out + ".pdf")
    payload = json.load(open(rp, encoding="utf-8"))
    original_hash = t.sha256(rp)
    audit_pack.record_receipt(payload, rp, "synthetic-reviewer", "approved", "probe", "pack")
    receipt = json.load(open(rp + ".receipt.json", encoding="utf-8"))
    t.check("P1.2 receipt after pricing leaves results/proposal hashes current",
            t.sha256(rp) == original_hash == receipt["results_sha256"]
            and proposal.load_estimate(ep, rp)["results_sha256"] == original_hash)
    empty = os.path.join(t.BUILD, "v51_empty.results.json")
    json.dump({}, open(empty, "w", encoding="utf-8"))
    t.check("P1.2 empty results payload refused a receipt",
            audit_pack.record_receipt({}, empty, "test", "approved", "", "pack") == 2
            and not os.path.exists(empty + ".receipt.json"))
    stale_case = rp + ".stale-SYNTHETIC"
    with open(stale_case, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    t.check("P1.2 receipt refuses case-aliased quarantine filename",
            audit_pack.record_receipt(payload, stale_case.upper(), "test", "approved", "", "pack") == 2)
    bad = json.load(open(jobs, encoding="utf-8"))
    bad["source"]["sha256"] = "0" * 64
    json.dump(bad, open(jobs, "w", encoding="utf-8"))
    try:
        measure.main([jobs, "--json", rp])
    except t.TakeoffError:
        pass
    t.check("P1.1 stopped integrity rerun quarantines all proposal formats + receipt",
            all(not os.path.exists(out + ext) for ext in (".json", ".md", ".pdf"))
            and not os.path.exists(rp + ".receipt.json")
            and json.load(open(rp, encoding="utf-8"))["run_status"] == "stopped")
    json.dump(t.mixed_v5_spec(), open(jobs, "w", encoding="utf-8"))
    bad_profile = os.path.join(t.BUILD, "v51_bad.rates.json")
    bad = copy.deepcopy(t.HOTEL_ALLMATCH_PROFILE)
    bad["rates"][0]["unit_price"] = "bad-price"
    json.dump(bad, open(bad_profile, "w", encoding="utf-8"))
    measure.main([jobs, "--json", rp])
    estimate.build_estimate(rp, profile, out_json=ep)
    proposal.build_proposal(rp, ep, profile, out_json=out + ".json")
    import report_out
    quarantine_events = []
    original_quarantine = report_out.quarantine_stale_export
    def inspect_quarantine(path, when):
        if not aliases(path, rp):
            diagnostic = json.load(open(rp, encoding="utf-8"))
            quarantine_events.append(diagnostic.get("run_status") == "stopped")
        return original_quarantine(path, when)
    report_out.quarantine_stale_export = inspect_quarantine
    try:
        measure.main([jobs, "--json", rp, "--estimate-profile", bad_profile,
                      "--estimate-json", ep])
    except t.TakeoffError:
        pass
    finally:
        report_out.quarantine_stale_export = original_quarantine
    diag = json.load(open(rp, encoding="utf-8"))
    t.check("P1.1 actual pricing SystemExit cleans fresh exports and prior proposals",
            diag["run_status"] == "stopped" and "bad-price" in diag["stopped_reason"]
            and not os.path.exists(ep) and not os.path.exists(out + ".json"))
    t.check("P1.1 stopped JSON exists before any dependent artifact quarantine",
            bool(quarantine_events) and all(quarantine_events))
    original = measure.run_pipeline
    for name, error in (("SystemExit", SystemExit("malformed pricing")),
                        ("unexpected exception", RuntimeError("synthetic crash"))):
        # Recreate fresh deliverables, then exercise the actual main cleanup boundary.
        measure.main([jobs, "--json", rp])
        estimate.build_estimate(rp, profile, out_json=ep)
        proposal.build_proposal(rp, ep, profile, out_json=out + ".json")
        def fail(args):
            raise error
        measure.run_pipeline = fail
        try:
            try:
                measure.main([jobs, "--json", rp])
            except t.TakeoffError:
                pass
        finally:
            measure.run_pipeline = original
        diag = json.load(open(rp, encoding="utf-8"))
        t.check("P1.1 " + name + " writes stopped JSON and quarantines dependent proposals",
                diag["run_status"] == "stopped" and str(error) in diag["stopped_reason"]
                and not os.path.exists(out + ".json") and not os.path.exists(ep)
                and any(p.endswith("proposal.json") for p in dependent_paths(rp)))
