# Company profile (v2 schema — identity + optional EA rates)

A company profile is a small JSON file that captures how THIS shop does
takeoffs, so job specs can reference identity instead of re-declaring
conventions. Two profiles exist in the repo:

- `examples/example.profile.json` — **identity profile** (SF workflow; no
  pricing)
- `examples/example.rate-profile.json` — **rate profile** (v2 pricing
  schema for the assembly-EA estimate)

## Identity schema (`"profile": "<path>"` in a job spec)

| key | type | meaning |
|-----|------|---------|
| `profile_version` | `"1"` / `"2"` | schema version |
| `company` | string | display name |
| `material_aliases` | map alias → canonical | spelling/naming tolerance; canonical names are what reports record |
| `gross_net_policy` | `"gross"` \| `"net_of_declared_cutouts"` | the shop's DEFAULT policy; a job spec may override explicitly |
| `required_components` | list of strings | components this shop always takes off; the audit checks omissions against it |
| `report_preferences` | object | free-form display prefs (group_by, show_edge_lf) — recorded, not enforced |
| `approved_assumptions` | list of strings | statements an approver has signed off on; echoed into every report |
| `package_defaults` | `{"exclude": ["FFE", ...]}` | packages excluded from main totals by default (reported separately) |

Validation rules:
- if the spec names a profile, the file must exist and parse; unknown
  top-level keys are rejected (typos should not pass silently)
- a region `material` must resolve via the profile's aliases or canonical
  names; an unresolved material is a hard error, not a warning
- if `policy.gross_area` is absent in the spec, the profile's
  `gross_net_policy` is used; if both are absent the spec is invalid
- profiles never change takeoff MATH: no waste factors, no seam planning

## Pricing schema (v2, P1.1) — `rates[]` + `currency`

| key | meaning |
|-----|---------|
| `currency` | profile-level currency (e.g. `"USD"`); every rate's currency must agree — mixed currencies refuse |
| `rates[]` | one entry per company rate; each prices an ASSEMBLY as EA × `unit_price` |

Each rate:

| key | required | meaning |
|-----|----------|---------|
| `item_code` | yes | the stable code every estimate line cites (unique in the profile) |
| `match` | yes | which assemblies the rate prices. **`match.assembly_kind` (the assembly type) is REQUIRED** — a rate must pin the assembly identity; finish alone never selects a price (finish-only rates refuse at load). Optional exact matchers: `finish_tag`, `width_in`, `depth_in`, `height_in`, `handing`, `package` |
| `uom` | yes | must be `"EA"` (v4 prices assembly EA × rate; SF pricing is not built) |
| `unit_price` | yes | finite ≥ 0. An explicit `0` prices a REAL 0.00 line — distinguishable from a missing rate |
| `currency` | no | must equal the profile currency when both are present |
| `includes` | no | components the rate already covers (top/edge/splash/cutout labor) so they are not charged again |

Estimate behavior (scripts/estimate.py):
- exactly ONE matching rate → priced line (`qty EA × unit_price`, Decimal,
  ROUND_HALF_UP to whole cents)
- zero matching rates → amount BLANK + callout (no rate found)
- two+ matching rates → amount BLANK + "AMBIGUOUS" callout listing the
  codes — disambiguate the profile, code never picks
- assembly EA withheld upstream → amount BLANK + callout (quantity
  evidence travels with the line); EA pricing never reads SF, so a valid
  EA price survives SF being unresolved
- package-excluded assemblies are listed as EXCLUSIONS, never priced
- the grand total is BLANK while any in-scope amount is unknown

## Activation status

| capability | status |
|---|---|
| counter/vanity SF, edge LF, splash, cutouts | **active** (measured/BoQ) |
| assembly/material identity | **active** (resolved + recorded) |
| package exclusion rules | **active** (profile defaults, job override) |
| assembly-EA pricing | **active** (rate profile; estimate.md/json/pdf) |
| SF × material price matrix, waste, seam planning | not built (roadmap) |
