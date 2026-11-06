# /// script
# requires-python = ">=3.12"
# dependencies = ["pymupdf>=1.26,<2", "Pillow>=12,<13", "pillow-heif>=1,<2"]
# ///
"""Check phone sketches and render pictures for the agent; never measure them."""

import argparse
import json
from pathlib import Path
from typing import Literal, TypedDict

import pymupdf
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()


class Inspection(TypedDict):
    path: str
    ok: bool
    kind: Literal["image", "pdf"]
    pages: int
    previews: list[str]
    problem: str | None


def inspect_file(file: str | Path) -> Inspection:
    """Return one plain result per input, including ordinary file failures."""
    path = Path(file).resolve()
    result: Inspection = {
        "path": str(path), "ok": False,
        "kind": "pdf" if path.suffix.lower() == ".pdf" else "image",
        "pages": 0, "previews": [], "problem": None,
    }
    try:
        if not path.is_file():
            result["problem"] = "I couldn't find that file. Please send it again."
        elif path.stat().st_size == 0:
            result["problem"] = "That file is empty. Please send the original again."
        elif result["kind"] == "pdf":
            with pymupdf.open(path) as document:
                if document.is_encrypted or (document.metadata or {}).get("encryption"):
                    result["problem"] = "That PDF is password protected. Please send an unlocked copy."
                elif document.page_count == 0:
                    result["problem"] = "That PDF has no pages. Please send the plans again."
                else:
                    directory = path.parent / "previews" / path.name
                    directory.mkdir(parents=True, exist_ok=True)
                    previews = []
                    for index, page in enumerate(document, start=1):
                        target = directory / f"page-{index}.png"
                        page.get_pixmap(dpi=144, alpha=False).save(str(target))
                        previews.append(str(target))
                    result.update(ok=True, pages=document.page_count, previews=previews)
        else:
            with Image.open(path) as source:
                if source.format not in {"PNG", "JPEG", "HEIF"}:
                    result["problem"] = "Please send a PNG, JPEG, HEIC photo, or PDF."
                    return result
                source.verify()
            with Image.open(path) as source:
                source.load()
                picture = ImageOps.exif_transpose(source)
                if picture.mode not in {"RGB", "RGBA", "L", "LA"}:
                    picture = picture.convert("RGB")
                directory = path.parent / "previews" / path.name
                directory.mkdir(parents=True, exist_ok=True)
                target = directory / "page-1.png"
                picture.save(target, format="PNG")
            result.update(ok=True, pages=1, previews=[str(target)])
    except PermissionError:
        result["problem"] = "I couldn't open that file or save its pictures. Please use a folder I can access."
    except (OSError, ValueError, RuntimeError, SyntaxError, Image.DecompressionBombError):
        result["problem"] = "I couldn't read that file. It may be damaged. Please send the original again."
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*")
    parser.add_argument("--selfcheck", action="store_true")
    args = parser.parse_args()
    if args.selfcheck:
        print('{"ok":true}')
    elif args.files:
        print(json.dumps({"files": [inspect_file(file) for file in args.files]}))
    else:
        parser.error("send at least one input file")


if __name__ == "__main__":
    main()
