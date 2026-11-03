"""Calibration from agent-selected dimension spans (V2).

V1 auto-matched labels to nearby segments; a wrong nearby segment produced
36 pt/ft with zero spread because a single label trivially agrees with
itself. V2 rules:

  - a calibration belongs to a (source page, viewport) pair, never to a page
    alone (sheets can carry two viewports at different scales)
  - the agent SELECTS each span: which words carry the dimension text and
    which segments make up the dimension line; code computes every length
    from the geometry - the agent never types a pt/ft factor
  - at least TWO independent spans must agree; one label can never calibrate
  - span factors are computed, then compared: spread <= PASS_SPREAD_PCT is
    clean, up to WARN_SPREAD_PCT is a warning, above FAIL_SPREAD_PCT is a
    hard stop (v1 enforced 5% but documented 2-5%; the bands are now the
    documented behavior)
  - the ACTUAL factor used per region is recorded and reported, so a report
    can never show 18.00 while the math used 18.36
"""

import re
import statistics

from spec_schema import TakeoffError, finite

PASS_SPREAD_PCT = 2.0
WARN_SPREAD_PCT = 5.0
MIN_SPANS = 2

# Accepts 10'-0" / 10'6" / 10'-6 1/2" / 6 1/2" / 10' / 7'-6.25" etc.
DIM_TEXT_RE = re.compile(
    r"^\s*(?:(\d{1,3})\s*'\s*-?\s*)?(\d{1,2})(?:\s+(\d{1,2})\s*/\s*(\d{1,2}))?"
    r"\s*(?:\"|''|”)?\s*$"
)
SCALE_LINE_WORDS = {"scale", "scale:"}


class CalibrationError(TakeoffError):
    pass


def parse_dim_text(text):
    """Feet-inches(-fraction) text -> real feet, or None if unparseable."""
    t = text.replace("”", '"').replace("''", '"').strip()
    m = DIM_TEXT_RE.match(t)
    if not m:
        return None
    feet = int(m.group(1)) if m.group(1) else 0.0
    inches = float(m.group(2))
    if m.group(3):
        frac = float(m.group(4))
        if frac <= 0:
            return None
        inches += float(m.group(3)) / frac
    real = feet + inches / 12.0
    return real if real >= 0.5 else None


def seg_length(s):
    return ((s["x1"] - s["x0"]) ** 2 + (s["y1"] - s["y0"]) ** 2) ** 0.5


def word_line_text(word_ids, words_by_id):
    """Join the selected words (in id order) into one label string."""
    missing = [i for i in word_ids if i not in words_by_id]
    if missing:
        raise CalibrationError(
            f"calibration span references word ids {missing} that are not on"
            " this page - re-extract the geometry or fix the span")
    return " ".join(words_by_id[i]["t"] for i in word_ids)


def calibrate_entry(entry, page):
    """Compute one calibration entry for (page, viewport).

    Returns dict with per-span evidence and the agreed factor. Raises
    CalibrationError on any v2 violation.
    """
    viewport = entry.get("viewport") or "main"
    spans_spec = entry.get("spans")
    if not isinstance(spans_spec, list) or len(spans_spec) < MIN_SPANS:
        raise CalibrationError(
            f"page {entry.get('page')} viewport {viewport!r}: calibration"
            f" needs at least {MIN_SPANS} independent dimension spans"
            " - one label agreeing with itself is how v1 shipped a 36 pt/ft"
            " factor")
    segs_by_id = {s["id"]: s for s in page["segments"]}
    words_by_id = {w["id"]: w for w in page["words"]}
    spans = []
    for i, sp in enumerate(spans_spec):
        label_ids = sp.get("word_ids", [])
        if not isinstance(label_ids, list) or not label_ids:
            raise CalibrationError(
                f"page {entry.get('page')} viewport {viewport!r} span {i}:"
                " word_ids must list the words carrying the dimension text")
        text = word_line_text(label_ids, words_by_id)
        real_ft = sp.get("real_ft")
        parsed = parse_dim_text(text)
        if real_ft is not None:
            if not finite(real_ft) or real_ft <= 0:
                raise CalibrationError(
                    f"span {i} ({text!r}): real_ft must be positive and finite")
            source = "explicit"
        elif parsed is not None:
            real_ft = parsed
            source = "parsed"
        else:
            raise CalibrationError(
                f"span {i}: text {text!r} is not a parseable dimension -"
                " fix the word selection or pass explicit real_ft")
        ids = sp.get("seg_ids")
        if not isinstance(ids, list) or not ids:
            raise CalibrationError(
                f"span {i} ({text!r}): seg_ids must name the dimension-line"
                " segments")
        missing = [j for j in ids if j not in segs_by_id]
        if missing:
            raise CalibrationError(
                f"span {i} ({text!r}): segment ids {missing} are not on page"
                f" {entry.get('page')}")
        length = sum(seg_length(segs_by_id[j]) for j in ids)
        if length < 3.0:
            raise CalibrationError(
                f"span {i} ({text!r}): selected segments total only"
                f" {length:.2f} pt - too short to be a dimension line")
        spans.append({
            "label": text, "real_ft": round(real_ft, 6),
            "real_ft_source": source, "word_ids": label_ids,
            "seg_ids": ids, "length_pt": round(length, 4),
            "pt_per_ft": round(length / real_ft, 6),
        })
    factors = [s["pt_per_ft"] for s in spans]
    factor = statistics.median(factors)
    spread_pct = (max(factors) - min(factors)) / factor * 100.0
    if spread_pct > WARN_SPREAD_PCT:
        raise CalibrationError(
            f"page {entry.get('page')} viewport {viewport!r}: span factors"
            f" disagree by {spread_pct:.2f}% (limit {WARN_SPREAD_PCT}%):"
            f" {[round(f, 4) for f in factors]}. Wrong segment picked? Two"
            " viewports mixed? Investigate - do not average.")
    return {
        "page": entry.get("page"), "viewport": viewport,
        "spans": spans, "factor_pt_per_ft": round(factor, 6),
        "spread_pct": round(spread_pct, 3),
        "status": ("pass" if spread_pct <= PASS_SPREAD_PCT else "warning"),
    }


def build_calibrations(spec_calibrations, pages_by_no):
    """Calibrate every (page, viewport) entry against the geometry."""
    out = {}
    for entry in spec_calibrations:
        pno = entry.get("page")
        if pno not in pages_by_no:
            raise CalibrationError(
                f"calibration page {pno} is not in the geometry file -"
                " re-run extract_geometry.py for it")
        cal = calibrate_entry(entry, pages_by_no[pno])
        out[(pno, cal["viewport"])] = cal
    return out
