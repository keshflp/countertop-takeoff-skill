"""Phone-readable v2 geometry and evidence panels; no physical rules live here."""

from __future__ import annotations

from pathlib import Path

from draw_layout import COLORS, WHITE, WIDTH, bbox, dimension, feet_inches, font
from layout_geometry import FabricationPolygon, Rect, solid_cells, stone_segments
from PIL import Image, ImageDraw
from seam_model import closed, read_request

AMBER = "#ffd36e"


def validate_drawing(data: dict) -> None:
    closed(data, "version slab settings installations assessment layout geometryEstimates")
    assessment = closed(data["assessment"], "status geometry profile checks conditions unresolved handling limitations installations search")
    profile = closed(assessment["profile"], "id provenance nominalThicknessMm")
    read_request({"version": data["version"], "mode": "assessment", "phase": "assess",
                  "material": {"profileId": profile["id"], "profileProvenance": profile["provenance"],
                               "nominalThicknessMm": profile["nominalThicknessMm"]},
                  "slab": data["slab"], "settings": data["settings"], "installations": data["installations"]})
    closed(assessment["search"], "status candidateFamilies candidateCount qualifyingCount packing optimality limits")
    for item in assessment["unresolved"]:
        closed(item, "field question")
    for item in assessment["installations"]:
        closed(item, "id seamNecessity explanation")
    for check in assessment["checks"]:
        closed(check, "id ruleId installationId cutoutIndex joinId status operator actual required source explanation fields")
        for key in ("actual", "required"):
            if check[key] is not None:
                closed(check[key], "value unit")
    for condition in assessment["conditions"]:
        closed(condition, "id kind installationId cutoutIndex joinId status source explanation evidenceNote fields")
    for record in [*assessment["checks"], *assessment["conditions"]]:
        if record["source"] is not None:
            closed(record["source"], "id title edition url sha256 filePages printedPages quotation interpretation")
    for estimate in data["geometryEstimates"]:
        closed(estimate, "installationId cutoutIndex fields note xIn yIn wIn hIn")
    layout = data["layout"]
    if layout is not None:
        closed(layout, "pieces joins slabs slabCount lowerBound provenOptimal footprintMode warnings")
        for piece in layout["pieces"]:
            closed(piece, "id installationId outline cutouts")
            polygon(piece["outline"])
            for clip in piece["cutouts"]:
                closed(clip, "cutoutIndex outline")
                polygon(clip["outline"])
        for join in layout["joins"]:
            closed(join, "id installationId pieceIds kind axis offsetIn startIn endIn segments cutoutIndex origin reason")
            for segment in join["segments"]:
                closed(segment, "x0 y0 x1 y1")
        for slab in layout["slabs"]:
            closed(slab, "index placements")
            for placement in slab["placements"]:
                closed(placement, "pieceId x y quarterTurns")
                if type(placement["quarterTurns"]) is not int or placement["quarterTurns"] not in range(4):
                    raise ValueError("Piece rotation must be zero, one, two or three quarter turns.")


def wrapped(text: str, size: int = 32, width: int = WIDTH - 88) -> list[str]:
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines = []
    line = ""
    for word in text.split():
        if line and draw.textlength(line + " " + word, font=font(size)) > width:
            lines.append(line)
            line = ""
        while draw.textlength(word, font=font(size)) > width:
            n = len(word)
            while draw.textlength(word[:n], font=font(size)) > width:
                n -= 1
            if line:
                lines.append(line)
                line = ""
            lines.append(word[:n])
            word = word[n:]
        line = (line + " " + word).strip()
    if line:
        lines.append(line)
    return lines


def text_panel(title: str, paragraphs: list[tuple[str, str]], *, size: int = 32) -> Image.Image:
    rows = [(line, color) for text, color in paragraphs for line in [*wrapped(text, size), ""]]
    heading = wrapped(title, 42)
    image = Image.new("RGB", (WIDTH, 56 + len(heading) * 54 + len(rows) * (size + 10)), "black")
    draw = ImageDraw.Draw(image)
    y = 24
    for line in heading:
        draw.text((44, y), line, font=font(42, True), fill=WHITE)
        y += 54
    for line, color in rows:
        draw.text((44, y), line, font=font(size), fill=color)
        y += size + 10
    return image


