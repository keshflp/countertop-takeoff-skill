# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1"]
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
  build/estimate.pdf   - a PyMuPDF text render of estimate.md (V5, P1.2):
                         exact rate precision visible, first line below the
                         page top, wrapped + paginated, and every rendered
                         amount is re-read from the PDF and checked against
                         estimate.json before the file ships.

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
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

BLANK = "__blank__"
_CURRENCY_SYMBOLS = "$€£¥"


def parse_money(v, what="unit_price"):
    """Exact Decimal from a number or a currency-formatted string (P0.3).

    Accepts plain numbers and unambiguous currency strings:
    `$1,234.56`, `1,234.56`, `1.234,56`, `1234.56`, `-12.5`.
    When both separators appear, the LAST one is the decimal separator.
    Ambiguous strings (`1.234` under US/EU conventions) produce a CLEAR
    error telling the operator to write a plain number - never a raw
    Decimal traceback.
    """
    if isinstance(v, bool) or v is None:
        raise SystemExit(f"ERROR: {what} must be a number, got {v!r}")
    if isinstance(v, Decimal):
        return v
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            raise SystemExit(f"ERROR: {what} must be finite, got {v!r}")
        return Decimal(repr(v))
    if not isinstance(v, str):
        raise SystemExit(f"ERROR: {what} must be a number, got"
                         f" {type(v).__name__} {v!r}")
    s = v.strip()
    for sym in _CURRENCY_SYMBOLS:
        s = s.replace(sym, "")
    s = s.strip()
    neg = s.startswith("-")
    if neg or s.startswith("+"):
        s = s[1:].strip()
    if not re.fullmatch(r"[\d.,]+", s):
        raise SystemExit(
            f"ERROR: {what} {v!r} is not a parseable amount - use a plain"
            " number (optionally currency-formatted like '$1,234.56')")
    if "," in s and "." in s:
        dec_sep = "." if s.rfind(".") > s.rfind(",") else ","
        thou_sep = "," if dec_sep == "." else "."
        s = s.replace(thou_sep, "").replace(dec_sep, ".")
    elif "," in s:
        if re.search(r",\d{1,2}$", s):
            s = s.replace(".", "").replace(",", ".")   # decimal comma
        elif re.search(r",\d{3}(\D|$)", s):
            s = s.replace(",", "")                    # thousands groups
        else:
            raise SystemExit(
                f"ERROR: {what} {v!r} is ambiguous - write a plain number"
                " like 1234.56")
    elif "." in s and re.search(r"\.\d{3}$", s):
        raise SystemExit(
            f"ERROR: {what} {v!r} is ambiguous (decimal point or thousands"
            " separator?) - write a plain number like 1234.56 or 1234")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        raise SystemExit(
            f"ERROR: {what} {v!r} is not a parseable amount - use a plain"
            " number like 1234.56")
    d = Decimal(s)
    return -d if neg else d


def rate_amount(r, what):
    """Parse a rate's numeric amount; negatives and garbage refuse with a
    useful diagnostic (P0.3), never a raw Decimal traceback."""
    code = r.get("item_code")
    d = parse_money(r.get(what), what=f"rates[{code}] {what}")
    if d < 0:
        raise SystemExit(
            f"ERROR: rates[{code}] {what} is negative ({d}) - prices cannot"
            " be negative; fix the profile")
    return d


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
    for i, r in enumerate(rates):
        if not isinstance(r, dict):
            raise SystemExit(f"ERROR: profile rates[{i}] must be an object")
        for k in ("item_code", "match", "uom", "unit_price"):
            if k not in r:
                raise SystemExit(f"ERROR: profile rates[{i}] missing {k!r}")
        if r["uom"] != "EA":
            raise SystemExit(f"ERROR: profile rates[{i}] uom must be 'EA'")
        rate_amount(r, "unit_price")
    currency = effective_currency(profile, rates, path)
    return profile, rates, currency


