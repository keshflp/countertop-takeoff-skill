"""Structured unresolved scope shared by measurement and pricing."""


def unresolved_scope(ledger=(), unavailable_inputs=()):
    entries = [dict(e) for e in ledger if e.get("state") == "unresolved"]
    entries.extend({"item": e["item"], "kind": "input", "state": "unresolved",
                    "detail": e["detail"], "source": e.get("source") or {}}
                   for e in unavailable_inputs)
    return entries
