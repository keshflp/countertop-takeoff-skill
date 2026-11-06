import { BunServices } from "@effect/platform-bun"
import { Config, Console, Effect } from "effect"
import { fileURLToPath } from "node:url"
import { decodeJson, JobError } from "./errors"
import { liveKernels } from "./kernels"
import { Job } from "./schema"
import { takeoff } from "./takeoff"

// Dev-only override lets the evaluator call a detached sibling checkout's kernels.
const program = Effect.gen(function* () {
  const skillDir = yield* Config.String("TAKEOFF_DEV_SKILL_DIR").pipe(Config.withDefault(fileURLToPath(new URL("../../", import.meta.url))))
  const text = yield* Effect.tryPromise({ try: () => Bun.stdin.text(), catch: () => new JobError({ message: "I couldn't read job.json from standard input." }) })
  const job = yield* decodeJson(Job, text, new JobError({ message: "job.json has missing or invalid facts. Please check the sketch and use null for unanswered facts." }))
  const quote = yield* takeoff(job).pipe(Effect.provide(liveKernels(skillDir)))
  yield* Console.log(JSON.stringify(quote))
}).pipe(Effect.provide(BunServices.layer))
const exit = await Effect.runPromiseExit(Effect.catchTags(program, {
  JobError: error => Console.error(error.message).pipe(Effect.tap(() => Effect.sync(() => { process.exitCode = 1 }))),
  KernelError: error => Console.error(error.message).pipe(Effect.tap(() => Effect.sync(() => { process.exitCode = 1 }))),
}))
if (exit._tag === "Failure") {
  console.error("The evaluator could not run. Ask Rishi to check its configuration.")
  process.exitCode = 1
}
