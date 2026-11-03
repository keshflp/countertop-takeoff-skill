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
| `required_components` | list of strings | components this shop always takes off. **Recorded + echoed into results only — NOT enforced by the audit.** The coverage ledger and callouts carry the completeness findings; the operator/auditor reads `required_components` against them |
| `report_preferences` | object | free-form display prefs (group_by, show_edge_lf) — recorded, not enforced |
| `approved_assumptions` | list of strings | statements an approver has signed off on; echoed into every report |
| `package_defaults` | `{"exclude": ["FFE", ...]}` | packages excluded from main totals by default (reported separately) |
| `terms` | list of strings | the shop's SUPPLIED terms a proposal may quote verbatim (`scripts/proposal.py`); the proposal never invents terms |

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
| `unit_price` | yes | finite ≥ 0. Accepts plain numbers or unambiguous currency-formatted strings (`"$1,234.56"`, `"1.234,56"`) — parsed Decimal-exact; negatives and ambiguous strings refuse with a diagnostic. An explicit `0` prices a REAL 0.00 line — distinguishable from a missing rate |
| `currency` | see `currency` rule | must equal the profile currency when both are present; when the profile currency is absent, EVERY rate must declare the SAME currency explicitly — one effective currency is enforced, USD+EUR mixing refuses |
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
- a derived EA of ZERO prices a REAL 0.00 line (a resolved zero, never
  treated as unresolved)
- omitted in-scope scope (a room covered by NO assembly) is an UNKNOWN
  amount: priced lines + subtotal survive, the grand total goes BLANK, and
  the callout names what is missing
- package-excluded assemblies are listed as EXCLUSIONS, never priced
- the grand total is BLANK while any in-scope amount is unknown
- a `stopped` results run, or a results JSON without `assembly_boq`,
  REFUSES to be priced (never silently 0.00)

## Activation status

| capability | status |
|---|---|
| counter/vanity SF, edge LF, splash, cutouts | **active** (measured/BoQ) |
| assembly/material identity | **active** (resolved + recorded) |
| package exclusion rules | **active** (profile defaults, job override) |
| assembly-EA pricing | **active** (rate profile; estimate.md/json/pdf) |
| proposal-lite quote document | **active** (`scripts/proposal.py`; proposal.json/md/pdf from the corrected estimate) |
| QuickBooks export | **groundwork only** — candidate CSV mapping documented in `references/quickbooks-mapping.md`; NO integration; import readiness must be validated against the operator's real account sample before any support claim |
| SF × material price matrix, waste, seam planning | not built (roadmap) |
