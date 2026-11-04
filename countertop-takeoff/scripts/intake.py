# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1"]
# ///
"""Step 0 intake (P0.7, repaired per P1.2): one job directory + manifest.

Resolves the requested sources into ONE auto-created job directory on the
target machine and writes an INTAKE MANIFEST: requested vs resolved paths,
cloud ids/revisions when supplied, sizes, SHA-256 digests, PDF page counts,
and an expected-count verdict. Unavailable inputs are recorded as
`unavailable` entries (disclosed callouts downstream) - the job completes
with what arrived and names what did not.

V4 repairs (P1.2):
  - COLLISION-SAFE destinations: two sources with the same basename land on
    distinct files (name.pdf, name-2.pdf, ...); every entry records BOTH
    the requested name and the actual destination, so a collision can never
    silently overwrite evidence
  - STRUCTURED per-source metadata: pass --entry JSON (one object per
    source: requested/local_path/name/cloud_id/cloud_revision/kind/note) -
    no positional pairing of flags; the positional --source/--name/--cloud-*
    flags still work for quick runs
  - the DRIVE FETCH IS AN AGENT-SIDE CONTRACT: this script imports LOCAL
    paths only. The host agent fetches Drive/OneDrive/attachment binaries
    into the job dir FIRST (or supplies structured entries with their cloud
    ids); scripts never talk to Drive themselves.

Input kinds the agent handles BEFORE calling this script:
  - local paths: passed straight through (copied into the job dir)
  - chat-dragged attachments: the harness saved them to temp files; pass
    the temp path and the ORIGINAL name via --name or --entry
  - Google Drive names/links: the agent fetches the ORIGINAL binary to the
    job dir first, then passes the local path (record cloud id/revision via
    --entry or --cloud-id/--cloud-rev)
  - OneDrive personal: same pattern via its local sync folder

Usage:
    uv run scripts/intake.py --job-dir jobs/riverside --expect 2
        --entry {"requested": "plans.pdf", "local_path": "p.pdf",
                 "cloud_id": "drv_1", "cloud_revision": "3",
                 "kind": "google_drive"}
        --source addendum.pdf
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from preflight_lib import file_sha256


def pdf_page_count(path):
    try:
        import pymupdf
        doc = pymupdf.open(path)
        n = doc.page_count
        doc.close()
        return n
    except Exception:
        return None


def collision_free_dest(src_dir, original, taken):
    """P1.2: a destination that never collides - 'plans.pdf',
    'plans-2.pdf', 'plans-3.pdf', ... for repeat basenames."""
    base = original.replace("\\", "/").rstrip("/").split("/")[-1] or "source"
    stem, ext = os.path.splitext(base)
    candidate = base
    n = 2
    while os.path.normcase(os.path.abspath(os.path.join(src_dir, candidate))) \
            in taken:
        candidate = f"{stem}-{n}{ext}"
        n += 1
    return os.path.join(src_dir, candidate)


def require_entry(e):
    if not isinstance(e, dict) or not e.get("requested"):
        print("ERROR: --entry JSON needs at least {'requested': ...}",
              file=sys.stderr)
        raise SystemExit(2)


def classify_kind(e):
    """Best-effort intake kind for structured metadata."""
    requested = str(e.get("requested") or "").lower()
    if e.get("cloud_id") or requested.startswith("drive") \
            or requested.startswith("http"):
        return e.get("kind") or "cloud"
    return e.get("kind") or "local"


def pre_existing_destinations(src_dir):
    """P0.1: files ALREADY sitting in the sources directory are collisions
    too - a retry must never overwrite an earlier intake's copy."""
    taken = set()
    if os.path.isdir(src_dir):
        for name in os.listdir(src_dir):
            p = os.path.join(src_dir, name)
            if os.path.isfile(p):
                taken.add(os.path.normcase(os.path.abspath(p)))
    return taken


