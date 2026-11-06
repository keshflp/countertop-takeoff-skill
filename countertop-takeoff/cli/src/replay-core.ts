import { Effect, Schema } from "effect"
import { calculate, prepare } from "./core"
import { JobError, KernelError } from "./errors"
import { originalEdgeWarnings } from "./geometry"
import { Kernels } from "./kernels"
import { Job, LayoutInput, LegacyJob, Quote } from "./schema"
import { replyIssue } from "./validate"

const ReplayQuote = Schema.Struct({ ...Quote.fields, developmentOnly: Schema.Literal("geometry-replay-unassessed") })

/** Historical geometry evidence only. This module is never imported by the shipped CLI. */
export const replay = Effect.fn("Development.replay")(function* (old: Schema.Schema.Type<typeof LegacyJob>) {
  const { minSeamToCutoutIn = 3, minMaterialBesideCutoutIn = 2, ...settings } = old.settings
  const job: Job = { ...old, version: 2, settings,
    material: { ...old.material, profileId: null, profileProvenance: null, nominalThicknessMm: null },
    installations: old.installations.map(i => ({ ...i, insideCornerRadiusMm: null, sourceArrangement: null, conditions: [],
      cutouts: i.cutouts.map(c => ({ ...c, radiusMm: null, mount: null })) })),
  }
  const prepared = yield* prepare(job)
  const kernels = yield* Kernels
  const request: LayoutInput = { version: 2, mode: "geometry-replay", phase: "plan",
    material: { profileId: null, profileProvenance: null, nominalThicknessMm: null }, slab: job.material.slab,
    installations: prepared.kernelInstallations, settings: prepared.settings, legacySettings: { minSeamToCutoutIn, minMaterialBesideCutoutIn } }
  const result = yield* kernels.layout(request)
  const issue = replyIssue(request, result)
  if (issue !== null) return yield* Effect.fail(new KernelError({ message: `The development replay reply could not be accepted: ${issue}.` }))
  const quote = calculate(job, prepared, result)
  return yield* Schema.decodeUnknownEffect(ReplayQuote)({ ...quote, developmentOnly: "geometry-replay-unassessed",
    warnings: [...quote.warnings, ...originalEdgeWarnings(prepared.kernelInstallations, { minMaterialBesideCutoutIn })],
  }).pipe(Effect.mapError(() => new JobError({ message: "The development replay quote could not be checked." })))
})
