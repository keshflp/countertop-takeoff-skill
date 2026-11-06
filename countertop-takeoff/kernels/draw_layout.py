# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow==12.0.0"]
# ///
"""Draw confirmed kitchen outlines and slab layouts as a phone-readable PNG."""

from __future__ import annotations

import argparse
import json
import sys
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1080
MARGIN = 130
COLORS = ("#76d7ff", "#ffd36e", "#d7a4ff", "#7ae2ac", "#ffac9b", "#bcccff")
WHITE = "#ffffff"


def feet_inches(value: float) -> str:
    ticks = round(value * 16)
    feet, remainder = divmod(ticks, 192)
    inches, numerator = divmod(remainder, 16)
    fraction = f" {Fraction(numerator, 16)}" if numerator else ""
    return f"{feet}' {inches}{fraction}\""


@lru_cache(maxsize=32)
def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in (("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
                 ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                 "/System/Library/Fonts/Supplemental/Arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def bbox(points: list[list[float]]) -> tuple[float, float, float, float]:
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def fitted_text(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, width: float,
                *, size: int = 38, fill: str = WHITE, anchor: str = "mm") -> None:
    while size > 28 and draw.textlength(text, font=font(size, True)) > width:
        size -= 2
    draw.text(xy, text, font=font(size, True), fill=fill, anchor=anchor)


def dimension(image: Image.Image, a: tuple[float, float], b: tuple[float, float], label: str,
              horizontal: bool, offset: int) -> None:
    draw = ImageDraw.Draw(image)
    if horizontal:
        x0, x1, y = min(a[0], b[0]), max(a[0], b[0]), a[1] + offset
        draw.line((x0, y, x1, y), fill=WHITE, width=2)
        for x in (x0, x1):
            draw.line((x, y - 7, x, y + 7), fill=WHITE, width=2)
        center = ((x0 + x1) / 2, y + (24 if offset > 0 else -24))
        bounds = draw.textbbox(center, label, font=font(30), anchor="mm")
        draw.rectangle((bounds[0] - 5, bounds[1] - 3, bounds[2] + 5, bounds[3] + 3), fill="black")
        draw.text(center, label, font=font(30), anchor="mm", fill=WHITE)
    else:
        y0, y1, x = min(a[1], b[1]), max(a[1], b[1]), a[0] + offset
        draw.line((x, y0, x, y1), fill=WHITE, width=2)
        for y in (y0, y1):
            draw.line((x - 7, y, x + 7, y), fill=WHITE, width=2)
        length = int(draw.textlength(label, font=font(30))) + 12
        text = Image.new("RGB", (length, 42), "black")
        ImageDraw.Draw(text).text((length / 2, 21), label, font=font(30), fill=WHITE, anchor="mm")
        text = text.rotate(90, expand=True)
        image.paste(text, (round(x + (26 if offset > 0 else -26) - text.width / 2),
                           round((y0 + y1) / 2 - text.height / 2)))


def installation_panel(inst: dict, layout: dict | None, colors: dict[str, str]) -> Image.Image:
    outline = inst["outline"]
    x0, y0, x1, y1 = bbox(outline)
    scale = min((WIDTH - 2 * MARGIN) / (x1 - x0), 720 / (y1 - y0))
    diagram_bottom = round(190 + (y1 - y0) * scale)
    pieces = [p for p in layout["pieces"] if p["installationId"] == inst["id"]] if layout else []
    rows = len(pieces) + 2 * len(inst["cutouts"])
    image = Image.new("RGB", (WIDTH, diagram_bottom + 140 + 52 * rows), "black")
    draw = ImageDraw.Draw(image)
    fitted_text(draw, (44, 42), str(inst.get("label", inst["id"])), WIDTH - 88, size=46, anchor="lm")
    join = inst.get("seam")
    if join:
        draw.text((44, 92), f"Join equal halves at opening {join['cutoutIndex'] + 1}",
                  font=font(34, True), fill=WHITE)

    def point(x: float, y: float) -> tuple[float, float]:
        return MARGIN + (x - x0) * scale, 190 + (y - y0) * scale

    draw.polygon([point(x, y) for x, y in outline], fill="#163346", outline=WHITE, width=3)
    for piece in pieces:
        a, b, c, d = bbox(piece["outline"])
        draw.polygon([point(x, y) for x, y in piece["outline"]], fill=colors[piece["id"]], outline="black", width=2)
        # IDs also appear in the full-size key below when a cutout covers one.
        if (c - a) * scale > 45 and (d - b) * scale > 40:
            draw.text(point((a + c) / 2, (b + d) / 2), piece["id"], font=font(36, True), fill="black", anchor="mm")
    if layout:
        for s in layout["seams"]:
            if s["installationId"] == inst["id"]:
                draw.line([point(s["x0"], s["y0"]), point(s["x1"], s["y1"])], fill=WHITE, width=6)
    elif join:
        middle = (x0 + x1) / 2
        draw.line([point(middle, y0), point(middle, y1)], fill=WHITE, width=6)
    for n, cut in enumerate(inst["cutouts"], 1):
        a = point(cut["x"], cut["y"])
        b = point(cut["x"] + cut["w"], cut["y"] + cut["h"])
        draw.rectangle((*a, *b), fill="black", outline=WHITE, width=3)
        # Paint the void after the seam. The selected opening stays empty; its
        # number is in the join caption and cutout key, not on the join's path.
        if not join or n - 1 != join["cutoutIndex"]:
            draw.text(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), str(n), font=font(32, True), fill=WHITE, anchor="mm")
    # Every wall and return gets its own dimension; no shape-specific formulas.
    for a, b in zip(outline, outline[1:] + outline[:1]):
        horizontal = a[1] == b[1]
        if a == b:
            continue
        length = abs(a[0] - b[0]) + abs(a[1] - b[1])
        offset = (-28 if b[0] > a[0] else 28) if horizontal else (28 if b[1] > a[1] else -28)
        dimension(image, point(*a), point(*b), feet_inches(length), horizontal, offset)
    y = diagram_bottom + 112
    for piece in pieces:
        a, b, c, d = bbox(piece["outline"])
        draw.text((44, y), f"{piece['id']}   {feet_inches(c - a)} x {feet_inches(d - b)}",
                  font=font(36, True), fill=colors[piece["id"]])
        y += 52
    for n, cut in enumerate(inst["cutouts"], 1):
        draw.text((44, y), f"{n}. {cut['kind'].capitalize()}   {feet_inches(cut['w'])} x {feet_inches(cut['h'])}",
                  font=font(34, True), fill=WHITE)
        draw.text((80, y + 46), f"Left {feet_inches(cut['x'])}   Top {feet_inches(cut['y'])}",
                  font=font(32), fill=WHITE)
        y += 104
    return image


def slab_panel(slab: dict, data: dict, colors: dict[str, str]) -> Image.Image:
    length, depth = data["slab"]["lengthIn"], data["slab"]["widthIn"]
    trim = data["settings"]["slabTrimIn"]
    scale = min((WIDTH - 88) / length, 720 / depth)
    bottom = round(150 + depth * scale)
    image = Image.new("RGB", (WIDTH, bottom + 142 + len(slab["placements"]) * 52), "black")
    draw = ImageDraw.Draw(image)
    draw.text((44, 28), f"Slab {slab['index']}", font=font(46, True), fill=WHITE)
    draw.text((44, 88), f"{feet_inches(length)} x {feet_inches(depth)}", font=font(34), fill=WHITE)
    x0, y0, x1, y1 = 44, 150, 44 + length * scale, bottom
    draw.rectangle((x0, y0, x1, y1), fill="#282828", outline=WHITE, width=3)
    # Waste is visible even when printed without color.
    for start in range(-int(y1 - y0), int(x1 - x0), 24):
        lo, hi = max(0, -start), min(y1 - y0, x1 - x0 - start)
        draw.line((x0 + start + lo, y0 + lo, x0 + start + hi, y0 + hi), fill="#666666", width=2)
    pieces = {p["id"]: p for p in data["layout"]["pieces"]}
    for p in slab["placements"]:
        a, b, c, d = bbox(pieces[p["pieceId"]]["outline"])
        w, h = (d - b, c - a) if p["rotated"] else (c - a, d - b)
        x, y = 44 + (trim + p["x"]) * scale, 150 + (trim + p["y"]) * scale
        draw.rectangle((x, y, x + w * scale, y + h * scale), fill=colors[p["pieceId"]], outline="black", width=2)
        if min(w, h) * scale >= 42:
            fitted_text(draw, (x + w * scale / 2, y + h * scale / 2), p["pieceId"], w * scale - 8, fill="black")
    ux0, uy0, ux1, uy1 = x0 + trim * scale, y0 + trim * scale, x1 - trim * scale, y1 - trim * scale
    for start in range(round(ux0), round(ux1), 20):
        for y in (uy0, uy1):
            draw.line((start, y, min(start + 11, ux1), y), fill=WHITE, width=3)
    for start in range(round(uy0), round(uy1), 20):
        for x in (ux0, ux1):
            draw.line((x, start, x, min(start + 11, uy1)), fill=WHITE, width=3)
    draw.text((44, bottom + 24), f"Usable {feet_inches(length - 2 * trim)} x {feet_inches(depth - 2 * trim)}",
              font=font(32), fill=WHITE)
    draw.text((44, bottom + 68), "Dashed border: usable area. Hatched: waste.", font=font(30), fill=WHITE)
    for n, p in enumerate(slab["placements"]):
        a, b, c, d = bbox(pieces[p["pieceId"]]["outline"])
        text = f"{p['pieceId']}   {feet_inches(c - a)} x {feet_inches(d - b)}" + ("   turned" if p["rotated"] else "")
        draw.text((44, bottom + 124 + n * 52), text, font=font(36, True), fill=colors[p["pieceId"]])
    return image


def render(data: dict, out: Path, *, preview: bool = False) -> None:
    layout = None if preview else data["layout"]
    if layout is not None and not layout.get("ok"):
        raise ValueError("A safe slab layout is needed before drawing the slabs.")
    colors = {p["id"]: COLORS[n % len(COLORS)] for n, p in enumerate(layout["pieces"])} if layout else {}
    panels = [installation_panel(inst, layout, colors) for inst in data["installations"]]
    if layout:
        panels.extend(slab_panel(slab, data, colors) for slab in layout["slabs"])
    heading = "Confirm these measurements" if preview else (
        f"{layout['slabCount']} slab{'s' if layout['slabCount'] != 1 else ''} | "
        f"{len(layout['pieces'])} piece{'s' if len(layout['pieces']) != 1 else ''}")
    estimates = data.get("geometryEstimates", [])
    notices = []
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for estimate in estimates:
        inst = next(i for i in data["installations"] if i["id"] == estimate["installationId"])
        index = estimate["cutoutIndex"]
        fields = ", ".join({"wIn": "width", "hIn": "height", "at": "position"}[f] for f in estimate["fields"])
        description = f"{inst.get('label', inst['id'])}, cutout {index + 1} ({inst['cutouts'][index]['kind']}): {fields} estimated."
        for paragraph in (description, estimate["note"]):
            line = ""
            for word in paragraph.split():
                joined = f"{line} {word}".strip()
                if line and measure.textlength(joined, font=font(34)) > WIDTH - 88:
                    notices.append(line)
                    line = word
                else:
                    line = joined
            if line:
                notices.append(line)
    header = 140 + (74 + 46 * len(notices) if estimates else 0)
    image = Image.new("RGB", (WIDTH, header + sum(p.height for p in panels)), "black")
    draw = ImageDraw.Draw(image)
    draw.text((44, 32), heading, font=font(46, True), fill=WHITE)
    if estimates:
        draw.text((44, 104), "Preliminary: estimated geometry", font=font(44, True), fill="#ffd36e")
        for n, line in enumerate(notices):
            draw.text((44, 168 + n * 46), line, font=font(34), fill=WHITE)
    y = header
    for panel in panels:
        image.paste(panel, (0, y))
        y += panel.height
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, format="PNG")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--selfcheck", action="store_true")
    args = parser.parse_args()
    if args.selfcheck:
        print('{"ok":true}')
        return
    if args.out is None:
        parser.error("--out is required")
    try:
        render(json.load(sys.stdin), args.out, preview=args.preview)
        print(json.dumps({"ok": True, "path": str(args.out)}))
    except (KeyError, TypeError, ValueError, OSError, ZeroDivisionError):
        print(json.dumps({"ok": False, "error": {"tag": "drawing_failed", "message": "The picture could not be saved. Check the outlines, layout and output folder."}}))
        sys.exit(1)


if __name__ == "__main__":
    main()