def effective_currency(profile, rates, path):
    """ONE effective currency across all rates (P0.3): a rate without a
    currency inherits the profile currency; when the profile currency is
    absent, every rate must declare the SAME currency explicitly - USD+EUR
    mixing refuses with the offending codes named."""
    profile_currency = profile.get("currency")
    if profile_currency is not None and \
            (not isinstance(profile_currency, str)
             or not profile_currency.strip()):
        raise SystemExit(f"ERROR: profile {path}: currency must be a"
                         " non-empty string when present")
    resolved = {}
    for i, r in enumerate(rates):
        cur = r.get("currency") or profile_currency
        if cur is None:
            raise SystemExit(
                f"ERROR: rates[{i}] ({r.get('item_code')}) declares no"
                " currency and the profile has none - one effective currency"
                " is required (declare profile.currency or rate currencies)")
        resolved.setdefault(cur, []).append(str(r.get("item_code")))
    if len(resolved) > 1:
        detail = "; ".join(f"{cur}: {codes}" for cur, codes in
                           sorted(resolved.items()))
        raise SystemExit(
            "ERROR: mixed currencies in the profile refuse - ONE effective"
            f" currency is required ({detail})")
    if profile_currency is not None and resolved \
            and next(iter(resolved)) != profile_currency:
        raise SystemExit(
            f"ERROR: a rate currency disagrees with the profile currency"
            f" {profile_currency!r} - currency consistency is enforced")
    return next(iter(resolved)) if resolved else profile_currency


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
def validate_results_payload(results, path):
    """P0.3: the estimate inherits scope completeness - it prices ONLY a
    results payload whose run actually completed and that carries the
    assembly BoQ. A `stopped` result never gets a priced grand total; a
    result missing `assembly_boq` must not silently price as 0.00."""
    if not isinstance(results, dict):
        raise SystemExit(f"ERROR: {path} is not a results JSON object")
    status = results.get("run_status") or results.get("status")
    if status in ("stopped", "failed"):
        raise SystemExit(
            f"ERROR: refusing to price {path}: the source run is {status!r}"
            " - stopped runs have no quotable quantities (resolve the named"
            " stops, re-measure, then estimate)")
    if status not in ("complete", "complete_with_callouts"):
        raise SystemExit(
            f"ERROR: refusing to price {path}: run status is {status!r}"
            " (expected complete / complete_with_callouts) - re-run"
            " measure.py with --json to produce a priceable evidence"
            " package")
    boq = results.get("assembly_boq")
    if not isinstance(boq, list) or not boq:
        raise SystemExit(
            f"ERROR: refusing to price {path}: no assembly_boq - the V4/V5"
            " estimate prices assembly EA x exact rate; re-run measure.py on"
            " a job spec that declares assemblies (an empty assembly list"
            " must not silently price as 0.00)")
    return boq


def unknown_scope_from_ledger(results):
    """Every unresolved in-scope contribution withholds the grand total."""
    from scope_state import unresolved_scope
    out = unresolved_scope(results.get("coverage_ledger") or [],
                           results.get("unavailable_inputs") or [])
    for e in results.get("scope_incomplete") or []:
        if e not in out:
            out.append(e)
    return out


