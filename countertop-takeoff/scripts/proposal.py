# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1"]
# ///
"""Proposal-lite (V5, P1.3): a branded proposal/BoQ PDF from the
CORRECTED estimate.

Reads the measure results + the estimate payload + the rate profile
(terms/company) and writes:

  build/proposal.json  - the structured proposal (packages, lines,
                         exclusions, terms, totals, provenance)
  build/proposal.md    - fixed local layout: cover note; package summaries
                         (millwork/countertop-style groupings FROM THE DATA);
                         line items (UNCHANGED EA quantities and rates);
                         exclusions; supplied terms; blank signature lines
  build/proposal.pdf   - PyMuPDF render of proposal.md, amount-checked

Rules (accuracy hierarchy, neutral language):
  - quantities and rates are copied from the estimate VERBATIM - never
    recalculated, never rounded differently;
  - package summaries group what the data already carries (package field
    on the assemblies) - NO invented material/labor/install/tax splits;
  - exclusions are auto-assembled from the estimate's exclusions + its
    callouts - nothing is invented;
  - terms are only the SUPPLIED terms from the company profile;
  - totals: the priced subtotal and the estimate total (BLANK preserved
    when the estimate is incomplete). The proposal NEVER invents
    percentages, tax treatment, or payable balances.
  - agreement: json/md/pdf grand totals must agree (same contract as
    estimates); the estimate payload must be BOUND to the results file
    (sha256 match) and internally consistent, or the proposal refuses.

Usage:
    uv run scripts/proposal.py build/results.json \
        --estimate build/estimate.json --profile <rate-profile.json> \
        --out-md build/proposal.md --out-json build/proposal.json \
        --out-pdf build/proposal.pdf
"""

import argparse
import json
import os
import re
import textwrap
import sys
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import estimate as estimate_mod  # noqa: E402
from estimate import BLANK, cents, money
from preflight_lib import file_sha256 as sha256_file

