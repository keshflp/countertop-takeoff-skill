# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1", "shapely==2.2.0", "ezdxf==1.4.2"]
# ///
"""V4 acceptance tests: one resolved model, evidence binding, degradation,
CAD correctness, estimate, intake collisions.

Run from the skill folder:  uv run examples/tests_v4.py

On top of tests_v2.py (47 checks) and tests_v3.py (34 checks), which stay
green, this suite locks the V4 regressions:

  resolved model (P0.1)
    - MIXED job (repeated + enumerated + public_BOH + FFE-excluded, included
      ADA variants): project total == assembly-view == piece-view == report
      == CSV grand total (equality asserted); ADA EA subtracted from the
      parent count; excluded scope reported separately; EA extends edge LF
      and cutout counts like SF
  evidence binding (P0.2)
    - 3 -> 30 over a retained "3" word box: caught, extension withheld
    - per_type_counts edited to 30 while tags show 6: conflict + withhold
    - duplicate raster anchors are NOT independent
    - edited image result number over unchanged pixels: REJECTED
    - image crop unbound to (source, page, transform): rejected
  degradation (P0.3)
    - image-route range breach degrades LOCALLY (exit 0), area truly null
    - planned overlap pair: BOTH records withheld, job completes
    - audit pack renders multi-source + blank-area results without crashing
    - a stopped result NEVER receives an approved receipt
  CAD (P0.4)
    - 25.00 SF exact at THREE unit encodings ($INSUNITS 1/4/6)
    - MINSERT arrays expand; layer-0 children inherit the effective layer
    - bulge arcs: area error <= 0.5%, tolerance disclosed
    - moved/renamed CAD source: integrity stop, never cached results
  estimate (P1.1)
    - Decimal ROUND_HALF_UP (3 x 55.555 -> 166.67; banker's gives 166.66)
    - unmatched rate -> BLANK + callout; explicit zero-rate -> real 0.00
    - md / json / pdf grand-total agreement (blank and priced cases)
    - finish-only rates refuse at profile load
  intake (P1.2)
    - filename collisions land on distinct destinations
    - structured --entry metadata (no positional pairing)

Exits 0 only if every check passes; prints a case -> verdict matrix.
"""

import copy
import json
import os
import shutil
import subprocess
import sys
from test_support import sh, sha256, run_measure as shared_run_measure

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SKILL, "scripts"))
sys.path.insert(0, HERE)

import measure  # noqa: E402
import audit_pack  # noqa: E402
import estimate as estimate_mod  # noqa: E402
import image_measure  # noqa: E402
import cad_input  # noqa: E402
import regions as regions_mod  # noqa: E402
from spec_schema import TakeoffError, SpecError  # noqa: E402
import spec_schema  # noqa: E402

BUILD = os.path.join(SKILL, "build", "test")
HOTEL_JOBS = os.path.join(BUILD, "hotel", "hotel.jobs.json")
HOTEL_PDF = os.path.join(BUILD, "hotel", "hotel.pdf")
HOTEL_GEO = os.path.join(BUILD, "hotel", "hotel.geometry.json")
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}"
          + (f" - {detail}" if detail and not ok else ""))


def run_measure(spec, tag, extra=(), jobs_path=None):
    return shared_run_measure(spec, tag, extra, jobs_path, build=BUILD)


def build_fixtures():
    """messy + hotel + orig fixtures, geometry + canonical hotel spec."""
    os.makedirs(BUILD, exist_ok=True)
    sh(os.path.join(HERE, "make_fixture.py"), "--case", "messy",
       "--out", os.path.join(BUILD, "messy.pdf"))
    sh(os.path.join(HERE, "make_fixture.py"), "--out",
       os.path.join(BUILD, "orig.pdf"))
    sh(os.path.join(SKILL, "scripts", "extract_geometry.py"),
       os.path.join(BUILD, "messy.pdf"), "--pages", "all",
       "--out", os.path.join(BUILD, "messy.geometry.json"))
    sh(os.path.join(SKILL, "scripts", "extract_geometry.py"),
       os.path.join(BUILD, "orig.pdf"), "--pages", "all",
       "--out", os.path.join(BUILD, "orig.geometry.json"))
    hdir = os.path.join(BUILD, "hotel")
    os.makedirs(hdir, exist_ok=True)
    sh(os.path.join(HERE, "make_fixture.py"), "--case", "hotel",
       "--out", HOTEL_PDF)
    sh(os.path.join(SKILL, "scripts", "extract_geometry.py"), HOTEL_PDF,
       "--pages", "all", "--out", HOTEL_GEO)
    sh(os.path.join(HERE, "make_hotel_jobs.py"), "--pdf", HOTEL_PDF,
       "--geometry", HOTEL_GEO, "--out", HOTEL_JOBS,
       "--workdir", os.path.join(hdir, "evidence"))
    print("fixtures built.")