def polygon(points: list[list[float]]) -> FabricationPolygon:
    return FabricationPolygon(tuple((round(x * 16), round(y * 16)) for x, y in points))


def label_in_stone(draw, points, openings, label, point, scale, color="black") -> tuple[float, float] | None:
    gross = polygon(points)
    cells = solid_cells(gross, [Rect(round(c["x"] * 16), round(c["y"] * 16), round(c["w"] * 16), round(c["h"] * 16)) for c in openings])
    candidates = sorted(cells, key=lambda c: (-c.area, c))
    if not candidates:
        return None
    for cell in candidates:
        if cell.w / 16 * scale > draw.textlength(label, font=font(32, True)) + 12 and cell.h / 16 * scale > 42:
            draw.text(point((cell.x + cell.w / 2) / 16, (cell.y + cell.h / 2) / 16), label,
                      font=font(32, True), fill=color, anchor="mm")
            return None
    cell = candidates[0]
    return point((cell.x + cell.w / 2) / 16, (cell.y + cell.h / 2) / 16)


def preview_segments(inst: dict) -> list[dict]:
    intent = inst.get("seam")
    if not intent or intent["cutoutIndex"] >= len(inst["cutouts"]):
        return []
    cut = inst["cutouts"][intent["cutoutIndex"]]
    arrangement = inst["sourceArrangement"]
    axis = "x" if intent["kind"] == "center-through-cutout" else arrangement["axis"] if arrangement else None
    if axis is None:
        return []
    x0, y0, x1, y1 = bbox(inst["outline"])
    start, length = (cut["x"], cut["w"]) if axis == "x" else (cut["y"], cut["h"])
    at = (x0 + x1) / 2 if intent["kind"] == "center-through-cutout" else start + length / 2
    if intent["kind"] == "tangent-cutout":
        at = start + (length if intent["side"] == "end" else 0)
    if at * 16 != round(at * 16):
        return []
    line = Rect(round(at * 16), round(y0 * 16), 0, round((y1 - y0) * 16)) if axis == "x" else Rect(round(x0 * 16), round(at * 16), round((x1 - x0) * 16), 0)
    cuts = [Rect(round(c["x"] * 16), round(c["y"] * 16), round(c["w"] * 16), round(c["h"] * 16)) for c in inst["cutouts"]]
    return [{"x0": s.x / 16, "y0": s.y / 16, "x1": (s.x + s.w) / 16, "y1": (s.y + s.h) / 16}
            for s in stone_segments(polygon(inst["outline"]), line, cuts)]


