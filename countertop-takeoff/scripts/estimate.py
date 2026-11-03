# /// script
# requires-python = ">=3.9"
# dependencies = []
# /// 
"""Assembly-EA estimate (V4, P1.1): prices assembly EA x exact rate.

Reads a measure.py results JSON (the assembly BoQ carries the RESOLVED EA
and the assembly identity) plus a company profile carrying rates[] (the v2
profile pricing schema, references/company-profile.md), and writes:

  build/estimate.json  - lines with FULL arithmetic provenance (rate code,
                         quantity evidence, rounding rule, per-line math)
  build/estimate.md    - the deliverable: header; Item code | Description |
                         QTY EA | Unit price | Total; priced subtotal;
                         exclusions/callouts; grand total - BLANK when any
                         in-scope amount is unknown
  build/estimate.pdf   - a minimal text PDF rendered by THIS script from
                         the estimate.md content (stdlib-only writer, no new
                         dependencies). The AGENT HOST's document tooling may
                         render a richer PDF from estimate.md instead; the
                         contract is: the PDF must carry the SAME grand total
                         as md + json.

Pricing rules (accuracy hierarchy):
  - a rate matches an assembly ONLY when its match pins the assembly
    identity (assembly_kind = the type) and every other declared matcher
    (finish_tag, width_in, depth_in, handing, package) equals the
    assembly's value - NEVER finish alone
  - ZERO matching rates  -> amount BLANK + callout (no rate found)
  - TWO+ matching rates  -> amount BLANK + callout (ambiguous; the agent
    must disambiguate the profile, code never picks)
  - EA unresolved         -> amount BLANK + callout (quantity evidence
    withheld upstream); valid EA pricing survives even when the SF alone
    is unresolved (EA pricing never reads SF)
  - unit_price 0          -> a REAL 0.00 line (explicit zero-rate stays
    distinguishable from a missing rate)
  - Decimal arithmetic, every line_total rounded HALF_UP to whole cents;
    single currency enforced (mixed currencies refuse at profile load)

Usage:
    uv run scripts/estimate.py build/results.json --profile profile.rates.json \
        --out-md build/estimate.md --out-json build/estimate.json \
        --out-pdf build/estimate.pdf
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

BLANK = "__blank__"
LINES_PER_PDF_PAGE = 46


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def D(v):
    """Exact Decimal from int/float/str (floats via repr to avoid
    binary noise: 485.335 -> Decimal('485.335'))."""
    if isinstance(v, Decimal):
        return v
    if isinstance(v, float):
        return Decimal(repr(v))
    return Decimal(str(v))


def cents(d):
    return D(d).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def money(d):
    return f"{cents(d):,.2f}"


# ---------------------------------------------------------------- loading
def load_profile(path):
    with open(path, "r", encoding="utf-8") as f:
        profile = json.load(f)
    rates = profile.get("rates")
    if not rates:
        raise SystemExit(f"ERROR: profile {path} carries no rates[] - the"
                         " v4 estimate prices EA x rate (see"
                         " references/company-profile.md)")
    currency = profile.get("currency")
    for i, r in enumerate(rates):
        for k in ("item_code", "match", "uom", "unit_price"):
            if k not in r:
                raise SystemExit(f"ERROR: profile rates[{i}] missing {k!r}")
        if r["uom"] != "EA":
            raise SystemExit(f"ERROR: profile rates[{i}] uom must be 'EA'")
        cur = r.get("currency")
        if cur and currency and cur != currency:
            raise SystemExit(f"ERROR: mixed currencies in profile"
                             f" (rates[{i}] {cur!r} vs profile {currency!r})"
                             " - currency consistency is enforced")
    return profile, rates, currency


def rate_matches(rate, assembly):
    """match.assembly_kind is the assembly TYPE; every other declared
    matcher must equal the assembly's value exactly."""
    match = rate.get("match") or {}
    if str(match.get("assembly_kind")) != str(assembly.get("type")):
        return False
    for key, field in (("finish_tag", "finish_tag"),
                       ("handing", "handing"), ("package", "package")):
        want = match.get(key)
        if want is not None and want != assembly.get(field):
            return False
    for key, field in (("width_in", "width_in"), ("depth_in", "depth_in"),
                       ("height_in", "height_in")):
        want = match.get(key)
        if want is None:
            continue
        got = assembly.get(field)
        if got is None or abs(D(want) - D(got)) > Decimal("0.0001"):
            return False
    return True