def messy_spec():
    import importlib.util
    spec_mod = importlib.util.spec_from_file_location(
        "tv2mod", os.path.join(HERE, "tests_v2.py"))
    tv2 = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(tv2)
    return tv2.spec_messy(
        {"messy": os.path.join(BUILD, "messy.pdf")},
        {"messy": os.path.join(BUILD, "messy.geometry.json")})


# ------------------------------------------------- P0.1 resolved model
def mixed_spec():
    """MIXED job: repeated (room_type_count) + enumerated + public_BOH
    + FFE-excluded assemblies, with an ADA variant INCLUDED in the parent
    count. Under V3 this spec reproduced the headline bug (project total
    90.00-style mismatch vs BoQ with a 'pass' reconciliation); under V4 all
    views MUST agree."""
    spec = messy_spec()
    spec["schedule"]["variants"][0]["included_in_parent_total"] = True
    spec["schedule"]["variants"][0]["row_text"] = ("TYPE A (ADA) 1 per"
        " floor - included in the parent type count")
    spec["policy"]["packages"] = {"exclude": ["FFE"]}
    spec["assemblies"] = [
        {"assembly_id": "fl1-a", "type": "A", "package": "millwork",
         "width_in": 72, "depth_in": 25.5, "finish_tag": "PL",
         "quantity_basis": {"mode": "room_type_count", "type": "A"},
         "pieces": ["p:k"], "sources": [{"source_id": "plans", "page": 5}]},
        {"assembly_id": "fl2-a", "type": "A", "package": "millwork",
         "width_in": 72, "depth_in": 25.5, "finish_tag": "PL",
         "quantity_basis": {"mode": "room_type_count", "type": "A"},
         "pieces": ["p:i"], "sources": [{"source_id": "plans", "page": 5}]},
        {"assembly_id": "aada", "type": "A", "variant": "ADA",
         "package": "millwork", "width_in": 72, "depth_in": 25.5,
         "finish_tag": "PL",
         "quantity_basis": {"mode": "room_type_count", "type": "A",
                            "variant": "ADA"},
         "pieces": ["p:ak", "p:av"],
         "sources": [{"source_id": "plans", "page": 3}]},
        {"assembly_id": "van-enum", "type": "A", "package": "public_BOH",
         "quantity_basis": {"mode": "enumerated"},
         "pieces": ["p:v"], "sources": [{"source_id": "plans", "page": 5}]},
        {"assembly_id": "b-fl", "type": "B", "package": "millwork",
         "width_in": 96, "depth_in": 25.5, "finish_tag": "ST",
         "quantity_basis": {"mode": "room_type_count", "type": "B"},
         "pieces": ["p:bk", "p:bv"],
         "sources": [{"source_id": "plans", "page": 4}]},
        {"assembly_id": "pub", "type": "PUB", "package": "public_BOH",
         "quantity_basis": {"mode": "enumerated"},
         "pieces": ["p:stated"], "sources": [{"source_id": "plans",
                                              "page": 5}]},
        {"assembly_id": "ffe1", "type": "FFE1", "package": "FFE",
         "quantity_basis": {"mode": "enumerated"},
         "pieces": ["p:ffe"], "sources": [{"source_id": "plans",
                                            "page": 5}]}]
    spec["pieces"] = [
        {"piece_id": "p:k", "assembly_id": "fl1-a", "route": "geometry",
         "region_id": "A:kitchen", "finish_tag": "PL",
         "edge_runs": [{"profile": "eased", "exposure": "front",
                        "length_in": 72}],
         "cutouts": [{"kind": "sink", "ea": 2}]},
        {"piece_id": "p:i", "assembly_id": "fl2-a", "route": "geometry",
         "region_id": "A:island", "finish_tag": "PL", "edge_runs": []},
        {"piece_id": "p:v", "assembly_id": "van-enum", "route": "geometry",
         "region_id": "A:vanity", "finish_tag": "PL", "edge_runs": []},
        {"piece_id": "p:ak", "assembly_id": "aada", "route": "geometry",
         "region_id": "AADA:kitchen", "finish_tag": "PL", "edge_runs": []},
        {"piece_id": "p:av", "assembly_id": "aada", "route": "geometry",
         "region_id": "AADA:vanity", "finish_tag": "PL", "edge_runs": []},
        {"piece_id": "p:bk", "assembly_id": "b-fl", "route": "geometry",
         "region_id": "B:kitchen", "finish_tag": "ST", "edge_runs": []},
        {"piece_id": "p:bv", "assembly_id": "b-fl", "route": "geometry",
         "region_id": "B:vanity", "finish_tag": "ST", "edge_runs": []},
        {"piece_id": "p:stated", "assembly_id": "pub", "route": "stated",
         "dims_in": {"width": 24, "depth": 36, "thickness": 2,
                     "height": 36}, "edge_runs": []},
        {"piece_id": "p:ffe", "assembly_id": "ffe1", "route": "stated",
         "dims_in": {"width": 40, "depth": 24, "thickness": 2,
                     "height": 36}, "edge_runs": []}]
    return spec


