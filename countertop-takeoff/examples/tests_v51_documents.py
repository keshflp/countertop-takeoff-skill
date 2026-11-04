"""Synthetic pricing and contractor-document regressions for 5.1."""
import copy
import json
import os


def run(t):
    import estimate
    import proposal
    import measure
    import pymupdf
    from spec_schema import validate_rates, TakeoffError
    spec = t.mixed_v5_spec()
    report = os.path.join(t.BUILD, "v51_document.report.md")
    _, res, _ = t.run_measure(spec, "v51_document", extra=("--report", report))
    rp = os.path.join(t.BUILD, "v51_document.results.json")
    profile = {"company": "Synthetic Shop", "currency": "USD", "rates": [
        {"item_code": "R-" + typ, "match": {"assembly_kind": typ}, "uom": "EA",
         "unit_price": "100.1234567890123456789"}
        for typ in sorted({a["type"] for a in res["assembly_boq"]})]}
    pp = os.path.join(t.BUILD, "v51_document.rates.json")
    ep = os.path.join(t.BUILD, "v51_document.estimate.json")
    json.dump(profile, open(pp, "w", encoding="utf-8"))
    est = estimate.build_estimate(rp, pp, out_json=ep,
        out_md=os.path.join(t.BUILD, "v51_document.estimate.md"),
        out_pdf=os.path.join(t.BUILD, "v51_document.estimate.pdf"))
    pristine = copy.deepcopy(est)
    for key in ("results_sha256", "profile_sha256"):
        bad = copy.deepcopy(pristine)
        del bad[key]
        json.dump(bad, open(ep, "w", encoding="utf-8"))
        try:
            proposal.load_estimate(ep, rp)
            rejected = False
        except SystemExit as exc:
            rejected = "provenance hash" in str(exc)
        t.check("P1.3 missing " + key + " refuses proposal", rejected)
    bad = copy.deepcopy(pristine)
    bad["lines"][0].update(qty_ea=2, unit_price=100, unit_price_exact="100", line_total=999)
    bad["priced_subtotal"] = sum(l["line_total"] or 0 for l in bad["lines"])
    if bad["grand_total"] is not None:
        bad["grand_total"] = bad["priced_subtotal"]
    json.dump(bad, open(ep, "w", encoding="utf-8"))
    try:
        proposal.load_estimate(ep, rp)
        rejected = False
    except SystemExit as exc:
        rejected = "line arithmetic mismatch" in str(exc)
    t.check("P1.3 2 EA x 100 cannot validate as 999 even when subtotal/grand agree", rejected)
    json.dump(pristine, open(ep, "w", encoding="utf-8"))

    # Exact decimal JSON input also retains all digits before calculation.
    raw = json.dumps(profile).replace('"100.1234567890123456789"', '100.1234567890123456789')
    with open(pp, "w", encoding="utf-8") as f:
        f.write(raw)
    exact = estimate.build_estimate(rp, pp)
    t.check("P1.3 numeric JSON rate retains decimal digits before float conversion",
            all(l["unit_price_exact"] == "100.1234567890123456789" for l in exact["lines"]))
    json.dump(profile, open(pp, "w", encoding="utf-8"))
    # Omitted measured region: all surviving lines price, scope remains incomplete.
    spec["assemblies"] = [a for a in spec["assemblies"] if a["assembly_id"] != "fl1-a"]
    spec["pieces"] = [p for p in spec["pieces"] if p["piece_id"] != "p:k"]
    for a in spec["assemblies"]:
        a["room"] = "ROOM-" + a["assembly_id"]
    _, res, _ = t.run_measure(spec, "v51_doc_incomplete", extra=("--report", report))
    rp = os.path.join(t.BUILD, "v51_doc_incomplete.results.json")
    est = estimate.build_estimate(rp, pp, out_json=ep,
        out_pdf=os.path.join(t.BUILD, "v51_document.estimate.pdf"))
    base = os.path.join(t.BUILD, "v51_document.proposal")
    prop = proposal.build_proposal(rp, ep, pp, out_json=base + ".json",
                                   out_md=base + ".md", out_pdf=base + ".pdf")
    report_text = open(report, encoding="utf-8").read()
    t.check("P1.4 project total prints once with known-subtotal qualification",
            report_text.count("Project total:") == 1
            and "known subtotal" in report_text.split("Project total:")[1].split("\n")[0])
    md = open(base + ".md", encoding="utf-8").read()
    t.check("P1.4 incomplete proposal uses known package subtotals and inherits omission",
            "fully priced" not in md and "known subtotal" in md
            and "A:kitchen" in md and prop["grand_total"] is None
            and prop["lines"] == est["lines"])
    for kind in ("estimate", "proposal"):
        with pymupdf.open(os.path.join(t.BUILD, "v51_document." + kind + ".pdf")) as doc:
            txt = "\n".join(pg.get_text() for pg in doc)
        t.check("P1.3/P1.4 " + kind + " PDF uses exact rate and clean plain text",
                "100.1234567890123456789" in txt and "__blank__" not in txt
                and "**" not in txt and "BLANK" in txt
                and all(estimate.money(l["line_total"]) in txt for l in est["lines"]))
        joined = txt.replace("\n", "").replace(" ", "")
        t.check("P1.4 " + kind + " repeated lines carry assembly + room identifiers",
                all(aid in joined for l in est["lines"] for aid in l["assembly_ids"])
                and all(l["room"] in joined for l in est["lines"]))
    t.check("P1.3 estimate/proposal package subtotals equal priced line sums",
            estimate.cents(sum(estimate.D(l["line_total"]) for l in est["lines"]))
            == estimate.D(est["priced_subtotal"])
            and all(estimate.cents(sum(estimate.D(l["line_total"]) for l in prop["lines"]
                                     if l["package"] == g["package"]))
                    == estimate.D(g["known_amount"]) for g in prop["packages"]))
    for key, value in (("width_inches", 60), ("variant", "STD")):
        bad = copy.deepcopy(profile)
        bad["rates"][0]["match"][key] = value
        json.dump(bad, open(pp, "w", encoding="utf-8"))
        try:
            estimate.load_profile(pp)
            rejected = False
        except SystemExit as exc:
            rejected = "unknown matcher" in str(exc) and key in str(exc)
        # The job-profile schema independently rejects the same typo.
        bad["rates"][0]["unit_price"] = 100
        try:
            validate_rates(bad)
            schema_rejected = False
        except TakeoffError as exc:
            schema_rejected = "unknown matcher" in str(exc)
        t.check("P1.3 unknown matcher key " + key + " rejected in both loaders",
                rejected and schema_rejected)
    json.dump(profile, open(pp, "w", encoding="utf-8"))
