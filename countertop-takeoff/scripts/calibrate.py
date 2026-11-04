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

# Dimension text, extended in V3 (P0.4): total inches (211"), decimal
# values (10.5' / 6.25"), inch-only (6 1/2") alongside the existing
# feet-inches with optional fraction.
_DIM_FEET_INCHES_RE = re.compile(
    r"^\s*(?:(\d{1,3})\s*')?\s*-?\s*(\d{1,3}(?:\.\d+)?)"
    r"(?:\s+(\d{1,2})\s*/\s*(\d{1,2}))?\s*(?:\"|''|”)?\s*$"
)
_DIM_TOTAL_INCHES_RE = re.compile(
    r"^\s*(\d{1,4}(?:\.\d+)?)(?:\s+(\d{1,2})\s*/\s*(\d{1,2}))?"
    r"\s*(?:\"|''|”|in\.|ins\.|inches?)\s*$",
    re.I,
)
_DIM_FEET_ONLY_RE = re.compile(
    r"^\s*(\d{1,4}(?:\.\d+)?)\s*'(?:\s*-?\s*(?:0\s*\")?)?\s*$")


def _fraction_to_float(whole_txt, num_txt, den_txt):
    """('6', '1', '2') -> 6.5; invalid fraction -> None."""
    val = float(whole_txt)
    if num_txt is not None:
        den = float(den_txt)
        if den <= 0:
            return None
        val += float(num_txt) / den
    return val


class CalibrationError(TakeoffError):
    pass


def parse_dim_text(text):
    """Dimension text -> real feet, or None if unparseable.

    Accepts: 10'-0" / 10'6" / 10'-6 1/2" / 6 1/2" (inch-only) / 211"
    (total inches) / 10.5' / 6.25" (decimals) / 10' (feet only).
    """
    t = text.replace("”", '"').replace("''", '"').strip()
    # feet-only first so "10'" never reads as 10 inches
    m = _DIM_FEET_ONLY_RE.match(t)
    if m:
        return float(m.group(1))
    # total-inches form: a number with a trailing inch marker/word
    m = _DIM_TOTAL_INCHES_RE.match(t)
    if m:
        val = _fraction_to_float(m.group(1), m.group(2), m.group(3))
        if val is not None:
            return val / 12.0
    m = _DIM_FEET_INCHES_RE.match(t)
    if not m:
        return None
    feet = float(m.group(1)) if m.group(1) else 0.0
    val = _fraction_to_float(m.group(2), m.group(3), m.group(4))
    if val is None:
        return None
    real = feet + val / 12.0
    if feet == 0.0 and not t.endswith('"') and not t.endswith("'"):
        return None  # bare '6' with no unit is not dimension evidence
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
    """Compute one calibration entry for (source, page, viewport).

    Returns dict with per-span evidence and the agreed factor. Raises
    CalibrationError on any violation. V3 rules added on top of V2:
      - spans must be INDEPENDENT: duplicating one span (same segments or
        same parsed length twice) never satisfies the two-span rule
      - an optional viewport_box bounds the viewport in displayed page
        points; every span segment must lie inside it
    """
    viewport = entry.get("viewport") or "main"
    vp_box = entry.get("viewport_box")
    if vp_box is not None:
        require_viewport_box(vp_box, entry)
    overrides = []
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
        if parsed is not None and parsed <= 0:
            raise CalibrationError(
                f"span {i} ({text!r}): parsed dimension must be positive")
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
        if len(set(ids)) != len(ids):
            raise CalibrationError(
                f"span {i} ({text!r}): repeated segment ids would count the"
                " same dimension-line length more than once")
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
        if vp_box is not None and not _ids_inside_box(
                segs_by_id, ids, vp_box):
            raise CalibrationError(
                f"span {i} ({text!r}): dimension segments fall OUTSIDE the"
                f" viewport_box {vp_box} - a span must calibrate the"
                " viewport it is declared in")
        # P0.2: an explicit real_ft override that CONTRADICTS the readable
        # label is disclosed as a callout, never applied silently
        override_warning = None
        if source == "explicit" and parsed is not None \
                and abs(real_ft - parsed) / parsed > 0.01:
            override_warning = (
                f"real_ft override {real_ft} contradicts the readable label"
                f" {text!r} (= {parsed:.4f} ft) - confirm the override or"
                " fix the selection")
            overrides.append({"span": i, "label": text,
                              "real_ft": real_ft, "parsed_ft": parsed,
                              "warning": override_warning})
        spans.append({
            "label": text, "real_ft": round(real_ft, 6),
            "real_ft_source": source, "word_ids": label_ids,
            "seg_ids": ids, "length_pt": round(length, 4),
            "pt_per_ft": round(length / real_ft, 6),
            "parsed_ft": (round(parsed, 6) if parsed is not None else None),
            "override_warning": override_warning,
        })
    _require_span_independence(spans, entry, viewport)
    factors = [s["pt_per_ft"] for s in spans]
    factor = statistics.median(factors)
    spread_pct = (max(factors) - min(factors)) / factor * 100.0
    if spread_pct > WARN_SPREAD_PCT:
        err = CalibrationError(
            f"page {entry.get('page')} viewport {viewport!r}: span factors"
            f" disagree by {spread_pct:.2f}% (limit {WARN_SPREAD_PCT}%):"
            f" {[round(f, 4) for f in factors]}. Wrong segment picked? Two"
            " viewports mixed? Investigate - do not average.")
        # P0.2: override contradictions are disclosed EVEN when the entry
        # fails the spread check (they may be the CAUSE of the disagreement)
        if overrides:
            err.overrides = overrides
            err.args = (str(err) + " | "
                        + " ".join(o["warning"] for o in overrides),)
        raise err
    return {
        "page": entry.get("page"), "viewport": viewport,
        "source_id": entry.get("source_id"),
        "viewport_box": vp_box,
        "spans": spans, "factor_pt_per_ft": round(factor, 6),
        "spread_pct": round(spread_pct, 3),
        "overrides": overrides,
        "status": ("pass" if spread_pct <= PASS_SPREAD_PCT else "warning"),
    }