def mixed_resolved_tests():
    # expected: std A EA 8 x (25+18) = 344 + ADA EA 2 x 32 = 64
    #   + enumerated vanity 12 + B EA 8 x 47 = 376 + public stated 6
    #   = 802.00; FFE 40x24/144 = 6.67 excluded separately
    rc, res, err = run_measure(mixed_spec(), "v4_mixed", (
        "--csv", os.path.join(BUILD, "v4_mixed.csv"),
        "--piece-csv", os.path.join(BUILD, "v4_mixed_pieces.csv")))
    check("mixed: exit 0", rc == 0, err[:160])
    t = res["totals"]
    check("mixed: project == piece view == assembly view == 802.00",
          abs(t["project_sf"] - 802.0) < 0.01
          and abs(t["piece_view_sf"] - 802.0) < 0.01
          and abs(t["assembly_view_sf"] - 802.0) < 0.01, str(t))
    import csv as _csv
    rows = list(_csv.reader(open(os.path.join(BUILD, "v4_mixed.csv"),
                                 encoding="utf-8")))
    grand = [r for r in rows if r and r[0] == "grand_total"][0]
    excl = [r for r in rows if r and r[0] == "excluded_package_total"]
    check("mixed: CSV grand total equals the project total",
          abs(float(grand[9]) - 802.0) < 0.01, str(grand))
    check("mixed: excluded package on its own documented row (6.67)",
          len(excl) == 1 and abs(float(excl[0][9]) - 6.67) < 0.01
          and "NEVER" in excl[0][12], str(excl))
    report = res.get("_report_text") or ""
    dual = next(i for i in res["audit"]
                if i["check"] == "dual BoQ reconciliation")
    check("mixed: dual-BoQ reconciliation pass (three-way)",
          dual["status"] == "pass", dual["detail"][:140])
    asm = {a["assembly_id"]: a for a in res["assembly_boq"]}
    check("mixed: included ADA EA 2, standard EA 8 (subtracted, not added)",
          asm["aada"]["ea"] == 2 and asm["fl1-a"]["ea"] == 8
          and asm["fl2-a"]["ea"] == 8,
          str({k: v["ea"] for k, v in asm.items()}))
    check("mixed: FFE assembly package_excluded",
          asm["ffe1"]["state"] == "package_excluded")
    pk = next(p for p in res["piece_boq"] if p["piece_id"] == "p:k")
    check("mixed: edge LF and cutouts extend with EA (8x)",
          pk["edge_lf_ext"] == {"eased": 48.0}
          and pk["cutouts_ea_ext"] == {"sink": 16}
          and abs(pk["extension_sf"] - 200.0) < 0.01, str(pk))
    ledger = json.dumps(res.get("coverage_ledger") or [])
    check("mixed: ledger distinguishes included_scope + package_excluded",
          '"included_scope"' in ledger and '"package_excluded"' in ledger)
    return res