def installation_panel(inst: dict, layout: dict | None, colors: dict[str, str]) -> list[Image.Image]:
    outline = inst["outline"]
    x0, y0, x1, y1 = bbox(outline)
    scale = min((WIDTH - 260) / (x1 - x0), 680 / (y1 - y0))
    bottom = round(180 + (y1 - y0) * scale)
    pieces = [p for p in layout["pieces"] if p["installationId"] == inst["id"]] if layout else []
    joins = [j for j in layout["joins"] if j["installationId"] == inst["id"]] if layout else []
    image = Image.new("RGB", (WIDTH, bottom + 100 + 48 * len(pieces)), "black")
    draw = ImageDraw.Draw(image)
    draw.text((44, 24), inst["id"], font=font(44, True), fill=WHITE)
    draw.text((44, 82), "Installed outline | origin: upper left", font=font(30), fill=WHITE)
    def point(x, y):
        return 130 + (x - x0) * scale, 180 + (y - y0) * scale
    draw.polygon([point(*p) for p in outline], fill="#163346", outline=WHITE, width=3)
    for piece in pieces:
        draw.polygon([point(*p) for p in piece["outline"]], fill=colors[piece["id"]], outline="black", width=2)
    for n, cut in enumerate(inst["cutouts"], 1):
        draw.rectangle((*point(cut["x"], cut["y"]), *point(cut["x"] + cut["w"], cut["y"] + cut["h"])), fill="black", outline=WHITE, width=3)
        # The number identifies an opening, never a piece floating in a void.
        if cut["w"] * scale >= 38 and cut["h"] * scale >= 38:
            draw.text(point(cut["x"] + cut["w"] / 2, cut["y"] + cut["h"] / 2), str(n), font=font(30), fill=WHITE, anchor="mm")
    segments = [s for j in joins for s in j["segments"]] if layout else preview_segments(inst)
    for s in segments:
        draw.line([point(s["x0"], s["y0"]), point(s["x1"], s["y1"])], fill=WHITE if layout else AMBER, width=5)
    for n, piece in enumerate(pieces):
        center = label_in_stone(draw, piece["outline"], inst["cutouts"], piece["id"], point, scale)
        a, b, c, d = bbox(piece["outline"])
        y = bottom + 82 + n * 48
        draw.text((44, y), f"{piece['id']}   bounds {feet_inches(c - a)} x {feet_inches(d - b)}", font=font(32, True), fill=colors[piece["id"]])
        if center is not None:
            draw.line([center, (WIDTH - 55, y + 18)], fill=WHITE, width=2)
    for a, b in zip(outline, outline[1:] + outline[:1]):
        horizontal = a[1] == b[1]
        offset = (-28 if b[0] > a[0] else 28) if horizontal else (28 if b[1] > a[1] else -28)
        dimension(image, point(*a), point(*b), feet_inches(abs(a[0] - b[0]) + abs(a[1] - b[1])), horizontal, offset)
    notes = []
    if inst.get("requiredPieceCount"):
        notes.append((f"Supplied requirement: exactly {inst['requiredPieceCount']} fabrication pieces.", AMBER))
    if inst.get("seam"):
        s = inst["seam"]
        label = {"center-through-cutout": "equal halves at the opening", "opening-center": "join at the opening center; additional joins may be needed", "tangent-cutout": "tangent join (unsupported detail)"}[s["kind"]]
        notes.append((f"Supplied intent: {label}, opening {s['cutoutIndex'] + 1}. Amber preview lines show intent, not an admitted plan.", AMBER))
    for j in joins:
        notes.append((f"{j['id']}: {j['origin']}, {j['reason']}; {j['kind']}. {j['axis']} = {feet_inches(j['offsetIn'])} from installation origin; span {feet_inches(j['startIn'])} to {feet_inches(j['endIn'])}. {len(j['segments'])} stone segment(s).", WHITE))
    arrangement = inst["sourceArrangement"]
    notes.append((f"Source datum: run axis {arrangement['axis']}, rear {arrangement['rear']}. {arrangement['provenance']}" if arrangement else "Source arrangement / front-rear datum: unknown.", WHITE))
    if len(outline) > 4:
        notes.append((f"Continuous inside radius: {inst['insideCornerRadiusMm'] or 'unknown'} mm.", WHITE))
    for n, c in enumerate(inst["cutouts"], 1):
        notes.append((f"Opening {n}, {c['kind']}: {feet_inches(c['w'])} x {feet_inches(c['h'])}; left {feet_inches(c['x'])}, top {feet_inches(c['y'])}. Inside radius: {c['radiusMm'] if c['radiusMm'] is not None else 'unknown'} mm; mount: {c['mount'] or 'unknown'}.", WHITE))
    for c in inst["conditions"]:
        scope = "whole installation" if c["cutoutIndex"] is None else f"opening {c['cutoutIndex'] + 1}"
        notes.append((f"Supplied {c['kind']} ({scope}): {c['status']}. {c['note'] or 'No evidence supplied.'}", WHITE))
    return [image, text_panel(f"{inst['id']}: dimensions and supplied facts", notes)]


def transformed(points, gross, placement):
    a, b, c, d = bbox(gross)
    q = placement["quarterTurns"]
    result = []
    for x, y in points:
        x, y = x - a, y - b
        if q == 1:
            x, y = d - b - y, x
        elif q == 2:
            x, y = c - a - x, d - b - y
        elif q == 3:
            x, y = y, c - a - x
        result.append([x + placement["x"], y + placement["y"]])
    return result


