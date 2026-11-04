# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1"]
# ///
"""Shared drawing-pack preflight primitives (V3).

ONE implementation of page statistics, fingerprints, content classes and
content REGIONS, used by index_pdf.py (pack QA report), extract_geometry.py
(records the same values into the geometry JSON) and measure.py (validates
job specs against them). Sharing the code guarantees the digests and classes
recorded by different tools always agree.

Coordinate convention
---------------------
All bboxes/points are in DISPLAYED page space: what a renderer shows, i.e.
page rotation applied AND the crop box as origin. Helpers below transform
content-space values with ``page.rotation_matrix`` so callers never handle
rotation themselves. Every tool output records the source->display transform
(``coordinate_transforms``) and pixel images carry their displayed bbox so
pixel-space crops can be mapped back (the round trip is verified by
``transform_roundtrip_ok``).

Text presence NEVER establishes vector suitability: a searchable raster page
(OCR'd scan) has a full text layer and zero usable linework. Classification
therefore weighs image coverage against flattened segment counts, and the
result is recorded with its reasons so an auditor can re-check it. Since V3,
classification ALSO happens per content REGION inside a sheet: a pasted
raster schedule table under a vector header must neither disappear (it is
recorded as a raster region the agent can render and transcribe) nor
disqualify unrelated vector geometry (regions outside the raster bbox stay
measurable).
"""

import hashlib
import json
import re

SHEET_RE = re.compile(r"(?im)^\s*SHEET\s*[:#]?\s*([A-Z]{0,3}[-\s]?\d{1,4}[A-Z]?)\s*$")
SHEET_FALLBACK_RE = re.compile(r"(?im)^\s*([A-Z]{1,3}-\d{1,4})\s*$")
TYPE_TAG_WORD_RE = re.compile(r"^type$", re.I)

# Classification thresholds, in PERCENT of page area (0-100). V2 defined
# these as fractions (0.20/0.60) but compared them against the percent value
# ``image_cover_pct``, so every page with < 20% image coverage looked like a
# vector page and pages 20-60% were misclassed; the units now match the
# values compared against them (documented in references/method.md, section 2).
IMAGE_COVER_VECTOR_MAX = 20.0   # <= this coverage (percent) can still be a vector page
IMAGE_COVER_FULL = 60.0         # >= this coverage (percent) dominates the page
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


def detect_sheet(text):
    m = SHEET_RE.search(text) or SHEET_FALLBACK_RE.search(text)
    return m.group(1).replace(" ", "-").upper() if m else None


def room_tag_boxes(words):
    """Word-level TYPE X pairs with displayed boxes for room reconciliation."""
    tags = []
    for i, w in enumerate(words):
        if TYPE_TAG_WORD_RE.match(w["t"]):
            nxt = words[i + 1] if i + 1 < len(words) else None
            if nxt and abs(nxt["y0"] - w["y0"]) < (w["y1"] - w["y0"]) * 1.5:
                tags.append({"tag": nxt["t"].upper(), "kind": "type_tag",
                             "box": [w["x0"], w["y0"], nxt["x1"], nxt["y1"]]})
    return tags


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


def coordinate_transforms(page):
    """Record the source->display convention explicitly (V3).

    ``display`` is what renderers show: crop-box origin + rotation applied.
    Recorded per page so crop-offset surprises are visible and so pixel
    crops (rendered in displayed space) can be mapped back to displayed
    points 1:1 at a known zoom.
    """
    crop = page.cropbox
    media = page.mediabox
    return {
        "space": "displayed",
        "rotation_deg": int(page.rotation or 0),
        "displayed_width": round(page.rect.width, 3),
        "displayed_height": round(page.rect.height, 3),
        "cropbox_origin": [round(crop.x0, 3), round(crop.y0, 3)],
        "mediabox_origin": [round(media.x0, 3), round(media.y0, 3)],
        "crop_offset_pt": [round(crop.x0 - media.x0, 3),
                           round(crop.y0 - media.y0, 3)],
        "transform": "displayed = content-space * page.rotation_matrix"
                     " (crop box applied); rendered pixels at zoom Z map to"
                     " displayed points as px / Z",
    }


def transform_roundtrip_ok(points, page_rect, tol_pt=1.0):
    """Round-trip check: displayed-space points must fall inside the
    displayed page rect (catches crop-offset / double-rotation bugs).
    Returns (ok, offenders)."""
    offenders = [p for p in points
                 if not (-tol_pt <= p[0] <= page_rect.width + tol_pt
                         and -tol_pt <= p[1] <= page_rect.height + tol_pt)]
    return (not offenders), offenders[:4]

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
    """Raster images drawn on the page: bbox (displayed), pixel size, digest.

    V3 fix: ``get_image_info(xrefs=True)`` is required. Without xrefs the
    probe showed xref 0 for every placement, so every digest was None and
    two DIFFERENT rasters contributed the same '?' to the page fingerprint
    (duplicate/revision detection silently blind to raster changes). With
    xrefs we hash the actual stored pixels of each placement.
    """
    out = []
    try:
        infos = page.get_image_info(xrefs=True) or []
    except Exception:
        infos = page.get_image_info() or []
    for info in infos:
        bbox = rotated_rect(page, pymupdf_rect(info["bbox"]))
        xref = info.get("xref") or 0
        digest = None
        if xref:
            try:
                digest = hashlib.sha256(doc.xref_stream(xref)).hexdigest()[:16]
            except Exception:
                digest = None
        out.append({"bbox": bbox, "pixel_width": info.get("width"),
                    "pixel_height": info.get("height"),
                    "xref": xref or None, "stream_sha": digest})
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
    """Classify page content from PERCENT image coverage.
    Text never implies vector suitability."""
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