# ---------------------------------------------- P0.2 evidence binding
def evidence_binding_tests():
    # (1) 3 -> 30 over a retained "3" word box (original fixture shape)
    import importlib.util
    spec_mod = importlib.util.spec_from_file_location(
        "tv2mod2", os.path.join(HERE, "tests_v2.py"))
    tv2 = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(tv2)
    base = tv2.spec_original(
        {"orig": os.path.join(BUILD, "orig.pdf")},
        {"orig": os.path.join(BUILD, "orig.geometry.json")})
    spec = copy.deepcopy(base)
    spec["schedule"]["types"][0]["count"] = 30
    rc, res, err = run_measure(spec, "v4_p30")
    co = " | ".join(c["scope"] + ": " + c["reason"]
                    for c in (res.get("callouts") or []))
    check("3->30 with retained '3' box: caught + withheld",
          rc == 0 and "numeric correspondence" in co
          and res["totals"]["project_sf"] < 100.0,
          f"rc={rc} total={res and res['totals']['project_sf']}"
          f" callouts={co[:160]}")

    # (2) per_type_counts edited to 30 while the tags show 6 (hotel)
    hspec = json.load(open(HOTEL_JOBS, encoding="utf-8"))
    spec = copy.deepcopy(hspec)
    spec["schedule"]["room_inventory"]["per_type_counts"]["A"] = 30
    jobs_path = os.path.join(BUILD, "hotel", "v4_ptc.jobs.json")
    rc, res, err = run_measure(spec, "v4_ptc", jobs_path=jobs_path)
    co = " | ".join(c["scope"] + ": " + c["reason"]
                    for c in (res.get("callouts") or []))
    check("per_type_counts edited to 30 vs 6 tags: conflict + withheld",
          rc == 0 and "contradicts the tag records" in co,
          f"rc={rc} callouts={co[:200]}")
    ledger = json.dumps(res.get("coverage_ledger") or [])
    check("edited inventory: type A unresolved in the ledger",
          '"unresolved"' in ledger and "type A x6" in ledger,
          ledger[:160])

    # (3) duplicate raster anchors are NOT independent
    m = image_measure.measure_from_points(
        [{"label": "12'-0\"", "p1": [0, 0], "p2": [216, 0]},
         {"label": "12'-0\"", "p1": [0, 0], "p2": [216, 0]}],
        [{"name": "p1", "px": [0, 0]}, {"name": "p2", "px": [216, 0]},
         {"name": "p3", "px": [216, 54]}, {"name": "p4", "px": [0, 54]}])
    check("duplicate raster anchors: not independent (unusable quality)",
          not m["quality"]["usable"]
          and any("NOT independent" in w for w in m["warnings"])
          and any("only ONE usable anchor" in w for w in m["warnings"]),
          str(m["warnings"][:2]))

    # (4) edited image result number over unchanged pixels: REJECTED
    ev = json.load(open(os.path.join(BUILD, "hotel", "evidence",
                                     "clubroom_measure.json"),
                        encoding="utf-8"))
    region = {"region_id": "clubroom:counter", "kind": "base",
              "type": "CLUB", "variant": None, "page": 9,
              "source_id": "plans", "sheet": "A-306", "route": "image",
              "image_measurement": os.path.join(BUILD, "hotel", "evidence",
                                                "clubroom_measure.json"),
              "expected_sf_range": [15, 35]}
    ok_rec = regions_mod.measure_region_image(region, str(BUILD))
    edited = copy.deepcopy(ev)
    edited["area_sf"] = 99.0
    epath = os.path.join(BUILD, "hotel", "evidence", "clubroom_edited.json")
    json.dump(edited, open(epath, "w"), indent=1)
    bad = regions_mod.measure_region_image(
        dict(region, image_measurement=epath), str(BUILD))
    check("edited image result over unchanged pixels: rejected",
          ok_rec["status"] == "measured"
          and bad["status"] == "unresolved"
          and "RECORDED RESULT REJECTED" in bad["unresolved_reason"],
          (bad.get("unresolved_reason") or "")[:120])

    # (5) crop unbound to (source, page, transform): rejected
    unbound = copy.deepcopy(ev)
    unbound.pop("provenance")
    upath = os.path.join(BUILD, "hotel", "evidence", "clubroom_unbound.json")
    json.dump(unbound, open(upath, "w"), indent=1)
    unb = regions_mod.measure_region_image(
        dict(region, image_measurement=upath), str(BUILD))
    check("image crop unbound to (source, page, transform): rejected",
          unb["status"] == "unresolved"
          and "NOT bound" in unb["unresolved_reason"],
          (unb.get("unresolved_reason") or "")[:120])

    # (6) real_ft override contradicting the readable label -> callout
    spec = copy.deepcopy(hspec)
    for c in spec.get("calibrations") or []:
        if c["page"] == 3:
            c["spans"][0]["real_ft"] = 25.0   # label says 20'-0"
    rc, res, err = run_measure(spec, "v4_override",
                               jobs_path=os.path.join(BUILD, "hotel",
                                                      "v4_override.jobs.json"))
    co = " | ".join(c["scope"] + ": " + c["reason"]
                    for c in (res.get("callouts") or []))
    check("real_ft override contradicting the label: callout",
          rc == 0 and "contradicts the readable label" in co,
          f"rc={rc} callouts={co[:160]}")