def find_rate(rates, assembly):
    """Exactly ONE rate must match: (rate, None) | (None, reason)."""
    hits = [r for r in rates if rate_matches(r, assembly)]
    if not hits:
        return None, ("no rate in the profile matches this assembly"
                      " (type "
                      f"{assembly.get('type')!r}, finish"
                      f" {assembly.get('finish_tag')!r}, dims"
                      f" {assembly.get('width_in')}x"
                      f"{assembly.get('depth_in')})")
    if len(hits) > 1:
        return None, ("AMBIGUOUS rate: " +
                      ", ".join(sorted(r["item_code"] for r in hits)) +
                      " both match this assembly - disambiguate the profile"
                      " (tighten match dims/finish)")
    return hits[0], None


# ---------------------------------------------------------------- building
def build_lines(results, rates):
    """One estimate line per in-scope assembly. Returns (lines, callouts,
    exclusions). Blank amounts stay None - never zero."""
    lines = []
    callouts = []
    exclusions = []
    for a in results.get("assembly_boq") or []:
        aid = a["assembly_id"]
        if a.get("state") == "package_excluded":
            exclusions.append({
                "assembly_id": aid, "type": a.get("type"),
                "package": a.get("package"),
                "reason": "package-excluded scope is reported separately and"
                          " is NOT priced in this estimate",
            })
            continue
        qty = a.get("ea")
        rate, why = find_rate(rates, a)
        line_callouts = []
        if qty is None:
            line_callouts.append(
                f"quantity withheld: {a.get('basis', 'EA unresolved')} -"
                " amount blank")
        if rate is None:
            line_callouts.append(why)
        unit_price = D(rate["unit_price"]) if rate is not None else None
        if qty is not None and unit_price is not None:
            line_total = cents(D(qty) * unit_price)
            arithmetic = (f"{qty} EA x {money(unit_price)} ="
                          f" {money(line_total)} (ROUND_HALF_UP to cents)")
        else:
            line_total = None
            arithmetic = None
        lines.append({
            "item_code": rate["item_code"] if rate is not None else None,
            "description": (
                f"{a.get('type')} counter assembly"
                + (f" {a.get('width_in')} x {a.get('depth_in')} in"
                   if a.get("width_in") is not None
                   and a.get("depth_in") is not None else "")
                + (f", finish {a.get('finish_tag')}" if a.get("finish_tag")
                   else "")
                + (f", {a.get('handing')}" if a.get("handing") else "")),
            "assembly_ids": [aid],
            "qty_ea": qty,
            "unit_price": (float(unit_price) if unit_price is not None
                           else None),
            "line_total": (float(line_total) if line_total is not None
                           else None),
            "rate_reference": {
                "item_code": rate["item_code"] if rate is not None else None,
                "includes": (rate.get("includes") or []) if rate else [],
                "uom": "EA",
            },
            "quantity_evidence": a.get("basis"),
            "callout_references": ([f"estimate {aid}"] if line_callouts
                                   else []),
            "arithmetic": arithmetic,
        })
        for c in line_callouts:
            callouts.append({"scope": f"estimate {aid}", "reason": c,
                             "blank_fields": ["amount"]})
    return lines, callouts, exclusions


def summarize(lines):
    """Priced subtotal + grand total (BLANK when ANY in-scope amount is
    unknown - never a guessed number)."""
    priced = [l for l in lines if l["line_total"] is not None]
    subtotal = cents(sum(D(l["line_total"]) for l in priced)) if priced \
        else Decimal("0.00")
    unknown = [l for l in lines if l["line_total"] is None]
    grand = None if unknown else subtotal
    return subtotal, grand, [l["assembly_ids"][0] for l in unknown]


