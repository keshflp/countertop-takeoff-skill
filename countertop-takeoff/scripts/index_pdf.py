# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1"]
# ///
"""Drawing-pack preflight + page inventory (step 1 of the V2 takeoff).

V2 goes beyond V1's text scan. Per page it records:
  - identity: rotation, media/crop box, displayed size (rotation-aware)
  - vector operator counts + flattened segment count + linework bounds
  - raster images drawn on the page and how much of the page they cover
  - a content CLASS: vector | text_only | searchable_raster | raster |
    hybrid | uncertain  (text presence NEVER establishes vector suitability:
    OCR'd scans carry a full text layer and zero usable linework)
  - a content fingerprint (duplicate-page + revision-conflict detection)
  - revision marks found in the text (REV A / REV B ...)

At pack level it reports:
  - source file SHA-256 (the measurement later re-verifies it)
  - duplicate pages (identical fingerprints)
  - sheet-id conflicts (same sheet number, different content)
  - every page that needs an explicit scope disposition before work continues

Writes `<pdf>.index.json` with full per-page text so the agent READS the unit
schedule without guessing from images.

Usage:
    uv run scripts/index_pdf.py <file.pdf> [more.pdf ...] [--out PATH]
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pymupdf  # noqa: E402  (uv installs it from the header above)
import preflight_lib as pl  # noqa: E402

# --- text patterns (kept in sync with the other scripts) --------------------
SHEET_RE = re.compile(r"(?im)^\s*SHEET\s*[:#]?\s*([A-Z]{0,3}[-\s]?\d{1,4}[A-Z]?)\s*$")
SHEET_FALLBACK_RE = re.compile(r"(?im)^\s*([A-Z]{1,3}-\d{1,4})\s*$")
DIM_WORD_RE = re.compile(
    r"^\s*(\d{1,3})\s*'\s*-?\s*(\d{1,2}(?:\.\d+)?)?\s*(?:\"|''|”)?\s*$"
)
UNIT_SCHEDULE_RE = re.compile(r"unit schedule|room schedule|schedule of units|unit type", re.I)
SCHEDULE_RE = re.compile(r"\bschedule\b", re.I)
QTY_RE = re.compile(r"\b(qty|quantity|units|count)\b", re.I)
TYPE_TAG_RE = re.compile(r"\btype\s+([a-z0-9]{1,4})\b", re.I)
PLAN_RE = re.compile(r"floor plan|\bplan\b|enlarged", re.I)
COUNTER_RE = re.compile(r"countertop|counter|vanity|kitchen|cabinet", re.I)
SPEC_RE = re.compile(r"specification|division\s*\d{1,2}", re.I)
FINISH_RE = re.compile(r"finish", re.I)
SCALE_LINE_RE = re.compile(r"\bscale\b", re.I)
REVISION_RE = re.compile(r"\brev(?:ision)?\s*[.:#-]?\s*([A-Z0-9]{1,4})\b", re.I)


def parse_dim_word(word):
    m = DIM_WORD_RE.match(word)
    if not m:
        return None
    feet = int(m.group(1))
    inches = float(m.group(2)) if m.group(2) else 0.0
    real_ft = feet + inches / 12.0
    return real_ft if real_ft >= 0.5 else None


def detect_sheet(text):
    m = SHEET_RE.search(text) or SHEET_FALLBACK_RE.search(text)
    return m.group(1).replace(" ", "-").upper() if m else None


def title_guess(text, sheet):
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if sheet and s.upper().startswith("SHEET"):
            continue
        if SCALE_LINE_RE.search(s):
            continue
        return s[:80]
    return None


def dim_labels(text):
    """Dimension-like labels per line, skipping any line that notes a scale."""
    out = []
    for line in text.splitlines():
        if SCALE_LINE_RE.search(line):
            continue
        for word in line.split():
            real_ft = parse_dim_word(word)
            if real_ft is not None:
                out.append({"label": word, "real_ft": round(real_ft, 4)})
    return out


def text_flags(text):
    return {
        "unit_schedule": bool(UNIT_SCHEDULE_RE.search(text))
        or bool(SCHEDULE_RE.search(text) and QTY_RE.search(text) and TYPE_TAG_RE.search(text)),
        "schedule": bool(SCHEDULE_RE.search(text)),
        "plan": bool(PLAN_RE.search(text)),
        "spec": bool(SPEC_RE.search(text)),
        "finish_schedule": bool(FINISH_RE.search(text) and SCHEDULE_RE.search(text)),
        "counter_terms": len(COUNTER_RE.findall(text)),
        "type_tags": sorted({t.upper() for t in TYPE_TAG_RE.findall(text)}),
    }


def preflight_page(doc, page):
    """Full preflight record for one page (displayed-space geometry)."""
    text = page.get_text("text") or ""
    words = pl.words_of_page(page)
    stats = pl.drawing_stats(page)
    images = pl.image_stats(page, doc)
    segs = pl.segments_of_page(page)
    regions = pl.content_regions(page, images, segs, words)
    page_area = float(page.rect.width * page.rect.height) or 1.0
    img_area = 0.0
    for im in images:
        x0, y0, x1, y1 = im["bbox"]
        img_area += max(0.0, (x1 - x0)) * max(0.0, (y1 - y0))
    cover_pct = min(100.0, img_area / page_area * 100.0)
    cls = pl.classify_page(stats["segment_count"], cover_pct, len(text))
    revisions = sorted({m.upper() for m in REVISION_RE.findall(text)})
    rt_pts = [(w["x0"], w["y0"]) for w in words[:200]]
    rt_ok, rt_bad = pl.transform_roundtrip_ok(rt_pts, page.rect)
    return {
        "page": page.number + 1,
        "sheet": detect_sheet(text),
        "title": title_guess(text, detect_sheet(text)),
        "width": round(page.rect.width, 2),
        "height": round(page.rect.height, 2),
        "dim_labels": dim_labels(text),
        "dim_count": len(dim_labels(text)),
        "flags": text_flags(text),
        "identity": pl.page_identity(doc, page),
        "transforms": pl.coordinate_transforms(page),
        "transform_check": {"ok": rt_ok,
                            "offenders": [[round(p[0], 2), round(p[1], 2)]
                                          for p in rt_bad]},
        "word_count": len(words),
        "content_regions": regions,
        "preflight": {
            "op_counts": stats["op_counts"],
            "segment_count": stats["segment_count"],
            "segment_bounds": stats["segment_bounds"],
            "images": images,
            "image_cover_pct": round(cover_pct, 2),
            "class": cls["class"],
            "class_reasons": cls["reasons"],
            "fingerprint": pl.page_fingerprint(page, images),
            "revision_marks": revisions,
        },
        "text": text,
    }


def analyze_pack(pages):
    """Pack-level findings: duplicates, sheet-id conflicts, review needs."""
    by_fp = {}
    by_sheet = {}
    for p in pages:
        pf = p["preflight"]
        by_fp.setdefault(pf["fingerprint"], []).append(p["page"])
        if p["sheet"]:
            by_sheet.setdefault(p["sheet"], []).append(p)
    duplicate_pages = sorted(
        [sorted(g) for g in by_fp.values() if len(g) > 1])
    sheet_conflicts = []
    for sheet, group in sorted(by_sheet.items()):
        fps = {p["preflight"]["fingerprint"] for p in group}
        if len(fps) > 1:
            sheet_conflicts.append({
                "sheet": sheet,
                "pages": [p["page"] for p in group],
                "fingerprints_differ": True,
                "detail": "same sheet id with DIFFERENT content - one of these"
                          " is probably a superseded revision; the approved"
                          " scope must say which page is authoritative",
            })
    needs_disposition = [
        p["page"] for p in pages
        if p["preflight"]["class"] not in pl.VECTOR_CLASSES
        or any(c["pages"] and p["page"] in c["pages"] for c in sheet_conflicts)
        or any(g and p["page"] in g for g in duplicate_pages)
    ]
    return {
        "duplicate_pages": duplicate_pages,
        "sheet_id_conflicts": sheet_conflicts,
        "pages_needing_disposition": needs_disposition,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--out", help="output JSON path (default: <pdf>.index.json)")
    args = ap.parse_args()

    for path in args.pdfs:
        if not os.path.exists(path):
            sys.exit(f"ERROR: {path} not found")
        doc = pymupdf.open(path)
        pages = [preflight_page(doc, doc[i]) for i in range(doc.page_count)]
        findings = analyze_pack(pages)
        doc.close()
        out = args.out or os.path.splitext(path)[0] + ".index.json"
        payload = {
            "pdf": path,
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": {"sha256": pl.file_sha256(path)},
            "page_count": len(pages),
            "pages": pages,
            "findings": findings,
        }
        out_dir = os.path.dirname(out)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1)
        print(f"# PDF preflight: {path}  ({len(pages)} pages)  ->  {out}")
        print(f"  source sha256: {payload['source']['sha256']}")
        print("| page | sheet | title | unit sched | class | rot | segs | img% | dims | type tags |")
        print("|-----:|-------|-------|------------|-------|----:|-----:|-----:|-----:|-----------|")
        for p in pages:
            pf, f_ = p["preflight"], p["flags"]
            print(
                f"| {p['page']} | {p['sheet'] or '?'} "
                f"| {(p['title'] or '?')[:34]} "
                f"| {'YES' if f_['unit_schedule'] else '-'} "
                f"| {pf['class']} "
                f"| {p['identity']['rotation']} "
                f"| {pf['segment_count']} "
                f"| {pf['image_cover_pct']:.0f} "
                f"| {p['dim_count']} "
                f"| {','.join(f_['type_tags']) or '-'} |")
        print()
        print("Unit-schedule candidates :",
              [p["page"] for p in pages if p["flags"]["unit_schedule"]] or "NONE")
        print("Vector plan-sheet candidates:",
              [p["page"] for p in pages
               if p["preflight"]["class"] in pl.VECTOR_CLASSES
               and p["flags"]["plan"] and p["flags"]["counter_terms"] > 0] or "NONE")
        if findings["duplicate_pages"]:
            print(f"DUPLICATE PAGES (identical content): {findings['duplicate_pages']}")
        if findings["sheet_id_conflicts"]:
            for c in findings["sheet_id_conflicts"]:
                print(f"SHEET-ID CONFLICT sheet {c['sheet']} pages {c['pages']}:"
                      f" {c['detail']}")
        print("Pages needing an explicit scope disposition:",
              findings["pages_needing_disposition"] or "none")
        print("Next: READ the full page text in the JSON; resolve every page"
              " above in the approved scope (measured / intentionally_skipped /"
              " blocked). Never measure a non-vector page.")
        print()


if __name__ == "__main__":
    main()
