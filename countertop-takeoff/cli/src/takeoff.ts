import { Effect, Schema } from "effect"
import { calculate, prepare } from "./core"
import { JobError, KernelError } from "./errors"
import { Kernels } from "./kernels"
import { Job, LayoutInput, Quote } from "./schema"
import { replyIssue } from "./validate"

/** Shared normal v2 path, including source assessment when no stock/profile is known. */
export const takeoff = Effect.fn("Takeoff.quote")(function* (job: Job, phase: LayoutInput["phase"] = "plan") {
  const prepared = yield* prepare(job)
  const kernels = yield* Kernels
  const { profileId, profileProvenance, nominalThicknessMm } = job.material
  const request: LayoutInput = { version: 2, mode: "assessment", phase,
    material: { profileId, profileProvenance, nominalThicknessMm }, slab: job.material.slab,
    settings: prepared.settings, installations: prepared.kernelInstallations }
  const result = yield* kernels.layout(request)
  const issue = replyIssue(request, result)
  if (issue !== null) return yield* Effect.fail(new KernelError({ message: `The layout tool's reply could not be accepted: ${issue}. Ask Rishi to check the takeoff tools.` }))
  return yield* Schema.decodeUnknownEffect(Quote)(calculate(job, prepared, result)).pipe(Effect.mapError(() =>
    new JobError({ message: "The quote could not be checked. Ask Rishi to check the takeoff calculations." })))
})
