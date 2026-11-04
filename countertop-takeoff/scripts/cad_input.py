# /// script
# requires-python = ">=3.9"
# dependencies = ["ezdxf==1.4.2"]
# ///
"""Supplied native-CAD input: DXF adapter (V4 measurement route 2).

Route order (P0.6): (1) vector PDF geometry, (2) supplied native CAD via
THIS adapter, (3) calibrated image-space measurement, (4) optional CAD-MCP
escalation - see references/cad-context.md (documentation only, never a
runtime dependency).

V4 correctness fixes (P0.4):
  - metre conversion FIXED: 0.3048 drawing units per real foot (was 3.048
    - a 25 SF rectangle computed 0.25 SF); miles/yards/km had the same
    ft-per-unit vs units-per-ft inversion and are corrected too
  - $INSUNITS table corrected: 8 = MICROINCHES (not microns); mils, miles,
    km, microns, decimeters, US survey feet added
  - MINSERT rectangular arrays are EXPANDED row x col (ezdxf's
    virtual_entities() yields only the first insert); arrays above the
    expansion cap are skipped with a named callout
  - layer-0 children inherit the INSERT's EFFECTIVE layer; layer filtering
    happens AFTER block expansion, never before
  - polyline bulges become disclosed arc approximations: chords are added
    per curve so the AREA error stays <= 0.5% of the curve's own sector
    (the tolerance is recorded in the payload and disclosed as a callout)
  - entities with non-standard OCS transforms (extrusion != +Z) are named
    local exclusions (op + handle recorded, never silently measured)

DWG is NOT directly supported by this skill. Convert DWG -> DXF with the
free ODA File Converter (https://www.opendesign.com) first, then run this
script. Nothing here reads DWG binaries.

Unit verification (the accuracy hierarchy demands it):
  - $INSUNITS present -> units are recorded and factor derived from them
  - $INSUNITS == 0 / absent -> the file is UNITLESS: pass --units
    <in|ft|mm|cm|m> to declare them (recorded as operator-verified, with a
    warning + callout); without --units the import REFUSES - a unitless
    file has no honest scale
  - the verified units then act as the calibration for every region on
    this source (code-computed, never typed by the agent)

Output JSON matches the extract_geometry.py shape so measure.py can ingest
it as an additional source:
  pages[0] = {page: 1, segments: [{id, layer, handle, x0..}], words: [...]}
  source = {sha256, page_count: 1, kind: "cad", units, units_verified,
            units_per_ft, unsupported_entities, callouts}

Usage:
    uv run scripts/cad_input.py <file.dxf> --out build/<name>.cad.json
        [--units in|ft|mm|cm|m] [--layers A-101,COUNTER]
"""

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from preflight_lib import file_sha256

ARC_AREA_TOL = 0.005      # max chord-approximation area error per curve (0.5%)
ARC_MIN_SEGMENTS = 8      # never fewer than 8 chords per curve
ARC_MAX_SEGMENTS = 4096   # subdivision cap (degenerate arcs)
MINSERT_CAP = 10000       # max expanded cells per MINSERT array
# $INSUNITS -> drawing units per REAL FOOT (units-per-ft semantics: the
# factor divides drawing lengths to get feet). 8 is MICROINCHES (1e-6 in),
# NOT microns; 13 is microns. 6 (metres) is 0.3048 m per ft - the V3 value
# 3.048 was decimetres per foot and made every metric file 10x off; miles,
# yards and km had the same inversion in early V4 and are corrected here.
INSUNITS_PER_FT = {
    1: 12.0,                    # inches
    2: 1.0,                     # feet
    3: 1.0 / 5280.0,            # miles (1 ft = 1/5280 mile)
    4: 304.8,                   # millimeters
    5: 30.48,                   # centimeters
    6: 0.3048,                  # meters  (1 ft = 0.3048 m)
    7: 0.0003048,               # kilometers
    8: 12_000_000.0,            # MICROINCHES (12 in x 1e6)
    9: 12_000.0,                # mils (0.001 in)
    10: 1.0 / 3.0,              # yards (1 ft = 1/3 yd)
    13: 304_800.0,              # microns
    14: 3.048,                  # decimeters
    20: 1200.0 / 3937.0,        # US survey feet
}
INSUNITS_NAMES = {1: "in", 2: "ft", 3: "mile", 4: "mm", 5: "cm", 6: "m",
                  7: "km", 8: "microinch", 9: "mil", 10: "yd",
                  13: "micron", 14: "dm",
                  20: "us_survey_ft"}
