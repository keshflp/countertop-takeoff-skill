import { BunServices } from "@effect/platform-bun"
import { Config, Console, Effect } from "effect"
import { fileURLToPath } from "node:url"
import { decodeJson, JobError } from "./errors"
import { liveKernels } from "./kernels"
import { replay } from "./replay-core"
import { LegacyJob } from "./schema"

const program = Effect.gen(function* () {
  const skillDir = yield* Config.String("TAKEOFF_DEV_SKILL_DIR").pipe(Config.withDefault(fileURLToPath(new URL("../../", import.meta.url))))
  const text = yield* Effect.tryPromise({ try: () => Bun.stdin.text(), catch: () => new JobError({ message: "I couldn't read the historical job from standard input." }) })
  const job = yield* decodeJson(LegacyJob, text, new JobError({ message: "Development replay requires a frozen v1 job with explicit nullable prices." }))
  yield* Console.log(JSON.stringify(yield* replay(job).pipe(Effect.provide(liveKernels(skillDir)))))
}).pipe(Effect.provide(BunServices.layer))
const exit = await Effect.runPromiseExit(Effect.catchTags(program, {
  JobError: e => Console.error(e.message).pipe(Effect.tap(() => Effect.sync(() => { process.exitCode = 1 }))),
  KernelError: e => Console.error(e.message).pipe(Effect.tap(() => Effect.sync(() => { process.exitCode = 1 }))),
}))
if (exit._tag === "Failure") {
  console.error("The development replay could not run. Ask Rishi to check its configuration.")
  process.exitCode = 1
}
