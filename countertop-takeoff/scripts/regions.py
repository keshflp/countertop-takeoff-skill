"""Region measurement from selected boundary segments (V2).

V1 kept every segment inside a bbox, polygonized, and took the smallest face
containing the seed. That made scope fuzzy (bbox windows), crashed with
TypeError when nothing polygonized (``nearest=None``), accepted a seed ON the
boundary via ``.covers()``, silently applied gross or net areas depending on
which face was smallest, and passed a duplicated region at double area.

V2 rules (all errors are hard stops with explicit messages):
  - the agent selects the boundary segment IDs; code builds the polygon
  - the selection must close into EXACTLY one cycle (every node degree 2);
    dangling endpoints (open boundary, stray hatch tick) and branched nodes
    (ambiguous junction) are named in the error
  - the seed must be STRICTLY interior (boundary distance > 0), never on the
    shell
  - gross-area policy is explicit: "gross" ignores inner loops; declared
    cutouts are subtracted only under "net_of_declared_cutouts"
  - counted instances must not overlap: two base regions of the same
    (type, variant) sharing any area is a hard fail (the v1 208.75 SF bug);
    cross-type overlap warns
"""

import hashlib
import json
import math
import os

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from image_measure import measure_from_points
from spec_schema import TakeoffError, finite

SEED_MARGIN_PT = 0.01          # seed must sit this far inside the shell
OVERLAP_EPS_PT2 = 1e-6         # polygon overlap tolerance in pt^2
SNAP_DEFAULT = 0.05            # endpoint snap grid, pt


class RegionError(TakeoffError):
    pass


