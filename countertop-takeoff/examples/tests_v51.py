"""5.1 correctness regressions, run by tests_v5 after its original checks."""
import copy
import json
import os


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
                 "detail": "unknown contribution, no special room phrase"}]})):
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


def run(t):
    measurement_tests(t)
