# CAD routes and provenance

Use routes in order: vector PDF, supplied DXF with verified units, then
calibrated image measurement. CAD escalation is optional, not required.

| Input | Supported route |
|---|---|
| Vector PDF | `extract_geometry.py`, selected boundaries, per-viewport calibration |
| DXF | `cad_input.py` (ezdxf): entity handles/layers, expanded block inserts, lines/polylines/arcs/splines/ellipses; closed polylines as boundaries; unsupported entities disclosed |
| DWG | Convert to DXF first with [ODA File Converter](https://www.opendesign.com); no direct DWG reading |
| Legible raster | `image_measure.py`: selected crop, labeled anchors, boundary points, mandatory overlay |
| Unusable raster | Quantities BLANK with a named callout |

## Units

DXF `$INSUNITS` supplies scale. Unitless/missing units refuse unless
`--units in|ft|mm|cm|m` declares them; the declaration is recorded as
operator-verified with a warning/callout. Never borrow a title-block scale
or neighboring viewport's calibration. Source bytes are re-hashed before use.
Unsupported entities/extrusions and curve approximations remain disclosed;
see [method tolerances](method.md).

## Optional external-tool escalation

If supported routes cannot resolve scope and the operator explicitly requests
CAD-tool escalation, use an available local tool/connector and record its
identity, conversion/settings, source hashes, units, and resulting selections.
External outputs must return to the evidence package with provenance.
The same hierarchy applies: exact geometry > best-effort with callouts > blank;
coverage-ledger and three-stop rules remain unchanged. No connector is required.