def slab_panel(slab: dict, data: dict, colors: dict[str, str]) -> list[Image.Image]:
    length, depth = data["slab"]["lengthIn"], data["slab"]["widthIn"]
    trim = data["settings"]["slabTrimIn"]
    scale = min((WIDTH - 100) / length, 700 / depth)
    bottom = round(150 + depth * scale)
    image = Image.new("RGB", (WIDTH, bottom + 150), "black")
    draw = ImageDraw.Draw(image)
    draw.text((44, 24), f"Slab {slab['index']} | {feet_inches(length)} x {feet_inches(depth)}", font=font(40, True), fill=WHITE)
    draw.text((44, 86), "Gross blanks reserve opening stock", font=font(32), fill=WHITE)
    def point(x, y):
        return 44 + (trim + x) * scale, 150 + (trim + y) * scale
    x0, y0, x1, y1 = 44, 150, 44 + length * scale, 150 + depth * scale
    draw.rectangle((x0, y0, x1, y1), fill="#202020", outline=WHITE, width=3)
    for start in range(-round(y1 - y0), round(x1 - x0), 24):
        lo, hi = max(0, -start), min(y1 - y0, x1 - x0 - start)
        draw.line((x0 + start + lo, y0 + lo, x0 + start + hi, y0 + hi), fill="#777777", width=2)
    pieces = {p["id"]: p for p in data["layout"]["pieces"]}
    notes = []
    for n, placement in enumerate(slab["placements"]):
        piece = pieces[placement["pieceId"]]
        outline = transformed(piece["outline"], piece["outline"], placement)
        draw.polygon([point(*p) for p in outline], fill=colors[piece["id"]], outline=WHITE, width=3)
        openings = []
        for clip in piece["cutouts"]:
            points = transformed(clip["outline"], piece["outline"], placement)
            a, b, c, d = bbox(points)
            openings.append({"x": a, "y": b, "w": c - a, "h": d - b})
            # Adjacent clips are one void. Do not draw their collision-cell
            # boundaries as white lines inside the opening.
            draw.polygon([point(*p) for p in points], fill="black")
        center = label_in_stone(draw, outline, openings, piece["id"], point, scale)
        if center is not None:
            # Full-size callout avoids putting a fabrication label in an opening.
            target = (44 + n * (WIDTH - 100) / max(1, len(slab["placements"])), bottom + 20)
            draw.line([center, target], fill=WHITE, width=2)
            draw.text(target, str(n + 1), font=font(30, True), fill=WHITE)
        a, b, c, d = bbox(piece["outline"])
        notes.append((f"{n + 1}. {piece['id']} | bounds {feet_inches(c - a)} x {feet_inches(d - b)} | clockwise {placement['quarterTurns'] * 90} degrees | usable origin x {feet_inches(placement['x'])}, y {feet_inches(placement['y'])}.", colors[piece["id"]]))
    a, b = point(0, 0)
    c, d = point(length - 2 * trim, depth - 2 * trim)
    for x in range(round(a), round(c), 20):
        for y in (b, d):
            draw.line((x, y, min(x + 11, c), y), fill=WHITE, width=3)
    for y in range(round(b), round(d), 20):
        for x in (a, c):
            draw.line((x, y, x, min(y + 11, d)), fill=WHITE, width=3)
    draw.text((44, bottom + 65), "Dashed: usable border. Hatched: waste.", font=font(30), fill=WHITE)
    draw.text((44, bottom + 105), "Black openings: reserved stock, not reusable waste.", font=font(30), fill=WHITE)
    return [image, text_panel(f"Slab {slab['index']}: piece key", notes)]


