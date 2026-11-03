# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1"]
# ///
"""Evidence-pack renderer + independent-audit receipt (step 6 of the V2 flow).

Renders, for every measured region in a results JSON:
  - a FULL-PAGE overlay PNG (translucent measured shell, region id, seed
    marker, calibration spans of the region's viewport) and
  - a CLOSE-UP overlay PNG around the region,
both in DISPLAYED page space: recorded page rotation is applied by the
renderer, so overlays line up with what a human sees (v1 ignored rotation).
Plus an index.md summarizing the pack and pointing the reviewer at what to
check.

It can also RECORD the independent audit receipt into the results JSON:

    uv run scripts/audit_pack.py build/results.json --pack build/audit_pack
    uv run scripts/audit_pack.py build/results.json --record-receipt \
        --reviewer "fresh-agent: <session>" --verdict approved \
        --notes "checked counts, overlays, omissions" --pack build/audit_pack

Rules: receipts are only recorded on runs whose required checks passed;
`--verdict rejected` is recorded verbatim (a rejection is an outcome, not an
error). If no fresh agent is available, an independent HUMAN must review and
be recorded as `human: <name>` - SKILL.md documents this substitution.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pymupdf  # noqa: E402

PAD_PT = 60.0
SHELL_FILL = (0.05, 0.45, 0.95)
SPAN_COLOR = (0.95, 0.35, 0.05)
SEED_COLOR = (0.10, 0.70, 0.20)


def render_overlay(pdf_path, page_no, region, cal, segments, out_base, zoom):
    """Full-page + close-up overlay PNGs for one region.

    `segments` is the geometry page's segment list (displayed space); span
    seg_ids are looked up there so the drawn calibration spans are exactly
    the ones the factor was computed from. V4: tolerates regions with no
    numeric area (blank-marker rendering, never a crash)."""
    def label_for(region):
        if region.get("status") == "unresolved":
            return (f"{region['region_id']}  UNRESOLVED -"
                    f" {region.get('unresolved_reason', '')[:90]}")
        if region.get("area_sf") is None:
            return f"{region['region_id']}  AREA BLANK (degraded)"
        suffix = (f" at {region.get('factor_px_per_ft')} px/ft"
                  if region.get("route") == "image"
                  else f"  {region['factor_pt_per_ft']:.4f} pt/ft"
                       f"  ({region.get('gross_area_policy')})")
        return (f"{region['region_id']}  {region['area_sf']:.2f} SF"
                f"{suffix}")
    src = pymupdf.open(pdf_path)
    page = src[page_no - 1]
    disp_w, disp_h = page.rect.width, page.rect.height
    src.close()
    scratch = pymupdf.open()
    pg = scratch.new_page(width=disp_w, height=disp_h)
    base = pymupdf.open(pdf_path)
    pix = base[page_no - 1].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    base.close()
    pg.insert_image(pymupdf.Rect(0, 0, disp_w, disp_h), pixmap=pix)
    if region.get("route") == "image":
        # image-route areas are measured on a rendered CROP (crop-pixel
        # space), not on the PDF page: point the reviewer at the route's
        # own overlay proof instead of drawing a shell here.
        pg.insert_text((10, 20), label_for(region) + " - the overlay proof"
                       " was rendered by image_measure.py on the crop",
                       fontname="helv", fontsize=9, color=(0, 0, 0.6))
        clip = pymupdf.Rect(0, 0, disp_w, disp_h)
        out = f"{out_base}_full.png"
        pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip).save(out)
        scratch.close()
        return [out]
    if region.get("status") == "unresolved":
        # unresolved regions have no shell; render a marker + reason so the
        # reviewer sees the blank in the pack
        seed = region.get("seed") or [disp_w / 2, disp_h / 2]
        pg.draw_circle(seed, 5.0, color=SPAN_COLOR, width=1.5)
        pg.insert_text((10, 20), label_for(region),
                       fontname="helv", fontsize=9, color=(0.6, 0, 0))
        clip = pymupdf.Rect(0, 0, disp_w, disp_h)
        out = f"{out_base}_full.png"
        pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip).save(out)
        scratch.close()
        return [out]
    poly = region["polygon"]
    ring = list(poly) + [poly[0]]  # draw_polyline leaves the ring open
    pg.draw_polyline(ring, color=SHELL_FILL, fill=SHELL_FILL,
                     fill_opacity=0.35, width=1.5)
    for cut in region.get("cutout_polygons", []):
        pg.draw_polyline(list(cut) + [cut[0]], color=SPAN_COLOR, width=1.0)
    seed = region["seed"]
    pg.draw_circle(seed, 3.0, color=SEED_COLOR, fill=SEED_COLOR)
    span_ids = set()
    for s in (cal or {}).get("spans", []):
        span_ids.update(s.get("seg_ids", []))
    for s in segments:
        if s["id"] in span_ids:
            pg.draw_line((s["x0"], s["y0"]), (s["x1"], s["y1"]),
                         color=SPAN_COLOR, width=2.0)
    cx = min(p[0] for p in poly)
    cy = min(p[1] for p in poly) - 8
    pg.insert_text((cx, cy), label_for(region),
                   fontname="helv", fontsize=9, color=(0, 0, 0))
    bbox = poly_bbox(poly)
    clip_full = pymupdf.Rect(0, 0, disp_w, disp_h)
    clip_close = clamped(bbox, disp_w, disp_h)
    files = []
    for suffix, clip in (("full", clip_full), ("closeup", clip_close)):
        out = f"{out_base}_{suffix}.png"
        p2 = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip)
        p2.save(out)
        files.append(out)
    scratch.close()
    return files


def poly_bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return [min(xs), min(ys), max(xs), max(ys)]


def clamped(bbox, w, h):
    return pymupdf.Rect(max(0, bbox[0] - PAD_PT), max(0, bbox[1] - PAD_PT),
                        min(w, bbox[2] + PAD_PT), min(h, bbox[3] + PAD_PT))


def build_index_md(results, pack_dir, files_by_region):
    src = results.get("source") or {}
    status = results.get("run_status") or results.get("status")
    lines = [f"# Audit pack - {src.get('pdf', '')}", "",
             f"- source sha256: `{src.get('sha256', '')}`",
             f"- run status: **{status}**; review status:"
             f" {results.get('review_status')}",
             f"- mode: {results.get('mode')}; gross-area policy:"
             f" {results.get('policy', {}).get('gross_area')}",
             f"- totals: {results.get('totals', {}).get('project_sf', 0):.2f}"
             f" SF over {results.get('totals', {}).get('unit_count')}"
             " unit(s)", ""]
    callouts = results.get("callouts") or []
    if callouts:
        lines += ["## Callouts the reviewer must confirm", ""]
        for c in callouts:
            lines.append(f"- {c['scope']}: {c['reason']}")
        lines.append("")
    lines += ["## What the independent reviewer must check", "",
             "1. RAW SHEETS: do the highlighted shells sit on countertop",
             "   linework? anything cut off or swallowed by a neighbor?",
             "2. SCHEDULE EVIDENCE: re-read the schedule page; do the counts,",
             "   ADA subset handling and floor totals match what was used?",
             "3. OMISSIONS: every intentionally_skipped page and declaration",
             "   - is the clubroom/scan omission explicit and acceptable?",
             "4. OVERLAYS: seed inside each shell, calibration spans on real",
             "   dimension lines, close-up boundaries plausible.", "",
             "## Regions"]
    for rid, files in files_by_region.items():
        r = next(x for x in results["regions"] if x["region_id"] == rid)
        if r.get("status") == "unresolved" or r.get("area_sf") is None:
            lines.append(f"- `{rid}` ({r.get('type')},"
                         f" {'UNRESOLVED' if r.get('status') == 'unresolved' else 'AREA BLANK'})"
                         " quantities BLANK on page"
                         f" {r.get('page')}:"
                         f" {r.get('unresolved_reason', '')[:90]}")
            lines += [f"  - {os.path.relpath(f, pack_dir)}" for f in files]
            continue
        lines.append(f"- `{rid}` ({r['type']}"
                     + (f"/{r['variant']}" if r["variant"] else "")
                     + f", {r['kind']}) {r['area_sf']:.2f} SF on page"
                     f" {r['page']} viewport {r['viewport']}:")
        lines += [f"  - {os.path.relpath(f, pack_dir)}" for f in files]
    return "\n".join(lines) + "\n"


def safe_name(rid):
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in rid)


def render_pack(results, pack_dir, zoom):
    os.makedirs(pack_dir, exist_ok=True)
    # V4: multi-source jobs - geometry may be ONE path or {source_id: path};
    # segments and base pages are looked up per (source_id, page), and the
    # calibration per the region's OWN source (source-aware keys).
    geo_path = results.get("geometry")
    sources = results.get("sources") or []
    default_sid = (sources[0] or {}).get("source_id") if sources else None
    geo_by_source = {}
    if isinstance(geo_path, dict):
        for sid, gp in geo_path.items():
            gp = gp if os.path.isabs(gp) or os.path.exists(gp) else \
                os.path.join(os.path.dirname(args_results_path(results)), gp)
            geo_by_source[sid] = json.load(open(gp, encoding="utf-8")) \
                if os.path.exists(gp) else {"pages": []}
    elif geo_path and os.path.exists(geo_path):
        geo = json.load(open(geo_path, encoding="utf-8"))
        geo_by_source[default_sid] = geo
    segs_by_key = {}
    for sid, geo in geo_by_source.items():
        for p in geo.get("pages", []):
            segs_by_key[(sid, p["page"])] = p["segments"]
    pdf_by_source = {s["source_id"]: s["path"] for s in sources
                     if s.get("path")}
    default_pdf = (results.get("source") or {}).get("pdf") \
        or (sources[0] or {}).get("path") if sources else None
    files_by_region = {}
    for r in results["regions"]:
        sid = r.get("source_id") or default_sid
        cal = None
        cals = results.get("calibrations") or {}
        for cand in (f"{sid}:{r['page']}:{r['viewport']}",
                     f"{r['page']}:{r['viewport']}"):
            if cand in cals:
                cal = cals[cand]
                break
        pdf_path = pdf_by_source.get(sid) or default_pdf
        base = os.path.join(pack_dir, safe_name(r["region_id"]))
        try:
            files = render_overlay(pdf_path, r["page"], r, cal,
                                   segs_by_key.get((sid, r["page"]), []),
                                   base, zoom)
        except Exception as exc:
            # a page we cannot render (e.g. a CAD source without a raster
            # preview) must not crash the pack - render a marker instead
            files = [os.path.join(pack_dir,
                                  safe_name(r["region_id"]) + "_full.png")]
            with open(files[0], "wb") as f:
                f.write(_marker_png(str(exc)))
        files_by_region[r["region_id"]] = files
        print(f"rendered {r['region_id']}: {len(files)} image(s)")
    index = os.path.join(pack_dir, "index.md")
    with open(index, "w", encoding="utf-8") as f:
        f.write(build_index_md(results, pack_dir, files_by_region))
    print(f"wrote {index} ({len(files_by_region)} region(s))")


def args_results_path(results):
    """Best-effort base dir for resolving relative geometry paths."""
    return os.path.dirname(results.get("_results_path") or ".")


def _marker_png(text):
    """A tiny valid PNG rendered with pymupdf carrying the note text."""
    doc = pymupdf.open()
    pg = doc.new_page(width=420, height=90)
    pg.insert_text((10, 30), f"overlay unavailable: {text[:70]}",
                   fontname="helv", fontsize=9, color=(0.6, 0, 0))
    data = pg.get_pixmap(matrix=pymupdf.Matrix(1, 1)).tobytes("png")
    doc.close()
    return data


def record_receipt(results, results_path, reviewer, verdict, notes, pack_dir):
    """Write the independent-audit receipt into the results JSON."""
    # V4: a `stopped` run must NEVER receive an approved receipt. The guard
    # checks the CURRENT status names (complete / complete_with_callouts /
    # stopped) and the obsolete V2 name `failed` for old files.
    status = results.get("run_status") or results.get("status")
    if status in ("stopped", "failed"):
        print(f"REFUSED: this run is {status.upper()} - required checks"
              " failed/were stopped; fix the job spec, re-measure, then"
              " audit. Nothing recorded.")
        return 2
    receipt = {
        "status": "independent_audit_recorded",
        "reviewer": reviewer,
        "verdict": verdict,
        "notes": notes or "",
        "pack_dir": pack_dir,
        "recorded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    results["review"] = receipt
    results["review_status"] = receipt["status"]
    if verdict == "approved":
        results["review_status"] = "independent_audit_approved"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)
    print(f"recorded receipt in {results_path}: reviewer={reviewer!r} "
          f"verdict={verdict!r}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("results", help="results JSON written by measure.py")
    ap.add_argument("--pack", default="build/audit_pack",
                    help="output directory for overlays")
    ap.add_argument("--zoom", type=float, default=2.0)
    ap.add_argument("--record-receipt", action="store_true",
                    help="record the audit receipt into the results JSON")
    ap.add_argument("--reviewer", help='e.g. "fresh-agent: <session>" or'
                    ' "human: <name>"')
    ap.add_argument("--verdict", choices=["approved", "rejected"])
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    results = json.load(open(args.results, encoding="utf-8"))
    if args.record_receipt:
        if not args.reviewer or not args.verdict:
            print("REFUSED: --record-receipt needs --reviewer and --verdict")
            return 2
        return record_receipt(results, args.results, args.reviewer,
                              args.verdict, args.notes, args.pack)
    render_pack(results, args.pack, args.zoom)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
