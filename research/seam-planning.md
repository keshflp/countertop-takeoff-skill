# Automatic countertop seam assessment

Research date: 2026-11-06. Scope: estimator seam decisions before nesting, with traceable reasons. All worked dimensions and mechanical properties below are unrelated synthetic examples. This report contains no customer geometry, purchasing decisions, prices, or private results.

Source audit: the S1 diagrams were rechecked visually. The sink rear strip is 100 mm, the cooktop rear strip is 50 mm, and the illustrated adjacent-opening gap is 50 mm. The sink/tap detail has its own scope. These relationships replace the earlier mistaken opening-gap reading. Current input fields are summarized in section 3; the beam scenario is explanatory research, outside the implemented planner.

## Recommendation

Implement a **versioned product-rule planner**, starting with the detailed Silestone manual [S1]. Generate no-seam, corner-seam, outside-opening, and explicitly permitted through-opening alternatives; validate their actual polygons; then nest their fabrication blanks. The estimator should select seams itself and explain which stock-fit constraint or documented rule made each seam necessary. Keep installed support obligations and handling uncertainty visible as separate results.

Do not use density plus reported flexural strength to manufacture a universal safe rail width or maximum transport length. Those properties support calculations only after loads, orientation, and supports are specified. The self-weight beam calculation below cannot even discriminate wide from narrow rails of the same length and thickness.

Useful automation is possible now. Missing product identity leaves automatic planning unresolved while independent SF and original-geometry checks remain available. Known applicable products with missing support can yield conditional candidates with the actual obligations visible. The fabricator need not draw every seam. A conditional estimate must not be presented as a complete fabrication or handling approval.

## 1. Sources and applicable facts

PDF page numbers below are **1-based file pages**. Where a PDF contains two printed pages per file page, both are supplied. Manufacturer guidance belongs to the named product, edition, application, and thickness; it is not a universal natural-stone rule.

### Source register

| ID | Primary document and exact URL | Edition/access limitation |
| --- | --- | --- |
| S1 | Cosentino, *Silestone Countertops: Design & Installation*: https://assetstools.cosentino.com/api/v1/bynder/doc/0B425745-8BAC-4A87-9D7B54DA7AC39A1D/silestone-installation-manual.pdf | 14 file pages, printed pp. 1–28; **REV. 03 - 02/2024**, print date February 2024, on file p. 14. Downloaded directly from Cosentino. This is the principal implementable profile. Confirm regional/product applicability when adopting it; do not label it the latest worldwide edition. |
| S2 | MSI, *Q Installation Guidelines*: https://cdn.msisurfaces.com/files/downloads/quartz-installation-guidelines.pdf | Four pages, retrieved from the official [resources page](https://www.msisurfaces.com/mineral-surfaces/resources-downloads/). No visible edition number. |
| S3 | MSI, *Q+ Installation Guidelines*: https://cdn.msisurfaces.com/files/downloads/q-plus-installation-guidelines.pdf | Four pages. Separate product document, even where instructions match Q. |
| S4 | MSI, *Technical Specifications for Q from MSI*: https://cdn.msisurfaces.com/files/downloads/quartz-technical-specifications.pdf | Two pages; table says **Rev. 1, 9/2022**. Product groups are listed on p. 1. |
| S5 | Caesarstone, *Fabrication & Installation Guide*: https://d147ljfxcj32ah.cloudfront.net/attachments/attachment/uploaded/5864/Caesarstone_Fabrication_and_Installation_Guide.pdf | 80-page manufacturer-authored guide retrieved from a third-party CDN. PDF creation metadata is February 2021, not a verified edition declaration. Treat the rules below as historical pending confirmation against the applicable current regional guide. |
| S6 | Caesarstone official current guide landing page: https://mos.caesarstone.com/professional-library/quartz-mineral-icon-fabrication-installation/ ; its embedded publication: https://online.fliphtml5.com/qejjy/pchz/ | Official landing page and embed verified. Full publication text/PDF could not be retrieved within this investigation; its configuration is encoded. The older S5 must not silently become a current ICON, mineral, porcelain, or all-Caesarstone profile. US legacy PDF https://www.caesarstoneus.com/wp-content/uploads/2021/10/Ceasarstone_CS_TechnicalDataManual-5.pdf returned HTTP 403. |
| S7 | Natural Stone Institute, *Dimension Stone Design Manual 2022*, chapter 17, *Countertops*. Retrieved manufacturer/industry-authored text in this public mirror: https://republicelite.com/wp-content/uploads/2022/06/DSDM_2022_All_Chapters.pdf | 523-page combined file. The [official all-chapters entry](https://pubs.naturalstoneinstitute.org/pubview/6841ADCF-1866-DAAC-99FB-A3BA6D835C05) describes a newer 2024 edition, published January 8, 2025, secured access. Direct publication access required human verification. This report verifies **2022**, not equivalence to the newer edition. No purchase/access bypass attempted. |
| S8 | ASTM C880/C880M-25: https://store.astm.org/c0880_c0880m-25.html | Official public scope and significance, sections 1 and 4; full paid standard not obtained. |
| S9 | ASTM C99/C99M-18: https://store.astm.org/c0099_c0099m-18.html | Official public scope and significance, sections 1 and 4; identifies test purpose, not design allowables. Edition pinned rather than assumed current. |
| S10 | ASTM C97/C97M-18: https://store.astm.org/c0097_c0097m-18.html | Official public scope and significance. Covers absorption and bulk specific gravity, except slate. Edition pinned. |
| S11 | Cosentino, *Manual for Professional Use*: https://assetstools.cosentino.com/api/v1/bynder/doc/FD803B72-DE13-4F49-829C88C92E2C0714/manual-for-professional-use-eng.pdf | Older 12-page Silestone/ECO manual; PDF metadata 2019. File p. 8 says a corner-hole radius should never be less than 4 mm. **Do not mix that limit into the more specific 2024 S1 profile**, which specifies 10 mm sink/cooktop radii. |