# ------------------------------------------------------ P0.4 CAD tests
def cad_tests():
    import ezdxf

    def rect_dxf(path, insunits, pts):
        doc = ezdxf.new("R2010")
        doc.header["$INSUNITS"] = insunits
        doc.modelspace().add_lwpolyline(pts, close=True)
        doc.saveas(path)
        cad_input.main([path, "--out", path + ".cad.json"])
        return path + ".cad.json"

    # 25.00 SF = 10 ft x 2.5 ft at three unit encodings
    cases = [
        ("in", 1, [(0, 0), (120.0, 0), (120.0, 30.0), (0, 30.0)]),
        ("mm", 4, [(0, 0), (3048.0, 0), (3048.0, 762.0), (0, 762.0)]),
        ("m", 6, [(0, 0), (3.048, 0), (3.048, 0.762), (0, 0.762)]),
    ]
    for name, ins, pts in cases:
        geo_path = rect_dxf(os.path.join(BUILD, f"v4_cad_{name}.dxf"),
                            ins, pts)
        geo = json.load(open(geo_path, encoding="utf-8"))
        upf = geo["source"]["units_per_ft"]
        dxf_path = geo_path[:-9]  # strip .cad.json
        spec = {
            "schema": "countertop-takeoff/v3",
            "sources": [{"source_id": "cad",
                         "path": dxf_path,
                         "sha256": sha256(dxf_path), "kind": "cad"}],
            "geometry": geo_path,
            "mode": "individual_rooms",
            "policy": {"gross_area": "gross"},
            "scope": {"pages": [{"source_id": "cad", "page": 1,
                                 "disposition": "measured",
                                 "expected_regions": ["slab:a"]}]},
            "calibrations": [],
            "regions": [{"region_id": "slab:a", "kind": "base",
                         "type": "A", "page": 1, "source_id": "cad",
                         "viewport": "main",
                         "boundary": {"seg_ids": [0, 1, 2, 3]},
                         "seed": [pts[1][0] / 2, pts[2][1] / 2],
                         "expected_sf_range": [24, 26]}],
            "_assemblies": [], "_pieces": [],
        }
        rc, res, err = run_measure(spec, f"v4_cad_{name}")
        area = next((r.get("area_sf") for r in (res or {}).get("regions", [])
                     if r["region_id"] == "slab:a"), None)
        check(f"cad metre/inch/mm equivalence ({name}): 25.00 SF exact",
              rc == 0 and area is not None and abs(area - 25.0) < 1e-6
              and upf > 0,
              f"rc={rc} area={area} upf={upf} err={err[:100]}")

    # MINSERT expansion + layer-0 inheritance (filter AFTER expansion)
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 1
    blk = doc.blocks.new(name="CTR")
    blk.add_lwpolyline([(0, 0), (120, 0), (120, 30), (0, 30)], close=True)
    doc.modelspace().add_blockref(
        "CTR", (100, 100),
        dxfattribs={"layer": "COUNTERTOP", "row_count": 2,
                    "column_count": 2, "row_spacing": 60.0,
                    "column_spacing": 200.0})
    minsert_path = os.path.join(BUILD, "v4_minsert.dxf")
    doc.saveas(minsert_path)
    cad_input.main([minsert_path, "--out", minsert_path + ".cad.json",
                    "--layers", "COUNTERTOP"])
    g = json.load(open(minsert_path + ".cad.json", encoding="utf-8"))
    segs = g["pages"][0]["segments"]
    layers = {s["layer"] for s in segs}
    check("MINSERT 2x2 expands to 16 segments on the EFFECTIVE layer",
          len(segs) == 16 and layers == {"COUNTERTOP"},
          f"n={len(segs)} layers={layers}")
    seg_keys = {(s["x0"], s["y0"], s["x1"], s["y1"]) for s in segs}
    origins = sorted({(s["x0"], s["y0"]) for s in segs})
    check("MINSERT cells land at distinct array offsets",
          len(seg_keys) == 16 and len(origins) == 16,
          f"distinct segments={len(seg_keys)} origins={len(origins)}")

    # bulge arcs: 120x30 rect + semicircular bulge (r=60) on the long edge
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 1
    doc.modelspace().add_lwpolyline(
        [(0, 0, 1.0), (120, 0, 0), (120, 30, 0), (0, 30, 0)],
        format="xyb", close=True)
    bulge_path = os.path.join(BUILD, "v4_bulge.dxf")
    doc.saveas(bulge_path)
    cad_input.main([bulge_path, "--out", bulge_path + ".cad.json"])
    g = json.load(open(bulge_path + ".cad.json", encoding="utf-8"))
    import math
    adj = {}
    for s in g["pages"][0]["segments"]:
        a = (s["x0"], s["y0"])
        b = (s["x1"], s["y1"])
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    ring = [next(iter(adj))]
    prev, cur = None, ring[0]
    while True:
        nxt = [n for n in adj[cur] if n != prev]
        prev, cur = cur, (nxt[0] if nxt else None)
        if cur == ring[0] or cur is None:
            break
        ring.append(cur)
    area_in2 = 0.0
    for i in range(len(ring)):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % len(ring)]
        area_in2 += x0 * y1 - x1 * y0
    area_in2 = abs(area_in2) / 2.0
    want = 3600.0 + math.pi * 60.0 ** 2 / 2.0
    err_pct = abs(area_in2 - want) / want * 100.0
    disclosed = any(c["scope"] == "cad arcs" for c in g["callouts"])
    check("bulge arc: area error <= 0.5% and tolerance disclosed",
          err_pct <= 0.5 and disclosed and g.get("arc_approximation"),
          f"err={err_pct:.3f}% disclosed={disclosed}")

    # moved/renamed CAD source: integrity stop, never cached results
    geo_path = rect_dxf(os.path.join(BUILD, "v4_move.dxf"), 1,
                        [(0, 0), (120.0, 0), (120.0, 30.0), (0, 30.0)])
    dxf_path = geo_path[:-9]
    spec = {
        "schema": "countertop-takeoff/v3",
        "sources": [{"source_id": "cad", "path": dxf_path,
                     "sha256": sha256(dxf_path), "kind": "cad"}],
        "geometry": geo_path,
        "mode": "individual_rooms",
        "policy": {"gross_area": "gross"},
        "scope": {"pages": [{"source_id": "cad", "page": 1,
                             "disposition": "measured",
                             "expected_regions": ["slab:a"]}]},
        "calibrations": [],
        "regions": [{"region_id": "slab:a", "kind": "base", "type": "A",
                     "page": 1, "source_id": "cad", "viewport": "main",
                     "boundary": {"seg_ids": [0, 1, 2, 3]},
                     "seed": [60.0, 15.0],
                     "expected_sf_range": [24, 26]}],
        "_assemblies": [], "_pieces": [],
    }
    moved = dxf_path + ".moved"
    os.replace(dxf_path, moved)
    rc, res, err = run_measure(spec, "v4_moved")
    os.replace(moved, dxf_path)
    check("moved CAD source: integrity stop (exit 2), no cached results",
          rc == 2 and ("not found" in err or "hash mismatch" in err),
          f"rc={rc} err={err[:140]}")


