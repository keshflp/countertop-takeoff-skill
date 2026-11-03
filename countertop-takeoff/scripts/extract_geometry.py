# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1"]
# ///
"""Extract vector geometry + text positions (step 2 of the V2 takeoff).

V2 upgrades over V1:
  - every segment and word carries a stable integer ID (the job spec SELECTS
    boundary segments and calibration spans by ID - code computes all lengths)
  - coordinates are normalized to DISPLAYED page space (rotation applied), so
    bbox/seed bookkeeping matches what a renderer shows; page rotation and
    crop metadata are recorded per page
  - each page records the shared preflight stats (segment count, image
    coverage, content class, fingerprint) so measurement can refuse
    raster/hybrid pages without re-deriving them
  - the file records the source PDF's SHA-256; measure.py verifies the
    geometry really belongs to the approved source

Output JSON, per page:
  segments: [{id, path, x0, y0, x1, y1, w}]   (displayed page points)
  words:    [{id, t, x0, y0, x1, y1}]
plus preflight/identity metadata and source digest.

Usage:
    uv run scripts/extract_geometry.py <file.pdf> [--pages 2,3 | --pages all]
                                        [--out PATH]
Default --pages: all.  Default --out: <pdf>.geometry.json. Pages are 1-based
as reported by index_pdf.py.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pymupdf  # noqa: E402
import preflight_lib as pl  # noqa: E402

SHEET_RE = re.compile(
    r"(?im)^\s*SHEET\s*[:#]?\s*([A-Z]{0,3}[-\s]?\d{1,4}[A-Z]?)\s*$")
SHEET_FALLBACK_RE = re.compile(r"(?im)^\s*([A-Z]{1,3}-\d{1,4})\s*$")
REVISION_RE = re.compile(r"\brev(?:ision)?\s*[.:#-]?\s*([A-Z0-9]{1,4})\b", re.I)


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


def page_record(doc, pno):
    """One geometry page: ID'd segments/words (displayed space) + preflight."""
    page = doc[pno - 1]
    raw_segs = pl.segments_of_page(page)
    # path ids by re-walking get_drawings() in the same order segments_of_page
    # used, so every segment keeps the id of the path it came from
    path_map = []
    for j, d in enumerate(page.get_drawings()):
        path_map.extend([j] * path_seg_count(d))
    segments = [
        {"id": i, "path": p, "x0": s[0], "y0": s[1], "x1": s[2], "y1": s[3],
         "w": s[4]}
        for i, (s, p) in enumerate(zip(raw_segs, path_map))
    ]
    words = [{"id": i, **w} for i, w in enumerate(pl.words_of_page(page))]
    text = page.get_text("text") or ""
    stats = pl.drawing_stats(page)
    images = pl.image_stats(page, doc)
    page_area = float(page.rect.width * page.rect.height) or 1.0
    img_area = sum(max(0.0, im["bbox"][2] - im["bbox"][0])
                   * max(0.0, im["bbox"][3] - im["bbox"][1]) for im in images)
    cover_pct = min(100.0, img_area / page_area * 100.0)
    cls = pl.classify_page(stats["segment_count"], cover_pct, len(text))
    return {
        "page": pno,
        "sheet": detect_sheet(text),
        "identity": pl.page_identity(doc, page),
        "coordinate_space": "displayed",
        "segment_count": len(segments),
        "word_count": len(words),
        "segments": segments,
        "words": words,
        "preflight": {
            "op_counts": stats["op_counts"],
            "segment_bounds": stats["segment_bounds"],
            "images": images,
            "image_cover_pct": round(cover_pct, 2),
            "class": cls["class"],
            "class_reasons": cls["reasons"],
            "fingerprint": pl.page_fingerprint(page, images),
            "revision_marks": sorted({m.upper() for m in REVISION_RE.findall(text)}),
        },
        "text_chars": len(text),
    }


def path_seg_count(d):
    """How many flattened segments one drawing path contributes."""
    n = 0
    for item in d["items"]:
        op = item[0]
        if op == "l":
            n += 1
        elif op == "c":
            n += pl.CURVE_SUBDIVISIONS
        elif op in ("re", "qu"):
            n += 4
    return n


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
    pages = [page_record(doc, pno) for pno in wanted]
    page_count = doc.page_count
    doc.close()
    for p in pages:
        print(f"page {p['page']}: {p['segment_count']} segments,"
              f" {p['word_count']} words, class {p['preflight']['class']}"
              f"  (sheet {p['sheet'] or '?'}), rot {p['identity']['rotation']})")

    out = args.out or os.path.splitext(args.pdf)[0] + ".geometry.json"
    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    payload = {
        "pdf": args.pdf,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {"sha256": pl.file_sha256(args.pdf), "page_count": page_count},
        "pages": pages,
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
