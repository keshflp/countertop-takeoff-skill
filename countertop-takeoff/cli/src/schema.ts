import { Schema } from "effect"

const Decimal = Schema.String.check(Schema.isPattern(/^\d+(?:\.\d+)?$/))
const PositiveDecimal = Decimal.check(Schema.makeFilter(s => /[1-9]/.test(s)))
const TwoDp = Schema.String.check(Schema.isPattern(/^\d+\.\d{2}$/))
const Inches = Schema.Number.check(Schema.isGreaterThanOrEqualTo(0), Schema.makeFilter(n => Number.isSafeInteger(n * 16)))
const Length = Inches.check(Schema.isGreaterThan(0))
const Count = Schema.Number.check(Schema.makeFilter(n => Number.isSafeInteger(n) && n >= 0))
const PositiveCount = Count.check(Schema.isGreaterThan(0))
const Text = Schema.String.check(Schema.makeFilter(s => s.trim().length > 0))
const Point = Schema.Tuple([Inches, Inches])
const Polygon = Schema.Array(Point).check(Schema.isMinLength(4))
const Blank = Schema.Struct({ field: Text, question: Text })
const CutoutKind = Schema.Literals(["sink", "cooktop", "other"])
const Mount = Schema.NullOr(Schema.Literals(["top", "under", "flush", "other"]))
const ConditionKind = Schema.Literals(["level-support", "corner-continuous-support", "corner-reinforcement", "opening-continuous-support", "fixture-support", "installation-support"])
const Conditions = Schema.Array(Schema.Struct({
  kind: ConditionKind, cutoutIndex: Schema.NullOr(Count), status: Schema.Literals(["documented", "failed", "unknown"]), note: Schema.NullOr(Text),
}).check(Schema.makeFilter(c => c.status === "unknown" || c.note !== null)))
const Arrangement = Schema.NullOr(Schema.Struct({ kind: Schema.Literal("rectangular-run"), axis: Schema.Literals(["x", "y"]), rear: Schema.Literals(["min", "max"]), provenance: Text }))
const Seam = Schema.Union([
  Schema.Struct({ kind: Schema.Literal("center-through-cutout"), cutoutIndex: Count }),
  Schema.Struct({ kind: Schema.Literal("opening-center"), cutoutIndex: Count }),
  Schema.Struct({ kind: Schema.Literal("tangent-cutout"), cutoutIndex: Count, side: Schema.Literals(["start", "end"]) }),
])
const EstimateFields = Schema.Array(Schema.Literals(["wIn", "hIn", "at"])).check(Schema.isMinLength(1), Schema.makeFilter(fields => new Set(fields).size === fields.length))
const LegacyCutout = Schema.Struct({
  kind: CutoutKind, wIn: Length, hIn: Length,
  at: Schema.Union([
    Schema.Struct({ leg: Schema.Literals(["main", "back", "left", "right"]), centerFromStartIn: Schema.Union([Inches, Schema.Literal("center")]) }),
    Schema.Struct({ xIn: Inches, yIn: Inches }),
  ]), estimate: Schema.optionalKey(Schema.Struct({ fields: EstimateFields, note: Text })),
})
const Shape = Schema.Union([
  Schema.Struct({ kind: Schema.Literal("rect"), lengthIn: Length, depthIn: Length }),
  Schema.Struct({ kind: Schema.Literal("L"), backIn: Length, sideIn: Length, depthIn: Length, side: Schema.Literals(["left", "right"]) }),
  Schema.Struct({ kind: Schema.Literal("U"), leftIn: Length, backIn: Length, rightIn: Length, depthIn: Length }),
  Schema.Struct({ kind: Schema.Literal("outline"), points: Polygon }),
])
/** Nominal stock dimensions on the existing inch grid. */
export const Slab = Schema.Struct({ lengthIn: Length, widthIn: Length })
/** Only stock/packing defaults remain; Python owns source seam rules. */
export const Settings = Schema.Struct({ slabTrimIn: Inches, kerfIn: Inches, allowRotate: Schema.Boolean })
export interface Settings extends Schema.Schema.Type<typeof Settings> {}
const OptionalSettings = Schema.Struct({ slabTrimIn: Schema.optionalKey(Inches), kerfIn: Schema.optionalKey(Inches), allowRotate: Schema.optionalKey(Schema.Boolean) })
const LegacyMaterial = Schema.Struct({ name: Schema.NullOr(Text), vendor: Schema.NullOr(Text), pricePerSf: Schema.NullOr(Decimal), markupPercent: Schema.NullOr(Decimal), slab: Schema.NullOr(Slab) })
const ProfileFacts = { profileId: Schema.NullOr(Text), profileProvenance: Schema.NullOr(Text), nominalThicknessMm: Schema.NullOr(PositiveDecimal) }
const Material = Schema.Struct({ ...LegacyMaterial.fields, ...ProfileFacts })
const LegacyInstallation = Schema.Struct({ id: Text, label: Text, shape: Shape, cutouts: Schema.Array(LegacyCutout), requiredPieceCount: Schema.optionalKey(PositiveCount), seam: Schema.optionalKey(Schema.Struct({ kind: Schema.Literal("center-through-cutout"), cutoutIndex: Count })) })
const JobInstallation = Schema.Struct({
  ...LegacyInstallation.fields, cutouts: Schema.Array(Schema.Struct({ ...LegacyCutout.fields, radiusMm: Schema.NullOr(Decimal), mount: Mount })),
  seam: Schema.optionalKey(Seam), insideCornerRadiusMm: Schema.NullOr(Decimal), sourceArrangement: Arrangement, conditions: Conditions,
})
/** Normal v2 facts. Unknown material identity, radii and conditions stay explicit. */
export const Job = Schema.Struct({ version: Schema.Literal(2), material: Material, laborPerSf: Schema.NullOr(Decimal), installations: Schema.Array(JobInstallation).check(Schema.isMinLength(1)), settings: OptionalSettings })
export interface Job extends Schema.Schema.Type<typeof Job> {}
/** Frozen v1 boundary, consumed only by the development replay entrypoint. */
export const LegacyJob = Schema.Struct({ version: Schema.Literal(1), material: LegacyMaterial, laborPerSf: Schema.NullOr(Decimal), installations: Schema.Array(LegacyInstallation).check(Schema.isMinLength(1)), settings: Schema.Struct({ ...OptionalSettings.fields, minSeamToCutoutIn: Schema.optionalKey(Inches), minMaterialBesideCutoutIn: Schema.optionalKey(Inches) }) })