def estimate_tests():
    from decimal import Decimal
    check("estimate rounding: 3 x 55.555 -> 166.67 (ROUND_HALF_UP)",
          estimate_mod.cents(Decimal("55.555") * 3)
          == Decimal("166.67"),
          str(estimate_mod.cents(Decimal("55.555") * 3)))
    hotel_res = os.path.join(BUILD, "v4_hotel_base.results.json")
    if not os.path.exists(hotel_res):
        rc, res, err = run_measure(json.load(open(HOTEL_JOBS,
                                                  encoding="utf-8")),
                                   "v4_hotel_base",
                                   jobs_path=os.path.join(BUILD, "hotel",
                                                          "v4_base.jobs.json"))
    prof = os.path.join(HERE, "example.rate-profile.json")
    payload = estimate_mod.build_estimate(
        hotel_res, prof,
        out_md=os.path.join(BUILD, "v4_est.md"),
        out_json=os.path.join(BUILD, "v4_est.json"),
        out_pdf=os.path.join(BUILD, "v4_est.pdf"))
    # hotel: room-204 matches CT-ST-9625 AND CT-ST-VAN -> AMBIGUOUS -> blank
    amb = [c for c in payload["callouts"] if "AMBIGUOUS" in c["reason"]]
    check("estimate: ambiguous rate -> blank + callout (never picked)",
          payload["grand_total"] is None and len(amb) >= 1
          and all(l["line_total"] is None
                  for l in payload["lines"] if l["qty_ea"] is None),
          str([c["reason"][:60] for c in amb]))
    md = open(os.path.join(BUILD, "v4_est.md"), encoding="utf-8").read()
    js = json.load(open(os.path.join(BUILD, "v4_est.json"),
                        encoding="utf-8"))
    check("estimate: md/json grand totals agree (BLANK case)",
          "GRAND TOTAL: __blank__" in md and js["grand_total"] is None
          and js["priced_subtotal"] == payload["priced_subtotal"])
    import pymupdf
    doc = pymupdf.open(os.path.join(BUILD, "v4_est.pdf"))
    txt = "".join(pg.get_text() for pg in doc)
    check("estimate: pdf carries the SAME grand total as md/json",
          "GRAND TOTAL: BLANK" in txt
          and f"{payload['priced_subtotal']:,.2f}" in txt,
          txt[:80])
    check("estimate: exclusions carry GR package, never priced",
          {e["assembly_id"] for e in payload["exclusions"]}
          == {"gr-104", "gr-206"},
          str(payload["exclusions"]))

    # zero-rate vs missing-rate, all-priced grand total
    zero_prof = {
        "profile_version": "2", "company": "Zero Shop", "currency": "USD",
        "rates": [
            {"item_code": "Z-A", "match": {"assembly_kind": "A"},
             "uom": "EA", "unit_price": 0, "currency": "USD"},
            {"item_code": "Z-B", "match": {"assembly_kind": "B"},
             "uom": "EA", "unit_price": 100.0, "currency": "USD"},
            {"item_code": "Z-P", "match": {"assembly_kind": "PUB"},
             "uom": "EA", "unit_price": 55.555, "currency": "USD"},
            {"item_code": "Z-F", "match": {"assembly_kind": "FFE1"},
             "uom": "EA", "unit_price": 10.0, "currency": "USD"}],
    }
    zpath = os.path.join(BUILD, "v4_zero_profile.json")
    json.dump(zero_prof, open(zpath, "w", encoding="utf-8"))
    payload = estimate_mod.build_estimate(
        os.path.join(BUILD, "v4_mixed.results.json"), zpath,
        out_md=os.path.join(BUILD, "v4_est2.md"),
        out_json=os.path.join(BUILD, "v4_est2.json"),
        out_pdf=os.path.join(BUILD, "v4_est2.pdf"))
    zero_line = next(l for l in payload["lines"]
                     if l["item_code"] == "Z-A")
    check("estimate: explicit zero-rate prices a REAL 0.00 line",
          zero_line["unit_price"] == 0 and zero_line["line_total"] == 0.0,
          str(zero_line))
    check("estimate: all-priced grand total = EA x rate with exclusions out"
          " (8x100 + 55.555 -> 855.56)",
          payload["grand_total"] is not None
          and abs(payload["grand_total"] - 855.56) < 0.01,
          str(payload["grand_total"]))
    md2 = open(os.path.join(BUILD, "v4_est2.md"), encoding="utf-8").read()
    js2 = json.load(open(os.path.join(BUILD, "v4_est2.json"),
                         encoding="utf-8"))
    doc2 = pymupdf.open(os.path.join(BUILD, "v4_est2.pdf"))
    txt2 = "".join(pg.get_text() for pg in doc2)
    grand_s = f"{payload['grand_total']:,.2f}"
    check("estimate: priced case agrees across md/json/pdf",
          f"GRAND TOTAL: {grand_s} USD" in md2
          and js2["grand_total"] == payload["grand_total"]
          and grand_s in txt2, md2[-300:])

    # finish-only rate refuses at profile load
    bad_prof = {"profile_version": "2", "company": "Bad",
                "rates": [{"item_code": "X", "match": {"finish_tag": "PL"},
                           "uom": "EA", "unit_price": 1.0}]}
    bpath = os.path.join(BUILD, "v4_bad_profile.json")
    json.dump(bad_prof, open(bpath, "w", encoding="utf-8"))
    try:
        spec_schema.validate_profile({"profile": bpath}, BUILD)
        refused = False
    except SpecError:
        refused = True
    check("estimate: finish-only rate refuses at profile load",
          refused, "validate_profile accepted a finish-only rate")


