# Company profile (V2 groundwork — SF active, identity only)

A company profile is a small JSON file that captures how THIS shop does
takeoffs, so job specs can reference identity instead of re-declaring
conventions. V2 activates SQUARE FEET ONLY: profile fields are recorded,
validated for consistency, and shown in reports — they never price anything.

## File schema (`--profile` referenced from a job spec via `"profile": "<path>"`)

| key | type | meaning |
|-----|------|---------|
| `profile_version` | `"1"` | schema version |
| `company` | string | display name |
| `material_aliases` | map alias → canonical | spelling/naming tolerance; canonical names are what reports record |
| `gross_net_policy` | `"gross"` \| `"net_of_declared_cutouts"` | the shop's DEFAULT policy; a job spec may override explicitly |
| `required_components` | list of strings | components this shop always takes off (e.g. counter, vanity); audit prompt checks omissions against it |
| `report_preferences` | object | free-form display prefs (group_by, show_edge_lf) — recorded, not enforced |
| `approved_assumptions` | list of strings | statements an approver has signed off on; echoed into every report for the reviewer |

## Region identity in the job spec (V2 groundwork)

Regions may carry:
- `"assembly"` — what this region is in shop language (e.g.
  `kitchen-run`, `island`, `vanity-top`, `peninsula`)
- `"material"` — an alias or canonical material name; resolved through
  `material_aliases` and recorded as `material_canonical`

Validation rules:
- if the spec names a profile, the file must exist and parse; unknown
  top-level keys are rejected (typos should not pass silently)
- a region `material` must resolve via the profile's aliases or canonical
  names; an unresolved material is a hard error, not a warning
- if `policy.gross_area` is absent in the spec, the profile's
  `gross_net_policy` is used; if both are absent the spec is invalid (v2
  never guesses a gross/net policy)
- profiles never change math: no pricing, no waste factors, no seam planning
  (out of scope by design — see SKILL.md "Extension points")

## Activation status

| capability | status in V2 |
|---|---|
| counter/vanity SF | **active** |
| assembly/material identity | recorded only |
| edge LF | informational only (computed, not a deliverable) |
| backsplash, cutout pricing, slab yield, quotes | not built |