const Installation = Schema.Struct({
  id: Text, shapeKind: Schema.Literals(["rect", "L", "U", "outline"]), outline: Polygon,
  cutouts: Schema.Array(Schema.Struct({ kind: CutoutKind, x: Inches, y: Inches, w: Length, h: Length, radiusMm: Schema.NullOr(Decimal), mount: Mount })),
  insideCornerRadiusMm: Schema.NullOr(Decimal), sourceArrangement: Arrangement, conditions: Conditions,
  requiredPieceCount: Schema.optionalKey(PositiveCount), seam: Schema.optionalKey(Seam),
})
/** Expanded numeric geometry; no price data crosses into the physical model. */
export const LayoutInput = Schema.Struct({
  version: Schema.Literal(2), mode: Schema.Literals(["assessment", "geometry-replay"]), phase: Schema.Literals(["assess", "plan"]),
  material: Schema.Struct(ProfileFacts), slab: Schema.NullOr(Slab), settings: Settings, installations: Schema.Array(Installation).check(Schema.isMinLength(1)),
  legacySettings: Schema.optionalKey(Schema.Struct({ minSeamToCutoutIn: Inches, minMaterialBesideCutoutIn: Inches })),
}).check(Schema.makeFilter(r => (r.mode === "geometry-replay") === (r.legacySettings !== undefined)))
export interface LayoutInput extends Schema.Schema.Type<typeof LayoutInput> {}
/** Owner-authorized estimated dimensions remain separate from rule conditions. */
export const GeometryEstimates = Schema.Array(Schema.Struct({ installationId: Text, cutoutIndex: Count, fields: EstimateFields, note: Text, xIn: Inches, yIn: Inches, wIn: Length, hIn: Length }))
const Source = Schema.Struct({
  id: Schema.Literals(["S1", "S2"]), title: Text, edition: Text, url: Text,
  sha256: Schema.String.check(Schema.isPattern(/^[a-f0-9]{64}$/)),
  filePages: Schema.Array(PositiveCount).check(Schema.isMinLength(1)), printedPages: Schema.Array(PositiveCount), quotation: Text, interpretation: Text,
})
const Measure = Schema.Struct({ value: Decimal, unit: Schema.Literals(["mm", "in", "count"]) })
const Check = Schema.Struct({
  id: Text, ruleId: Text, installationId: Schema.NullOr(Text), cutoutIndex: Schema.NullOr(Count), joinId: Schema.NullOr(Text),
  status: Schema.Literals(["pass", "fail", "unknown", "unsupported", "not-applicable"]), operator: Schema.Literals([">=", "=", "documented", "applicable"]),
  actual: Schema.NullOr(Measure), required: Schema.NullOr(Measure), source: Schema.NullOr(Source), explanation: Text, fields: Schema.Array(Text),
})
const Condition = Schema.Struct({
  id: Text, kind: Schema.Literals([...ConditionKind.literals, "radius-detail", "unsupported-detail"]), installationId: Text, cutoutIndex: Schema.NullOr(Count), joinId: Schema.NullOr(Text),
  status: Schema.Literals(["satisfied", "required-unverified", "failed", "unsupported"]), source: Schema.NullOr(Source), explanation: Text, evidenceNote: Schema.NullOr(Text), fields: Schema.Array(Text),
})
/** Independent result axes: product subset, conditions, handling and search. */
export const Assessment = Schema.Struct({
  status: Schema.Literals(["unresolved", "conditional", "assessed", "conflict", "search-incomplete"]), geometry: Schema.Literals(["valid", "invalid"]),
  profile: Schema.Struct({ id: ProfileFacts.profileId, provenance: ProfileFacts.profileProvenance, nominalThicknessMm: ProfileFacts.nominalThicknessMm }),
  checks: Schema.Array(Check), conditions: Schema.Array(Condition), unresolved: Schema.Array(Blank), handling: Schema.Literal("not-evaluated"), limitations: Schema.Array(Text),
  installations: Schema.Array(Schema.Struct({ id: Text, seamNecessity: Schema.Literals(["stock-fit", "source-rule", "none-required", "undetermined"]), explanation: Text })),
  search: Schema.Struct({
    status: Schema.Literals(["not-run", "complete", "capped"]), candidateFamilies: Schema.Array(Schema.Literals(["whole", "corner", "stock-fit", "opening-center", "supplied"])),
    candidateCount: Count, qualifyingCount: Count, packing: Schema.Literals(["not-run", "polygon-cells", "bounding-box"]),
    optimality: Schema.Literals(["not-proven", "within-candidates", "global-slab-bound"]), limits: Schema.Array(Text),
  }),
})
export interface Assessment extends Schema.Schema.Type<typeof Assessment> {}
const Segment = Schema.Struct({ x0: Inches, y0: Inches, x1: Inches, y1: Inches })
/** Gross polygon footprints reserve holes; clipped cutouts identify actual stone. */
export const Layout = Schema.Struct({
  pieces: Schema.Array(Schema.Struct({ id: Text, installationId: Text, outline: Polygon, cutouts: Schema.Array(Schema.Struct({ cutoutIndex: Count, outline: Polygon })) })).check(Schema.isMinLength(1)),
  joins: Schema.Array(Schema.Struct({
    id: Text, installationId: Text, pieceIds: Schema.Array(Text).check(Schema.isMinLength(2)), kind: Schema.Literals(["solid", "corner", "outside-opening", "inside-opening"]),
    axis: Schema.Literals(["x", "y"]), offsetIn: Inches, startIn: Inches, endIn: Inches, segments: Schema.Array(Segment), cutoutIndex: Schema.NullOr(Count),
    origin: Schema.Literals(["automatic", "supplied"]), reason: Schema.Literals(["stock-fit", "source-rule", "yield", "supplied-count", "supplied-join"]),
  })),
  slabs: Schema.Array(Schema.Struct({ index: PositiveCount, placements: Schema.Array(Schema.Struct({ pieceId: Text, x: Inches, y: Inches, quarterTurns: Schema.Literals([0, 1, 2, 3]) })) })),
  slabCount: PositiveCount, lowerBound: PositiveCount, provenOptimal: Schema.Boolean, footprintMode: Schema.Literals(["gross-polygons", "bounding-box"]), warnings: Schema.Array(Schema.String),
})
export interface Layout extends Schema.Schema.Type<typeof Layout> {}
const KernelFailure = Schema.Struct({ ok: Schema.Literal(false), error: Schema.Struct({ tag: Text, message: Text }) })
/** Expected assessment outcomes are successful protocol replies, including null layouts. */
export const PlanReply = Schema.Struct({ ok: Schema.Literal(true), version: Schema.Literal(2), assessment: Assessment, layout: Schema.NullOr(Layout) })
export interface PlanReply extends Schema.Schema.Type<typeof PlanReply> {}
export const LayoutReply = Schema.Union([PlanReply, KernelFailure])
/** Input facts and the full standalone assessment travel to both PNG modes. */
export const DrawInput = Schema.Struct({ version: Schema.Literal(2), slab: Schema.NullOr(Slab), settings: Settings, installations: Schema.Array(Installation), assessment: Assessment, layout: Schema.NullOr(Layout), geometryEstimates: GeometryEstimates })
export interface DrawInput extends Schema.Schema.Type<typeof DrawInput> {}
export const DrawReply = Schema.Union([Schema.Struct({ ok: Schema.Literal(true), path: Text }), KernelFailure])
export const SelfcheckReply = Schema.Struct({ ok: Schema.Literal(true) })
export const InspectInput = Schema.Array(Text).check(Schema.isMinLength(1))
export const InspectReply = Schema.Struct({ files: Schema.Array(Schema.Struct({ path: Text, ok: Schema.Boolean, kind: Schema.Literals(["image", "pdf"]), pages: Count, previews: Schema.Array(Text), problem: Schema.NullOr(Text) })) })
/** Partial quotes preserve every original fact and the actual scope of assessment. */
export const Quote = Schema.Struct({
  version: Schema.Literal(2), material: Material,
  installations: Schema.Array(Schema.Struct({ ...JobInstallation.fields, areaSqIn: Decimal, sf: TwoDp })),
  totalSf: TwoDp, assessment: Assessment, layout: Schema.NullOr(Layout), slabCount: Schema.NullOr(PositiveCount), slabSf: Schema.NullOr(Decimal),
  pricing: Schema.Struct({ materialCost: Schema.NullOr(TwoDp), markupPercent: Schema.NullOr(Decimal), materialCharge: Schema.NullOr(TwoDp), materialRatePerSf: Schema.NullOr(TwoDp), laborPerSf: Schema.NullOr(TwoDp), ratePerSf: Schema.NullOr(TwoDp) }),
  invoice: Schema.Array(Schema.Struct({ installation: Text, material: Schema.NullOr(Text), sf: TwoDp, ratePerSf: Schema.NullOr(TwoDp), amount: Schema.NullOr(TwoDp) })),
  blanks: Schema.Array(Blank), assumptions: Schema.Array(Schema.Struct({ setting: Text, value: Schema.String, note: Schema.Literal("assumed, confirm with Dad") })),
  warnings: Schema.Array(Schema.String), geometryEstimates: GeometryEstimates,
})
export interface Quote extends Schema.Schema.Type<typeof Quote> {}