def intake_tests_v4():
    jobdir = os.path.join(BUILD, "v4_intake_coll")
    shutil.rmtree(jobdir, ignore_errors=True)
    r = subprocess.run(
        [sys.executable, os.path.join(SKILL, "scripts", "intake.py"),
         "--job-dir", jobdir,
         "--entry", json.dumps({"requested": "plans.pdf",
                                 "local_path": HOTEL_PDF,
                                 "cloud_id": "drv1", "cloud_revision": "3",
                                 "kind": "google_drive"}),
         "--entry", json.dumps({"requested": "plans.pdf",
                                 "local_path": os.path.join(BUILD,
                                                            "messy.pdf"),
                                 "cloud_id": "drv2"}),
         "--entry", json.dumps({"requested": "drive://missing.pdf"}),
         "--expect", "3"],
        capture_output=True, text=True, cwd=SKILL)
    manifest = json.load(open(os.path.join(jobdir,
                                           "intake_manifest.json"),
                              encoding="utf-8"))
    srcs = manifest["sources"]
    dests = [e.get("destination_name") for e in srcs if e["status"] ==
             "resolved"]
    check("intake collisions: repeated basenames land on distinct files",
          sorted(dests) == ["plans-2.pdf", "plans.pdf"], str(dests))
    check("intake structured --entry: kinds + cloud ids recorded",
          srcs[0]["kind"] == "google_drive"
          and srcs[0]["cloud_id"] == "drv1"
          and srcs[0]["cloud_revision"] == "3"
          and srcs[1]["cloud_id"] == "drv2"
          and srcs[2]["kind"] == "cloud"
          and srcs[2]["status"] == "unavailable",
          str([(e["kind"], e.get("cloud_id"), e["status"])
               for e in srcs]))
    hashes = [e["sha256"] for e in srcs[:2]]
    check("intake: both colliding sources keep their OWN hashes",
          hashes[0] and hashes[1] and hashes[0] != hashes[1], str(hashes))