def measure_region_image(region, base_dir):
    """P0.6 route 3: ingest an image_measure.py result for one region.

    V4 acceptance rules (P0.2) - ALL must hold before an area is accepted:
      1. the crop file exists and its sha256 matches the recorded hash
         (integrity: proves WHICH pixels were measured)
      2. the crop is BOUND to (source_id, page, crop_bbox, render_zoom) and
         that binding matches the region's own source/page
      3. the recorded selections (anchors + boundary points) are present
         and the area is RECOMPUTED from them; a recorded result number
         that does not reproduce from unchanged selections is REJECTED
         (edited result numbers over unchanged pixels never pass)
      4. the OVERLAY PROOF exists on disk (mandatory for route acceptance)
    Unusable rasters (any warning on the recomputation) stay BLANK with the
    warnings carried into the record for callouts - never guessed.
    """
    rid = region["region_id"]
    base = {
        "region_id": rid, "kind": region.get("kind", "base"),
        "of": region.get("of"), "type": region.get("type"),
        "variant": region.get("variant"), "page": region["page"],
        "source_id": region.get("source_id"),
        "viewport": region.get("viewport") or "main",
        "sheet": region.get("sheet") or "?",
        "route": "image", "expected_sf_range": region.get("expected_sf_range"),
    }
    path = region["image_measurement"]
    if not os.path.isabs(path) and not os.path.exists(path):
        path = os.path.join(base_dir, path)
    rng = region.get("expected_sf_range") or [0, 1]
    ok = lambda area: bool(area is not None and rng[0] <= area <= rng[1])
    if not os.path.exists(path):
        return dict(base, status="unresolved",
                    unresolved_reason=f"image measurement file missing: {path}",
                    blank_fields=["area_sf"], area_sf=None,
                    factor_px_per_ft=None, expected_range_ok=False)
    m = json.load(open(path, encoding="utf-8"))
    crop = m.get("crop")
    if crop and not os.path.isabs(crop) and not os.path.exists(crop):
        crop = os.path.join(base_dir, crop)
    crop_ok = True
    if crop and os.path.exists(crop):
        got = hashlib.sha256(open(crop, "rb").read()).hexdigest()
        crop_ok = got == m.get("crop_sha256")
    else:
        crop_ok = False
    warnings = list(m.get("warnings") or [])
    if not crop_ok:
        warnings.insert(0, "crop hash mismatch - the measurement does not"
                        " prove which pixels it read; re-render and"
                        " re-measure")
    # ---- P0.2: crop must bind to (source, page, transform) -----------
    prov = m.get("provenance") or {}
    if not prov.get("source_id") or not prov.get("page") \
            or not prov.get("crop_bbox") or not prov.get("render_zoom"):
        warnings.insert(0, "image measurement is NOT bound to (source, page,"
                        " transform): provenance (source_id, page, crop_bbox,"
                        " render_zoom) missing - re-run image_measure.py with"
                        " --source-id/--page/--crop-bbox/--render-zoom")
    else:
        if prov["source_id"] != region.get("source_id") \
                or int(prov["page"]) != int(region["page"]):
            warnings.insert(0, f"crop provenance mismatch: measurement claims"
                            f" source {prov['source_id']!r} page"
                            f" {prov['page']} but the region is on"
                            f" {region.get('source_id')!r} page"
                            f" {region['page']}")
    # ---- P0.2: overlay proof is REQUIRED for acceptance ---------------
    overlay = m.get("overlay")
    if overlay and not os.path.isabs(overlay) and not os.path.exists(overlay):
        overlay = os.path.join(base_dir, overlay)
    if not overlay or not os.path.exists(overlay):
        warnings.insert(0, "overlay proof missing - the image route is not"
                        " accepted without the anchor/boundary overlay"
                        " rendered by image_measure.py")
    # ---- P0.2: RECOMPUTE from the recorded selections -----------------
    selections = m.get("selections") or {}
    re_anchors = selections.get("anchors") or m.get("anchors") or []
    re_points = selections.get("points")
    if re_points is None:
        poly = m.get("polygon_px") or []
        re_points = [{"name": f"p{i + 1}", "px": list(p)}
                     for i, p in enumerate(poly)]
    recomputed = None
    recomputed_scale = None
    if re_anchors and re_points:
        sel = measure_from_points(re_anchors, re_points)
        recomputed = sel.get("area_sf")
        recomputed_scale = sel.get("px_per_ft")
        for w in sel.get("warnings") or []:
            if w not in warnings:
                warnings.append(f"recomputed selections: {w}")
    else:
        warnings.append("recorded selections missing - the result cannot be"
                        " recomputed from unchanged pixels; re-measure")
    recorded = m.get("area_sf")
    if recomputed is not None and recorded is not None \
            and abs(recomputed - recorded) > max(0.01, 0.002 * recorded):
        warnings.insert(0, f"RECORDED RESULT REJECTED: area_sf {recorded} does"
                        f" not reproduce from the recorded selections"
                        f" (recomputed {recomputed}) - an edited result number"
                        " over unchanged pixels is never accepted")
    area = recomputed if recomputed is not None else None
    if area is None or warnings:
        return dict(base, status="unresolved",
                    unresolved_reason="; ".join(warnings)
                    or "image measurement unusable",
                    blank_fields=["area_sf"], area_sf=None,
                    measured_area_sf=area,
                    factor_px_per_ft=(recomputed_scale or m.get("px_per_ft")),
                    image_quality=m.get("quality"), expected_range_ok=False,
                    crop_sha256=m.get("crop_sha256"),
                    provenance=prov or None,
                    overlay=overlay if (overlay and os.path.exists(overlay))
                    else None)
    return dict(base, status="measured", area_sf=area,
                recorded_area_sf=recorded,
                factor_px_per_ft=(recomputed_scale or m.get("px_per_ft")),
                image_quality=m.get("quality"),
                image_warnings=[w for w in warnings if w],
                crop_sha256=m.get("crop_sha256"),
                provenance=prov or None, overlay=overlay,
                expected_range_ok=ok(area),
                polygon=[[float(x), float(y)] for x, y in
                         (m.get("polygon_px") or [])])


def _snap(v, tol):
    return round(v / tol) * tol if tol > 0 else v


