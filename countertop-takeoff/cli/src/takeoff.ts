import { Effect, Schema } from "effect"
import { calculate, prepare } from "./core"
import { JobError } from "./errors"
import { Kernels } from "./kernels"
import { Job, Quote } from "./schema"

/** Shared quote pipeline; the evaluator bypasses only the interactive workflow and drawing. */
export const takeoff = Effect.fn("Takeoff.quote")(function* (job: Job) {
  const prepared = yield* prepare(job)
  const kernels = yield* Kernels
  const layout = job.material.slab === null ? null : yield* kernels.layout({
    slab: job.material.slab, settings: prepared.settings,
    installations: prepared.installations.map(({ id, outline, cutouts }) => ({ id, outline, cutouts })),
  })
  const quote = calculate(job, prepared, layout)
  return yield* Schema.decodeUnknownEffect(Quote)(quote).pipe(Effect.mapError(() =>
    new JobError({ message: "The quote could not be checked. Ask Rishi to check the takeoff calculations." })))
})
