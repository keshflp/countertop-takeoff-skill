# QuickBooks mapping (groundwork — mapping + constraints ONLY)

**Status: DOCUMENTATION ONLY. There is NO QuickBooks API/MCP integration in
this skill, and none is planned without a validated sample of the
operator's real account.** This document records the CANDIDATE mapping
from the estimate/proposal data to a QuickBooks Desktop batch-import CSV
(US Simple Start / Essentials-style importer), plus the importer's
constraints, so the groundwork is reviewable before any integration is
built.

> Import readiness MUST be validated against the operator's REAL account
> sample (chart of accounts, item list, customer list, sales-tax
> configuration) before anyone claims import support. Until that
> validation is recorded here, treat this mapping as unproven.

## What the pipeline already guarantees (inputs to the mapping)

Every estimate line already carries the stable, importable identity:

| field | source | notes |
|---|---|---|
| stable item code | `rates[].item_code` | unique per profile; the natural key for a QuickBooks Item |
| quantity | `lines[].qty_ea` | resolved assembly EA (integer, evidence-backed; blanks refuse upstream) |
| exact rate | `lines[].unit_price_exact` | Decimal-exact (e.g. `55.555`); the importer column must NOT pre-round |
| line amount | `lines[].line_total` | `QTY x rate`, ROUND_HALF_UP to whole cents |
| currency | profile `currency` | ONE effective currency enforced at profile load |
| description | `lines[].description` | type + inch dims + finish |
| provenance | `estimate.json` | results sha256 + profile sha256 (audit trail) |

## Candidate CSV mapping (QuickBooks Desktop "import invoices" style)

One invoice per customer+date group; one CSV row per invoice LINE:

| CSV column | mapped from | example (synthetic) |
|---|---|---|
| `Customer:Job` | operator-assigned (job/contract name; NOT in the takeoff data) | `Riverside Apts — Phase 2` |
| `Invoice Date` | operator-assigned (bid/PO date; NOT in the takeoff data) | `2026-04-15` |
| `Invoice Number` | operator-assigned | `INV-1042` |
| `Item Code` | `lines[].item_code` | `CT-ST-9625` |
| `Description` | `lines[].description` | `B counter assembly 96 x 25.5 in, finish ST` |
| `Quantity` | `lines[].qty_ea` | `8` |
| `Unit Price` | `lines[].unit_price_exact` | `918.335` |
| `Amount` | `lines[].line_total` | `7346.68` |
| `Class` | optional; operator mapping (e.g. job phase) | `Phase 2` |
| `Tax` | operator decision — see the constraint below | `N` |

Required invoice-header fields the takeoff data does NOT carry and the
operator must supply: customer (and job), invoice date, invoice number,
terms, and location/class if used. The skill never invents these.

Synthetic example row (all fixtures in this repo are synthetic; these
values reference nothing real):

```csv
Customer:Job,Invoice Date,Invoice Number,Item Code,Description,Quantity,Unit Price,Amount
Riverside Apts — Phase 2,2026-04-15,INV-1042,CT-PL-7225,A counter assembly 72 x 25.5 in,8,485.00,3880.00
Riverside Apts — Phase 2,2026-04-15,INV-1042,CT-ST-9625,B counter assembly 96 x 25.5 in,1,918.335,918.34
```

## US importer constraints (documented; verify against the real account)

- **Sales-tax-configured accounts are excluded from scope.** Accounts
  with sales-tax configured (US sales tax tracked inside QuickBooks) need
  tax codes/rates on lines; this skill computes no tax and must not
  invent one. Such accounts are OUT of scope for a CSV import until an
  operator validates the tax handling on their own account.
- **Row limit: ~1000 rows per import batch** and **~100 invoices per
  batch** (QuickBooks Desktop importer limits). A large hotel job can fit
  (one line per item code per invoice), but a proposal line-per-assembly
  export must be grouped by item code first.
- Column order/names vary by QuickBooks Desktop year and region; the
  mapping above must be re-checked against the operator's actual import
  template (Export sample template from the importer dialog) before use.
- Amounts import as plain decimals; localized currency strings
  (`$1,234.56`) must be normalized to plain numbers first (the pipeline's
  `parse_money` accepts them; the CSV export writes plain numbers).

## What is intentionally NOT here

- No API/MCP/Sync-manager integration — no code talks to QuickBooks.
- No tax computation, no discounts, no percentages.
- No customer/vendor list sync.
- No claim of tested compatibility with any QuickBooks release.

Roadmap (docs-only until an operator sample lands): validate the mapping
against a real account sample → generate a draft CSV next to
`estimate.json` (operator reviews) → only then consider automation.
