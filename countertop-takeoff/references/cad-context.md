# CAD context (V3) — dated 2025-06, verify before relying on it

Measurement route 2 in the V3 order is **supplied native CAD**. This file is
BACKGROUND for the operator/agent — it documents the CAD landscape and the
optional escalation paths. Nothing here is a runtime dependency; the skill
works end-to-end without any of it.

## What the skill supports natively

| input | support |
|---|---|
| vector PDF | route 1 — the primary path (`extract_geometry.py`) |
| `.dxf` | route 2 — `scripts/cad_input.py` (ezdxf): verified units, entity handles/layers, block inserts expanded, lines/polylines/arcs/splines/ellipses measured, closed polylines usable as boundaries; unsupported entities recorded as callouts |
| `.dwg` | **NOT supported directly.** Convert first with the free [ODA File Converter](https://www.opendesign.com) (DWG→DXF), then run `cad_input.py`. The refusal message says the same. |
| decent raster | route 3 — `scripts/image_measure.py`: agent-selected crop, labeled-dimension anchors, boundary points; overlay proof mandatory |
| unusable raster | no route — quantities stay BLANK + callout |

## Unit verification

`$INSUNITS` is the only honest scale in a DXF. UnITLESS files (`$INSUNITS`
0/missing) refuse unless `--units in|ft|mm|cm|m` declares them; the
declaration is recorded as **operator-verified** with a warning + callout.
Never "borrow" a scale from a neighboring sheet or a title-block note.

## Optional CAD-MCP escalation (documentation only)

If a set cannot be measured by routes 1–3 and the operator explicitly wants
CAD-tool escalation, these are the realistic options as of mid-2025. The
skill NEVER requires them at runtime; record any use (and its provenance)
in the job declarations:

- **OpenAI/ChatGPT desktop**: no first-party CAD plugin exists (checked
  2025-06); do not assume one.
- **Fusion 360**: CAD-agnostic MCP integration is built into Fusion's
  API/automation surface (Autodesk's own tooling), not a plugin install.
- **AutoCAD**: paid, via third-party MCP/COM connectors; Autodesk's own
  desktop COM API (`.SendCommand`, ActiveX) remains the classic path on
  Windows.
- **FreeCAD**: free, community-maintained MCP server(s) exist; quality
  varies; fine for reading/converting geometry locally.
- **kernelCAD**: hosted CAD automation service (third party).
- **PlanSwift**: desktop takeoff product with a COM SDK on Windows — a
  pragmatic local escalation for estimators already licensing it.

Escalation discipline (applies to ALL of the above): the same accuracy
hierarchy holds — exact vector geometry > best-effort with callouts >
explicit blank. Anything an external tool produces must land back in the
evidence package with its provenance, and coverage-ledger discipline
(measured / package_excluded / superseded / unresolved) is unchanged.