def shell_from_segments(segments, seg_ids, label, snap_tol=SNAP_DEFAULT):
    """Build ONE closed polygon from selected segments.

    Raises RegionError when the selection does not close into a single
    simple cycle, naming the offending nodes so the agent can fix the
    selection. No nearest-face fallback, ever.
    """
    by_id = {s["id"]: s for s in segments}
    missing = [i for i in seg_ids if i not in by_id]
    if missing:
        raise RegionError(
            f"{label}: boundary segment ids {missing} are not in the geometry"
            " - re-extract or fix the selection")
    seen_pairs = set()
    lines = []
    for i in seg_ids:
        s = by_id[i]
        a = (_snap(s["x0"], snap_tol), _snap(s["y0"], snap_tol))
        b = (_snap(s["x1"], snap_tol), _snap(s["y1"], snap_tol))
        if a == b:
            continue  # zero-length after snapping
        key = tuple(sorted([a, b]))
        if key in seen_pairs:
            raise RegionError(
                f"{label}: boundary contains the same segment twice"
                f" (endpoints {key}) - duplicated selection")
        seen_pairs.add(key)
        lines.append((a, b))
    if not lines:
        raise RegionError(f"{label}: all selected segments collapse to zero"
                          " length - wrong selection")
    # node the graph: every vertex must have degree exactly 2
    adj = {}
    for a, b in lines:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    bad = {v: len(nbrs) for v, nbrs in adj.items() if len(nbrs) != 2}
    if bad:
        kind = ("dangling endpoints - the boundary does not close"
                " (hatch tick included? dimension line? missing segment?)"
                if any(d == 1 for d in bad.values())
                else "branched nodes - ambiguous junction (two loops touching)")
        worst = sorted(bad.items(), key=lambda kv: -kv[1])[:4]
        raise RegionError(
            f"{label}: boundary selection is not a single closed loop. "
            f"{kind}. Offending nodes (degree): "
            + ", ".join(f"({v[0]:.2f}, {v[1]:.2f}) deg {d}" for v, d in worst)
            + f". Selected {len(seg_ids)} segments.")
    # walk the single cycle
    start = next(iter(adj))
    ring = [start]
    prev, cur = None, start
    while True:
        nxt = [n for n in adj[cur] if n != prev]
        if not nxt:
            break
        prev, cur = cur, nxt[0]
        if cur == start:
            break
        ring.append(cur)
    if cur != start or len(ring) != len(adj):
        raise RegionError(
            f"{label}: selection closes into more than one loop or does not"
            f" return to start (walked {len(ring)} of {len(adj)} nodes) -"
            " split it into separate regions or fix the selection")
    poly = Polygon(ring)
    if not poly.is_valid or poly.area <= 0:
        raise RegionError(
            f"{label}: boundary closes into an invalid/self-intersecting or"
            " zero-area polygon - check the selection")
    return poly


def _require_strict_interior(poly, seed, label):
    p = Point(seed[0], seed[1])
    if not poly.contains(p):
        if poly.boundary.distance(p) <= SEED_MARGIN_PT:
            raise RegionError(
                f"{label}: seed ({seed[0]}, {seed[1]}) lies ON or within"
                f" {SEED_MARGIN_PT} pt of the boundary - v1's covers() accepted"
                " boundary-on-seed; v2 requires a strictly interior seed")
        raise RegionError(
            f"{label}: seed ({seed[0]}, {seed[1]}) is not inside the measured"
            " boundary - pick a point strictly inside the countertop")


def _cutout_polygons(region, segments, label, snap_tol):
    out = []
    for c in region.get("cutouts", []) or []:
        poly = shell_from_segments(segments, c["seg_ids"],
                                   f"{label} cutout {c['label']}", snap_tol)
        out.append((c["label"], poly))
    return out