DECLARED_PER_FT = {"in": 12.0, "ft": 1.0, "mm": 304.8, "cm": 30.48,
                   "m": 0.3048}
UNSUPPORTED_OPS = {"HATCH", "DIMENSION", "LEADER", "MLINE", "3DSOLID",
                   "REGION", "BODY", "IMAGE", "WIPEOUT", "OLE2FRAME"}


def resolve_units(doc, declared):
    """Returns (units_name, units_per_ft, verified, warning|None).
    Raises SystemExit when the file is unitless and nothing was declared."""
    insunits = 0
    try:
        var = doc.header.get("$INSUNITS")
        if var is not None:
            insunits = int(var)
    except Exception:
        insunits = 0
    if insunits in INSUNITS_PER_FT:
        name = INSUNITS_NAMES.get(insunits, f"insunits-{insunits}")
        return name, INSUNITS_PER_FT[insunits], True, None
    if declared:
        if declared not in DECLARED_PER_FT:
            print(f"ERROR: --units must be one of"
                  f" {sorted(DECLARED_PER_FT)}", file=sys.stderr)
            sys.exit(2)
        return (declared, DECLARED_PER_FT[declared], False,
                "drawing is UNITLESS ($INSUNITS missing/0); units declared on"
                " the command line and recorded as OPERATOR-VERIFIED - the"
                " warning is repeated in the job's callouts")
    print(
        "ERROR: this DXF is UNITLESS ($INSUNITS missing or 0). A unitless"
        " drawing has no honest scale: re-export with units, or pass"
        " --units in|ft|mm|cm|m to declare them explicitly (the declaration"
        " is recorded as operator-verified with a warning + callout)",
        file=sys.stderr)
    sys.exit(2)


def arc_chord_count(angle_rad, tol=ARC_AREA_TOL):
    """Minimum chord count so the chord polygon's AREA error vs the true
    arc sector stays <= tol (relative). Solved from the exact deficit
    n*(theta/n - sin(theta/n)) / theta; capped for degenerate input."""
    theta = abs(float(angle_rad))
    if theta <= 1e-9:
        return ARC_MIN_SEGMENTS
    n = ARC_MIN_SEGMENTS
    while n < ARC_MAX_SEGMENTS:
        seg = theta / n
        deficit = n * (seg - math.sin(seg)) / theta
        if deficit <= tol:
            return n
        n += 1
    return ARC_MAX_SEGMENTS


def arc_segments(center, radius, a0, a1, segs, emit_meta, ccw=True):
    """Emit chords for an arc from a0 to a1 (radians). CCW arcs run a0->a1;
    CW arcs run a1->a0 (same chord ring, reversed direction)."""
    sweep = (a1 - a0) % (2.0 * math.pi) if ccw else -((a0 - a1) % (2.0 * math.pi))
    n = arc_chord_count(abs(sweep) if abs(sweep) > 1e-9 else 2.0 * math.pi)
    prev = None
    steps = max(2, n)
    for k in range(steps + 1):
        a = a0 + sweep * k / steps
        p = (center[0] + radius * math.cos(a),
             center[1] + radius * math.sin(a))
        if prev is not None:
            emit_meta(prev, p)
        prev = p
    return n