def evidence_panels(assessment: dict) -> list[Image.Image]:
    questions = [(f"{q['field']}: {q['question']}", AMBER) for q in assessment["unresolved"]]
    questions.extend((f"{i['id']}: {i['seamNecessity']}. {i['explanation']}", WHITE) for i in assessment["installations"])
    checks = []
    sources = {}
    for record in [*assessment["checks"], *assessment["conditions"]]:
        src = record["source"]
        if src:
            entry = sources.setdefault(src["id"], {**src, "filePages": set(), "printedPages": set()})
            entry["filePages"].update(src["filePages"])
            entry["printedPages"].update(src["printedPages"])
        scope = ", ".join(str(v) for v in (record["installationId"],
                          f"opening {record['cutoutIndex'] + 1}" if record["cutoutIndex"] is not None else None,
                          record["joinId"]) if v is not None)
        label = record.get("ruleId", record.get("kind"))
        predicate = ""
        if record.get("actual") is not None:
            actual = record["actual"]
            predicate = f" Actual {actual['value']} {actual['unit']}."
        if record.get("required") is not None:
            required = record["required"]
            predicate += f" Required {record['operator']} {required['value']} {required['unit']}."
        citation = f" [{src['id']}, file p.{','.join(map(str, src['filePages']))}; printed p.{','.join(map(str, src['printedPages']))}]" if src else ""
        color = AMBER if record["status"] not in {"pass", "satisfied", "not-applicable"} else WHITE
        checks.append((f"{record['status'].upper()} | {scope} | {label}.{predicate}{citation} {record['explanation']}", color))
        if record.get("evidenceNote"):
            checks.append((f"Supplied evidence: {record['evidenceNote']}", WHITE))
    panels = [text_panel("Outstanding facts and seam reasons", questions),
              text_panel("Source checks and installation conditions", checks)]
    references = []
    for key, src in sorted(sources.items()):
        references.append((f"{key}: {src['title']}. {src['edition']}. File pages {', '.join(map(str, sorted(src['filePages'])))}; printed pages {', '.join(map(str, sorted(src['printedPages'])))}.", WHITE))
        references.append((src["url"], WHITE))
    references.extend((text, WHITE) for text in assessment["limitations"])
    references.extend((text, WHITE) for text in assessment["search"]["limits"])
    references.append((f"Search {assessment['search']['status']}; {assessment['search']['optimality']}. Handling: not evaluated.", AMBER))
    panels.append(text_panel("Source editions and limits", references, size=30))
    return panels


def render_assessment(data: dict, out: Path, *, preview: bool = False) -> None:
    validate_drawing(data)
    assessment = data["assessment"]
    layout = None if preview else data["layout"]
    status = assessment["status"]
    profile = assessment["profile"]
    notices = [(f"Assessment: {status.upper()}. Handling is not evaluated.", AMBER if status != "assessed" else WHITE),
               (f"Profile: {profile['id'] or 'unknown'}; nominal thickness: {profile['nominalThicknessMm'] or 'unknown'} mm.", WHITE),
               (f"Profile evidence: {profile['provenance'] or 'unknown'}", WHITE)]
    if status == "conditional":
        notices.insert(0, ("PRELIMINARY: source conditions remain outstanding", AMBER))
    if not layout and not preview:
        notices.insert(0, ("No final slab layout is available for this assessment.", AMBER))
    if data["geometryEstimates"]:
        notices.insert(0, ("Preliminary: estimated geometry", AMBER))
        for estimate in data["geometryEstimates"]:
            fields = ", ".join({"wIn": "width", "hIn": "height", "at": "position"}[f] for f in estimate["fields"])
            notices.append((f"{estimate['installationId']}, opening {estimate['cutoutIndex'] + 1}: {fields} estimated. {estimate['note']}", AMBER))
    outstanding = sum(c["status"] != "satisfied" for c in assessment["conditions"])
    if outstanding or assessment["unresolved"]:
        notices.append((f"{len(assessment['unresolved'])} unanswered fact(s); {outstanding} outstanding condition(s). Full questions and source details follow the drawings.", AMBER))
    heading = "Confirm geometry and model facts" if preview else f"{layout['slabCount']} slab(s) | {len(layout['pieces'])} pieces" if layout else "Installation assessment"
    panels = [text_panel(heading, notices)]
    colors = {p["id"]: COLORS[n % len(COLORS)] for n, p in enumerate(layout["pieces"])} if layout else {}
    for inst in data["installations"]:
        panels.extend(installation_panel(inst, layout, colors))
    if layout:
        for slab in layout["slabs"]:
            panels.extend(slab_panel(slab, data, colors))
    panels.extend(evidence_panels(assessment))
    image = Image.new("RGB", (WIDTH, sum(p.height for p in panels)), "black")
    y = 0
    for panel in panels:
        image.paste(panel, (0, y))
        y += panel.height
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, format="PNG")