def measure_region(region, page, factor, policy, snap_tol=SNAP_DEFAULT,
                   viewport_box=None):
    """Measure one region dict against one geometry page.

    factor: pt per real foot for this region's (page, viewport) - the ACTUAL
    factor used, recorded in the result. policy: gross-area policy string.
    viewport_box: the viewport's displayed bounding box, when declared; the
    region seed must sit inside it (a region outside its viewport is a
    selection error, not a measurement).
    """
    rid = region["region_id"]
    label = f"region {rid} on page {region['page']}"
    if viewport_box is not None:
        sx, sy = region["seed"]
        if not (viewport_box[0] <= sx <= viewport_box[2]
                and viewport_box[1] <= sy <= viewport_box[3]):
            raise RegionError(
                f"{label}: seed ({sx}, {sy}) lies OUTSIDE the viewport_box"
                f" {viewport_box} - a region belongs to the viewport it"
                " draws in")
    segs = page["segments"]
    shell = shell_from_segments(segs, region["boundary"]["seg_ids"],
                                label, snap_tol)
    _require_strict_interior(shell, region["seed"], label)
    by_id = {s["id"]: s for s in segs}
    curved = any(by_id[i].get("op") == "c"
                 for i in region["boundary"]["seg_ids"])
    cutouts = _cutout_polygons(region, segs, label, snap_tol)
    gross_sf = shell.area / factor ** 2
    applied = "gross"
    for cname, cpoly in cutouts:
        if not shell.contains(cpoly):
            raise RegionError(
                f"{label}: cutout {cname!r} is not fully inside the boundary"
                " - cutouts must be inner loops of the region")
    area_pt2 = shell.area
    if policy == "net_of_declared_cutouts":
        # regions with no observed cutouts legitimately declare none; the
        # overlay + independent review validate that assertion visually
        applied = "net"
        if cutouts:
            area_pt2 = shell.area - unary_union([p for _, p in cutouts]).area
    elif cutouts:
        applied = "gross (cutouts observed, NOT subtracted)"
    area_sf = area_pt2 / factor ** 2
    if not finite(area_sf) or area_sf <= 0:
        raise RegionError(f"{label}: non-finite or non-positive area")
    rng = region["expected_sf_range"]
    result = {
        "region_id": rid, "kind": region.get("kind", "base"),
        "of": region.get("of"), "type": region["type"],
        "variant": region.get("variant"), "page": region["page"],
        "source_id": region.get("source_id"),
        "viewport": region.get("viewport") or "main",
        "sheet": region.get("sheet") or page.get("sheet") or "?",
        "assembly": region.get("assembly"),
        "material_canonical": region.get("material_canonical"),
        "boundary_seg_ids": region["boundary"]["seg_ids"],
        "cutouts": [c for c in region.get("cutouts", []) or []],
        "seed": list(region["seed"]),
        "polygon": [list(xy) for xy in shell.exterior.coords[:-1]],
        "cutout_polygons": [[list(xy) for xy in p.exterior.coords[:-1]]
                            for _, p in cutouts],
        "vertices": len(shell.exterior.coords) - 1,
        "area_pt2": round(area_pt2, 4),
        "gross_area_sf": round(gross_sf, 4),
        "area_sf": round(area_sf, 4),
        "factor_pt_per_ft": round(factor, 6),
        "gross_area_policy": applied,
        "curved_boundary": curved,
        "expected_sf_range": rng,
    }
    result["expected_range_ok"] = rng[0] <= area_sf <= rng[1]
    return result


def _same_page(a, b):
    """Duplicate/overlap scope key: (source_id, page). V2 compared page
    numbers alone, so the same page number on two different sources
    (PDF page 2 vs DXF modelspace page 2) collided."""
    return (a.get("source_id"), a["page"]) == (b.get("source_id"), b["page"])


def check_duplicate_boundaries(results):
    """Two base regions selected via identical segment sets on the SAME
    (source, page) = one region measured twice (a scope error, not a
    spot-check). Cross-source identical ids are unrelated."""
    errors = []
    base = [r for r in results if r["kind"] == "base"
            and r.get("status") != "unresolved"]
    for i in range(len(base)):
        for j in range(i + 1, len(base)):
            a, b = base[i], base[j]
            if _same_page(a, b) and \
                    set(a["boundary_seg_ids"]) == set(b["boundary_seg_ids"]):
                errors.append(
                    f"regions {a['region_id']!r} and {b['region_id']!r} use"
                    " the identical boundary segment set - one counter cannot"
                    " be two regions")
    return errors


def check_overlaps(results):
    """Counted instances must not overlap on the same (source, page).

    Same (type, variant) overlap = hard fail (the v1 duplicate-Type-B bug
    that passed at 208.75 SF); cross-type overlap = warning (possible
    mirrored plans or a mislabeled bbox) reported for human review.
    """
    errors, warnings = [], []
    base = [r for r in results if r["kind"] == "base"
            and r.get("status") != "unresolved"]
    for i in range(len(base)):
        for j in range(i + 1, len(base)):
            a, b = base[i], base[j]
            if not _same_page(a, b):
                continue
            pa = Polygon(a["polygon"])
            pb = Polygon(b["polygon"])
            inter = pa.intersection(pb).area
            if inter <= OVERLAP_EPS_PT2:
                continue
            inter_sf = inter / (a["factor_pt_per_ft"] ** 2)
            detail = (f"regions {a['region_id']!r} and {b['region_id']!r} on"
                      f" page {a['page']} overlap by {inter_sf:.2f} SF")
            if (a["type"], a["variant"]) == (b["type"], b["variant"]):
                errors.append(detail + " within one counted scope - this is"
                              " how v1 doubled Type B to 208.75 SF and passed")
            else:
                warnings.append(detail + " across different types/variants -"
                                " check for mirrored plans or a selection"
                                " mistake")
    return errors, warnings