def load_estimate(estimate_path, results_path):
    """Load + validate the CORRECTED estimate this proposal prices from."""
    with open(estimate_path, "r", encoding="utf-8") as f:
        est = json.load(f)
    schema = str(est.get("schema", ""))
    if not schema.startswith("countertop-takeoff/") \
            or not schema.endswith("estimate"):
        raise SystemExit(
            f"ERROR: {estimate_path} is not an estimate payload"
            f" (schema {schema!r}) - run estimate.py first")
    if est.get("source_run_status") in ("stopped", "failed"):
        raise SystemExit(
            f"ERROR: the bound estimate's source run is"
            f" {est.get('source_run_status')!r} - stopped scope is never"
            " quoted; re-measure, re-estimate, then propose")
    bound = est.get("results_sha256")
    for key in ("results_sha256", "profile_sha256"):
        if not isinstance(est.get(key), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", est[key]):
            raise SystemExit(f"ERROR: estimate requires valid provenance hash {key}")
    actual = sha256_file(results_path)
    if bound != actual:
        raise SystemExit(
            f"ERROR: the estimate is bound to a DIFFERENT results file"
            f" (estimate sha256 {bound[:16]}..., results sha256"
            f" {actual[:16]}...) - proposals may only be built from the"
            " corrected estimate of the SAME run")
    rate_profile = est.get("profile_path")
    if not rate_profile or sha256_file(rate_profile) != est["profile_sha256"]:
        raise SystemExit("ERROR: estimate rate profile provenance hash mismatch")
    with open(results_path, encoding="utf-8") as f:
        source = json.load(f)
    estimate_mod.validate_results_payload(source, results_path)
    # internal agreement: the stored totals must equal the line arithmetic
    lines = est.get("lines")
    if not isinstance(lines, list) or not lines:
        raise SystemExit(f"ERROR: estimate {estimate_path} carries no lines")
    for line in lines:
        qty = line.get("qty_ea")
        if qty is not None and (isinstance(qty, bool) or not isinstance(qty, (int, float))
                                or not estimate_mod.D(qty).is_finite()
                                or qty < 0 or qty != int(qty)):
            raise SystemExit("ERROR: estimate line arithmetic requires whole non-negative EA")
        rate = estimate_mod.line_rate(line)
        if line.get("unit_price") is not None and rate is None:
            raise SystemExit("ERROR: estimate line requires unit_price_exact")
        expected = cents(estimate_mod.D(qty) * rate) if qty is not None and rate is not None else None
        got = estimate_mod.D(line["line_total"]) if line.get("line_total") is not None else None
        if got != expected:
            raise SystemExit(f"ERROR: estimate line arithmetic mismatch for {line.get('assembly_ids')}: "
                             f"{qty} EA x {rate} requires {expected}, got {got}")
    priced = [estimate_mod.D(l["line_total"]) for l in lines
              if l.get("line_total") is not None]
    subtotal = cents(sum(priced)) if priced else Decimal("0.00")
    if subtotal != estimate_mod.D(est.get("priced_subtotal")):
        raise SystemExit(
            "ERROR: the estimate's priced_subtotal disagrees with its own"
            " lines - not a consistent estimate; re-run estimate.py")
    grand = est.get("grand_total")
    unknown = [l for l in lines if l.get("line_total") is None]
    expect_grand = None if (unknown or est.get("unknown_scope")
                            or estimate_mod.unknown_scope_from_ledger(source)) else subtotal
    got_grand = estimate_mod.D(grand) if grand is not None else None
    if got_grand != expect_grand:
        raise SystemExit(
            "ERROR: the estimate's grand_total disagrees with its lines and"
            " unknown-scope - not a consistent estimate; re-run estimate.py")
    if bool(est.get("scope_complete")) != (expect_grand is not None):
        raise SystemExit("ERROR: estimate scope_complete disagrees with unresolved scope")
    return est


def load_terms(profile_path):
    """The SUPPLIED terms from the company profile (never invented)."""
    with open(profile_path, "r", encoding="utf-8") as f:
        profile = json.load(f)
    terms = profile.get("terms")
    if terms is None:
        return [], profile.get("company", "(unnamed shop)")
    if not isinstance(terms, list) or not all(
            isinstance(t, str) and t.strip() for t in terms):
        raise SystemExit(
            f"ERROR: profile {profile_path}: terms must be a list of"
            " non-empty strings (the proposal never invents terms)")
    return terms, profile.get("company", "(unnamed shop)")


def package_summaries(lines, exclusions, scope_incomplete=False):
    """Package groupings FROM THE DATA (P1.3): one summary per package with
    its line count, EA total and KNOWN amount - no invented splits."""
    packages = {}
    order = []
    for l in lines:
        pkg = l.get("package") or "(unassigned)"
        if pkg not in packages:
            packages[pkg] = {"package": pkg, "lines": 0, "ea": 0,
                             "known_amount": Decimal("0.00"),
                             "has_unknown": False}
            order.append(pkg)
        g = packages[pkg]
        g["lines"] += 1
        if l.get("qty_ea") is None:
            g["ea"] = None
        elif g["ea"] is not None:
            g["ea"] += l["qty_ea"]
        if l.get("line_total") is not None:
            g["known_amount"] += estimate_mod.D(l["line_total"])
        else:
            g["has_unknown"] = True
    out = []
    for pkg in order:
        g = packages[pkg]
        out.append({
            "package": g["package"],
            "lines": g["lines"],
            "ea_total": g["ea"],
            "known_amount": float(g["known_amount"]),
            "amount": (float(cents(g["known_amount"]))
                       if not g["has_unknown"] else None),
            "note": ("includes line(s) with unknown amounts - see the open"
                     " items" if g["has_unknown"]
                     else ("known subtotal; omitted scope remains unresolved"
                           if scope_incomplete else "fully priced from the estimate")),
        })
    exclusion_pkgs = []
    for e in exclusions:
        pkg = e.get("package")
        if pkg and pkg not in packages and pkg not in exclusion_pkgs:
            exclusion_pkgs.append(pkg)
    for pkg in exclusion_pkgs:
        out.append({"package": pkg, "lines": 0, "ea_total": 0,
                    "known_amount": 0.0, "amount": None,
                    "note": "excluded from this proposal"
                            " (package-excluded scope)"})
    return out


def build_proposal(results_path, estimate_path, profile_path, out_md=None,
                   out_json=None, out_pdf=None):
    from publish_safety import reject_aliases, register_artifacts, quarantine, manifest_path
    protected = {"results": results_path, "estimate": estimate_path, "profile": profile_path,
                 "audit receipt": str(results_path) + ".receipt.json"}
    with open(estimate_path, encoding="utf-8") as f:
        source_estimate = json.load(f)
    protected["rate profile"] = source_estimate.get("profile_path")
    protected["estimate results"] = source_estimate.get("results_path")
    reject_aliases(protected, {"artifact manifest": manifest_path(results_path),
                              "out-md": out_md, "out-json": out_json, "out-pdf": out_pdf})
    outputs = [out_md, out_json, out_pdf]
    try:
        payload = _build_proposal(results_path, estimate_path, profile_path,
                                  out_md, out_json, out_pdf)
        register_artifacts(results_path, outputs)
        return payload
    except (Exception, SystemExit):
        quarantine(outputs)
        raise


def _build_proposal(results_path, estimate_path, profile_path, out_md, out_json, out_pdf):
    est = load_estimate(estimate_path, results_path)
    terms, company = load_terms(profile_path)
    lines = est["lines"]
    exclusions = est.get("exclusions") or []
    packages = package_summaries(lines, exclusions, not est.get("scope_complete"))
    callouts = est.get("callouts") or []
    open_items = [c for c in callouts if "amount" in (c.get("blank_fields")
                                                      or [])]
    subtotal = estimate_mod.D(est["priced_subtotal"])
    grand = est.get("grand_total")
    currency = est.get("currency", "(unspecified)")
    payload = {
        "schema": "countertop-takeoff/v5 proposal",
        "company": company,
        "currency": currency,
        "generated_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "results_path": results_path,
        "results_sha256": sha256_file(results_path),
        "estimate_path": estimate_path,
        "estimate_sha256": sha256_file(estimate_path),
        "profile_path": profile_path,
        "profile_sha256": sha256_file(profile_path),
        "scope_complete": bool(est.get("scope_complete")),
        "unknown_scope": est.get("unknown_scope") or [],
        "callouts": callouts,
        "packages": packages,
        "lines": lines,
        "exclusions": exclusions,
        "open_items": [{"scope": c.get("scope"), "reason": c.get("reason")}
                       for c in open_items],
        "terms": terms,
        "priced_subtotal": est["priced_subtotal"],
        "grand_total": grand,
        "note": ("estimate total is BLANK while any in-scope amount is"
                 " unknown; this proposal invents no percentages, tax"
                 " treatment, or payable balances"),
    }
    md = proposal_markdown(payload)
    if out_json:
        d = os.path.dirname(out_json)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1)
        print(f"wrote {out_json}")
    if out_md:
        d = os.path.dirname(out_md)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(out_md, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"wrote {out_md}")
    if out_pdf:
        d = os.path.dirname(out_pdf)
        if d:
            os.makedirs(d, exist_ok=True)
        expect = [f"# Proposal - {company}",
                  f"Priced subtotal (known lines only): **{money(subtotal)}"]
        expect.append(f"ESTIMATE TOTAL: {BLANK}" if grand is None
                      else f"ESTIMATE TOTAL: {money(estimate_mod.D(grand))}"
                           f" {currency}")
        for l in lines:
            expect.append(money(estimate_mod.D(l["line_total"]))
                          if l.get("line_total") is not None else BLANK)
            if estimate_mod.line_rate(l) is not None:
                expect.append(estimate_mod.fmt_rate(estimate_mod.line_rate(l)))
        expect.extend(money(estimate_mod.D(g["known_amount"])) for g in packages)
        estimate_mod.render_pdf(md, out_pdf, title=f"Proposal - {company}",
                                expect_amounts=expect)
        print(f"wrote {out_pdf} (amount-checked against proposal.json)")
    print(f"proposal: {len(lines)} line(s),"
          f" {len(packages)} package(s), priced subtotal"
          f" {money(subtotal)} {currency}, estimate total"
          + (f" {money(estimate_mod.D(grand))}" if grand is not None
             else f" {BLANK}"))
    return payload