def require_viewport_box(vp_box, entry):
    """A viewport_box is [x0, y0, x1, y1] in displayed points: finite,
    x1>x0, y1>y0."""
    from spec_schema import finite
    ok = (isinstance(vp_box, list) and len(vp_box) == 4
          and all(finite(v) for v in vp_box)
          and vp_box[2] > vp_box[0] and vp_box[3] > vp_box[1])
    if not ok:
        raise CalibrationError(
            f"page {entry.get('page')} viewport"
            f" {entry.get('viewport') or 'main'!r}: viewport_box must be"
            " [x0, y0, x1, y1] in displayed points with x1>x0, y1>y0")


def _ids_inside_box(segs_by_id, ids, box):
    for j in ids:
        s = segs_by_id[j]
        for (x, y) in ((s["x0"], s["y0"]), (s["x1"], s["y1"])):
            if not (box[0] <= x <= box[2] and box[1] <= y <= box[3]):
                return False
    return True


def _require_span_independence(spans, entry, viewport):
    """Two spans describing the SAME physical dimension are one measurement
    said twice. Duplicate segment sets or duplicate parsed lengths refuse:
    duplicating one span must never satisfy the two-span rule."""
    where = f"page {entry.get('page')} viewport {viewport!r}"
    seen_segs, seen_fts = {}, {}
    for i, sp in enumerate(spans):
        key = tuple(sorted(sp["seg_ids"]))
        if key in seen_segs:
            raise CalibrationError(
                f"{where}: spans {seen_segs[key]} and {i} select the SAME"
                " segments - one dimension measured twice is not independent"
                " evidence; pick a different dimension line")
        seen_segs[key] = i
        ft = sp["real_ft"]
        if ft in seen_fts:
            raise CalibrationError(
                f"{where}: spans {seen_fts[ft]} and {i} both parse to"
                f" {ft} ft - spans must be DIFFERENT dimensions (same-length"
                " twins do not cross-check a scale); pick another labeled"
                " dimension")
        seen_fts[ft] = i


def build_calibrations(spec_calibrations, pages_by_no, default_source=None,
                       on_error=None):
    """Calibrate every (source, page, viewport) entry against the geometry.

    Duplicate keys (same source/page/viewport twice) are rejected outright:
    two calibrations for one viewport is an unsupported override - no silent
    scale borrowing. Per-entry failures (single span, disagreeing spans, out
    of viewport) are COLLECTED and reported via on_error(key, message) so
    only the affected viewport degrades (P0.1); when NO entry succeeds the
    caller decides on catastrophic stop 1.
    """
    out = {}
    errors = []
    seen_keys = set()
    for entry in spec_calibrations:
        pno = entry.get("page")
        source = entry.get("source_id") or default_source
        key = (source, pno, entry.get("viewport") or "main")
        if key in seen_keys:
            raise CalibrationError(
                f"duplicate calibration for source {source!r} page {pno}"
                f" viewport {key[2]!r} - one viewport has ONE calibration"
                " (unsupported overrides refuse)")
        seen_keys.add(key)
        if (source, pno) not in pages_by_no:
            # V5 (P1.1): a page whose geometry was never extracted degrades
            # LOCALLY (callout; that viewport's regions go unresolved) - it
            # must not abort the calibrations of every OTHER page
            msg = (f"calibration source {source!r} page {pno} is not in the"
                   " geometry file(s) - that viewport's quantities degrade to"
                   " blank (re-run extract_geometry.py for it); other pages"
                   " still calibrate")
            errors.append((key, msg))
            if on_error:
                on_error(key, msg)
            continue
        try:
            cal = calibrate_entry(entry, pages_by_no[(source, pno)])
        except CalibrationError as exc:
            errors.append((key, str(exc)))
            if on_error:
                on_error(key, str(exc))
            continue
        cal["source_id"] = source
        out[key] = cal
    return out, errors