def estimate_markdown(payload):
    lines = ["# Countertop Estimate", ""]
    lines.append(f"- company: {payload['company']}")
    lines.append(f"- generated: {payload['generated_utc']}"
                 f" - currency: **{payload['currency']}**")
    lines.append(f"- source: results sha256"
                 f" `{payload['results_sha256'][:16]}...`; rate profile"
                 f" `{payload['profile_path']}` (sha256"
                 f" `{payload['profile_sha256'][:16]}...`)")
    lines.append("")
    lines.append("| Item code | Description | QTY EA | Unit price | Total |")
    lines.append("|-----------|-------------|-------:|-----------:|------:|")
    for l in payload["lines"]:
        qty_s = str(l["qty_ea"]) if l["qty_ea"] is not None else BLANK
        unit_s = money(D(l["unit_price"])) if l["unit_price"] is not None \
            else BLANK
        total_s = money(D(l["line_total"])) if l["line_total"] is not None \
            else BLANK
        code_s = l["item_code"] or BLANK
        lines.append(
            f"| {code_s} | {l['description']}"
            f" | {qty_s} | {unit_s} | {total_s} |")
    lines.append("")
    lines.append(f"**Priced subtotal: {money(payload['priced_subtotal'])}"
                 f" {payload['currency']}**"
                 " (sum of lines with known amounts only)")
    if payload["exclusions"]:
        lines += ["", "## Exclusions (not priced in this estimate)", ""]
        for e in payload["exclusions"]:
            lines.append(f"- assembly {e['assembly_id']} ({e['type']},"
                         f" package {e['package']}): {e['reason']}")
    if payload["callouts"]:
        lines += ["", "## CALLOUTS (blank amounts, never zeros)", ""]
        for i, c in enumerate(payload["callouts"], 1):
            lines.append(f"{i}. **{c['scope']}** - {c['reason']}")
    lines.append("")
    grand = payload["grand_total"]
    if grand is None:
        lines.append(f"**GRAND TOTAL: {BLANK}** - in-scope amount(s) for"
                     " the assemblies named in CALLOUTS are unknown; the"
                     " estimate completes for the priced portion only")
    else:
        lines.append(f"**GRAND TOTAL: {money(D(grand))}"
                     f" {payload['currency']}**")
    lines.append("")
    lines.append("Arithmetic: every line total is `QTY EA x unit price`,"
                 " Decimal-exact, rounded HALF_UP to whole cents; the grand"
                 " total is the sum of the priced lines and is BLANK while"
                 " any in-scope amount is unknown.")
    return "\n".join(lines) + "\n"


def _pdf_escape(t):
    return (t.replace("\\", r"\\").replace("(", r"\(")
            .replace(")", r"\)"))