def proposal_markdown(payload):
    """Fixed local layout (P1.3): cover note; package summaries; line
    items (unchanged EA + exact rates); exclusions; supplied terms; blank
    signature lines. NEVER invents percentages, tax, or payable balances."""
    company = payload["company"]
    currency = payload["currency"]
    lines = [f"# Proposal - {company}", "",
             f"- date: {payload['generated_utc'][:10]}"
             f" - currency: **{currency}**",
             f"- prepared from: corrected estimate sha256"
             f" `{payload['estimate_sha256'][:16]}...`"
             f" bound to takeoff results sha256"
             f" `{payload['results_sha256'][:16]}...`",
             ""]
    lines += ["## Cover note", "",
              f"{company} proposes the countertop scope summarized below."
              " Quantities (EA) and unit rates are carried over UNCHANGED"
              " from the corrected estimate; package groupings come from"
              " the measured data, and every exclusion or open item is"
              " named."
              + ("" if payload["scope_complete"] else
                 " The scope is INCOMPLETE: the estimate total is blank"
                 " while the open items below are unresolved."), ""]
    lines += ["## Package summaries", "",
              "| package | lines | EA total | known subtotal | total | note |",
              "|---------|------:|---------:|---------------:|------:|------|"]
    for g in payload["packages"]:
        amount_s = (money(estimate_mod.D(g["amount"]))
                    if g.get("amount") is not None else BLANK)
        qty_s = str(g["ea_total"]) if g["ea_total"] is not None else BLANK
        lines.append(f"| {g['package']} | {g['lines']} | {qty_s}"
                     f" | {money(estimate_mod.D(g['known_amount']))}"
                     f" | {amount_s} | {g['note']} |")
    lines.append("")
    lines.append(f"Priced subtotal (known lines only):"
                 f" **{money(estimate_mod.D(payload['priced_subtotal']))}"
                 f" {currency}**")
    lines += ["", "## Line items", "",
              "EA quantities and rates are unchanged from the estimate;",
              "", "| Item code | Description | QTY EA | Unit price | Total |",
              "|-----------|-------------|-------:|-----------:|------:|"]
    for l in payload["lines"]:
        qty_s = str(l["qty_ea"]) if l.get("qty_ea") is not None else BLANK
        unit_s = estimate_mod.fmt_rate(estimate_mod.line_rate(l)) \
            if estimate_mod.line_rate(l) is not None else BLANK
        total_s = money(estimate_mod.D(l["line_total"])) \
            if l.get("line_total") is not None else BLANK
        code_s = l.get("item_code") or BLANK
        description = (l["description"] + " [assembly " + ", ".join(l["assembly_ids"])
                       + (f"; room {l['room']}" if l.get("room") else "") + "]")
        chunks = textwrap.wrap(description, 52, break_long_words=False,
                               break_on_hyphens=False) or [""]
        for ci, chunk in enumerate(chunks):
            last = ci == len(chunks) - 1
            lines.append(
                f"| {code_s if ci == 0 else ''} | {chunk}"
                f" | {qty_s if last else ''}"
                f" | {unit_s if last else ''}"
                f" | {total_s if last else ''} |")
    lines += estimate_mod.rate_basis_lines(payload["lines"])
    if payload["exclusions"]:
        lines += ["", "## Exclusions (not priced)", ""]
        for e in payload["exclusions"]:
            lines.append(f"- assembly {e['assembly_id']} ({e['type']},"
                         f" package {e['package']}): {e['reason']}")
    if payload["open_items"]:
        lines += ["", "## Open items (amounts unknown)", ""]
        for c in payload["open_items"]:
            lines.append(f"- {c['scope']}: {c['reason']}")
    if payload["scope_complete"]:
        grand_s = money(estimate_mod.D(payload["grand_total"]))
        lines += ["", f"**ESTIMATE TOTAL: {grand_s} {currency}**"
                  " (the corrected estimate's total, unchanged)"]
    else:
        lines += ["", f"**ESTIMATE TOTAL: {BLANK}** - unresolved while the"
                      " open items above stand; this proposal invents no"
                      " percentages, tax treatment, or payable balances."]
    lines += ["", "## Terms (as supplied)", ""]
    if payload["terms"]:
        for t in payload["terms"]:
            lines.append(f"- {t}")
    else:
        lines.append("- no terms were supplied in the company profile.")
    lines += ["", "## Acceptance", "",
              "Signature (authorised for the customer):", "",
              "________________________________________", "",
              "Signature (for " + company + "):", "",
              "________________________________________", "",
              "Date: ______________________", ""]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("results", help="measure.py results JSON")
    ap.add_argument("--estimate", required=True,
                    help="estimate.py estimate.json (the CORRECTED estimate)")
    ap.add_argument("--profile", required=True,
                    help="company/rate profile JSON (company name + terms)")
    ap.add_argument("--out-md", dest="out_md", help="write proposal.md")
    ap.add_argument("--out-json", dest="out_json", help="write proposal.json")
    ap.add_argument("--out-pdf", dest="out_pdf", help="write proposal.pdf")
    args = ap.parse_args(argv)
    if not any((args.out_md, args.out_json, args.out_pdf)):
        print("ERROR: pass at least one of --out-md/--out-json/--out-pdf",
              file=sys.stderr)
        return 2
    build_proposal(args.results, args.estimate, args.profile,
                   out_md=args.out_md, out_json=args.out_json,
                   out_pdf=args.out_pdf)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
