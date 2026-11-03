# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1"]
# ///
"""Shared drawing-pack preflight primitives (V2).

ONE implementation of page statistics, fingerprints, and content classes, used
by index_pdf.py (pack QA report), extract_geometry.py (records the same values
into the geometry JSON) and measure.py (validates job specs against them).
Sharing the code guarantees the digests and classes recorded by different
tools always agree.

Coordinate convention
---------------------
All bboxes/points are in DISPLAYED page space: what a renderer shows, i.e.
page rotation applied. Helpers below transform content-space values with
``page.rotation_matrix`` so callers never handle rotation themselves.

Text presence NEVER establishes vector suitability: a searchable raster page
(OCR'd scan) has a full text layer and zero usable linework. Classification
therefore weighs image coverage against flattened segment counts, and the
result is recorded with its reasons so an auditor can re-check it.
"""

import hashlib
import json

# Classification thresholds (documented in references/method.md, section 2).
IMAGE_COVER_VECTOR_MAX = 0.20   # <= this coverage can still be a vector page
IMAGE_COVER_FULL = 0.60         # >= this coverage dominates the page
MIN_VECTOR_SEGMENTS = 10        # fewer flattened segments = no usable linework
MIN_TEXT_CHARS = 200            # searchable-raster heuristic needs real text

