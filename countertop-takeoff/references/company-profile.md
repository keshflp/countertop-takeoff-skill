# Company profile

Examples: `examples/example.profile.json` (shop identity/conventions),
`examples/example.rate-profile.json` (also assembly-EA rates).

## Identity schema (`"profile": "<path>"` in a job spec)

| key | type | meaning |
|-----|------|---------|
| `profile_version` | `"1"` / `"2"` | schema version |
| `company` | string | display name |
| `material_aliases` | map alias → canonical | spelling/naming tolerance; canonical names are what reports record |
| `gross_net_policy` | `"gross"` \| `"net_of_declared_cutouts"` | the shop's DEFAULT policy; a job spec may override explicitly |
| `required_components` | list of strings | components this shop always takes off. **Recorded + echoed into results only — NOT enforced by the audit.** The coverage ledger and callouts carry the completeness findings; the operator/auditor reads `required_components` against them |
| `report_preferences` | object | accepted-but-unused display preferences; currently not applied to reports |
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

## Pricing schema (v2) — `rates[]` + `currency`

| key | meaning |
|-----|---------|
| `currency` | profile-level currency (e.g. `"USD"`); every rate's currency must agree — mixed currencies refuse |
| `rates[]` | one entry per company rate; each prices an ASSEMBLY as EA × `unit_price` |

Unknown `match` keys refuse in both profile validators (`width_inches` and
`variant` are unsupported). Use only the matchers listed below. Exact rates
travel as `unit_price_exact` decimal strings through arithmetic and every
document; the legacy numeric `unit_price` is for compatibility only.

| key | required | meaning |
|-----|----------|---------|
| `item_code` | yes | the stable code every estimate line cites (unique in the profile) |
| `match` | yes | which assemblies the rate prices. **`match.assembly_kind` (the assembly type) is REQUIRED** — a rate must pin the assembly identity; finish alone never selects a price (finish-only rates refuse at load). Optional exact matchers: `finish_tag`, `width_in`, `depth_in`, `height_in`, `handing`, `package` |
| `uom` | yes | must be `"EA"`; SF pricing is not built |
| `unit_price` | yes | finite ≥ 0. Accepts plain numbers or unambiguous currency-formatted strings (`"$1,234.56"`, `"1.234,56"`) — parsed Decimal-exact; negatives and ambiguous strings refuse with a diagnostic. An explicit `0` prices a REAL 0.00 line — distinguishable from a missing rate |
| `currency` | see `currency` rule | must equal the profile currency when both are present; when the profile currency is absent, EVERY rate must declare the SAME currency explicitly — one effective currency is enforced, USD+EUR mixing refuses |
| `includes` | no | components the rate already covers (top/edge/splash/cutout labor) so they are not charged again |
| `rate_basis` | no | object or null; optional `source`, `date` (valid `YYYY-MM-DD`) and `quote_reference`, each non-empty text or null. Only the uniquely matched rate supplies this metadata; estimates/proposals preserve it and show missing fields as BLANK |

For example, a shop may supply a rate with
`"rate_basis": {"source": "Shop rate sheet", "date": "2026-11-04", "quote_reference": "QUOTE-42"}`.
These are supplied facts, not a price lookup or an expiry policy. Metadata
never selects a rate, fills a missing price, or changes scope completeness.

Exactly one matching rate prices EA × exact rate (Decimal, ROUND_HALF_UP to
cents); no/ambiguous matches or withheld EA leave blanks + callouts. Valid EA
survives unresolved SF; zero EA/rates produce 0.00. Excluded packages never
price; omitted scope blanks the grand total. Stopped/missing-`assembly_boq`
results refuse. Documents/provenance: [output contracts](output-format.md).

## Activation status

| capability | status |
|---|---|
| counter/vanity SF, edge LF, splash, cutouts | **active** (measured/BoQ) |
| assembly/material identity | **active** (resolved + recorded) |
| package exclusion rules | **active** (profile defaults, job override) |
| assembly-EA pricing | **active** (rate profile; estimate.md/json/pdf) |
| proposal-lite quote document | **active** (`scripts/proposal.py`; proposal.json/md/pdf from the corrected estimate) |
| QuickBooks export | **groundwork only** — candidate CSV mapping documented in `references/quickbooks-mapping.md`; NO integration; import readiness must be validated against the operator's real account sample before any support claim |
| SF × material price matrix, waste, seam planning | not built |
