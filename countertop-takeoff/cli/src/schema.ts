import { Schema } from "effect"

const Decimal = Schema.String.check(Schema.isPattern(/^\d+(?:\.\d+)?$/))
const TwoDp = Schema.String.check(Schema.isPattern(/^\d+\.\d{2}$/))
const Inches = Schema.Number.check(
  Schema.isGreaterThanOrEqualTo(0),
  Schema.makeFilter((n) => Number.isSafeInteger(n * 16)),
)
const Length = Inches.check(Schema.isGreaterThan(0))
const Count = Schema.Int.check(Schema.isGreaterThanOrEqualTo(0))
const PieceCount = Count.check(Schema.isGreaterThan(0))
const Text = Schema.String.check(Schema.makeFilter((s) => s.trim().length > 0))
const Point = Schema.Tuple([Inches, Inches])
const Polygon = Schema.Array(Point).check(Schema.isMinLength(4))

/** The five explicit layout settings; defaults are applied by the core. */
export const Settings = Schema.Struct({
  slabTrimIn: Inches,
  kerfIn: Inches,
  minSeamToCutoutIn: Inches,
  minMaterialBesideCutoutIn: Inches,
  allowRotate: Schema.Boolean,
})
/** Resolved layout settings. */
export interface Settings extends Schema.Schema.Type<typeof Settings> {}

/** Nominal slab dimensions in inches. */
export const Slab = Schema.Struct({ lengthIn: Length, widthIn: Length })
const Shape = Schema.Union([
  Schema.Struct({ kind: Schema.Literal("rect"), lengthIn: Length, depthIn: Length }),
  Schema.Struct({ kind: Schema.Literal("L"), backIn: Length, sideIn: Length, depthIn: Length, side: Schema.Literals(["left", "right"]) }),
  Schema.Struct({ kind: Schema.Literal("U"), leftIn: Length, backIn: Length, rightIn: Length, depthIn: Length }),
  Schema.Struct({ kind: Schema.Literal("outline"), points: Polygon }),
])
const CutoutKind = Schema.Literals(["sink", "cooktop", "other"])
const CenterJoin = Schema.Struct({ kind: Schema.Literal("center-through-cutout"), cutoutIndex: Count })
const EstimateFields = Schema.Array(Schema.Literals(["wIn", "hIn", "at"])).check(
  Schema.isMinLength(1), Schema.makeFilter(fields => new Set(fields).size === fields.length),
)
const Cutout = Schema.Struct({
  kind: CutoutKind, wIn: Length, hIn: Length,
  at: Schema.Union([
    Schema.Struct({ leg: Schema.Literals(["main", "back", "left", "right"]), centerFromStartIn: Schema.Union([Inches, Schema.Literal("center")]) }),
    Schema.Struct({ xIn: Inches, yIn: Inches }),
  ]),
  estimate: Schema.optionalKey(Schema.Struct({ fields: EstimateFields, note: Text })),
})

/** Confirmed facts, including explicit nulls for facts Dad has not supplied. */
export const Job = Schema.Struct({
  version: Schema.Literal(1),
  material: Schema.Struct({
    name: Schema.NullOr(Text), vendor: Schema.NullOr(Text), pricePerSf: Schema.NullOr(Decimal),
    slab: Schema.NullOr(Slab), markupPercent: Schema.NullOr(Decimal),
  }),
  laborPerSf: Schema.NullOr(Decimal),
  installations: Schema.Array(Schema.Struct({ id: Text, label: Text, shape: Shape, cutouts: Schema.Array(Cutout), requiredPieceCount: Schema.optionalKey(PieceCount), seam: Schema.optionalKey(CenterJoin) })).check(Schema.isMinLength(1)),
  settings: Schema.Struct({
    slabTrimIn: Schema.optionalKey(Settings.fields.slabTrimIn),
    kerfIn: Schema.optionalKey(Settings.fields.kerfIn),
    minSeamToCutoutIn: Schema.optionalKey(Settings.fields.minSeamToCutoutIn),
    minMaterialBesideCutoutIn: Schema.optionalKey(Settings.fields.minMaterialBesideCutoutIn),
    allowRotate: Schema.optionalKey(Settings.fields.allowRotate),
  }),
})
/** Parsed job facts. */
export interface Job extends Schema.Schema.Type<typeof Job> {}

const Installation = Schema.Struct({
  id: Text, outline: Polygon, requiredPieceCount: Schema.optionalKey(PieceCount), seam: Schema.optionalKey(CenterJoin),
  cutouts: Schema.Array(Schema.Struct({ kind: CutoutKind, x: Inches, y: Inches, w: Length, h: Length })),
})
/** Owner-authorized estimates retain the actual rectangle sent to the kernels. */
export const GeometryEstimates = Schema.Array(Schema.Struct({
  installationId: Text, cutoutIndex: Count, fields: EstimateFields, note: Text,
  xIn: Inches, yIn: Inches, wIn: Length, hIn: Length,
}))
/** CLI-expanded geometry sent to the layout kernel. */
export const LayoutInput = Schema.Struct({ slab: Slab, settings: Settings, installations: Schema.Array(Installation) })
/** Layout request in inches, converted from exact sixteenth-inch integers. */
export interface LayoutInput extends Schema.Schema.Type<typeof LayoutInput> {}