def intake_one_source(e, i, src_dir, taken):
    """Resolve ONE source entry. Copy/hash/page-count failures are RETAINED
    as a per-source `error` entry (P0.1) instead of escaping before the
    manifest is written - one bad source never discards the manifest."""
    requested = e["requested"]
    local_path = e.get("local_path") or requested
    original = (e.get("name") or os.path.basename(
        requested.replace("\\", "/").rstrip("/"))) or "source"
    entry = {"entry_index": i,
             "requested": requested,
             "name": original,
             "kind": classify_kind(e),
             "cloud_id": e.get("cloud_id"),
             "cloud_revision": e.get("cloud_revision"),
             "resolved_path": None, "status": None, "size_bytes": None,
             "sha256": None, "page_count": None}
    if e.get("note"):
        entry["note"] = e["note"]
    # P0.1: collision-safe destination - repeated basenames AND pre-existing
    # files never overwrite each other
    pre_existing = os.path.normcase(os.path.abspath(os.path.join(
        src_dir, original))) in taken
    dest = collision_free_dest(src_dir, original, taken)
    taken.add(os.path.normcase(os.path.abspath(dest)))
    try:
        if os.path.isfile(local_path):
            if os.path.abspath(local_path) != os.path.abspath(dest):
                shutil.copy2(local_path, dest)
            entry["resolved_path"] = dest
            entry["destination_name"] = os.path.basename(dest)
            entry["status"] = "resolved"
            entry["size_bytes"] = os.path.getsize(dest)
            entry["sha256"] = file_sha256(dest)
            if dest.lower().endswith(".pdf"):
                entry["page_count"] = pdf_page_count(dest)
            if pre_existing:
                entry["note"] = (e.get("note") or "") + (
                    " destination basename already held an earlier intake"
                    " copy - it was preserved untouched; this copy landed on"
                    f" {entry['destination_name']}").strip()
        else:
            entry["status"] = "unavailable"
            entry["note"] = e.get("note") or (
                "not found locally - fetch Drive/OneDrive/attachment"
                " binaries to the job dir first, then re-run intake with the"
                " local path; the job proceeds without it and discloses the"
                " gap as a callout")
    except Exception as exc:  # noqa: BLE001 - per-source, retained
        entry["status"] = "error"
        entry["error"] = f"{type(exc).__name__}: {exc}"
        entry["note"] = ((e.get("note") or "") + " intake FAILED for this"
                         " source (retained in the manifest; the manifest is"
                         " still written) - fix the source and re-run"
                         " intake").strip()
    return entry


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job-dir", required=True,
                    help="job directory (auto-created; sources land in"
                         " <job-dir>/sources)")
    ap.add_argument("--entry", action="append", default=[],
                    help="structured per-source metadata JSON (P1.2: no"
                         " positional pairing): {requested, local_path?,"
                         " name?, cloud_id?, cloud_revision?, kind?, note?};"
                         " repeat for every source")
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

    # normalize BOTH input shapes into structured entry dicts (P1.2)
    entries_in = []
    for raw in args.entry:
        try:
            e = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"ERROR: --entry is not valid JSON ({exc}): {raw[:80]}",
                  file=sys.stderr)
            return 2
        require_entry(e)
        entries_in.append(e)
    for i, requested in enumerate(args.source):
        entries_in.append({
            "requested": requested,
            "name": args.name[i] if i < len(args.name) else None,
            "cloud_id": args.cloud_id[i] if i < len(args.cloud_id) else None,
            "cloud_revision": (args.cloud_rev[i]
                               if i < len(args.cloud_rev) else None),
        })

    src_dir = os.path.join(args.job_dir, "sources")
    os.makedirs(src_dir, exist_ok=True)
    entries = []
    taken = pre_existing_destinations(src_dir)
    for i, e in enumerate(entries_in):
        entries.append(intake_one_source(e, i, src_dir, taken))

    resolved = [e for e in entries if e["status"] == "resolved"]
    errors = [e for e in entries if e["status"] == "error"]
    verdict = "ok"
    if errors:
        verdict = (f"source_errors: {len(errors)} source(s) failed during"
                   " intake (retained in the manifest; re-run intake for"
                   " them)")
    if args.expect is not None and len(resolved) != args.expect:
        if errors:
            verdict += " + "
        verdict += ("expected_count_mismatch: requested"
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
            renamed = ("" if e.get("destination_name") == e["name"]
                       else " (collision-safe dest:"
                            f" {e.get('destination_name')})")
            print(f"  resolved: {e['name']} ({e['size_bytes']} bytes"
                  f"{pages}) sha256 {e['sha256'][:16]}...{renamed}")
        else:
            note = (e.get("note") or "")[:90]
            print(f"  UNAVAILABLE: {e['requested']} - {note}")
    for e in errors:
        print(f"  ERROR: {e['requested']} - {e.get('error', '')[:90]}")
    print(f"  verdict: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