def render_pdf(text, out_path, title="Countertop Estimate"):
    """Minimal stdlib PDF: Courier text pages rendered from the estimate
    content (same numbers as md/json; the AGENT HOST may render a richer
    PDF from estimate.md instead - the contract is the same grand total)."""
    raw_lines = text.split("\n")
    pages = [raw_lines[i:i + LINES_PER_PDF_PAGE]
             for i in range(0, len(raw_lines), LINES_PER_PDF_PAGE)]
    if not pages:
        pages = [[""]]
    objects = []

    def add(obj):
        objects.append(obj)
        return len(objects)

    font_id = add("<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")
    bold_id = add("<< /Type /Font /Subtype /Type1 /BaseFont /Courier-Bold"
                  " >>")
    page_ids = []
    for page in pages:
        parts = ["BT", "/F1 8 Tf", "40 800 Td", "14 TL"]
        for ln in page:
            parts.append("(" + _pdf_escape(ln) + ") Tj")
            parts.append("T*")
        parts.append("ET")
        stream = "\n".join(parts)
        cid = add({"stream": stream})
        pid = add({"page": True, "contents": cid, "font": font_id,
                   "bold": bold_id})
        page_ids.append(pid)
    pages_id = add({"pages": page_ids})
    catalog_id = add("<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
    out = bytearray()
    out += b"%PDF-1.4\n"
    offsets = []
    for idx, obj in enumerate(objects, 1):
        offsets.append(len(out))
        if isinstance(obj, dict) and "stream" in obj:
            data = obj["stream"].encode("latin-1", "replace")
            head = ("%d 0 obj\n<< /Length %d >>\nstream\n" % (idx,
                    len(data))).encode()
            out += head + data + b"\nendstream\nendobj\n"
        elif isinstance(obj, dict) and obj.get("page"):
            body = ("%d 0 obj\n<< /Type /Page /Parent %d 0 R /Contents %d 0 R"
                    " /Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >>"
                    " /MediaBox [0 0 612 792] >>\nendobj\n"
                    % (idx, pages_id, obj["contents"], obj["font"],
                       obj["bold"]))
            out += body.encode()
        elif isinstance(obj, dict) and "pages" in obj:
            kids = " ".join("%d 0 R" % p for p in obj["pages"])
            body = ("%d 0 obj\n<< /Type /Pages /Kids [%s] /Count %d >>\n"
                    "endobj\n" % (idx, kids, len(obj["pages"])))
            out += body.encode()
        else:
            body = "%d 0 obj\n%s\nendobj\n" % (idx, obj)
            out += body.encode()
    xref_at = len(out)
    out += ("xref\n0 %d\n" % (len(objects) + 1)).encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += ("trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, catalog_id, xref_at)).encode()
    with open(out_path, "wb") as f:
        f.write(bytes(out))
    return out_path



def build_estimate(results_path, profile_path, out_md=None, out_json=None,
                   out_pdf=None):
    results = json.load(open(results_path, encoding="utf-8"))
    profile, rates, currency = load_profile(profile_path)
    lines, callouts, exclusions = build_lines(results, rates)
    subtotal, grand, unknown = summarize(lines)
    payload = {
        "schema": "countertop-takeoff/v4 estimate",
        "company": profile.get("company", "(unnamed shop)"),
        "currency": currency or "(unspecified)",
        "generated_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "results_path": results_path,
        "results_sha256": sha256_file(results_path),
        "profile_path": profile_path,
        "profile_sha256": sha256_file(profile_path),
        "source_run_status": results.get("run_status"),
        "lines": lines,
        "priced_subtotal": float(subtotal),
        "grand_total": (float(grand) if grand is not None else None),
        "unknown_amounts": unknown,
        "exclusions": exclusions,
        "callouts": callouts,
        "arithmetic": {
            "per_line": "qty_ea x unit_price (Decimal exact)",
            "rounding": "ROUND_HALF_UP to whole cents at each line total",
            "grand_total": "sum of priced lines; BLANK while any in-scope"
                           " amount is unknown",
            "currency_rule": "single currency enforced; profile and rate"
                             " currencies must agree",
        },
    }
    md = estimate_markdown(payload)
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
        render_pdf(md, out_pdf)
        print(f"wrote {out_pdf} (minimal stdlib render of estimate.md;"
              " the agent host may render a richer PDF from the same md -"
              " the grand total must agree)")
    print(f"estimate: {len(lines)} line(s), priced subtotal"
          f" {money(subtotal)} {payload['currency']}, grand total"
          + (f" {money(D(grand))}" if grand is not None
             else f" {BLANK} ({len(unknown)} unknown)"))
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("results", help="measure.py results JSON")
    ap.add_argument("--profile", required=True,
                    help="company profile JSON with rates[] (v2 pricing"
                         " schema)")
    ap.add_argument("--out-md", dest="out_md", help="write estimate.md")
    ap.add_argument("--out-json", dest="out_json", help="write estimate.json")
    ap.add_argument("--out-pdf", dest="out_pdf", help="write estimate.pdf")
    args = ap.parse_args(argv)
    if not any((args.out_md, args.out_json, args.out_pdf)):
        print("ERROR: pass at least one of --out-md/--out-json/--out-pdf",
              file=sys.stderr)
        return 2
    build_estimate(args.results, args.profile, out_md=args.out_md,
                   out_json=args.out_json, out_pdf=args.out_pdf)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