def effective_layer_of(ent, parent_layer):
    """Block children drawn on layer '0' inherit the INSERT's effective
    layer (P0.4); anything else keeps its own layer."""
    layer = ent.dxf.layer if ent.dxf.hasattr("layer") else "?"
    if layer.strip().upper() == "0":
        return parent_layer
    return layer


def _has_bad_extrusion(ent):
    """True when the entity carries a non-standard OCS extrusion (not
    +Z): measuring it as flat 2D geometry would be a silent transform."""
    try:
        if not ent.dxf.hasattr("extrusion"):
            return False
        e = ent.dxf.extrusion
        vec = (float(e[0]), float(e[1]), float(e[2]))
        return abs(vec[0]) > 1e-9 or abs(vec[1]) > 1e-9 or vec[2] < 0.999
    except Exception:
        return False


def flatten_entity(ent, segs, texts, unsupported, units_per_ft,
                   parent_layer="0", offset=(0.0, 0.0), arc_stats=None):
    """One entity -> segments (drawing units) / word records. Block inserts
    are expanded via virtual_entities so transforms apply; MINSERT arrays
    are expanded row x col with the array offsets rotated onto the insert's
    axes. Segments carry their EFFECTIVE layer (layer-0 children inherit
    the insert's layer) and an optional array-cell offset."""
    op = ent.dxftype()
    handle = ent.dxf.handle if ent.dxf.hasattr("handle") else "?"
    layer = effective_layer_of(ent, parent_layer)

    def emit(p1, p2):
        segs.append({"x0": round(p1[0] + offset[0], 6),
                     "y0": round(p1[1] + offset[1], 6),
                     "x1": round(p2[0] + offset[0], 6),
                     "y1": round(p2[1] + offset[1], 6),
                     "layer": layer, "handle": handle})

    if _has_bad_extrusion(ent) and op not in ("INSERT",):
        unsupported.append({"op": op, "handle": handle,
                            "layer": layer,
                            "reason": "non-standard OCS extrusion (transform)"
                                     " not measured - named local exclusion"})
        return
    if op == "LINE":
        emit((ent.dxf.start.x, ent.dxf.start.y),
             (ent.dxf.end.x, ent.dxf.end.y))
    elif op in ("LWPOLYLINE", "POLYLINE"):
        bulged = False
        if op == "LWPOLYLINE":
            try:
                bulged = any(abs(float(p[2])) > 1e-12
                             for p in ent.get_points("xyb"))
            except Exception:
                bulged = False
        if bulged:
            # P0.4: bulged vertices are ARCS. ezdxf's virtual_entities()
            # yields them as LINE/ARC entities - flatten each arc with the
            # disclosed 0.5%-area-error chord tolerance.
            try:
                for sub in ent.virtual_entities():
                    if sub.dxftype() == "LINE":
                        emit((sub.dxf.start.x, sub.dxf.start.y),
                             (sub.dxf.end.x, sub.dxf.end.y))
                    elif sub.dxftype() == "ARC":
                        _emit_arc(sub, emit, arc_stats)
            except Exception as exc:
                unsupported.append({"op": op, "handle": handle,
                                    "layer": layer,
                                    "reason": f"bulge expansion failed: {exc}"})
            return
        try:
            pts = [tuple(p)[:2] for p in ent.vertices()] if op == "LWPOLYLINE" \
                else [tuple(v.dxf.location)[:2] for v in ent.vertices]
        except Exception:
            unsupported.append({"op": op, "handle": handle, "layer": layer,
                                "reason": "could not read vertices"})
            return
        closed = bool(getattr(ent, "closed", False)) or op == "POLYLINE" \
            and ent.dxf.hasattr("flags") and (ent.dxf.flags & 1)
        n = len(pts)
        if n < 2:
            unsupported.append({"op": op, "handle": handle, "layer": layer,
                                "reason": "fewer than 2 vertices"})
            return
        last = n if closed else n - 1
        for i in range(last):
            emit(pts[i], pts[(i + 1) % n])
    elif op == "ARC":
        _emit_arc(ent, emit, arc_stats)
    elif op == "CIRCLE":
        c = (ent.dxf.center.x, ent.dxf.center.y)
        r = ent.dxf.radius
        used = arc_segments(c, r, 0.0, 2.0 * math.pi, None, emit)
        if arc_stats is not None:
            arc_stats.append({"op": "CIRCLE", "handle": handle,
                              "chords": used,
                              "area_error_pct": ARC_AREA_TOL * 100.0})
    elif op in ("TEXT", "MTEXT"):
        try:
            if op == "TEXT":
                txt = ent.dxf.text
                pos = (ent.dxf.insert.x, ent.dxf.insert.y)
                h = ent.dxf.height or 2.0
            else:
                txt = ent.plain_text()
                pos = (ent.dxf.insert.x, ent.dxf.insert.y)
                h = ent.dxf.char_height or 2.0
            txt = " ".join(txt.split())
            if txt:
                for i, word in enumerate(txt.split(" ")):
                    texts.append({"t": word,
                                  "x0": round(pos[0] + i * h * 0.6, 4),
                                  "y0": round(pos[1], 4),
                                  "x1": round(pos[0] + (i + 1) * h * 0.6, 4),
                                  "y1": round(pos[1] + h, 4),
                                  "layer": layer})
        except Exception:
            unsupported.append({"op": op, "handle": handle,
                                "reason": "could not read text"})
    elif op == "INSERT":
        # P0.4: expand MINSERT rectangular arrays row x col. ezdxf's
        # virtual_entities() yields only ONE cell; the array offsets are
        # applied here, rotated onto the insert's own axes. Skipped arrays
        # (cap) and failed expansions become named callouts.
        try:
            rows = max(1, int(ent.dxf.get("row_count", 1) or 1))
            cols = max(1, int(ent.dxf.get("column_count", 1) or 1))
            rspace = float(ent.dxf.get("row_spacing", 0.0) or 0.0)
            cspace = float(ent.dxf.get("column_spacing", 0.0) or 0.0)
            rot = math.radians(float(ent.dxf.get("rotation", 0.0) or 0.0))
        except Exception:
            rows, cols, rspace, cspace, rot = 1, 1, 0.0, 0.0, 0.0
        cells = rows * cols
        if cells > MINSERT_CAP:
            unsupported.append({"op": "MINSERT", "handle": handle,
                                "layer": layer,
                                "reason": f"array {rows}x{cols} above the"
                                          f" expansion cap ({MINSERT_CAP})"
                                          " - skipped, named exclusion"})
            return
        cos_r, sin_r = math.cos(rot), math.sin(rot)
        for r in range(rows):
            for c in range(cols):
                dx, dy = c * cspace, r * rspace
                off = (dx * cos_r - dy * sin_r, dx * sin_r + dy * cos_r)
                try:
                    for virtual in ent.virtual_entities():
                        flatten_entity(virtual, segs, texts, unsupported,
                                       units_per_ft, parent_layer=layer,
                                       offset=off, arc_stats=arc_stats)
                except Exception as exc:
                    unsupported.append({"op": "MINSERT", "handle": handle,
                                        "layer": layer,
                                        "reason": f"block expansion failed:"
                                                  f" {exc}"})
    elif op == "SPLINE":
        try:
            prev = None
            for p in ent.flattening(0.5):
                pt = (p[0], p[1])
                if prev is not None:
                    emit(prev, pt)
                prev = pt
        except Exception:
            unsupported.append({"op": op, "handle": handle,
                                "reason": "could not flatten spline"})
    elif op in ("ELLIPSE",):
        try:
            prev = None
            for p in ent.flattening(0.5):
                pt = (p[0], p[1])
                if prev is not None:
                    emit(prev, pt)
                prev = pt
        except Exception:
            unsupported.append({"op": op, "handle": handle,
                                "reason": "could not flatten ellipse"})
    elif op in UNSUPPORTED_OPS:
        unsupported.append({"op": op, "handle": handle,
                            "reason": "entity type not measured (recorded as"
                                     " a callout, never guessed)"})
    else:
        unsupported.append({"op": op, "handle": handle,
                            "reason": "unhandled entity type"})