def build_lines(results, rates):
    """One estimate line per in-scope assembly; PLUS unknown-scope entries
    for omitted in-scope work (priced lines and the subtotal survive; the
    grand total goes BLANK). Returns (lines, callouts, exclusions,
    unknown_scope). Blank amounts stay None - never zero.

    P0.3: a malformed quantity (negative or fractional EA) refuses with a
    useful diagnostic naming the assembly - never a silent or garbage line.
    A LEGITIMATE derived EA of zero prices a real 0.00 line (no callout).
    """
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
        if qty is not None:
            bad_qty = (isinstance(qty, bool)
                       or not isinstance(qty, (int, float))
                       or qty < 0
                       or (isinstance(qty, float) and not qty.is_integer()))
            if bad_qty:
                raise SystemExit(
                    f"ERROR: assembly {aid} has a malformed EA {qty!r} in the"
                    " results - EA must be a non-negative whole count (a"
                    " fractional or negative quantity is not priceable;"
                    " re-measure)")
        rate, why = find_rate(rates, a)
        line_callouts = []
        if qty is None:
            line_callouts.append(
                f"quantity withheld: {a.get('basis', 'EA unresolved')} -"
                " amount blank")
        if rate is None:
            line_callouts.append(why)
        unit_price = rate_amount(rate, "unit_price") \
            if rate is not None else None
        if qty is not None and unit_price is not None:
            line_total = cents(D(qty) * unit_price)
            arithmetic = (f"{qty} EA x {fmt_rate(unit_price)} ="
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
            "package": a.get("package"),
            "qty_ea": qty,
            "unit_price": (float(unit_price) if unit_price is not None
                           else None),
            "unit_price_exact": (str(unit_price)
                                 if unit_price is not None else None),
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
    unknown_scope = unknown_scope_from_ledger(results)
    for u in unknown_scope:
        callouts.append({
            "scope": f"estimate scope {u['item']}",
            "reason": f"{u['detail']} - scope contribution unresolved; its amount"
                      " is UNKNOWN; the grand total is withheld",
            "blank_fields": ["amount"],
        })
    return lines, callouts, exclusions, unknown_scope


def fmt_rate(d):
    """Exact rate display (P1.2): a cents-precise rate renders as money;
    a finer exact rate (55.555) renders EXACTLY - never silently rounded
    to 55.56."""
    if d == d.quantize(Decimal("0.01")):
        return money(d)
    return str(d.normalize())


def summarize(lines, unknown_scope=()):
    """Priced subtotal + grand total (BLANK when ANY in-scope amount is
    unknown - never a guessed number). Omitted in-scope scope (P0.3) also
    blanks the grand total while the priced lines survive."""
    priced = [l for l in lines if l["line_total"] is not None]
    subtotal = cents(sum(D(l["line_total"]) for l in priced)) if priced \
        else Decimal("0.00")
    unknown = [l for l in lines if l["line_total"] is None]
    grand = None if (unknown or unknown_scope) else subtotal
    return subtotal, grand, [l["assembly_ids"][0] for l in unknown]


def estimate_markdown(payload):
    lines = ["# Countertop Estimate", ""]
    lines.append(f"- company: {payload['company']}")
    lines.append(f"- generated: {payload['generated_utc']}"
                 f" - currency: **{payload['currency']}**"
                 + ("" if payload.get("scope_complete")
                    else " - **scope INCOMPLETE: the grand total is blank**"))
    lines.append(f"- source: results sha256"
                 f" `{payload['results_sha256'][:16]}...`; rate profile"
                 f" `{payload['profile_path']}` (sha256"
                 f" `{payload['profile_sha256'][:16]}...`)")
    lines.append("")
    lines.append("| Item code | Description | QTY EA | Unit price | Total |")
    lines.append("|-----------|-------------|-------:|-----------:|------:|")
    for l in payload["lines"]:
        qty_s = str(l["qty_ea"]) if l["qty_ea"] is not None else BLANK
        unit_s = fmt_rate(D(l["unit_price"])) \
            if l["unit_price"] is not None else BLANK
        total_s = money(D(l["line_total"])) if l["line_total"] is not None \
            else BLANK
        code_s = l["item_code"] or BLANK
        # V5 (P1.2): wrap a long DESCRIPTION into continuation rows so the
        # numeric columns stay on the final row - a wrapped row must never
        # split an amount
        chunks = [l["description"][i:i + 52]
                  for i in range(0, len(l["description"]), 52)] or [""]
        for ci, chunk in enumerate(chunks):
            last = ci == len(chunks) - 1
            lines.append(
                f"| {code_s if ci == 0 else ''} | {chunk}"
                f" | {qty_s if last else ''}"
                f" | {unit_s if last else ''}"
                f" | {total_s if last else ''} |")
    lines.append("")
    lines.append(f"**Priced subtotal: {money(payload['priced_subtotal'])}"
                 f" {payload['currency']}**"
                 " (sum of lines with known amounts only"
                 + ("" if payload.get("scope_complete")
                    else "; the scope is INCOMPLETE - see CALLOUTS") + ")")
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
    lines.append("")
    lines.append("Per-line arithmetic (exact rate precision retained):")
    for l in payload["lines"]:
        if l.get("arithmetic"):
            lines.append(f"- {l['item_code']}: {l['arithmetic']}")
        else:
            lines.append(f"- {l['item_code'] or BLANK}: no amount (blank -"
                         " see CALLOUTS)")
    return "\n".join(lines) + "\n"


# ------------------------------------------------- PDF render (PyMuPDF)
PDF_MARGIN = 40.0
PDF_TOP_PT = 64.0        # V5 (P1.2): the first line sits BELOW the page top
PDF_LEADING = 12.0
PDF_FONTSIZE = 8.0
PDF_MAX_LINES = 46       # per page


def render_pdf(text, out_path, title="Countertop Estimate",
               expect_amounts=()):
    """Render the estimate content to PDF with PyMuPDF (V5, P1.2):
      - the first text line sits below the page top (the title used to
        clip against the MediaBox edge);
      - long lines wrap and paginate (every source line's text lands in
        the extracted text);
      - after writing, the PDF is REOPENED and every amount string in
        `expect_amounts` is checked against the extracted text - a
        rendered amount that disagrees with estimate.json refuses.
    """
    import pymupdf
    usable_w = 612.0 - 2 * PDF_MARGIN
    char_w = PDF_FONTSIZE * 0.6        # Courier advance width
    max_chars = int(usable_w / char_w)
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    y = PDF_TOP_PT
    lines_on_page = 0

    def new_page():
        nonlocal page, y, lines_on_page
        page = doc.new_page(width=612, height=792)
        y = PDF_TOP_PT
        lines_on_page = 0

    def emit(s):
        nonlocal y, lines_on_page
        if lines_on_page >= PDF_MAX_LINES:
            new_page()
        wrapped = [s[i:i + max_chars] for i in range(0, len(s), max_chars)] \
            or [""]
        for chunk in wrapped:
            if lines_on_page >= PDF_MAX_LINES:
                new_page()
            page.insert_text((PDF_MARGIN, y), chunk, fontname="cour",
                             fontsize=PDF_FONTSIZE, color=(0, 0, 0))
            y += PDF_LEADING
            lines_on_page += 1

    for ln in text.split("\n"):
        emit(ln)
    doc.save(out_path)
    doc.close()
    # ---- rendered-amount agreement check (P1.2) ----
    check_doc = pymupdf.open(out_path)
    extracted = "\n".join(pg.get_text() for pg in check_doc)
    n_pages = check_doc.page_count
    check_doc.close()
    missing = [a for a in expect_amounts if a not in extracted]
    if missing:
        raise SystemExit(
            f"ERROR: rendered PDF amounts disagree with estimate.json -"
            f" missing from the rendered text: {missing!r}; refusing to"
            " ship a PDF whose numbers cannot be re-read")
    if not extracted.strip():
        raise SystemExit("ERROR: rendered PDF carries no extractable text")
    return out_path, n_pages, extracted



def reject_aliases(results_path, profile_path, out_md, out_json, out_pdf):
    """P0.1: an estimate output may never alias the evidence it reads -
    the `--json build/results.json --estimate-profile X` combo used to
    make the estimate overwrite its own results.json."""
    from publish_safety import reject_aliases as reject, manifest_path
    reject({"results": results_path, "rate profile": profile_path,
            "artifact manifest": manifest_path(results_path),
            "audit receipt": str(results_path) + ".receipt.json"},
           {"out-md": out_md, "out-json": out_json, "out-pdf": out_pdf})


def build_estimate(results_path, profile_path, out_md=None, out_json=None,
                   out_pdf=None):
    reject_aliases(results_path, profile_path, out_md, out_json, out_pdf)
    from publish_safety import register_artifacts, quarantine
    outputs = [out_md, out_json, out_pdf]
    try:
        payload = _build_estimate(results_path, profile_path, out_md, out_json, out_pdf)
        register_artifacts(results_path, outputs)
        return payload
    except (Exception, SystemExit):
        quarantine(outputs)
        raise


def _build_estimate(results_path, profile_path, out_md, out_json, out_pdf):
    results = json.load(open(results_path, encoding="utf-8"))
    validate_results_payload(results, results_path)
    profile, rates, currency = load_profile(profile_path)
    lines, callouts, exclusions, unknown_scope = build_lines(results, rates)
    subtotal, grand, unknown = summarize(lines, unknown_scope)
    payload = {
        "schema": "countertop-takeoff/v5 estimate",
        "company": profile.get("company", "(unnamed shop)"),
        "currency": currency or "(unspecified)",
        "generated_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "results_path": results_path,
        "results_sha256": sha256_file(results_path),
        "profile_path": profile_path,
        "profile_sha256": sha256_file(profile_path),
        "source_run_status": results.get("run_status"),
        "scope_complete": (grand is not None),
        "lines": lines,
        "priced_subtotal": float(subtotal),
        "grand_total": (float(grand) if grand is not None else None),
        "unknown_amounts": unknown,
        "unknown_scope": unknown_scope,
        "exclusions": exclusions,
        "callouts": callouts,
        "arithmetic": {
            "per_line": "qty_ea x unit_price (Decimal exact)",
            "rounding": "ROUND_HALF_UP to whole cents at each line total",
            "grand_total": "sum of priced lines; BLANK while any in-scope"
                           " amount is unknown (blank lines AND omitted"
                           " in-scope scope)",
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
        # V5 (P1.2): the PDF is re-read after rendering and every amount
        # (exact rates, line totals, subtotal, grand total / blank marker)
        # is checked against the estimate payload
        expect = ["# Countertop Estimate",
                  f"Priced subtotal: {money(payload['priced_subtotal'])}"]
        if grand is None:
            expect.append(f"GRAND TOTAL: {BLANK}")
        else:
            expect.append(f"GRAND TOTAL: {money(D(grand))}"
                          f" {payload['currency']}")
        for l in lines:
            if l["line_total"] is not None:
                expect.append(money(D(l["line_total"])))
                expect.append(fmt_rate(D(l["unit_price"])))
            else:
                expect.append(BLANK)
        render_pdf(md, out_pdf, expect_amounts=expect)
        print(f"wrote {out_pdf} (PyMuPDF render of estimate.md; every"
              " rendered amount re-checked against estimate.json - the"
              " grand total must agree)")
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
