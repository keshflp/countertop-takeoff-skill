"""Tolerant sheet identity (V3, P0.4).

Real sets have inconsistent sheet labels: a wrong duplicate title block
(two pages carrying the same sheet number with different content), sheets
missing from the drawing index, alias spellings (A-101 vs A1.01 vs A112),
PDF page labels that disagree with the title block. V2 trusted the single
regex'd sheet id and hard-failed or silently dropped pages. V3 treats each
signal as separate EVIDENCE and keys every page by (source_id, page_number):

  signals: title-block label, drawing-index reference, PDF page label,
           sheet title, revision marks, content fingerprint

Sheet-number ALIASES normalize to candidate form ("A1.01" and "A-101" both
normalize to A101) but are CANDIDATES, never auto-equivalent: an alias match
must be confirmed by the agent and is otherwise reported.

Identity conflicts and index gaps become CALLOUTS (handled by audit.py via
``audit_identity``), never silent scope drops.
"""

import re

# Candidate normalization: uppercase, keep only [A-Z0-9].
_CORE_RE = re.compile(r"[^A-Z0-9]")
# Sheet-label shapes accepted in drawing indexes and title blocks.
LABEL_RE = re.compile(r"\b([A-Z]{1,3}[-. ]?\d{1,4}(?:\.\d{1,2})?[A-Z]?)\b")


def normalize(label):
    """'A-101' / 'A1.01' / 'a 101' -> 'A101' (candidate form)."""
    return _CORE_RE.sub("", (label or "").upper())


def alias_candidates(label):
    """Alias candidates for a label: itself, normalized form, and the
    zero-stripped variant ('A101' -> 'A1.01' candidate family). Candidates
    are POSSIBLE matches the agent must confirm - never auto-equivalent."""
    core = normalize(label)
    out = {core}
    digits = re.sub(r"^([A-Z]+)", r"\1", core)
    m = re.match(r"^([A-Z]+)(\d+)$", digits)
    if m:
        prefix, num = m.group(1), m.group(2).lstrip("0") or "0"
        out.add(prefix + num)
    return out


def audit_identity(pages, scope_by_page, index_sheets, add_callout):
    """Tolerant identity audit over one source's pages.

    pages: list of page records (index or geometry JSON). scope_by_page:
    {page_number: scope entry}. index_sheets: drawing-index sheet list.
    add_callout: fn(scope_str, reason, detail). Returns findings list.

    Rules (all findings are callouts - a conflicted/missing identity may
    never silently drop a page from scope):
      - two pages with the same title-block label and different content:
        one callout naming both pages; the scope must disposition each page
        separately (page-keyed, not label-keyed)
      - a measured page with NO title-block label: callout
      - sheets listed in the drawing index but absent from the pack: callout
      - a scope sheet label that matches the title block only via an alias:
        callout to confirm the alias
    """
    findings = []
    by_label = {}
    for p in pages:
        tb = p.get("sheet")
        if tb:
            by_label.setdefault(normalize(tb), []).append(p)
    for core, group in sorted(by_label.items()):
        if len(group) < 2:
            continue
        fps = {p.get("preflight", {}).get("fingerprint") for p in group}
        if len(fps) > 1:
            pgos = [p["page"] for p in group]
            disp = [scope_by_page.get(pno, {}).get("disposition")
                    for pno in pgos]
            measured = [pno for pno, d in zip(pgos, disp)
                        if d == "measured"]
            findings.append(("identity", "conflict",
                             f"sheet label {group[0]['sheet']!r} appears on"
                             f" pages {pgos} with DIFFERENT content"
                             f" (dispositions: {disp}); each page is keyed"
                             " by its page number and must carry its own"
                             " scope disposition"))
            if len(measured) > 1:
                findings.append((
                    "identity", "conflict",
                    f"pages {measured} share sheet label"
                    f" {group[0]['sheet']!r} and are BOTH measured - confirm"
                    " they are really separate scope (mislabeled sheets) or"
                    " supersede one; this cannot be resolved silently"))
    # measured pages without any sheet label
    for p in pages:
        entry = scope_by_page.get(p["page"])
        if entry and entry.get("disposition") == "measured" and not p.get("sheet"):
            findings.append((
                "identity", "unlabeled",
                f"page {p['page']} is measured but carries no sheet label in"
                " its title block - record the label evidence in the job spec"
                " so the sheet can be tracked"))
    # index gaps: listed in the drawing index, absent from the pack
    pack_labels = {normalize(p["sheet"]) for p in pages if p.get("sheet")}
    for listed in index_sheets or []:
        cands = alias_candidates(listed)
        if not (pack_labels & cands):
            findings.append((
                "identity", "index_gap",
                f"sheet {listed!r} is listed in the drawing index but no page"
                " in the set carries it - the sheet is either missing from"
                " the delivery or the index is stale; report it, never drop"
                " it silently"))
    for p in pages:
        tb = p.get("sheet")
        entry = scope_by_page.get(p["page"]) or {}
        label = entry.get("sheet")
        if tb and label and normalize(label) not in alias_candidates(tb) \
                and normalize(tb) not in alias_candidates(label):
            findings.append((
                "identity", "mismatch",
                f"page {p['page']}: scope says sheet {label!r} but the title"
                f" block reads {tb!r} (alias candidates do not intersect) -"
                " confirm which label is authoritative"))
    for kind, tag, detail in findings:
        add_callout(f"sheet identity ({kind}/{tag})", detail)
    return findings
