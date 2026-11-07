import { Context, Effect, Layer, Schema, Stream } from "effect"
import { ChildProcess, ChildProcessSpawner } from "effect/process"
import { join, resolve } from "node:path"
import { decodeJson, KernelError } from "./errors"
import { DrawInput, DrawReply, InspectInput, InspectReply, LayoutInput, LayoutReply, SelfcheckReply } from "./schema"

const names = ["layout", "draw_layout", "inspect_input"] as const
type KernelName = typeof names[number]
type Runner = (name: KernelName, args: readonly string[], stdin: string) => Effect.Effect<string, KernelError>

function implementation(run: Runner, tools: Effect.Effect<void, KernelError>) {
  const reply = <A>(schema: Schema.Codec<A, unknown>, stdout: string, name: string) => decodeJson(schema, stdout,
    new KernelError({ message: `The ${name} tool sent an unreadable reply. Ask Rishi to repair the takeoff tools.` }))
  const input = <A>(schema: Schema.Codec<A>, value: A) => Schema.encodeEffect(schema)(value).pipe(
    Effect.map(JSON.stringify),
    Effect.mapError(() => new KernelError({ message: "The takeoff tool received invalid measurements. Ask Rishi to check job.json." })),
  )
  return {
    checkTools: Effect.fn("Kernels.checkTools")(() => tools),
    selfcheck: Effect.fn("Kernels.selfcheck")(function* () {
      for (const name of names) yield* reply(SelfcheckReply, yield* run(name, ["--selfcheck"], ""), name)
    }),
    inspect: Effect.fn("Kernels.inspect")(function* (files: readonly string[]) {
      yield* input(InspectInput, files)
      return yield* reply(InspectReply, yield* run("inspect_input", files, ""), "input")
    }),
    layout: Effect.fn("Kernels.layout")(function* (request: LayoutInput) {
      const result = yield* reply(LayoutReply, yield* run("layout", [], yield* input(LayoutInput, request)), "layout")
      if (!result.ok) return yield* Effect.fail(new KernelError({ message: result.error.message }))
      return result
    }),
    draw: Effect.fn("Kernels.draw")(function* (request: DrawInput, out: string, preview: boolean) {
      const stdout = yield* run("draw_layout", ["--out", out, ...(preview ? ["--preview"] : [])], yield* input(DrawInput, request))
      const result = yield* reply(DrawReply, stdout, "drawing")
      if (!result.ok) return yield* Effect.fail(new KernelError({ message: result.error.message }))
      if (resolve(result.path) !== resolve(out)) return yield* Effect.fail(new KernelError({ message: "The drawing tool saved the picture in the wrong place. Ask Rishi to repair it." }))
    }),
  }
}

/** Python calculations and input inspection, with decoded replies at this boundary. */
export class Kernels extends Context.Service<Kernels, ReturnType<typeof implementation>>()("takeoff/Kernels") {}

/** Build a fake transport with the same schema decoding as the real Python adapter. */
export const kernelLayer = (run: Runner) => Layer.succeed(Kernels, implementation(run, Effect.void))

/** Run bundled PEP 723 kernels through uv, using scoped processes with drained stderr. */
export const liveKernels = (skillDir: string) => Layer.effect(Kernels, Effect.gen(function* () {
  const spawner = yield* ChildProcessSpawner.ChildProcessSpawner
  const execute = Effect.fn("Kernels.execute")(function* (command: string, args: readonly string[], stdin: string, message: string) {
    return yield* Effect.scoped(Effect.gen(function* () {
      const child = yield* spawner.spawn(ChildProcess.make(command, args, {
        stdin: Stream.make(new TextEncoder().encode(stdin)), stdout: "pipe", stderr: "pipe",
      }))
      const [stdout, , code] = yield* Effect.all([
        child.stdout.pipe(Stream.decodeText(), Stream.mkString),
        child.stderr.pipe(Stream.runDrain),
        child.exitCode,
      ], { concurrency: "unbounded" })
      if (code !== 0) return yield* Effect.fail(new KernelError({ message }))
      return stdout
    })).pipe(Effect.mapError(() => new KernelError({ message })))
  })
  const run: Runner = (name, args, stdin) => execute("uv", ["run", join(skillDir, "kernels", `${name}.py`), ...args], stdin,
    `The ${name === "inspect_input" ? "input" : name === "draw_layout" ? "drawing" : "layout"} tool could not run. Ask Rishi to run setup or repair it.`)
  const tools = Effect.gen(function* () {
    for (const tool of ["bun", "uv"]) yield* execute(tool, ["--version"], "",
      `The takeoff tools aren't installed on this laptop (${tool} is missing or won't run). Ask Rishi to run setup.`)
  })
  return Kernels.of(implementation(run, tools))
}))