def main():
    shutil.rmtree(BUILD, ignore_errors=True)
    os.makedirs(BUILD, exist_ok=True)
    build_fixtures()
    mixed_resolved_tests()
    evidence_binding_tests()
    degradation_tests()
    cad_tests()
    estimate_tests()
    intake_tests_v4()
    print()
    failed = [r for r in RESULTS if not r[1]]
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}"
              + (f"  [{detail}]" if detail and not ok else ""))
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


def degradation_tests():
    hspec = json.load(open(HOTEL_JOBS, encoding="utf-8"))

    # (1) image-route range breach degrades LOCALLY (V3 stopped the job)
    spec = copy.deepcopy(hspec)
    for r in spec["regions"]:
        if r["region_id"] == "clubroom:counter":
            r["expected_sf_range"] = [1.0, 2.0]
    jobs_path = os.path.join(BUILD, "hotel", "v4_imgbreach.jobs.json")
    rc, res, err = run_measure(spec, "v4_imgbreach", jobs_path=jobs_path)
    club = next((r for r in (res or {}).get("regions", [])
                 if r["region_id"] == "clubroom:counter"), {})
    check("image-range breach: local degradation (exit 0, callouts)",
          rc == 0 and res.get("run_status") == "complete_with_callouts",
          f"rc={rc} status={res and res.get('run_status')} err={err[:120]}")
    check("image-range breach: degraded field GENUINELY null",
          club.get("area_sf") is None
          and club.get("measured_area_sf") is not None,
          str((club.get("area_sf"), club.get("measured_area_sf"))))

    # (2) planned overlap pair: BOTH records withheld, job completes
    spec = copy.deepcopy(hspec)
    for p in spec["scope"]["pages"]:
        if p.get("page") == 3 and p.get("disposition") == "measured":
            p["expected_regions"].append("room-102:counter@copy")
    src = next(r for r in spec["regions"]
               if r["region_id"] == "room-102:counter")
    clone = copy.deepcopy(src)
    clone["region_id"] = "room-102:counter@copy"
    spec["regions"].append(clone)
    jobs_path = os.path.join(BUILD, "hotel", "v4_overlap.jobs.json")
    rc, res, err = run_measure(spec, "v4_overlap", jobs_path=jobs_path)
    by_id = {r["region_id"]: r for r in (res or {}).get("regions", [])}
    check("overlap within counted scope: BOTH withheld, exit 0",
          rc == 0
          and by_id.get("room-102:counter", {}).get("area_sf") is None
          and by_id.get("room-102:counter@copy", {}).get("area_sf") is None
          and res.get("run_status") == "complete_with_callouts",
          f"rc={rc} status={res and res.get('run_status')}")

    # (3) audit pack on the (blank-area + multi-region) results: no crash
    res_path = os.path.join(BUILD, "v4_imgbreach.results.json")
    pack = os.path.join(BUILD, "v4_pack")
    try:
        audit_pack.render_pack(json.load(open(res_path, encoding="utf-8")),
                               pack, 2.0)
        pngs = [f for f in os.listdir(pack) if f.endswith(".png")]
        ok_pack = (os.path.exists(os.path.join(pack, "index.md"))
                   and len(pngs) >= 10)
    except Exception as exc:
        ok_pack = False
        pngs = [str(exc)]
    check("audit pack: multi-region + blank-area results render (no crash)",
          bool(ok_pack), str(pngs[:3]))

    # (4) stopped result never receives an approved receipt
    orig_add = measure.audit_mod.Audit.add

    def failing_add(self, chk, status, detail):
        if chk == "coverage ledger" and status == "pass":
            status = "fail"
            detail = "simulated required-check failure (tests_v4)"
        orig_add(self, chk, status, detail)
    measure.audit_mod.Audit.add = failing_add
    try:
        rc2, res2, err2 = run_measure(
            hspec, "v4_stopped",
            jobs_path=os.path.join(BUILD, "hotel", "v4_stopped.jobs.json"))
    finally:
        measure.audit_mod.Audit.add = orig_add
    receipt_rc = audit_pack.record_receipt(
        res2, os.path.join(BUILD, "v4_stopped.results.json"),
        "fresh-agent: tests_v4", "approved", "n", "pack")
    after = json.load(open(os.path.join(BUILD,
                                        "v4_stopped.results.json"),
                           encoding="utf-8"))
    check("stopped run: approved receipt REFUSED",
          rc2 == 2 and (res2 or {}).get("run_status") == "stopped"
          and receipt_rc == 2
          and after.get("review_status") != "independent_audit_approved",
          f"rc={rc2} receipt_rc={receipt_rc}"
          f" review={after.get('review_status')}")


if __name__ == "__main__":
    sys.exit(main())