Retrieved PDF SHA-256 fingerprints, so changing URLs cannot silently change an adopted profile:

```text
S1 56535666e6ed4e33ea1bc452968ea1b7922abd13c57d98fff40312c0aa24794a
S2 8b9011f17cf55712fc17a4b2aecc40a87cbf2d9f30b6bfe00803c56c425a4074
S3 2885ec657ef3ad1ba53c61444023f525360ae629092377098bd1ae4416a05f86
S4 f48f06adeac23b2217afccdb728247a7af7a74821432610688e76ba38b0c7a6b
S5 2a2b77c870f07e1902c596e6325e9936c483a33218d21b76161ebe106eab2473
S7 eebd2fd1fdd5de873196cf935733a5c723ca841196b1802a73961b4069fa60de
```

### Openings, strips, seams, and corners

| Fact and short quotation | Source | Implementable meaning and limit |
| --- | --- | --- |
| Sink and cooktop inside corners: “minimum radius of **10 mm [3/8\"]**.” Other cutouts: minimum **5 mm [3/16\"]**. | S1 file p. 5 / printed pp. 8–9, “Minimum radius (sink)”; file p. 6 / printed pp. 10–11, “Minimum radius (cooktop)” and “Other cut-outs.” | Test each applicable corner and routing separately. These are stress-detail rules, not a maximum opening size or a breakage guarantee. The illustrated crossed/overcut corners are unacceptable. |
| “Cosentino® does not recommend leaving joints in the cut-out area.” If required for design/dimensions, the same section illustrates outside, tangent, and **inside** opening joints. Outside distance **D ≥150 mm for 12 mm** Silestone, **D ≥100 mm for 20/30 mm**. | S1 file pp. 5–6 / printed pp. 9, 11, “Joints in the cut-out area.” Figures were visually inspected. | Prefer outside joints; retain an explicitly documented alternative through the opening. A preference is not a prohibition. Do not apply the outside clearance to an inside-opening joint, which is a separate illustrated configuration. |
| “Only for top-mounted sinks” / “Only for top-mounted cooktops”; “Ensure continuous, seamless support in this area.” | Same S1 sections. | The asterisk restricts the **tangent** arrangement to top-mounted fixtures. The support annotation and red support lines appear on all three arrangements. Inside-opening seams are illustrated without that top-mount-only asterisk. Check support along the illustrated front/back rail areas; simply knowing the sink has its own support is insufficient. |
| Sink/tap diagram: **≥50 mm front strip**, **≥100 mm rear strip**, **≥50 mm between adjacent illustrated openings**. Cooktop diagram: **≥50 mm front and rear strips**, **≥50 mm adjacent-opening gap**. Both show original end distances **≥150 mm at 12 mm thickness / ≥100 mm at 20/30 mm**. | S1 file p. 5 / printed p. 8; file p. 6 / printed p. 10. | The 100 mm dimension is the sink rear strip, not the adjacent-opening gap. Apply named front/rear/end relations only to the documented rectangular-run arrangement with an established rear datum. The sink drawing includes taps; its separate Ø35 mm tap-hole detail is not a universal opening-spacing formula. Full tap/fixture detailing is outside the implemented subset. |
| “All corners on the countertop must be rounded to a minimum **3/8\" radius**,” including sinks, cooktops and L tops; rounding is unnecessary “where the seams fall at the corners.” | S2 p. 2, “Fabrication”; identical wording for Q+ in S3 p. 2. | **9.525 mm**, not an exact 10 mm. A corner seam is an available alternative to a continuous radiused inside corner. This wording does **not** require every L to be seamed. |
| “Include an allowance of an extra **1/8\"** between the cooktop/sink and the edge of the cutout for expansion.” | S2/S3 p. 2, “Fabrication.” | Fixture-to-opening fit allowance, not seam-to-opening clearance or rail width. Do not accidentally shrink the actual required opening to satisfy a rail rule. |
| “Always fabricate L-shaped or U-shaped countertops with a join on the inside corner.” | S5 p. 36, §7.4; p. 37 discourages changes of direction without joins. | A concrete corner-seam rule **for this historical Caesarstone guide**. It conflicts with treating one-piece L permission as universal. Confirm S6/current regional applicability before making this an active product rule. |
| “The distance between a cutout and an edge or seam must be no less than **60 mm**”; below **150 mm**, support with a Caesarstone strip. Minimum cutout corner radius **10 mm**. | S5 p. 41, §8.3. | Below 60 mm fails this guide. From 60 mm inclusive to 150 mm exclusive requires reinforcement. This is not an unreinforced 60 mm pass. Within the initial exclusion of reinforcement design, emit the requirement, not an invented reinforcement calculation. No explicit through-opening exception was established in this edition. |
| “PROVIDE REINFORCEMENT FOR JOINTS AT SINK”; “SEAMS OVER DISHWASHERS ARE NOT RECOMMENDED”; “TYPICAL JOINTS MUST ALIGN WITH CABINET SEAMS BELOW.” | S7 combined PDF p. 298, drawing **17-D-1**; sink joinery detail **17-D-4**, combined p. 301; reinforcement discussion §15, printed p. 17-11 / combined p. 293. | NSI illustrates sink joints for natural stone, with reinforcement obligations. That is not unconditional permission for an unsupported seam through any opening. Reinforcement design is outside this model; do not delete the obligation or infer that a seam cures a weak strip. |

**Seam-through-opening answer:** S1 explicitly illustrates it for Silestone sink and cooktop openings, under its support conditions and as an exception to its preference. S7 illustrates natural-stone sink joints with reinforcement. S2/S3 do not establish a through-opening permission or numerical seam exclusion zone. S5's 60 mm separation rule supplies no such exception in the retrieved text. Lack of an identified prohibition is not documented permission. None of these findings licenses a blanket boolean `allowSeamThroughAnyCutout` for every material.

### Thickness, support, and handling are different questions

| Fact and short quotation | Source | What it does and does not establish |
| --- | --- | --- |
| One-piece and multi-piece L tops are both illustrated, including **R ≥10 mm** at a one-piece internal corner. “Fixing corner reinforcements and supports in place.” Support points A/B/C must have the same height. | S1 file p. 10 / printed p. 18, “L-shaped countertop.” | A one-piece L is a legitimate candidate. Its documented corner/support conditions remain obligations, including reinforcement that this model does not design. Rectangular-piece restrictions must not manufacture an otherwise unnecessary seam. |
| “It is important to ensure continuous support, passing through the corner area,” especially for one-piece L tops. | S1 file p. 11 / printed p. 20, “L-shaped countertops support.” | A seam may alter a corner configuration, but does not make support irrelevant. |
| Distance between supports: diagram dimension **A ≤900 mm at 12 mm thickness; A ≤1200 mm at 20/30 mm; B ≤700 mm**. Large (**>600 mm**) or particularly heavy sinks/cooktops need cabinet-anchored support bars. | S1 file p. 11 / printed pp. 20–21, “Supports and reinforcements.” | Installed cabinet-support geometry only. Retain the A/B diagram mapping and fixture-weight condition. These are not free unsupported handling lengths or maximum finished-piece lengths. Reinforcements near cutouts are also specified here. |
| Overhang tables distinguish six support configurations, thicknesses, and the presence of openings; “Maximum concentrated static load = **100 Kg [220 lb]**.” Selected named colors require halving the listed overhang/support values. | S1 file pp. 7–8 / printed pp. 12–15. | Strong evidence against one generic span threshold. These tables have explicit support geometry, static loading, and product exceptions. Do not transfer their numbers to transport, arbitrary strips, other colors/classes, or omitted reinforcement. The manual states load in mass units; it is not a universal distributed pressure. |
| “Provide perimeter support of full deck. Front to back support must be given every **24\"**.” Sink installations are recommended to be fully supported “independent of the Q top.” | S2 p. 3 “Installation mandatory procedures,” p. 4 “Sinks and basins.” | Keep Q's general deck-support requirement separate from its sink-only independent-support recommendation. That sink statement is not a cooktop rule or evidence of rail support at a seam. Q+ has separate sink-manufacturer instructions in S3 p. 3. No S1 corner-reinforcement or continuous-corner requirement is established by this Q wording. |
| S2/S3 fabrication says **3/8-inch radius**, while installation wording on p. 3 says minimum **diameter** 3/8 inch. Their overhang sentence is incomplete, and extracted table layouts are easy to misread. | S2/S3 pp. 2–4. | Use the explicit fabrication radius as the operative fabrication requirement. Record the wording discrepancy. Do not invent the missing overhang number or derive a handling rule from that table. |
| “Provide support under all countertop seams.” Front-to-back support every **500–600 mm**; cutouts longer than **600 mm** need side-to-side beams. | S5 p. 57, §9.1. | Source conditions for a historical installation profile, not a handling model. Thinner tops also have different subdeck requirements on this page. |
| Natural-stone installed spans: **600 mm for 20 mm**, **900 mm for 30 mm**. Cantilevers: **150 mm for 20 mm**, **250 mm for 30 mm**, and no more than **1/3** countertop width. Less sound stone can need support at smaller projections. | S7 printed p. **17-4**, §8.2 / combined p. **286**. | These nominal paired inch/mm limits apply to installed supports. They neither establish maximum cutout lengths nor validate carrying a frame with an opening. The caveat prevents classifying every natural stone as equally sound. |
| “In the interest of safe handling, some cutouts will be partially or completely performed in the field after installation.” | S7 printed p. **17-5**, §9.4 / combined p. **287**. | Fabrication sequence changes the transported geometry. A finished cutout and an intact transport blank are not the same load case. This is evidence for a sequence input, not automatic authorization for field cutting or a reason to hide its requirements. |

Trade names do not establish geological stone class. Engineered quartz/mineral surfaces, natural quartzite, granite, marble, and porcelain need distinct applicability. Even a manufacturer's marketed name may contain a geological term while naming an engineered product. Preserve explicit product identity and independently sourced material classification.

**Sparse MSI scope:** `msi-q-pinned` can evaluate S2's exact 3/8-inch fabrication radius and its corner-seam exception, with Q's own deck-support and sink-specific conditions. S2 does not supply the numerical opening-strip/seam model or through-opening permission used by S1. It also does not establish S1's continuous-corner support or corner-reinforcement detail. Keep missing scope visible as incomplete, including for a Q L without openings; passing known radius/support checks alone is not full assessment. A cooktop does not acquire the independent sink-support condition.

### What the property tests establish

ASTM C880/C880M-25 §1.1 describes “a simple beam using **quarter-point loading**,” not third-point loading. §§1.2–1.3 address bedding orientation and wet testing when pertinent. §4.1 says the method provides “one element in comparing stones of the same type.” A reported rupture stress is a specimen test result, not an allowable stress for a countertop with notches, holes, handling contacts, and unknown loading.

ASTM C99/C99M-18 §1.1 determines modulus of rupture for dimension stone except slate. Its §4.1 likewise describes comparison. Do not silently substitute C99 for C880 or treat compressive strength as bending strength. The full paid procedures were not retrieved; this report does not assert specimen dimensions or a statistical design conversion from them.

ASTM C97/C97M-18 §1.1 determines absorption and **bulk specific gravity**, except slate. Specific gravity is dimensionless; density in kg/m³ requires a stated conversion/reference and moisture condition. A label saying only “density” with an unexplained value is not a fully specified engineering input.

S4 p. 2 reports Q groups with C99 modulus-of-rupture values **1,980–7,495 psi** and C880 flexural values **5,525–10,365 psi**. Its density row is **2.18–2.43**, with no unit printed in that row. It says tests were performed by an external independent laboratory. It does not supply a specimen-level design lower bound, wet/dry and orientation detail for each value, a supported handling scenario, or a universal allowable. Group membership must be read from p. 1; do not select a group from a similar-looking trade name. Density is insufficiently specified for automatic mechanics import without clarification.

## 2. Candidate implementations

### A. Product rules plus geometric search: implement now

1. Resolve a rule profile by manufacturer, product family, exact applicability/edition, nominal thickness, and application. Unknown identity stays unknown. Start with S1; add independently sourced profiles rather than copying S1 limits to MSI/natural stone.
2. Validate the final outline and cutouts before adding seams. Compute named edge/rail/end distances, opening-to-opening distances, radii, and any source-required relations. A violated original 40 mm strip does not become acceptable because pieces are renamed or shrunk.
3. Generate a **no-seam polygon first**, including L/U shapes. A rectangular supplier slab or rectangular allocation blank does not require rectangular finished pieces. Preserve holes and connectedness. Check the blank's stock fit as a separate fact.
4. Generate corner joins at re-entrant vertices, transverse run joins on legal stock/geometry intervals, and outside-opening joins at the profile's exclusion boundaries. Include cabinet/support-line intersections as candidate events when known. Generate through-opening joins only for a profile's documented detail, with an explicit opening ID and support obligations. For S1, initially use the illustrated opening-centerline arrangement; the opening need not be centered on the countertop. Do not infer that every arbitrary oblique/off-center intersection is covered by the figure. Tangencies are a different join class, with their own fixture restrictions.
5. Split the **actual solid polygon**, subtracting openings. A join crossing a sink may consist of two separated solid seam segments; its drawn stone length excludes the void, while the objective counts physical joins. Retain the parent opening and each resulting notch. No zero-area or disconnected fabrication piece is legal.
6. Validate every resulting piece and seam against the original installation and profile. Record an evidence entry for each predicate, including measured distance, limit, operator, source/page, and outstanding obligations. A seam creates no support by itself. Missing reinforcement/support evidence stays conditional; it cannot satisfy a hard feasibility gate by assumption.
7. Give the nester admitted alternatives, preserving connected gross piece polygons, reserved openings, kerf, trim and quarter-turn placements. Collision-cell boundaries are not joins; cells of one piece share one rigid transform and have no internal saw gap. Bounding-box nesting is an explicitly conservative fallback. Vein matching remains outside scope.
8. Rank assessed candidates before conditional ones; reject failed candidates. Within each pool, prefer fewer slabs, fewer physical joins, S1's outside-opening preference, then a larger smallest positive gross piece area and stable geometry order. Balance is a usability tie-break, not a strength rule. Distinguish **seam required for stock fit**, **required by profile**, **chosen for yield**, **supplied count/join**, and **no seam required by evaluated rules**. Search coverage limits remain visible.

Use independent result axes:

```text
geometry: valid | invalid
profileApplicability: established | unresolved
productRuleAssessment: pass | fail | unresolved
installationConditions: satisfied | required-unverified | failed
handlingAssessment: not-evaluated
search: complete | capped
seamDecision: required | none-required-by-evaluated-rules | undetermined
candidateEligibility: eligible-within-declared-scope | conditional | rejected
```

“Pass” always names the evaluated profile/scope. Requirements can be emitted automatically without designing reinforcement. A conditional estimate retains its unmet conditions; it is not a completed product assessment. Preflight checks tools and input readability independently of this status.

No arbitrary minimum piece size is needed to reject the tiny-piece trick: original rail/end constraints persist, every piece must be connected and fabricable under the profile, and added seams retain support obligations. Where fabrication-tool access or handling minimums are not documented, that check is unresolved, not a new magic threshold.

The earlier rectangular partition restriction unnecessarily turned every nonrectangular L into multiple pieces. Whole L candidates now belong to the planner. U/general geometry is representable, but an uninspected source arrangement remains unsupported. A supplied join or piece count does not waive product rules.

### B. Optional specified-scenario mechanics: diagnostics only initially

For a **straight, uniform rectangular beam**, horizontal, thickness `t`, width `b`, length `L`, density `rho`, supported vertically by a pin and roller at `x=0,L`, with only its own uniform gravitational load:

```text
q = rho * g * b * t                       [N/m]
Rleft = Rright = qL/2                     [N]
M(x) = qLx/2 - qx²/2                     [N m]
Mmax = qL²/8, at x=L/2
I = b t³/12                              [m⁴]
sigmaMax = Mmax(t/2)/I
         = 3 rho g L² / (4t)              [Pa]
```

Dimensions: `(kg/m³)(m/s²)(m²)/m = kg/(m s²) = Pa`. For a cantilever fixed at one end under the same self-weight, `Mmax=qL²/2`, so `sigmaMax=3 rho g L²/t`, **four times** the simple-support value. For a midpoint transverse point load `P` on the simple beam, `Mmax=PL/4` and the additional stress is `3PL/(2bt²)`. These follow from equilibrium and `sigma=Mc/I`; no empirical countertop threshold is introduced.

Synthetic check: `rho=2500 kg/m³`, `g=9.81 m/s²`, `L=0.80 m`, `b=0.060 m`, `t=0.020 m` gives `q=29.43 N/m`, `Mmax=2.3544 N m`, and simple-support self-weight stress **0.5886 MPa**. The cantilever is **2.3544 MPa**. A synthetic **200 N midpoint load** adds **10 MPa**. These are calculation checks, not assertions about a real stone, realistic handling loads, or allowable stress.

Why this is not a cutout-breakage model:

- Width **cancels** under self-weight. It predicts equal nominal stress for 30 mm and 90 mm rails of equal length/thickness, although hole-edge stress concentrations, load sharing, machining damage and point contacts differ. It cannot justify an automatic minimum rail width.
- An opening's front/back rails form a connected frame with end webs, corner notches, eccentric loads, and possible torsion. Treating each rail as an independent simply supported beam assumes support/reactions at its ends that have not been established. A plate model would additionally need elastic constants, plate boundary conditions, contacts, and a specified loading field; density and rupture strength do not close that problem.
- Carried vertically, the bending axis and contact geometry change. The installed cabinet span is not the transport span. Unknown orientation, support spacing, or external loads makes this scenario inapplicable.
- Splitting outside the opening may leave its rail length and loading unchanged. Splitting **through** it can turn connected rails into fingers supported at only one end during handling. Halving the overall countertop length does not prove that the vulnerable beam span halves. A glued seam without support does not restore monolithic bending capacity by definition.

If retained, output `scenarioStressPa` and assumptions only. Comparing stress to a test rupture value produces a **test-strength ratio**, not a certified utilization or failure probability. A decision threshold would need a justified allowable, uncertainty model, and independently established load/support scenario. A free safety-factor field cannot supply those missing facts. Do not ship B as the initial automatic seam gate.

## 3. Implemented v2 input and evidence scope

The maintained [job reference](../countertop-takeoff/references/job-format.md) describes the serialized input. Geometry stays on the 1/16-inch grid; thickness/radii are exact decimal mm strings, off-grid. Source predicates compare exact original-unit minima. The planner stores rule id, predicate status, measured/required values, URL, edition, PDF hash, file/printed pages, quotation and interpretation. Input authorization and scoped support notes do not become manufacturer authority. No general provenance system or mechanics input is implemented.

| Field | Required form | Null/unknown behavior |
| --- | --- | --- |
| `material.profileId` / `profileProvenance` | Explicit versioned profile plus product/source basis for selecting it. | Missing profile or provenance makes normal automatic planning unresolved; no generic fallback or slab layout. |
| `material.nominalThicknessMm` | Positive documented nominal thickness; exact profile class such as 12, 20, 30. | Required for thickness-dependent rules. Unknown does not default to 20/30. Do not interpolate tables unless the source permits it. |
| `installations[].shape` / `insideCornerRadiusMm` | Shape or supplied clockwise orthogonal corners; minimum actual continuous inside-corner radius in mm. | Whole L geometry is allowed; radius unknown stays null. Zero is an explicitly supplied sharp corner, not unknown. |
| `sourceArrangement` | Explicit rectangular-run axis, rear side and provenance identifying the source-facing datum. | Null datum remains unknown. L/U leg envelopes are not the documented rectangular-run detail. |
| `cutouts[]` | Kind, written envelope/position, nullable `radiusMm` and `mount`; optional authorized `estimate` fields/note. | Empty list means confirmed none. A rectangular envelope does not establish radius, mount or fixture detailing. |
| `material.slab` / `settings` | Nominal stock dimensions; trim, kerf and rotation settings only. | Missing slab prevents a final stock layout; defaults are reported assumptions. Retired generic opening clearances are not v2 settings. |
| `conditions[]` | Typed support/reinforcement evidence, installation or cutout scope, documented/failed/unknown status and note. | Empty evidence is not satisfied support. Apply only the selected source's relevant conditions; no cross-profile inheritance. |
| Optional `seam` / `requiredPieceCount` | Supplied opening-center join or historical midpoint/equal-halves request; optional exact positive count. | Automatic decisions require neither. Opening-center pins that join without forbidding additional joins; the historical variant fixes two equal halves. Source checks still apply. |
| `assessment` output | Unresolved, conditional, assessed, conflict or search-incomplete; source checks, conditions, missing fields and search limits. | Preserve independent SF and prices; null layout means slab-derived charges stay null. Handling always remains not evaluated. |

Every unknown is a value, not zero. Derive rail widths and cutout positions from geometry; do not require users to type redundant metrics. Keep support/conditions separate from final dimensional quantities so pricing remains exact.

**Units/grid trap:** S1's 100 mm and approximate 4-inch label are not identical. Use the metric rule for that profile. A 1/16-inch grid is 1.5875 mm; conservative gridding of a 100 mm minimum requires **63 ticks =100.0125 mm**. For 150 mm the ceiling is **95 ticks =150.8125 mm**. Code constructs boundary candidates by rounding coordinates upward; metric radii/thickness are retained exactly and never snapped to this grid.

## 4. Synthetic decision examples

1. **Stock forces a seam, opening off-center.** S1 20 mm profile; top `3100 ×760 mm`, sink opening `[950,1650] ×[130,630] mm`, required radii 10 mm. Usable stock `2850 ×1600 mm`, kerf 5 mm. The unseamed blank cannot fit at either permitted 0°/90° orientation. A cross-seam at `x=1900 mm` is 250 mm from the opening; its `1900 ×760` and `1200 ×760` blanks fit stacked within one slab (`1525 mm` including kerf). The estimator generates this join automatically. Eligibility still checks source-required support and applicable end/rail constraints. This is a stock-fit seam, not a calculated fracture prediction.
2. **Through an off-center opening is an alternative, not a special centered-top override.** Same installation, seam at `x=1300 mm`. The two actual solid seam segments total `130+130=260 mm`. S1's inside-opening detail can admit it with documented continuous support. The outside-opening 100 mm rule does not accidentally reject that different detail. The through seam is disfavored by the source and remains conditional when support is unknown, as does an outside-opening seam with missing continuous rail support. Tangencies at `x=950` or `1650` have source-specific mount/support conditions and remain unsupported in this bounded implementation.
3. **Thin material changes seam eligibility.** At an outside seam 125 mm from an opening, S1 20/30 mm clears the 100 mm criterion; 12 mm fails the 150 mm criterion. The planner searches another legal position. It does not declare 12 mm inherently unable to contain that opening.
4. **A one-piece L should survive candidate generation.** Synthetic L vertices `(0,0),(2200,0),(2200,650),(650,650),(650,1850),(0,1850)`, usable slab `2300 ×1950 mm`. Its allocation rectangle fits. For S2 Q, retain the geometry candidate with Q's radius and general deck-support checks, while disclosing incomplete source scope. Do not add S1 corner-reinforcement/continuous-corner obligations to Q. For S1, retain its radius, level support, continuous-corner support and reinforcement conditions. S5's historical corner-join rule remains research, not an active current profile. A rectangular-only partition would incorrectly force a seam before evaluating these differences.
5. **Splitting does not cure a thin rail.** S1 opening with only 40 mm clear front material fails the illustrated 50 mm front-strip constraint. Cutting a 70 mm end piece elsewhere leaves that 40 mm unchanged; reject the alleged cure. A through-opening seam cannot automatically waive the original opening-strip condition either. Return a dimensional conflict or a specifically supported alternative detail, not “safe after splitting.”

Examples 1–2 are geometry demonstrations, not completed shop drawings or proof that all fixture/support requirements have been supplied.

## 5. Independent tests and failure cases

Use hand-checkable fixtures and a verifier that recomputes predicates from the original polygons. Do not let the optimizer grade its own output.

| Test | Independent expected result |
| --- | --- |
| S1 outside seam distance 99/100/101 mm at 20 mm | Fail/pass/pass for **that clearance predicate**. Other gates remain independent. At 12 mm, 149/150/151 gives fail/pass/pass. |
| S1 sink/cooktop radius 9/10/11 mm | Fail/pass/pass. S2's exact 9.525 mm radius passes its own fabrication rule, but fails S1's 10 mm minimum. |
| Historical S5 distance 59/60/149/150 mm | Fail / reinforcement-required / reinforcement-required / no extra strip required by this particular distance clause. Never four unconditional passes. |
| S1 outside/inside/tangent joins at the same opening | Separate predicate paths. Inside cannot inherit an unverified top-mount-only restriction; tangent must enforce it. Unknown support stays unresolved in all support-dependent cases. |
| Unrelated second opening near a permitted through seam | Permission for opening A does not exempt B's clearance, strip, or topology constraints. |
| Weak-rail split from example 5 | Recomputed original rail remains 40 mm. Renaming pieces or adding a tiny piece does not pass. |
| Split conservation | Piece interiors are disjoint; union equals original solid within declared seam-gap accounting; holes remain void; no disconnected piece; seam endpoints are on the correct boundaries. |
| Blank propagation | Every actual piece lies in its allocation blank; blank dimensions include real allowances and rotation; nesting verifier checks trim/kerf/no overlap independently. Never feed the original full-top blank for each split piece. |
| Slab fit example 1 | Reject 3100 mm unseamed stock fit; independently confirm both split rectangles within 2850 ×1600 including 5 mm interpiece kerf. |
| L example 4 | No-seam silhouette exists before policy evaluation; rectangle allocation and finished-piece shape are distinct. Source-specific corner rules produce different outcomes. |
| Exact conversion | `ceil(100/1.5875)=63`; `ceil(150/1.5875)=95`; 10 mm does not become 3/8 inch. Test thresholds in original units. |
| Missing nominal thickness, product, radius, or support | Unknown never turns into a favorable default. Return exact missing fields and preserve independent geometry results. |
| Search caps | No qualifying incumbent means `search-incomplete`, not proof that no legal seam exists or that a seam is necessary. A capped incumbent retains its search/proof limits. |
| Beam equilibrium | For the synthetic scenario, reactions are 11.772 N each, sum 23.544 N =qL; center moment 2.3544 N m; stress 0.5886 MPa. Cantilever factor is exactly four. |
| Mechanics scaling | Self-weight stress scales as `rho L²/t`; doubling L gives ×4, doubling t gives ×1/2, doubling rho gives ×2, changing b alone gives no change. For fixed P, stress scales as `PL/(bt²)`. |
| Unchanged load path after splitting | A split that leaves rail L and supports unchanged leaves that beam result unchanged. A new free end invalidates the simple-support scenario instead of resetting L favorably. |

**Monotonicity must name what is held fixed.** Increasing an outside seam's clearance, with topology/mount/support and other openings unchanged, cannot worsen that clearance predicate. Increasing a profile minimum cannot expand its feasible set. More usable slab area cannot invalidate an existing geometric placement. More thickness need not improve every rule or objective; use the actual documented table. Moving one seam away from opening A can move it closer to B. Widening an opening can change topology and support, so no blanket monotonic pass is promised. Unit conversions must preserve equivalent decisions. Removing uncertainty must resolve a check from evidence, not automatically improve it.

## 6. Honest claims and remaining source limitations

The initial implementation can honestly claim: **automatic seam alternatives and a selected estimate, with verified stock fit, explicit product-rule checks, and reasons linked to their sources**. It can report when stock or an applicable rule requires a seam, when no evaluated rule requires one, and when selection is conditional on a named missing fact. It can treat thickness, cutout size/position, corners, support, and material identity as real inputs without inventing a strength model.

It cannot claim a breakage guarantee, a general probability of failure, validated dynamic transport safety, automatic reinforcement design, absence of defects, or structural certification. A source-compliant estimate is not proof that every load case has been considered. These omissions are material, even if a numerical safety factor is large.

Unresolved source limitations are specific: the newer Caesarstone full guide and newer NSI chapter were not inspected; MSI's accessible Q/Q+ guidance does not supply enough opening-strip/seam-placement detail for a complete counterpart to S1; density units/test details in the MSI property table are insufficient for automatic mechanics; no investigated source supplies a universal unreinforced rail-span rule for carrying arbitrary cutout frames. The old Silestone 4 mm corner text must not override S1's 10 mm detail. Source diagrams contain application-specific conditions that must survive extraction.

**Implement A now.** Pin S1 and its exact applicability, keep sparse profiles visibly incomplete, and make the engine produce seam locations itself. Retain B only as an explicitly specified analytical scenario until an independently defensible loading/support contract exists.
