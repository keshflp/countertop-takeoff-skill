# /// script
# requires-python = ">=3.9"
# dependencies = ["ezdxf==1.4.2"]
# ///
"""Supplied native-CAD input: DXF adapter (V3 measurement route 2).

Route order (P0.6): (1) vector PDF geometry, (2) supplied native CAD via
THIS adapter, (3) calibrated image-space measurement, (4) optional CAD-MCP
escalation - see references/cad-context.md (documentation only, never a
runtime dependency).

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
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

INSUNITS_PER_FT = {
    1: 12.0,            # inches
    2: 1.0,             # feet
    4: 304.8,           # mm
    5: 30.48,           # cm
    6: 3.048,           # m
    8: 1000.0 / 3.048,  # microns (rare) -> treat as mm*1000
}
DECLARED_PER_FT = {"in": 12.0, "ft": 1.0, "mm": 304.8, "cm": 30.48, "m": 3.048}
ARC_SEGMENTS = 16          # chords per arc/bitmap curve
UNSUPPORTED_OPS = {"HATCH", "DIMENSION", "LEADER", "MLINE", "3DSOLID",
                   "REGION", "BODY", "IMAGE", "WIPEOUT", "OLE2FRAME"}


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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
        name = {1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m",
                8: "micron"}.get(insunits, f"insunits-{insunits}")
        return name, INSUNITS_PER_FT[insunits], True, None
    if declared:
        if declared not in DECLARED_PER_FT:
            print(f"ERROR: --units must be one of {sorted(DECLARED_PER_FT)}",
              file=sys.stderr)
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


def flatten_entity(ent, segs, texts, unsupported, units_per_ft):
    """One entity -> segments (drawing units) / word records. Block inserts
    are expanded via virtual_entities so transforms apply. Entity handles
    and layers are recorded on every segment."""
    op = ent.dxftype()
    handle = ent.dxf.handle if ent.dxf.hasattr("handle") else "?"
    layer = ent.dxf.layer if ent.dxf.hasattr("layer") else "?"

    def emit(p1, p2):
        segs.append({"x0": round(p1[0], 6), "y0": round(p1[1], 6),
                     "x1": round(p2[0], 6), "y1": round(p2[1], 6),
                     "layer": layer, "handle": handle})

    if op == "LINE":
        emit((ent.dxf.start.x, ent.dxf.start.y),
             (ent.dxf.end.x, ent.dxf.end.y))
    elif op in ("LWPOLYLINE", "POLYLINE"):
        try:
            pts = [tuple(p)[:2] for p in ent.vertices()] if op == "LWPOLYLINE" \
                else [tuple(v.dxf.location)[:2] for v in ent.vertices]
        except Exception:
            unsupported.append({"op": op, "handle": handle,
                                "reason": "could not read vertices"})
            return
        closed = bool(getattr(ent, "closed", False)) or op == "POLYLINE" \
            and ent.dxf.hasattr("flags") and (ent.dxf.flags & 1)
        n = len(pts)
        if n < 2:
            unsupported.append({"op": op, "handle": handle,
                                "reason": "fewer than 2 vertices"})
            return
        last = n if closed else n - 1
        for i in range(last):
            emit(pts[i], pts[(i + 1) % n])
    elif op == "ARC":
        import math
        c = (ent.dxf.center.x, ent.dxf.center.y)
        r = ent.dxf.radius
        a0 = math.radians(ent.dxf.start_angle)
        a1 = math.radians(ent.dxf.end_angle)
        if a1 <= a0:
            a1 += 2 * math.pi
        prev = None
        for k in range(ARC_SEGMENTS + 1):
            a = a0 + (a1 - a0) * k / ARC_SEGMENTS
            p = (c[0] + r * math.cos(a), c[1] + r * math.sin(a))
            if prev is not None:
                emit(prev, p)
            prev = p
    elif op == "CIRCLE":
        import math
        c = (ent.dxf.center.x, ent.dxf.center.y)
        r = ent.dxf.radius
        prev = None
        for k in range(ARC_SEGMENTS + 1):
            a = 2 * math.pi * k / ARC_SEGMENTS
            p = (c[0] + r * math.cos(a), c[1] + r * math.sin(a))
            if prev is not None:
                emit(prev, p)
            prev = p
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
        try:
            for virtual in ent.virtual_entities():
                flatten_entity(virtual, segs, texts, unsupported, units_per_ft)
        except Exception as exc:
            unsupported.append({"op": op, "handle": handle,
                                "reason": f"block expansion failed: {exc}"})
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
    segs, texts, unsupported = [], [], []
    for ent in msp:
        if wanted_layers is not None and \
                ent.dxf.layer.upper() not in wanted_layers:
            continue
        flatten_entity(ent, segs, texts, unsupported, units_per_ft)
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
