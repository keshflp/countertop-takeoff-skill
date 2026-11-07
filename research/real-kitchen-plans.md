# Public residential kitchen plan sources

Screened 12 first-party sources on 2026-11-07. Three pages are useful candidates for a later private selected-detail evaluation. They are published or sample drawings, not confirmed as-built customer plans. This note cites sources and describes the drawings; it reproduces no plan images.

Where no separate source page was found, the landing URL is the direct PDF. All selected source files and page renders remain private because no explicit reuse grant was found for them.

| ID | Source | Result and page | Terms and reason |
| --- | --- | --- | --- |
| R01 | [City of San Pablo, General Residential Floor Plan](https://www.sanpabloca.gov/DocumentCenter/View/17330/General-Residential-Floor-Plan) | Rejected: direct PDF returned HTTP 403; not visually verified. | No terms found; no redistribution permission verified. |
| R02 | [Town of Bethel, apartment alterations floor plans](https://bethel-ct.gov/vertical/sites/%7B90B1B948-C443-4CA6-8B88-90B1EEA9B1E2%7D/uploads/Floor_Plans.pdf) | Rejected: p. 1 shows multiple apartment layouts. | No terms found; out of scope. |
| R03 | [Walter J. Keith, *Keith's House Plans*, Vol. II](https://dahp.wa.gov/sites/default/files/KeithsHousePlans_1915.pdf), hosted by Washington DAHP | Kept: file p. 31, printed p. 27. Scanned, compact kitchen with written dimensions. | Page 5 says “Copyright, 1915, by Walter J. Keith.” No reuse grant found; private. |
| R04 | [HUD, *Architectural Drawing*, Parts 1](https://www.huduser.gov/portal/sites/default/files/pdf/Architectural-Drawing-Part-1.pdf) and [2](https://www.huduser.gov/portal/sites/default/files/pdf/Architectural-Drawing-Part-2.pdf) | Rejected: both direct URLs returned HTTP 202 with zero bytes; not visually verified. | No terms found; no document content retrieved. |
| R05 | [City of Highland, residential floor-plan set](https://www.highlandca.gov/DocumentCenter/View/2356/Floor-Plans-PDF) | Rejected: p. 1 is a plan-review-stamped residential drawing. | No terms found; permit material is out of scope. |
| R06 | [Westchester County, *Kingsfield - Floor Plans*](https://homes.westchestercountyny.gov/images/archive/stories/FloorPlans/kingfp3bed.pdf) | Kept: p. 1, first-floor kitchen on a two-story single-home plan. | Page says “For illustrative purposes only.” No reuse terms found; private. |
| R07 | [HUD, *House Planning*, Part 2](https://www.huduser.gov/portal/sites/default/files/pdf/House-Planning-Part-2.pdf) | Rejected: direct URL returned HTTP 202 with zero bytes; not visually verified. | No terms found; no document content retrieved. |
| R08 | [City of Fresno, Plan 3 floor plan](https://www.fresno.gov/wp-content/uploads/2024/03/Plan-3-View-Floor-Plan.pdf) | Rejected: p. 1 carries a municipal plan-review stamp. | No terms found; permit material is out of scope. |
| R09 | [Maricopa County Environmental Services, sample floor plan](https://www.maricopa.gov/DocumentCenter/View/7469/Sample-Floor-Plan-PDF) | Kept: p. 1, one residence with a dimensioned galley kitchen. | No terms found; private. The document labels itself a sample. |
| R10 | [Pacific First Federal Savings and Loan Association, *The Blue Book of Home Plans*](https://dahp.wa.gov/sites/default/files/TheBlueBookofHomePlans_1937.pdf), hosted by Washington DAHP | Rejected: p. 7 is a scanned home-plan page, but kitchen counters and fixtures are not clear enough for selected-detail truth. | Page 2 says “Copyright 1937 by Pacific First Federal Savings and Loan Association of Tacoma.” No reuse grant found; private. |
| R11 | [University of Georgia, Jones Residence construction-document set](https://www.fcs.uga.edu/docs/TXMI_3330_CAD_JONES_RES_SYDNEY_HOOPES_CD_SET.pdf) | Rejected: p. 2 has a strong kitchen plan, but the source is a nine-page whole-building set. | Sheets carry “© Mark Gross & Associates, Inc.” No reuse grant found; out of scope and private. |
| R12 | [FreeFarmhouse downloads](https://www.freefarmhouse.com/downloads) | Rejected: detailed kitchen drawing is explicitly a fictional design, not a real-plan example; source image is PNG rather than PDF. | The page says the work is under a Creative Commons Attribution ShareAlike license and permits sharing/adaptation with attribution and ShareAlike. Embedded references conflict between BY-SA 3.0 and 4.0; verify the version before reuse. |

## Candidate pages

- **R03, file p. 31 / printed p. 27:** a scanned 1915 bungalow plan. It labels the kitchen 7 ft 6 in by 10 ft and shows a sink and a range with short counter or dresser runs. The kitchen is a compact, roughly L-shaped layout. PyMuPDF finds a text layer over the raster scan. This is the only clear scanned-plan candidate. Use it as a raster linework challenge; the old fixture symbols and faint scan make it a poor source for modern cooktop labels. The book describes the floor plan as suggested, so it is not evidence of a built home.
- **R06, p. 1:** Westchester County's Kingsfield plan shows a single home with two separated parallel work surfaces, one with a sink and one with a four-burner cooktop. Cabinets are drawn clearly. The PDF has native text and vector linework. It gives a 1/4 in = 1 ft scale, but no written countertop lengths. The page is explicitly illustrative.
- **R09, p. 1:** Maricopa County's sample has a narrow galley kitchen labeled 5 ft 6 in by 15 ft 6 in. It shows opposing counter runs, a sink, dishwasher, cooktop and cabinet blocks. The plan is a raster image with only partial selectable text. Its clear, dimensioned linework makes it a useful image-based candidate, but it is explicitly a sample.

## Limits

The three selected pages come from three independent source owners, but none is confirmed as an as-built home plan. They can support a small test of outline suggestions on published plan drawings; they cannot establish real-job accuracy. Reaching that claim still needs a source that is both an ordinary residential plan and permissible to retain privately, without using permit or personal-address material.

The strongest fourth candidate was the University of Georgia construction set, but its full document is outside this task's whole-building-set scope. The remaining close candidates were excluded because they were apartment plans, plan-review material, fictional designs, or did not show countertop and fixture outlines clearly enough.
