import { BunServices } from "@effect/platform-bun"
import { Cause, Console, Effect } from "effect"
import { Argument, Command } from "effect/cli"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { liveKernels } from "./kernels"
import { workflow } from "./workflow"

// The single-file bundle lives in cli/; the development entry lives in cli/src/.
const here = dirname(fileURLToPath(import.meta.url))
const skillDir = resolve(here, import.meta.url.endsWith(".ts") ? "../.." : "..")
const jobDir = Argument.String("jobDir")
const preflight = Command.make("preflight", { jobDir, inputs: Argument.String("input").pipe(Argument.variadic({ min: 1 })) }, ({ jobDir, inputs }) =>
  workflow(skillDir).pipe(Effect.flatMap(w => w.preflight(jobDir, inputs)), Effect.flatMap(Console.log)))
const commands = (["check", "confirm", "quote", "next"] as const).map(name =>
  Command.make(name, { jobDir }, ({ jobDir }) => workflow(skillDir).pipe(Effect.flatMap(w => w[name](jobDir)), Effect.flatMap(Console.log))))
const cli = Command.make("takeoff").pipe(
  Command.withDescription("Kitchen takeoffs. Keep private jobs in %USERPROFILE%\\Takeoffs\\<job>."),
  Command.withSubcommands([preflight, ...commands]),
)
const program = Effect.catchTags(Command.run(cli, { version: "1.0.0" }), {
  JobError: error => Console.error(error.message).pipe(Effect.tap(() => Effect.sync(() => { process.exitCode = 1 }))),
  FileError: error => Console.error(error.message).pipe(Effect.tap(() => Effect.sync(() => { process.exitCode = 1 }))),
  KernelError: error => Console.error(error.message).pipe(Effect.tap(() => Effect.sync(() => { process.exitCode = 1 }))),
  WorkflowError: error => Console.error(error.message).pipe(Effect.tap(() => Effect.sync(() => { process.exitCode = 1 }))),
}).pipe(
  Effect.provide(liveKernels(skillDir)),
  Effect.provide(BunServices.layer),
)
const exit = await Effect.runPromiseExit(program)
if (exit._tag === "Failure") {
  // CLI parse errors already print usage. Defects get a plain fallback, never a stack trace.
  if (Cause.hasDies(exit.cause)) console.error("The takeoff stopped unexpectedly. Ask Rishi to check the takeoff tools.")
  process.exitCode = 1
}
