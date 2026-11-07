# Selected scan-detail suggestions

## Choose a route

- Dimensioned phone photo: read its written numbers; no scan tool is needed.
- PDF with selectable dimensions: use rendered `inspect_input` previews. When OPS is connected, positioned text can help read labels (docs-based; untested).
- One faint or unreadable raster detail: optionally run `kernels/scan_detail.py` on that exact crop, review the original and overlay, then ask Dad to resolve dimensions.
- OPS unavailable: use the local preview and written labels. No live OPS was available to test these routes (2026-11-07); treat them as untested.

## Crop suggestions

Use only a PNG preview made by `inspect_input` and integer pixel bounds. The script crops those pixels without resampling and records the source, page when applicable, crop box, transform, crop hash and size, plus the cleaned and overlay paths. Its `--help` lists the command options.

For PDF previews, `inspect_input` renders the displayed page at zoom 2, so preview pixels map to rendered page points at one half. These points include PDF `/Rotate`, use the visible CropBox's top-left as the origin, and increase y downward. Conversion to unrotated PDF, annotation or OPS coordinates is unsupported. For image previews, coordinates stay in the image-pixel space of the EXIF-transposed preview and have no page scale. The script's own pinned OpenCV and NumPy dependencies are fetched by `uv` only when this optional script runs; the plain dimensioned-sketch workflow does not need them.

Treat every outline as unreviewed linework. It may be a wall, cabinet or sink, and cleanup may erase labels or gaps. Read written dimensions or ask Dad. Keep measured facts separate from estimates. Suggestions never supply dimensions, areas, quantities, material, price or confirmation, and never update `job.json`.

## OPS (docs-based; untested in this experiment)

These notes are based on the [official MCP tool catalogue](https://raw.githubusercontent.com/OpenAEC-Foundation/open-pdf-studio/main/mcp-stdio/tools.json), checked 2026-11-07. No live OPS was available to test these routes; treat them as untested.

`app_get_page_text` returns positioned text spans. `app_capture_region` renders in the view rotation and returns its page, actual rectangle, pixel width and height, DPI, and resolution-limit flag; it may cap resolution. The catalogue does not specify a rotation-angle field in that receipt. Preserve the receipt and record the view rotation separately when known. Its app-point rectangle is view-rotated; do not treat it as an unrotated 72-point page mapping. If the rotation or conversion cannot be established, mark the mapping unsupported.

`app_create_annotation` can create a manually supplied `measureArea` polygon; it does not auto-trace or snap a suggestion. `app_get_takeoff` reads totals from named schedules and does not promise that a new annotation appears in those totals.