const KernelFailure = Schema.Struct({ ok: Schema.Literal(false), error: Schema.Struct({ tag: Text, message: Text }) })
/** A successful layout, including placement and seam coordinates. */
export const Layout = Schema.Struct({
  ok: Schema.Literal(true),
  pieces: Schema.Array(Schema.Struct({ id: Text, installationId: Text, outline: Polygon })),
  seams: Schema.Array(Schema.Struct({ installationId: Text, x0: Inches, y0: Inches, x1: Inches, y1: Inches })),
  slabs: Schema.Array(Schema.Struct({ index: Count.check(Schema.isGreaterThan(0)), placements: Schema.Array(Schema.Struct({ pieceId: Text, x: Inches, y: Inches, rotated: Schema.Boolean })) })),
  slabCount: Count, lowerBound: Count, provenOptimal: Schema.Boolean, warnings: Schema.Array(Schema.String),
}).check(Schema.makeFilter(layout => {
  const ids = new Set(layout.pieces.map(piece => piece.id))
  const placed = layout.slabs.flatMap(slab => slab.placements.map(p => p.pieceId))
  return layout.pieces.length > 0 && ids.size === layout.pieces.length &&
    layout.slabCount === layout.slabs.length && layout.lowerBound > 0 && layout.lowerBound <= layout.slabCount &&
    layout.slabs.every((slab, i) => slab.index === i + 1 && slab.placements.length > 0) &&
    placed.length === ids.size && new Set(placed).size === ids.size && placed.every(id => ids.has(id))
}))
/** Successful layout kernel result. */
export interface Layout extends Schema.Schema.Type<typeof Layout> {}
/** Layout success and domain failure share a zero process exit status. */
export const LayoutReply = Schema.Union([Layout, KernelFailure])

/** Drawing uses the same geometry, optionally with a solved layout. */
export const DrawInput = Schema.Struct({ slab: Schema.NullOr(Slab), settings: Settings, installations: Schema.Array(Installation), layout: Schema.optionalKey(Layout), geometryEstimates: Schema.optionalKey(GeometryEstimates) })
/** Preview or finished-layout drawing request. */
export interface DrawInput extends Schema.Schema.Type<typeof DrawInput> {}
/** T2's concrete drawing protocol returns the saved PNG path on success. */
export const DrawReply = Schema.Union([Schema.Struct({ ok: Schema.Literal(true), path: Text }), KernelFailure])
/** A kernel selfcheck must affirm that its imports worked. */
export const SelfcheckReply = Schema.Struct({ ok: Schema.Literal(true) })
/** File paths are the input kernel's positional arguments. */
export const InspectInput = Schema.Array(Text).check(Schema.isMinLength(1))
/** Input inspection never silently skips an unreadable picture. */
export const InspectReply = Schema.Struct({ files: Schema.Array(Schema.Struct({
  path: Text, ok: Schema.Boolean, kind: Schema.Literals(["image", "pdf"]),
  pages: Count, previews: Schema.Array(Text), problem: Schema.NullOr(Text),
})) })

/** Persisted output consumed by the agent to prepare an invoice. */
export const Quote = Schema.Struct({
  installations: Schema.Array(Schema.Struct({ id: Text, label: Text, areaSqIn: Decimal, sf: TwoDp, requiredPieceCount: Schema.optionalKey(PieceCount), seam: Schema.optionalKey(CenterJoin) })),
  totalSf: TwoDp, layout: Schema.NullOr(Layout), slabCount: Schema.NullOr(Count), slabSf: Schema.NullOr(Decimal),
  pricing: Schema.Struct({ materialCost: Schema.NullOr(TwoDp), markupPercent: Schema.NullOr(Decimal), materialCharge: Schema.NullOr(TwoDp), materialRatePerSf: Schema.NullOr(TwoDp), laborPerSf: Schema.NullOr(TwoDp), ratePerSf: Schema.NullOr(TwoDp) }),
  invoice: Schema.Array(Schema.Struct({ installation: Text, material: Schema.NullOr(Text), sf: TwoDp, ratePerSf: Schema.NullOr(TwoDp), amount: Schema.NullOr(TwoDp) })),
  blanks: Schema.Array(Schema.Struct({ field: Text, question: Text })),
  assumptions: Schema.Array(Schema.Struct({ setting: Text, value: Schema.String, note: Schema.Literal("assumed, confirm with Dad") })),
  warnings: Schema.Array(Schema.String),
  geometryEstimates: GeometryEstimates,
})
/** Computed quantities, pricing, and the unanswered questions. */
export interface Quote extends Schema.Schema.Type<typeof Quote> {}
