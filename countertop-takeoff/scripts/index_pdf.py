# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf>=1.24"]
# ///
"""Page inventory for plan/spec PDFs (step 1 of the countertop takeoff).

Reads each page's vector TEXT ONLY (never images) and reports:
  - detected sheet number + title guess
  - flags: unit schedule / plan / schedule / spec / finish schedule
  - countertop-related keyword hits (counter, vanity, kitchen, cabinet)
  - type tags (TYPE A, TYPE B, ...) found on the page
  - dimension-like labels (e.g. 10'-0") found on the page

Writes a JSON file with the full per-page text so the agent can READ the unit
schedule (the multiplier table) without ever guessing from a rendered image.

Usage:
    uv run scripts/index_pdf.py <file.pdf> [more.pdf ...] [--out PATH]

Default --out: <pdf>.index.json next to the PDF. Prints a summary table.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

try:
    import pymupdf
except ImportError:  # older releases ship as fitz
    import fitz as pymupdf

# --- kept in sync with extract_geometry.py / measure.py ----------------------
SHEET_RE = re.compile(r"(?im)^\s*SHEET\s*[:#]?\s*([A-Z]{0,3}[-\s]?\d{1,4}[A-Z]?)\s*$")
SHEET_FALLBACK_RE = re.compile(r"(?im)^\s*([A-Z]{1,3}-\d{1,4})\s*$")
DIM_WORD_RE = re.compile(
    r"^\s*(\d{1,3})\s*'\s*-?\s*(\d{1,2}(?:\.\d+)?)?\s*(?:\"|''|”)?\s*$"
)
UNIT_SCHEDULE_RE = re.compile(r"unit schedule|room schedule|schedule of units|unit type", re.I)
SCHEDULE_RE = re.compile(r"\bschedule\b", re.I)
QTY_RE = re.compile(r"\b(qty|quantity|units|count)\b", re.I)
TYPE_TAG_RE = re.compile(r"\btype\s+([a-z0-9]{1,4})\b", re.I)
PLAN_RE = re.compile(r"floor plan|\bplan\b|enlarged", re.I)
COUNTER_RE = re.compile(r"countertop|counter|vanity|kitchen|cabinet", re.I)
SPEC_RE = re.compile(r"specification|division\s*\d{1,2}", re.I)
FINISH_RE = re.compile(r"finish", re.I)
SCALE_LINE_RE = re.compile(r"\bscale\b", re.I)


def parse_dim_word(word):
    m = DIM_WORD_RE.match(word)
    if not m:
        return None
    feet = int(m.group(1))
    inches = float(m.group(2)) if m.group(2) else 0.0
    real_ft = feet + inches / 12.0
    return real_ft if real_ft >= 0.5 else None


def detect_sheet(text):
    m = SHEET_RE.search(text) or SHEET_FALLBACK_RE.search(text)
    return m.group(1).replace(" ", "-").upper() if m else None


def title_guess(text, sheet):
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if sheet and s.upper().startswith("SHEET"):
            continue
        if SCALE_LINE_RE.search(s):
            continue
        return s[:80]
    return None


def dim_labels(text):
    """Dimension-like labels per line, skipping any line that notes a scale."""
    out = []
    for line in text.splitlines():
        if SCALE_LINE_RE.search(line):
            continue
        for word in line.split():
            real_ft = parse_dim_word(word)
            if real_ft is not None:
                out.append({"label": word, "real_ft": round(real_ft, 4)})
    return out


def index_pdf(path):
    doc = pymupdf.open(path)
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text("text") or ""
        labels = dim_labels(text)
        flags = {
            "unit_schedule": bool(UNIT_SCHEDULE_RE.search(text))
            or bool(SCHEDULE_RE.search(text) and QTY_RE.search(text) and TYPE_TAG_RE.search(text)),
            "schedule": bool(SCHEDULE_RE.search(text)),
            "plan": bool(PLAN_RE.search(text)),
            "spec": bool(SPEC_RE.search(text)),
            "finish_schedule": bool(FINISH_RE.search(text) and SCHEDULE_RE.search(text)),
            "counter_terms": len(COUNTER_RE.findall(text)),
            "type_tags": sorted({t.upper() for t in TYPE_TAG_RE.findall(text)}),
        }
        pages.append({
            "page": i + 1,  # 1-based, matches how humans cite sheets
            "sheet": detect_sheet(text),
            "title": title_guess(text, detect_sheet(text)),
            "width": round(page.rect.width, 2),
            "height": round(page.rect.height, 2),
            "dim_labels": labels,
            "dim_count": len(labels),
            "flags": flags,
            "text": text,
        })
    doc.close()
    return pages


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--out", help="output JSON path (default: <pdf>.index.json)")
    args = ap.parse_args()

    for path in args.pdfs:
        if not os.path.exists(path):
            sys.exit(f"ERROR: {path} not found")
        pages = index_pdf(path)
        out = args.out or os.path.splitext(path)[0] + ".index.json"
        payload = {
            "pdf": path,
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "page_count": len(pages),
            "pages": pages,
        }
        with open(out, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1)
        print(f"# PDF index: {path}  ({len(pages)} pages)  ->  {out}")
        print("| page | sheet | title | unit sched | plan | counter terms | dims | type tags |")
        print("|-----:|-------|-------|------------|------|---------------|------|-----------|")
        for p in pages:
            f_ = p["flags"]
            print(
                f"| {p['page']} | {p['sheet'] or '?'} "
                f"| {(p['title'] or '?')[:38]} "
                f"| {'YES' if f_['unit_schedule'] else '-'} "
                f"| {'yes' if f_['plan'] else '-'} "
                f"| {f_['counter_terms']} "
                f"| {p['dim_count']} "
                f"| {','.join(f_['type_tags']) or '-'} |"
            )
        print()
        print("Unit-schedule candidates :",
              [p["page"] for p in pages if p["flags"]["unit_schedule"]] or "NONE")
        print("Plan-sheet candidates    :",
              [p["page"] for p in pages if p["flags"]["plan"] and p["flags"]["counter_terms"] > 0] or "NONE")
        print("Next: READ the full page text in the JSON to extract the unit schedule counts.")
        print("      (Never read quantities from rendered images. Text and vector data only.)")


if __name__ == "__main__":
    main()
