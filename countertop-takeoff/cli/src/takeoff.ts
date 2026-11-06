import { Effect, Schema } from "effect"
import { calculate, prepare } from "./core"
import { JobError, KernelError } from "./errors"
import { Kernels } from "./kernels"
import { Job, Quote } from "./schema"

/** Shared quote pipeline; the evaluator bypasses only the interactive workflow and drawing. */
export const takeoff = Effect.fn("Takeoff.quote")(function* (job: Job) {
  const prepared = yield* prepare(job)
  const kernels = yield* Kernels
  const layout = job.material.slab === null ? null : yield* kernels.layout({
    slab: job.material.slab, settings: prepared.settings,
    installations: prepared.kernelInstallations,
  })
  if (layout !== null) {
    const ids = new Set(job.installations.map(i => i.id))
    if (layout.pieces.some(piece => !ids.has(piece.installationId))) return yield* Effect.fail(new KernelError({ message: "The layout tool returned pieces for an unknown installation. Ask Rishi to repair it." }))
    for (const installation of job.installations) {
      const count = layout.pieces.filter(piece => piece.installationId === installation.id).length
      if (count === 0 || (installation.requiredPieceCount !== undefined && count !== installation.requiredPieceCount)) return yield* Effect.fail(new KernelError({
        message: `${installation.label} needs ${installation.requiredPieceCount === undefined ? "at least one" : `exactly ${installation.requiredPieceCount}`} cut piece(s), but the layout returned ${count}. Ask Rishi to check the layout tool.`,
      }))
    }
  }
  const quote = calculate(job, prepared, layout)
  return yield* Schema.decodeUnknownEffect(Quote)(quote).pipe(Effect.mapError(() =>
    new JobError({ message: "The quote could not be checked. Ask Rishi to check the takeoff calculations." })))
})