# Page classes:
#   vector           - linework only; measurable by this skill
#   text_only        - no image, almost no vectors (schedule/notes pages)
#   searchable_raster- image dominates AND text layer exists (OCR'd scan)
#   raster           - image dominates, no text layer
#   hybrid           - meaningful image AND vector content (e.g. scan pasted
#                      over a vector title block) - NOT trustworthy for area
#   uncertain        - mixed/ambiguous signals - human must look
VECTOR_CLASSES = {"vector"}


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def digest_obj(obj):
    """Stable digest of a JSON-serializable object (canonical dump)."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def rotated_rect(page, rect):
    """Return `rect` in displayed space (rotation applied when != 0)."""
    if page.rotation in (0, None):
        return [round(rect.x0, 3), round(rect.y0, 3),
                round(rect.x1, 3), round(rect.y1, 3)]
    r = pymupdf_rect(rect) * page.rotation_matrix
    return [round(r.x0, 3), round(r.y0, 3), round(r.x1, 3), round(r.y1, 3)]


def pymupdf_rect(rect):
    import pymupdf
    return pymupdf.Rect(rect)

def page_identity(doc, page):
    """Identity + metadata for one page (displayed-space sizes)."""
    disp_w, disp_h = page.rect.width, page.rect.height
    return {
        "page": page.number + 1,
        "rotation": int(page.rotation or 0),
        "mediabox": [round(page.mediabox.x0, 2), round(page.mediabox.y0, 2),
                     round(page.mediabox.x1, 2), round(page.mediabox.y1, 2)],
        "cropbox": [round(page.cropbox.x0, 2), round(page.cropbox.y0, 2),
                    round(page.cropbox.x1, 2), round(page.cropbox.y1, 2)],
        "displayed_width": round(disp_w, 2),
        "displayed_height": round(disp_h, 2),
    }


def words_of_page(page):
    """Words with displayed-space boxes: [{t, x0, y0, x1, y1}]."""
    import pymupdf
    out = []
    for w in page.get_text("words") or []:
        r = pymupdf.Rect(w[0], w[1], w[2], w[3])
        if page.rotation not in (0, None):
            r = r * page.rotation_matrix
        out.append({"t": w[4], "x0": round(r.x0, 3), "y0": round(r.y0, 3),
                    "x1": round(r.x1, 3), "y1": round(r.y1, 3)})
    return out


def image_stats(page, doc):
    """Raster images drawn on the page: bbox (displayed), pixel size, digest."""
    out = []
    for info in page.get_image_info() or []:
        bbox = rotated_rect(page, pymupdf_rect(info["bbox"]))
        xref = info.get("xref") or 0
        digest = None
        if xref:
            try:
                digest = hashlib.sha256(doc.xref_stream(xref)).hexdigest()[:16]
            except Exception:
                digest = None
        out.append({"bbox": bbox, "pixel_width": info.get("width"),
                    "pixel_height": info.get("height"), "stream_sha": digest})
    return out


CURVE_SUBDIVISIONS = 8


def segments_of_page(page):
    """Flatten all drawing items into straight segments (displayed space).

    Same flattening extract_geometry.py has always used (lines, beziers -> 8
    chords, rects/quads -> 4 edges each), now shared so counts and geometry
    agree across tools. Returns list of (x0, y0, x1, y1, width) tuples.
    """
    import pymupdf
    segs = []
    m = page.rotation_matrix if page.rotation not in (0, None) else None

    def tx(p):
        q = pymupdf.Point(p.x, p.y)
        if m is not None:
            q = q * m
        return (q.x, q.y)

    for d in page.get_drawings():
        w = round(float(d.get("width") or 0.0), 3)
        for item in d["items"]:
            op = item[0]
            if op == "l":
                a, b = tx(item[1]), tx(item[2])
                segs.append((a[0], a[1], b[0], b[1], w))
            elif op == "c":
                p0, p1, p2, p3 = item[1], item[2], item[3], item[4]
                pts = [tx(p0)]
                for k in range(1, CURVE_SUBDIVISIONS + 1):
                    t = k / CURVE_SUBDIVISIONS
                    mt = 1 - t
                    x = (mt**3 * p0.x + 3 * mt**2 * t * p1.x
                         + 3 * mt * t**2 * p2.x + t**3 * p3.x)
                    y = (mt**3 * p0.y + 3 * mt**2 * t * p1.y
                         + 3 * mt * t**2 * p2.y + t**3 * p3.y)
                    pts.append((x, y))
                for i in range(len(pts) - 1):
                    segs.append((pts[i][0], pts[i][1],
                                 pts[i + 1][0], pts[i + 1][1], w))
            elif op == "re":
                r = item[1]
                corners = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
                for i in range(4):
                    a, b = tx(pymupdf.Point(*corners[i])), tx(pymupdf.Point(*corners[(i + 1) % 4]))
                    segs.append((a[0], a[1], b[0], b[1], w))
            elif op == "qu":
                q = item[1]
                corners = [q.ul, q.ur, q.lr, q.ll]
                for i in range(4):
                    a, b = tx(corners[i]), tx(corners[(i + 1) % 4])
                    segs.append((a[0], a[1], b[0], b[1], w))
    return [(round(s[0], 4), round(s[1], 4), round(s[2], 4), round(s[3], 4), s[4])
            for s in segs]


def drawing_stats(page):
    """Vector-operator counts + flattened segment count + bounds (displayed)."""
    ops = {"l": 0, "c": 0, "re": 0, "qu": 0}
    for d in page.get_drawings():
        for item in d["items"]:
            if item[0] in ops:
                ops[item[0]] += 1
    segs = segments_of_page(page)
    bounds = None
    if segs:
        xs = [s[0] for s in segs] + [s[2] for s in segs]
        ys = [s[1] for s in segs] + [s[3] for s in segs]
        bounds = [round(min(xs), 2), round(min(ys), 2),
                  round(max(xs), 2), round(max(ys), 2)]
    return {"op_counts": ops, "segment_count": len(segs), "segment_bounds": bounds}


def page_fingerprint(page, images):
    """Content fingerprint: segments + word boxes + image digests.

    Identical content on two pages -> identical fingerprint (duplicate-page
    detection); different content under the same sheet id -> revision
    conflict. Computed in displayed space with stable rounding. `images` is
    the list returned by image_stats() (pass [] to skip).
    """
    seg_pairs = sorted([s[0], s[1], s[2], s[3]] for s in segments_of_page(page))
    words = sorted([w["t"], w["x0"], w["y0"], w["x1"], w["y1"]]
                   for w in words_of_page(page))
    imgs = sorted((i.get("stream_sha") or "?") for i in images)
    return digest_obj({"segments": seg_pairs, "words": words, "images": imgs})


def classify_page(segment_count, image_cover_pct, text_chars):
    """Classify page content. Text never implies vector suitability."""
    reasons = []
    if image_cover_pct >= IMAGE_COVER_FULL:
        if segment_count >= MIN_VECTOR_SEGMENTS:
            cls = "hybrid"
            reasons.append(f"image covers {image_cover_pct:.0f}% of the page AND"
                           f" {segment_count} vector segments exist - a scan"
                           " pasted over vector furniture (often title block"
                           " only); vector linework cannot be trusted here")
        elif text_chars >= MIN_TEXT_CHARS:
            cls = "searchable_raster"
            reasons.append(f"image covers {image_cover_pct:.0f}% of the page with"
                           f" {text_chars} chars of (OCR) text but only"
                           f" {segment_count} vector segments: a searchable scan -"
                           " text presence does NOT make it measurable")
        else:
            cls = "raster"
            reasons.append(f"image covers {image_cover_pct:.0f}% of the page,"
                           f" {segment_count} vector segments, {text_chars} text"
                           " chars")
    elif image_cover_pct >= IMAGE_COVER_VECTOR_MAX:
        cls = "hybrid" if segment_count >= MIN_VECTOR_SEGMENTS else "uncertain"
        reasons.append(f"image covers {image_cover_pct:.0f}% of the page with"
                       f" {segment_count} vector segments")
    elif segment_count >= MIN_VECTOR_SEGMENTS:
        cls = "vector"
        reasons.append(f"{segment_count} vector segments, image coverage"
                       f" {image_cover_pct:.0f}%")
    elif text_chars >= MIN_TEXT_CHARS:
        cls = "text_only"
        reasons.append(f"text page ({text_chars} chars), only"
                       f" {segment_count} vector segments - fine for schedules/"
                       " notes, not for measuring linework")
    else:
        cls = "uncertain"
        reasons.append(f"little content: {segment_count} segments,"
                       f" {text_chars} chars, {image_cover_pct:.0f}% image")
    return {"class": cls, "reasons": reasons}
