"""Windows-aware identity and dependent artifact publication bookkeeping."""
import json
import os
from datetime import datetime, timezone


def identity(path):
    return os.path.normpath(os.path.realpath(os.path.abspath(path))).replace("\\", "/").casefold()


def aliases(a, b):
    if identity(a) == identity(b):
        return True
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def reject_aliases(inputs, outputs):
    seen = dict(inputs)
    for label, path in outputs.items():
        if not path:
            continue
        for other, protected in seen.items():
            if protected and aliases(path, protected):
                raise SystemExit(f"ERROR: {label} {path!r} aliases {other}; use distinct paths")
        seen[label] = path


def manifest_path(results_path):
    return str(results_path) + ".artifacts.json"


def dependent_paths(results_path):
    try:
        with open(manifest_path(results_path), encoding="utf-8") as f:
            return json.load(f).get("paths") or []
    except FileNotFoundError:
        return []


def register_artifacts(results_path, paths):
    reject_aliases({"results": results_path}, {"artifact manifest": manifest_path(results_path)})
    paths = [os.path.abspath(p) for p in [*dependent_paths(results_path), *paths] if p]
    unique = {identity(p): p for p in paths}
    os.makedirs(os.path.dirname(os.path.abspath(results_path)), exist_ok=True)
    with open(manifest_path(results_path), "w", encoding="utf-8") as f:
        json.dump({"results_path": os.path.abspath(results_path),
                   "paths": list(unique.values())}, f, indent=1)


def quarantine(paths):
    from report_out import quarantine_stale_export
    when = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    for path in paths:
        if path and os.path.exists(path):
            quarantine_stale_export(path, when)