def _rects_overlap(a, b, pad=0.0):
    return not (a[2] + pad < b[0] or b[2] + pad < a[0]
                or a[3] + pad < b[1] or b[3] + pad < a[1])


def _point_in_rect(p, r, pad=0.0):
    return (r[0] - pad <= p[0] <= r[2] + pad and r[1] - pad <= p[1] <= r[3] + pad)


def content_regions(page, images, segments, words):
    """Classify content REGIONS inside one sheet (V3).

    A page can mix a pasted raster table and unrelated vector linework. The
    page-level class alone either hides the raster (so the schedule bitmap
    under a vector 'ROOM DISTRIBUTION' header is never read) or condemns the
    whole sheet as hybrid (so unrelated vector geometry becomes unmeasurable).
    Both are wrong. This splits the sheet into:

      raster regions  - merged image bboxes; carry pixel digest + how many
                        text words sit inside (few/no words under a schedule
                        title => suspected bitmap table for vision reading)
      vector regions  - bounding box of the segments OUTSIDE every raster
                        region; measurable when class == 'vector'

    Returns a list sorted raster-first. Region bboxes are displayed-space.
    """
    regions = []
    merged = []
    for im in images:
        bb = im["bbox"]
        hit = None
        for m in merged:
            if _rects_overlap(bb, m["bbox"], pad=2.0):
                hit = m
                break
        if hit:
            hit["bbox"] = [min(hit["bbox"][0], bb[0]), min(hit["bbox"][1], bb[1]),
                           max(hit["bbox"][2], bb[2]), max(hit["bbox"][3], bb[3])]
            hit["images"].append(im)
        else:
            merged.append({"bbox": list(bb), "images": [im]})
    raster_boxes = []
    for m in merged:
        words_in = [w for w in words if _point_in_rect(
            ((w["x0"] + w["x1"]) / 2.0, (w["y0"] + w["y1"]) / 2.0), m["bbox"])]
        # effective resolution: best single image's pixel density over its
        # own displayed bbox (inches = points / 72)
        ppis = []
        for i in m["images"]:
            bb = i["bbox"]
            w_in = max(0.01, (bb[2] - bb[0]) / 72.0)
            h_in = max(0.01, (bb[3] - bb[1]) / 72.0)
            if i.get("pixel_width") and i.get("pixel_height"):
                ppis.append(min(i["pixel_width"] / w_in,
                                i["pixel_height"] / h_in))
        ppi = max(ppis) if ppis else 0.0
        regions.append({
            "kind": "raster", "bbox": [round(v, 2) for v in m["bbox"]],
            "image_count": len(m["images"]),
            "stream_shas": sorted({i.get("stream_sha") or "?"
                                   for i in m["images"]}),
            "words_inside": len(words_in),
            "pixels_per_inch": round(ppi, 1),
            "suspect_table": len(words_in) <= 2,
            "class": "raster",
            "note": "render a legible crop of this region and read it with"
                    " vision; do not measure its pixels as vectors",
        })
        raster_boxes.append(m["bbox"])
    outside = [s for s in segments
               if not any(_point_in_rect(((s[0] + s[2]) / 2.0,
                                          (s[1] + s[3]) / 2.0), rb, pad=1.0)
                          for rb in raster_boxes)]
    if outside:
        xs = [s[0] for s in outside] + [s[2] for s in outside]
        ys = [s[1] for s in outside] + [s[3] for s in outside]
        vbbox = [round(min(xs), 2), round(min(ys), 2),
                 round(max(xs), 2), round(max(ys), 2)]
        inside_words = [w for w in words
                        if not any(_point_in_rect(
                            ((w["x0"] + w["x1"]) / 2.0,
                             (w["y0"] + w["y1"]) / 2.0), rb)
                            for rb in raster_boxes)]
        regions.append({
            "kind": "vector", "bbox": vbbox,
            "segment_count": len(outside),
            "words_inside": len(inside_words),
            "class": ("vector" if len(outside) >= MIN_VECTOR_SEGMENTS
                      else "sparse_vector"),
            "note": ("vector linework OUTSIDE the raster region(s);"
                     " measurable with its own calibration"
                     if len(outside) >= MIN_VECTOR_SEGMENTS else
                     "only stray vector marks outside the raster region(s)"),
        })
    return regions
