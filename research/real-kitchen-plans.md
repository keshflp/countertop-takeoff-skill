# Public residential kitchen plan sources

Screened 12 first-party sources on 2026-11-07. Four records were kept: three countertop-bearing plan pages and one scanned zero-countertop control. All are published or sample drawings, not confirmed as-built customer plans. This note cites sources and describes the drawings without reproducing images.

Kept documents and renders remain private because no explicit reuse grant was found.

| ID | Source | Result and page | Terms and reason |
| --- | --- | --- | --- |
| R01 | [City of San Pablo, General Residential Floor Plan](https://www.sanpabloca.gov/DocumentCenter/View/17330/General-Residential-Floor-Plan) | Rejected: direct PDF returned HTTP 403; not visually verified. | No terms found; no redistribution permission verified. |
| R02 | [Town of Bethel, apartment alterations floor plans](https://bethel-ct.gov/vertical/sites/%7B90B1B948-C443-4CA6-8B88-90B1EEA9B1E2%7D/uploads/Floor_Plans.pdf) | Rejected: p. 1 shows multiple apartment layouts. | No terms found; apartments are out of scope. |
| R03 | [Walter J. Keith, *Keith's House Plans*, Vol. II](https://dahp.wa.gov/sites/default/files/KeithsHousePlans_1915.pdf), hosted by Washington DAHP | Kept as a scanned zero-countertop control: file p. 31, printed p. 27. | Page 5 says “Copyright, 1915, by Walter J. Keith.” No reuse grant found; private. |
| R04 | HUD, [*Architectural Drawing*, Part 1](https://www.huduser.gov/portal/sites/default/files/pdf/Architectural-Drawing-Part-1.pdf) and [Part 2](https://www.huduser.gov/portal/sites/default/files/pdf/Architectural-Drawing-Part-2.pdf) | Rejected: both URLs returned HTTP 202 with zero bytes; not visually verified. | No terms found; no document content retrieved. |
| R05 | [City of Highland, residential floor-plan set](https://www.highlandca.gov/DocumentCenter/View/2356/Floor-Plans-PDF) | Rejected: p. 1 is a plan-review-stamped residential drawing. | No terms found; permit material is out of scope. |
| R06 | [Westchester County, *Kingsfield - Floor Plans*](https://homes.westchestercountyny.gov/images/archive/stories/FloorPlans/kingfp3bed.pdf) | Kept: p. 1, first-floor kitchen on a single-home plan. | Page says “For illustrative purposes only.” No reuse terms found; private. |
| R07 | [HUD, *House Planning*, Part 2](https://www.huduser.gov/portal/sites/default/files/pdf/House-Planning-Part-2.pdf) | Rejected: direct URL returned HTTP 202 with zero bytes; not visually verified. | No terms found; no document content retrieved. |
| R08 | [City of Fresno, Plan 3 floor plan](https://www.fresno.gov/wp-content/uploads/2024/03/Plan-3-View-Floor-Plan.pdf) | Rejected: p. 1 carries a municipal plan-review stamp. | No terms found; permit material is out of scope. |
| R09 | [Maricopa County Environmental Services, sample floor plan](https://www.maricopa.gov/DocumentCenter/View/7469/Sample-Floor-Plan-PDF) | Kept: p. 1, one residence with a dimensioned galley kitchen. | No terms found; private. The document labels itself a sample. |
| R10 | [Pacific First Federal Savings and Loan Association, *The Blue Book of Home Plans*](https://dahp.wa.gov/sites/default/files/TheBlueBookofHomePlans_1937.pdf), hosted by Washington DAHP | Rejected: p. 7 is scanned, but countertop and fixture outlines are not clear enough for selected-detail truth. | Page 2 says “Copyright 1937 by Pacific First Federal Savings and Loan Association of Tacoma.” No reuse grant found; private. |
| R11 | [University of Georgia College of Family and Consumer Sciences](https://www.fcs.uga.edu/), TXMI 3330 course construction-document set | Kept: p. 2 is a single-residence kitchen plan; p. 8 elevations are text evidence only. | Sheets say “© Mark Gross & Associates, Inc.” No reuse grant found; private. |
| R12 | [FreeFarmhouse downloads](https://www.freefarmhouse.com/downloads) | Rejected: detailed kitchen drawing is explicitly fictional; source image is PNG rather than PDF. | The page says the work is under a Creative Commons Attribution ShareAlike license and permits sharing/adaptation with attribution and ShareAlike. Embedded references conflict between BY-SA 3.0 and 4.0; verify the version before reuse. The page also says “The site plans depict fictional places.” |

## Pages for later selected-detail evaluation

- **R06, p. 1:** a native-text/vector first-floor plan with two separated countertop runs, one with a sink and one with a four-burner cooktop. Cabinets and fixtures are clear. It gives a 1/4 in = 1 ft scale but no written counter lengths. The page is illustrative.
- **R09, p. 1:** a mostly raster sample with a narrow galley kitchen labeled 5 ft 6 in by 15 ft 6 in. It shows opposing runs, a sink, dishwasher, cooktop and cabinet blocks. Selectable text is partial.
- **R11, p. 2:** a native-text/vector rectangular galley plan in a single-residence construction set, with opposing runs, a sink/DW, cooktop and written feet-inch dimensions. Page 8 shows kitchen elevations and is retained only as text evidence. The course drawing is illustrative and cannot validate a customer job.
- **R03, file p. 31 / printed p. 27:** a raster scan with an OCR text layer. It labels a compact kitchen 7 ft 6 in by 10 ft, but no distinct countertop boundary was scorable in the exploratory corpus. Keep it as a zero-countertop control, not as positive countertop truth. The book describes the plan as suggested.

The three positive plan pages have different owners and include both vector and raster linework. None has an explicit reuse grant, so source files and derivatives stay private.

## Exploratory baseline

The private development corpus used four sources across eight crops: three countertop-bearing sources (R06/S07, R09/S10 and R11), plus R03/S03 as a zero-countertop control. The helper matched **0 of 8 countertop crop references** across **0 of 5 physical runs** at IoU >= 0.90. It also had 0 generic matches. Suggestions appeared in all crops and mostly outlined sinks, appliances or cabinet detail; three polygons were invalid.

The diagnosis attributed primary misses to crossing fixture linework in 4/8 crop references across 3/5 runs, vertex-cap rejection in 2/8 references across 1 run, and a room-leaking face in 2/8 references across 1 run. Repeated crop views are correlated. Directly measured best single-face coverage was 80.1% for the S07 island, 27.9% for the S07 perimeter, at most 24.3% for S10, and 19.2% for the R11 range-side run.

No safe bounded algorithm candidate meeting this experiment's target was identified (**0 of 3 candidates used**). Adaptive simplification, line separation or bridging, and external frame contours remain untested recovery hypotheses. Reaching IoU 0.90 on the traced cases would require merging faces across fixture lines, which is semantic segmentation, or bridging gaps, which conflicts with the helper's no-gap-repair contract. No algorithm change was made. This diagnosis does not prove that every possible algorithm is impossible.

The separate unchanged synthetic regression remained at 0 missed of 8 eligible details, 3 spurious proposals and 0 mapping discrepancy.

## Limits

This is an exploratory/development corpus with a disclosed ordering deviation: proposal counts were visible before the truth freeze, so it is not blinded. Raster-page truth was manually reviewed and remains advisory. The sources are published or sample drawings, not as-built customer jobs; this evaluation does not validate a customer takeoff. The corpus is small, crop views repeat physical runs, and the diagnosis only characterizes this helper on these examples.