def _emit_arc(arc_ent, emit, arc_stats):
    """Flatten one ARC entity with the disclosed 0.5% chord tolerance.
    DXF arcs run CCW from start_angle to end_angle (end may wrap)."""
    c = (arc_ent.dxf.center.x, arc_ent.dxf.center.y)
    r = arc_ent.dxf.radius
    a0 = math.radians(arc_ent.dxf.start_angle)
    a1 = math.radians(arc_ent.dxf.end_angle)
    if abs((a1 - a0) % (2.0 * math.pi)) < 1e-12:
        a1 = a0 + 2.0 * math.pi  # full circle encoded as 0..360
    used = arc_segments(c, r, a0, a1, None, emit, ccw=True)
    if arc_stats is not None:
        arc_stats.append({"op": "ARC", "handle": arc_ent.dxf.handle
                          if arc_ent.dxf.hasattr("handle") else "?",
                          "chords": used,
                          "area_error_pct": ARC_AREA_TOL * 100.0})


def main(argv=None):
    import ezdxf  # noqa: F401  (uv installs it from the header above)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dxf", help="path to a .dxf file (DWG: convert first via"
                    " ODA File Converter - not supported directly)")
    ap.add_argument("--out", help="output JSON (default <dxf>.cad.json)")
    ap.add_argument("--units", choices=sorted(DECLARED_PER_FT),
                    help="declare units when the file is UNITLESS"
                         " ($INSUNITS missing/0); recorded as"
                         " operator-verified")
    ap.add_argument("--layers", help="restrict to these layers"
                    " (comma-separated; default: all)")
    args = ap.parse_args(argv)

    if not os.path.exists(args.dxf):
        raise SystemExit(f"ERROR: {args.dxf} not found")
    try:
        doc = ezdxf.readfile(args.dxf)
    except Exception as exc:
        print(f"ERROR: could not read DXF ({exc}). DWG files are"
              " NOT supported directly - convert via ODA File Converter"
              " first, then re-run.", file=sys.stderr)
        sys.exit(2)
    units_name, units_per_ft, verified, warning = resolve_units(doc,
                                                                args.units)
    wanted_layers = None
    if args.layers:
        wanted_layers = {lnorm.strip().upper()
                         for lnorm in args.layers.split(",") if lnorm.strip()}
    msp = doc.modelspace()
    all_segs, all_words, unsupported, arc_stats = [], [], [], []
    for ent in msp:
        # P0.4: NO layer filtering here - block children on layer '0'
        # inherit the insert's effective layer, so filtering happens
        # AFTER expansion on the effective layer recorded per segment.
        flatten_entity(ent, all_segs, all_words, unsupported, units_per_ft,
                       arc_stats=arc_stats)
    if wanted_layers is not None:
        segs = [s for s in all_segs if s["layer"].strip().upper()
                in wanted_layers]
        texts = [w for w in all_words if w["layer"].strip().upper()
                 in wanted_layers]
        dropped = len(all_segs) - len(segs)
    else:
        segs, texts = all_segs, all_words
        dropped = 0
    segments = [dict(s, id=i, path=i, op="l", w=0.0)
                for i, s in enumerate(segs)]
    words = [dict(w, id=i) for i, w in enumerate(texts)]
    xs = [v for s in segs for v in (s["x0"], s["x1"])]
    ys = [v for s in segs for v in (s["y0"], s["y1"])]
    bounds = ([round(min(xs), 3), round(min(ys), 3),
               round(max(xs), 3), round(max(ys), 3)] if segs else None)
    callouts = []
    if warning:
        callouts.append({"scope": "cad units", "reason": warning,
                         "blank_fields": [], "source": {"pages": [1]}})
    if unsupported:
        by_op = {}
        for u in unsupported:
            by_op[u["op"]] = by_op.get(u["op"], 0) + 1
        callouts.append({
            "scope": "cad entities",
            "reason": f"unsupported CAD entities not measured: {by_op}"
                      " (handles recorded; the drawing's measurable"
                      " linework is unaffected)",
            "blank_fields": ["geometry of unsupported entities"],
            "source": {"pages": [1]}})
    if arc_stats:
        # P0.4: curved entities are chord approximations - the tolerance
        # is DISCLOSED, not hidden (area error <= 0.5% per curve).
        callouts.append({
            "scope": "cad arcs",
            "reason": f"{len(arc_stats)} curved entit(y/ies) approximated by"
                      f" chords; chord count solved per curve for area error"
                      f" <= {ARC_AREA_TOL * 100:.1f}% of the curve's own"
                      " sector (tolerance recorded in the payload)",
            "blank_fields": [],
            "source": {"pages": [1]}})
    if dropped:
        callouts.append({
            "scope": "cad layers",
            "reason": f"{dropped} expanded segment(s) on layers outside"
                      f" {sorted(wanted_layers)} excluded AFTER block"
                      " expansion (layer-0 children resolved to their"
                      " insert's effective layer first)",
            "blank_fields": [],
            "source": {"pages": [1]}})
    payload = {
        "pdf": args.dxf,
        "generated_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "source": {"sha256": file_sha256(args.dxf), "page_count": 1,
                   "kind": "cad", "units": units_name,
                   "units_verified": verified,
                   "units_per_ft": units_per_ft},
        "pages": [{
            "page": 1,
            "sheet": os.path.splitext(os.path.basename(args.dxf))[0],
            "identity": {"page": 1, "rotation": 0,
                         "displayed_width": None, "displayed_height": None},
            "transforms": {"space": "drawing_units",
                           "units": units_name,
                           "units_per_ft": units_per_ft,
                           "verified": verified},
            "coordinate_space": "drawing_units",
            "segment_count": len(segments),
            "word_count": len(words),
            "segments": segments,
            "words": words,
            "content_regions": [{
                "kind": "vector", "bbox": bounds,
                "segment_count": len(segments),
                "words_inside": len(words),
                "class": ("vector" if len(segments) >= 10
                          else "sparse_vector"),
                "note": "native CAD linework; factor comes from the"
                        " verified drawing units",
            }] if segs else [],
            "preflight": {
                "op_counts": {"l": len(segments)},
                "segment_count": len(segments),
                "segment_bounds": bounds,
                "images": [],
                "image_cover_pct": 0.0,
                "class": "vector",
                "class_reasons": ["native CAD source; units"
                                  f" {units_name} (verified={verified})"],
                "fingerprint": hashlib.sha256(
                    json.dumps([sorted([s["x0"], s["y0"], s["x1"], s["y1"]])
                                for s in segs], sort_keys=True)
                    .encode("utf-8")).hexdigest()[:16],
                "revision_marks": [],
            },
            "text_chars": sum(len(w["t"]) for w in words),
        }],
        "callouts": callouts,
        "unsupported_entities": unsupported,
        "arc_approximation": {
            "tolerance": f"area error <= {ARC_AREA_TOL * 100:.1f}% per"
                         " curved entity (chord count solved from the exact"
                         " polygon deficit)",
            "curves": arc_stats,
        } if arc_stats else None,
    }
    out = args.out or os.path.splitext(args.dxf)[0] + ".cad.json"
    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    print(f"# CAD import: {args.dxf} -> {out}")
    print(f"  units: {units_name} (verified={verified});"
          f" units_per_ft={units_per_ft}")
    print(f"  segments: {len(segments)}  words: {len(words)}"
          f"  unsupported: {len(unsupported)}")
    for c in callouts:
        print(f"  CALLOUT [{c['scope']}]: {c['reason'][:110]}")
    print("  measure.py ingests this file as a cad source; regions on it use"
          " the verified units as their calibration factor.")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
