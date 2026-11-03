# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf>=1.24"]
# ///
"""Extract vector geometry + text positions from PDF pages (step 2 of the takeoff).

Uses PyMuPDF page.get_drawings() to pull the page's VECTOR linework:
  - straight lines              ("l"  items)
  - bezier curves               ("c"  items, flattened into 8 chords)
  - rectangles / quads          ("re"/"qu" items, emitted as 4 edges each)
and page.get_text("words") for word bounding boxes (needed for calibration:
dimension labels must be matched to vector segments on the SAME sheet).

Output: one JSON file containing, per page:
  segments: [{x0, y0, x1, y1, w}]   (PDF points, page space, origin top-left)
  words:    [{t, x0, y0, x1, y1}]

Usage:
    uv run scripts/extract_geometry.py <file.pdf> [--pages 2,3 | --pages all]
                                        [--out PATH]

Default --pages: all.  Default --out: <pdf>.geometry.json next to the PDF.
Page numbers are 1-based (as reported by index_pdf.py).
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

try:
    import pymupdf
except ImportError:
    import fitz as pymupdf

CURVE_SUBDIVISIONS = 8

SHEET_RE = re.compile(r"(?im)^\s*SHEET\s*[:#]?\s*([A-Z]{0,3}[-\s]?\d{1,4}[A-Z]?)\s*$")
SHEET_FALLBACK_RE = re.compile(r"(?im)^\s*([A-Z]{1,3}-\d{1,4})\s*$")


def parse_pages(spec, page_count):
    if spec is None or spec.strip().lower() in ("all", ""):
        return list(range(1, page_count + 1))
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    bad = [p for p in out if p < 1 or p > page_count]
    if bad:
        sys.exit(f"ERROR: page(s) {bad} out of range 1..{page_count}")
    return sorted(set(out))


def detect_sheet(text):
    m = SHEET_RE.search(text) or SHEET_FALLBACK_RE.search(text)
    return m.group(1).replace(" ", "-").upper() if m else None


def segments_from_page(page):
    """Flatten all drawing items into straight segments in page points."""
    segs = []
    for d in page.get_drawings():
        w = round(float(d.get("width") or 0.0), 3)
        for item in d["items"]:
            op = item[0]
            if op == "l":
                p1, p2 = item[1], item[2]
                segs.append((p1.x, p1.y, p2.x, p2.y, w))
            elif op == "c":
                # cubic bezier: flatten into chords
                p0, p1, p2, p3 = item[1], item[2], item[3], item[4]
                pts = []
                for k in range(1, CURVE_SUBDIVISIONS + 1):
                    t = k / CURVE_SUBDIVISIONS
                    mt = 1 - t
                    x = (mt**3 * p0.x + 3 * mt**2 * t * p1.x
                         + 3 * mt * t**2 * p2.x + t**3 * p3.x)
                    y = (mt**3 * p0.y + 3 * mt**2 * t * p1.y
                         + 3 * mt * t**2 * p2.y + t**3 * p3.y)
                    pts.append((x, y))
                prev = (p0.x, p0.y)
                for pt in pts:
                    segs.append((prev[0], prev[1], pt[0], pt[1], w))
                    prev = pt
            elif op == "re":
                r = item[1]
                segs.extend([
                    (r.x0, r.y0, r.x1, r.y0, w),
                    (r.x1, r.y0, r.x1, r.y1, w),
                    (r.x1, r.y1, r.x0, r.y1, w),
                    (r.x0, r.y1, r.x0, r.y0, w),
                ])
            elif op == "qu":
                q = item[1]
                corners = [q.ul, q.ur, q.lr, q.ll]
                for i in range(4):
                    a, b = corners[i], corners[(i + 1) % 4]
                    segs.append((a.x, a.y, b.x, b.y, w))
    return [
        {"x0": round(s[0], 4), "y0": round(s[1], 4),
         "x1": round(s[2], 4), "y1": round(s[3], 4), "w": s[4]}
        for s in segs
    ]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf")
    ap.add_argument("--pages", default=None, help="1-based pages: '2,3' or 'all'")
    ap.add_argument("--out", help="output JSON (default <pdf>.geometry.json)")
    args = ap.parse_args()

    if not os.path.exists(args.pdf):
        sys.exit(f"ERROR: {args.pdf} not found")

    doc = pymupdf.open(args.pdf)
    wanted = parse_pages(args.pages, doc.page_count)
    pages = []
    for pno in wanted:
        page = doc[pno - 1]
        words = page.get_text("words") or []
        segs = segments_from_page(page)
        pages.append({
            "page": pno,
            "sheet": detect_sheet(page.get_text("text") or ""),
            "width": round(page.rect.width, 2),
            "height": round(page.rect.height, 2),
            "segment_count": len(segs),
            "word_count": len(words),
            "segments": segs,
            "words": [
                {"t": w[4], "x0": round(w[0], 3), "y0": round(w[1], 3),
                 "x1": round(w[2], 3), "y1": round(w[3], 3)}
                for w in words
            ],
        })
        print(f"page {pno}: {len(segs)} segments, {len(words)} words"
              f"  (sheet {pages[-1]['sheet'] or '?'})")
    doc.close()

    out = args.out or os.path.splitext(args.pdf)[0] + ".geometry.json"
    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    payload = {
        "pdf": args.pdf,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pages": pages,
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
