import { Effect } from "effect"
import { add, areaDecimal, decimal, multiply, rounded } from "./exact"
import { expand } from "./geometry"
import type { Job, Layout, Quote, Settings } from "./schema"

const defaults: Settings = { slabTrimIn: 1, kerfIn: 0.25, minSeamToCutoutIn: 6, minMaterialBesideCutoutIn: 3, allowRotate: true }

/** Resolve defaults once and retain exactly which choices need Dad's confirmation. */
export function resolveSettings(job: Job) {
  const settings = { ...defaults, ...job.settings }
  const keys = ["slabTrimIn", "kerfIn", "minSeamToCutoutIn", "minMaterialBesideCutoutIn", "allowRotate"] as const
  const assumptions: Quote["assumptions"] = keys
    .filter(key => job.settings[key] === undefined)
    .map(key => ({ setting: key, value: String(settings[key]), note: "assumed, confirm with Dad" }))
  return { settings, assumptions }
}

/** Expand geometry for both the evaluator and the interactive workflow. */
export const prepare = Effect.fn("Takeoff.prepare")(function* (job: Job) {
  const installations = yield* expand(job)
  const { settings, assumptions } = resolveSettings(job)
  const kernelInstallations = installations.map(({ label: _label, areaTicks: _area, geometryEstimates: _estimates, ...installation }) => installation)
  return { installations, kernelInstallations, settings, assumptions, geometryEstimates: installations.flatMap(i => i.geometryEstimates) }
})

/** Exact gross quantities and invoice arithmetic, independent of files and Python. */
export function calculate(job: Job, prepared: Effect.Success<ReturnType<typeof prepare>>, layout: Layout | null): Quote {
  const installations = prepared.installations.map(i => ({ id: i.id, label: i.label, areaSqIn: areaDecimal({ n: i.areaTicks, d: 256n }), sf: rounded({ n: i.areaTicks, d: 36864n }), ...(i.requiredPieceCount === undefined ? {} : { requiredPieceCount: i.requiredPieceCount }) }))
  const totalTicks = prepared.installations.reduce((sum, i) => sum + i.areaTicks, 0n)
  const slab = job.material.slab
  const slabArea = slab === null ? null : { n: BigInt(slab.lengthIn * 16) * BigInt(slab.widthIn * 16), d: 36864n }
  const cost = slabArea === null || layout === null || job.material.pricePerSf === null ? null
    : multiply(multiply(slabArea, { n: BigInt(layout.slabCount), d: 1n }), decimal(job.material.pricePerSf))
  // Divide the unrounded slab cost by exact gross job SF, then round the rate.
  const materialRatePerSf = cost === null ? null : rounded({ n: cost.n * 36864n, d: cost.d * totalTicks })
  const laborPerSf = job.laborPerSf === null ? null : rounded(decimal(job.laborPerSf))
  const ratePerSf = materialRatePerSf === null || job.laborPerSf === null ? null : rounded(add(decimal(materialRatePerSf), decimal(job.laborPerSf)))
  const questions = [
    { field: "material.name", value: job.material.name, question: "What is the material name?" },
    { field: "material.vendor", value: job.material.vendor, question: "Who is the material vendor?" },
    { field: "material.pricePerSf", value: job.material.pricePerSf, question: "What is the material price per square foot?" },
    { field: "material.slab", value: slab, question: "What are the slab length and width in inches?" },
    { field: "laborPerSf", value: job.laborPerSf, question: "What is the labor price per square foot?" },
  ]
  return {
    installations, totalSf: rounded({ n: totalTicks, d: 36864n }), layout,
    slabCount: layout?.slabCount ?? null, slabSf: slabArea === null ? null : areaDecimal(slabArea),
    pricing: { materialCost: cost === null ? null : rounded(cost), materialRatePerSf, laborPerSf, ratePerSf },
    invoice: installations.map(i => ({ installation: i.label, material: job.material.name, sf: i.sf, ratePerSf, amount: ratePerSf === null ? null : rounded(multiply(decimal(i.sf), decimal(ratePerSf))) })),
    blanks: questions.filter(q => q.value === null).map(({ field, question }) => ({ field, question })),
    assumptions: [...prepared.assumptions,
      { setting: "grossSf", value: "cutouts are not subtracted", note: "assumed, confirm with Dad" },
      { setting: "nominalSlabSf", value: "slab pricing uses the full untrimmed size", note: "assumed, confirm with Dad" },
      { setting: "shapeRules", value: "outer wall lengths; uniform depth; cutouts centered in their leg", note: "assumed, confirm with Dad" }],
    warnings: layout?.warnings ?? [],
    geometryEstimates: prepared.geometryEstimates,
  }
}
