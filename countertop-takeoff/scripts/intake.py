# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1"]
# ///
"""Step 0 intake (P0.7): one job directory + a manifest of resolved inputs.

Resolves the requested sources into ONE auto-created job directory on the
target machine and writes an INTAKE MANIFEST: requested vs resolved paths,
cloud ids/revisions when supplied, sizes, SHA-256 digests, PDF page counts,
and an expected-count verdict. Unavailable inputs are recorded as
`unavailable` entries (disclosed callouts downstream) - the job completes
with what arrived and names what did not.

Input kinds the agent handles BEFORE calling this script:
  - local paths: passed straight through (copied into the job dir)
  - chat-dragged attachments: the harness saved them to temp files; pass
    the temp path and the ORIGINAL name via --name
  - Google Drive names/links: the Drive plugin fetches ORIGINAL binaries;
    the agent fetches the file to the job dir first, then passes the local
    path (record cloud id/revision with --cloud-id/--cloud-rev)
  - OneDrive personal: same pattern via its local sync folder

Usage:
    uv run scripts/intake.py --job-dir jobs/riverside --expect 2 \
        --source plans.pdf --cloud-id drv_1 --cloud-rev 3 \
        --source addendum.pdf \
        --name plans.pdf --source C:/temp/att1
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pdf_page_count(path):
    try:
        import pymupdf
        doc = pymupdf.open(path)
        n = doc.page_count
        doc.close()
        return n
    except Exception:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job-dir", required=True,
                    help="job directory (auto-created; sources land in"
                         " <job-dir>/sources)")
    ap.add_argument("--source", action="append", default=[],
                    help="requested source: a local path, or a name/URL not"
                         " yet fetched (recorded as unavailable)")
    ap.add_argument("--name", action="append", default=[],
                    help="original display name for the preceding --source"
                         " (attachments); repeat as needed")
    ap.add_argument("--cloud-id", action="append", default=[],
                    help="cloud file id for the preceding --source")
    ap.add_argument("--cloud-rev", action="append", default=[],
                    help="cloud revision for the preceding --source")
    ap.add_argument("--expect", type=int, default=None,
                    help="expected number of sources; mismatch is disclosed"
                         " in the manifest verdict")
    args = ap.parse_args(argv)

    src_dir = os.path.join(args.job_dir, "sources")
    os.makedirs(src_dir, exist_ok=True)
    entries = []
    for i, requested in enumerate(args.source):
        original = args.name[i] if i < len(args.name) else \
            os.path.basename(requested.replace("\\", "/").rstrip("/"))
        cloud_id = args.cloud_id[i] if i < len(args.cloud_id) else None
        cloud_rev = args.cloud_rev[i] if i < len(args.cloud_rev) else None
        entry = {"requested": requested, "name": original,
                 "cloud_id": cloud_id, "cloud_revision": cloud_rev,
                 "resolved_path": None, "status": None, "size_bytes": None,
                 "sha256": None, "page_count": None}
        if os.path.isfile(requested):
            dest = os.path.join(src_dir, original)
            if os.path.abspath(requested) != os.path.abspath(dest):
                shutil.copy2(requested, dest)
            entry["resolved_path"] = dest
            entry["status"] = "resolved"
            entry["size_bytes"] = os.path.getsize(dest)
            entry["sha256"] = file_sha256(dest)
            if dest.lower().endswith(".pdf"):
                entry["page_count"] = pdf_page_count(dest)
        else:
            entry["status"] = "unavailable"
            entry["note"] = ("not found locally - fetch Drive/OneDrive/"
                             "attachment binaries to the job dir first,"
                             " then re-run intake with the local path;"
                             " the job proceeds without it and discloses"
                             " the gap as a callout")
        entries.append(entry)

    resolved = [e for e in entries if e["status"] == "resolved"]
    verdict = "ok"
    if args.expect is not None and len(resolved) != args.expect:
        verdict = ("expected_count_mismatch: requested"
                   f" {len(entries)}, resolved {len(resolved)},"
                   f" expected {args.expect} - the mismatch is disclosed"
                   " and travels into the takeoff callouts")
    manifest = {
        "schema": "countertop-takeoff/v3 intake",
        "job_dir": args.job_dir,
        "generated_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "expected_count": args.expect,
        "verdict": verdict,
        "sources": entries,
    }
    out = os.path.join(args.job_dir, "intake_manifest.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    print(f"# intake -> {out}")
    for e in entries:
        if e["status"] == "resolved":
            pages = f", {e['page_count']} pages" if e["page_count"] else ""
            print(f"  resolved: {e['name']} ({e['size_bytes']} bytes"
                  f"{pages}) sha256 {e['sha256'][:16]}...")
        else:
            print(f"  UNAVAILABLE: {e['requested']} - {e['note'][:90]}")
    print(f"  verdict: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
