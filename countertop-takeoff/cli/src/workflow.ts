import { Clock, Effect, FileSystem, Path, Schema } from "effect"
import { createHash } from "node:crypto"
import { homedir } from "node:os"
import { calculate, prepare } from "./core"
import { decodeJson, FileError, WorkflowError } from "./errors"
import { Kernels } from "./kernels"
import { Job, Quote } from "./schema"
import { takeoff } from "./takeoff"

const Hash = Schema.String.check(Schema.isPattern(/^[a-f0-9]{64}$/))
const Preflight = Schema.Struct({
  version: Schema.Literal(1), ok: Schema.Literal(true), checkedAt: Schema.Number,
  inputs: Schema.Array(Schema.Struct({ path: Schema.String, sha256: Hash })).check(Schema.isMinLength(1)),
})
const Checked = Schema.Struct({ jobHash: Hash, preflightHash: Hash, previewHash: Hash })
const Confirmed = Schema.Struct({ ...Checked.fields, confirmed: Schema.Literal(true) })
const Quoted = Schema.Struct({ jobHash: Hash, preflightHash: Hash, quoteHash: Hash, layoutHash: Hash })
const hash = (data: string | Uint8Array) => createHash("sha256").update(data).digest("hex")

/** Owns persisted step order; the concrete kernel Layer is chosen only by the entrypoint. */
export const workflow = Effect.fn("Workflow.make")(function* (skillDir: string) {
  const fs = yield* FileSystem.FileSystem
  const path = yield* Path.Path
  const kernels = yield* Kernels
  const io = <A, E, R>(effect: Effect.Effect<A, E, R>, message: string) => effect.pipe(Effect.mapError(() => new FileError({ message })))
  const read = (file: string) => io(fs.readFileString(file), `I couldn't read ${path.basename(file)}. Please check that it is saved in the job folder.`)
  const fingerprint = (file: string) => io(fs.readFile(file), `I couldn't read ${path.basename(file)}. Please run preflight again.`).pipe(Effect.map(hash))
  const exists = (file: string) => io(fs.exists(file), `I couldn't open the job folder. Please check its location.`)
  const write = Effect.fn("Workflow.write")(function* (file: string, value: unknown) {
    // Atomic replacement prevents an interrupted write from leaving valid-looking partial state.
    yield* io(fs.remove(`${file}.tmp`, { force: true }), `I couldn't prepare ${path.basename(file)} for saving.`)
    yield* io(fs.writeFileString(`${file}.tmp`, `${JSON.stringify(value, null, 2)}\n`, { flag: "wx" }), `I couldn't save ${path.basename(file)}. Check that the job folder can be written to.`)
    yield* io(fs.rename(`${file}.tmp`, file), `I couldn't finish saving ${path.basename(file)}. Close that file and try again.`)
  })
  const saved = <A>(schema: Schema.Codec<A, unknown>, file: string, message: string) => read(file).pipe(
    Effect.flatMap(text => decodeJson(schema, text, new WorkflowError({ message }))),
  )
  const canonical = Effect.fn("Workflow.canonical")(function* (target: string) {
    const tail: string[] = []
    let cursor = path.resolve(target)
    while (!(yield* exists(cursor))) {
      const parent = path.dirname(cursor)
      if (parent === cursor) return yield* Effect.fail(new FileError({ message: "I couldn't find the job folder's drive. Please check its location." }))
      tail.unshift(path.basename(cursor)); cursor = parent
    }
    return path.join(yield* io(fs.realPath(cursor), "I couldn't check the job folder's location."), ...tail)
  })
  const inside = (root: string, target: string) => {
    const relative = path.relative(root, target)
    return relative === "" || (relative !== ".." && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative))
  }
  const repository = Effect.fn("Workflow.repository")(function* (directory: string) {
    let cursor = directory
    while (true) {
      const marker = path.join(cursor, ".git")
      if (yield* exists(marker)) {
        const info = yield* io(fs.stat(marker), "I couldn't check whether the job folder keeps plans private.")
        let metadata = marker
        if (info.type !== "Directory") {
          const match = /^gitdir:\s*(.+)$/m.exec((yield* read(marker)).trim())
          if (!match?.[1]) return yield* Effect.fail(new WorkflowError({ message: "I couldn't check this code folder. Choose a fresh private job folder under Takeoffs." }))
          metadata = path.resolve(cursor, match[1].trim())
        }
        const commonFile = path.join(metadata, "commondir")
        const common = yield* canonical((yield* exists(commonFile)) ? path.resolve(metadata, (yield* read(commonFile)).trim()) : metadata)
        return { root: cursor, common }
      }
      const parent = path.dirname(cursor)
      if (parent === cursor) return null
      cursor = parent
    }
  })
  const privateDir = Effect.fn("Workflow.privateDir")(function* (jobDir: string) {
    const target = yield* canonical(jobDir)
    const skill = yield* canonical(skillDir)
    const ownRepo = yield* repository(skill)
    const targetRepo = yield* repository(target)
    if (inside(ownRepo?.root ?? skill, target) || (ownRepo !== null && targetRepo?.common === ownRepo.common)) return yield* Effect.fail(new WorkflowError({
      message: `Keep plans outside the takeoff code folder so they stay private. Use ${path.join(homedir(), "Takeoffs", "<job>")} for this job.`,
    }))
    return target
  })
  const preflightState = Effect.fn("Workflow.preflightState")(function* (dir: string) {
    const file = path.join(dir, "preflight.json")
    const message = "Run preflight with the current input pictures before continuing."
    if (!(yield* exists(file))) return yield* Effect.fail(new WorkflowError({ message }))
    const state = yield* saved(Preflight, file, message)
    for (const input of state.inputs) {
      if (!inside(path.join(dir, "inputs"), path.resolve(input.path)) || !(yield* exists(input.path)) || (yield* fingerprint(input.path)) !== input.sha256) {
        return yield* Effect.fail(new WorkflowError({ message: "An input picture changed or is missing. Run preflight again with the current pictures." }))
      }
    }
    return yield* fingerprint(file)
  })
  const jobState = Effect.fn("Workflow.jobState")(function* (dir: string) {
    const text = yield* read(path.join(dir, "job.json"))
    const job = yield* decodeJson(Job, text, new WorkflowError({ message: "Some job details are missing or invalid. Ask the agent to check job.json against the sketch and use null for unanswered facts." }))
    return { job, jobHash: hash(text) }
  })
  const currentCheck = Effect.fn("Workflow.currentCheck")(function* (dir: string, jobHash: string, preflightHash: string) {
    const file = path.join(dir, "check.json")
    const message = "Run check and show Dad the current preview before recording his yes."
    if (!(yield* exists(file))) return yield* Effect.fail(new WorkflowError({ message }))
    const state = yield* saved(Checked, file, message)
    if (state.jobHash !== jobHash || state.preflightHash !== preflightHash || !(yield* exists(path.join(dir, "preview.png"))) || state.previewHash !== (yield* fingerprint(path.join(dir, "preview.png")))) {
      return yield* Effect.fail(new WorkflowError({ message }))
    }
    return state
  })
  const confirmation = Effect.fn("Workflow.confirmation")(function* (dir: string, jobHash: string, preflightHash: string) {
    const file = path.join(dir, "confirm.json")
    const message = "Show Dad the current preview, get his yes, then run confirm before quoting."
    if (!(yield* exists(file))) return yield* Effect.fail(new WorkflowError({ message }))
    const state = yield* saved(Confirmed, file, message)
    if (state.jobHash !== jobHash || state.preflightHash !== preflightHash) return yield* Effect.fail(new WorkflowError({ message: "The job or its inputs changed since Dad said yes. Run check, show him the new preview, and confirm again." }))
    const checked = yield* currentCheck(dir, jobHash, preflightHash)
    if (state.previewHash !== checked.previewHash) return yield* Effect.fail(new WorkflowError({ message }))
  })

  return {
    preflight: Effect.fn("Workflow.preflight")(function* (jobDir: string, inputs: readonly string[]) {
      const dir = yield* privateDir(jobDir)
      if (inputs.length === 0) return yield* Effect.fail(new WorkflowError({ message: "Give preflight the kitchen sketch or plan files to check." }))
      // Clear old success before trying anything that can fail.
      yield* io(fs.makeDirectory(dir, { recursive: true }), "I couldn't create the private job folder.")
      for (const name of ["preflight.json", "check.json", "confirm.json", "quoted.json"]) {
        yield* io(fs.remove(path.join(dir, name), { force: true }), "I couldn't clear the previous run. Close files in the job folder and try again.")
      }
      yield* kernels.checkTools()
      yield* kernels.selfcheck()
      const inputDir = path.join(dir, "inputs")
      if ((yield* canonical(inputDir)) !== inputDir) return yield* Effect.fail(new WorkflowError({ message: "The input folder points somewhere else. Use a fresh private job folder." }))
      yield* io(fs.makeDirectory(inputDir, { recursive: true }), "I couldn't create the private input folder.")
      const copied = yield* Effect.forEach(inputs, (source, i) => Effect.gen(function* () {
        const destination = path.join(inputDir, `${i + 1}-${path.basename(source)}`)
        if ((yield* canonical(destination)) !== destination) return yield* Effect.fail(new WorkflowError({ message: "An input file points somewhere else. Use a fresh private job folder." }))
        yield* io(fs.copyFile(path.resolve(source), destination), `I couldn't copy ${path.basename(source)}. Please check that the picture is readable.`)
        return { path: destination, sha256: yield* fingerprint(destination) }
      }))
      const inspected = yield* kernels.inspect(copied.map(i => i.path))
      if (inspected.files.length !== copied.length || inspected.files.some((file, i) => path.resolve(file.path) !== copied[i]?.path)) {
        return yield* Effect.fail(new WorkflowError({ message: "The input tool didn't check every picture. Ask Rishi to repair it." }))
      }
      const unreadable = inspected.files.find(file => !file.ok)
      if (unreadable) return yield* Effect.fail(new WorkflowError({ message: unreadable.problem ?? "I couldn't read one of the pictures. Please send a clearer copy." }))
      yield* write(path.join(dir, "preflight.json"), { version: 1, ok: true, checkedAt: yield* Clock.currentTimeMillis, inputs: copied })
      yield* write(path.join(dir, "inputs.json"), inspected)
      return `The tools and ${copied.length} input file(s) are ready. Read the pictures and save Dad's facts in job.json.`
    }),
    check: Effect.fn("Workflow.check")(function* (jobDir: string) {
      const dir = yield* privateDir(jobDir)
      const preflightHash = yield* preflightState(dir)
      const { job, jobHash } = yield* jobState(dir)
      const prepared = yield* prepare(job)
      yield* kernels.draw({ slab: job.material.slab, settings: prepared.settings, installations: prepared.installations.map(({ id, outline, cutouts }) => ({ id, outline, cutouts })) }, path.join(dir, "preview.png"), true)
      yield* write(path.join(dir, "check.json"), { jobHash, preflightHash, previewHash: yield* fingerprint(path.join(dir, "preview.png")) })
      const lines = job.installations.map(i => {
        const s = i.shape
        const size = s.kind === "rect" ? `${s.lengthIn} by ${s.depthIn} inches`
          : s.kind === "L" ? `back ${s.backIn}, ${s.side} side ${s.sideIn}, depth ${s.depthIn} inches`
          : s.kind === "U" ? `left ${s.leftIn}, back ${s.backIn}, right ${s.rightIn}, depth ${s.depthIn} inches`
          : `corners ${s.points.map(p => `(${p.join(", ")})`).join(" ")} inches`
        return `${i.label}: ${s.kind}, ${size}. ${i.cutouts.length ? i.cutouts.map(c => `${c.kind} ${c.wIn} by ${c.hIn} inches, ${"leg" in c.at ? `${c.at.leg} leg center ${c.at.centerFromStartIn} inches from its outer start` : `top-left (${c.at.xIn}, ${c.at.yIn}) inches`}`).join("; ") : "No cutouts"}.`
      })
      const readback = calculate(job, prepared, null)
      return [...lines, `Material: ${job.material.name ?? "blank"}; vendor: ${job.material.vendor ?? "blank"}; price/SF: ${job.material.pricePerSf ?? "blank"}; slab: ${job.material.slab ? `${job.material.slab.lengthIn} by ${job.material.slab.widthIn} inches` : "blank"}; labor/SF: ${job.laborPerSf ?? "blank"}.`,
        ...readback.assumptions.map(a => `${a.setting}: ${a.value}, ${a.note}.`),
        ...readback.blanks.map(b => b.question), "Show Dad preview.png and this readback. Run confirm only after he says yes."].join("\n")
    }),
    confirm: Effect.fn("Workflow.confirm")(function* (jobDir: string) {
      const dir = yield* privateDir(jobDir)
      const preflightHash = yield* preflightState(dir)
      const { jobHash } = yield* jobState(dir)
      const state = yield* currentCheck(dir, jobHash, preflightHash)
      yield* write(path.join(dir, "confirm.json"), { ...state, confirmed: true })
      return "Dad's yes is recorded for these exact job details. Next, run quote."
    }),
    quote: Effect.fn("Workflow.quote")(function* (jobDir: string) {
      const dir = yield* privateDir(jobDir)
      const preflightHash = yield* preflightState(dir)
      const { job, jobHash } = yield* jobState(dir)
      yield* confirmation(dir, jobHash, preflightHash)
      const quote = yield* takeoff(job)
      const prepared = yield* prepare(job)
      yield* kernels.draw({ slab: job.material.slab, settings: prepared.settings, installations: prepared.installations.map(({ id, outline, cutouts }) => ({ id, outline, cutouts })), ...(quote.layout === null ? {} : { layout: quote.layout }) }, path.join(dir, "layout.png"), quote.layout === null)
      // Refuse to publish if the facts or inputs changed while Python was running.
      if ((yield* preflightState(dir)) !== preflightHash || (yield* jobState(dir)).jobHash !== jobHash) return yield* Effect.fail(new WorkflowError({ message: "The job changed while quoting. Run check and confirm again." }))
      yield* write(path.join(dir, "quote.json"), quote)
      yield* write(path.join(dir, "quoted.json"), { jobHash, preflightHash, quoteHash: yield* fingerprint(path.join(dir, "quote.json")), layoutHash: yield* fingerprint(path.join(dir, "layout.png")) })
      return [`${quote.totalSf} SF; slabs: ${quote.slabCount ?? "blank"}; material cost: ${quote.pricing.materialCost === null ? "blank" : `$${quote.pricing.materialCost}`}; rate/SF including labor: ${quote.pricing.ratePerSf ?? "blank"}.`, `Saved quote.json and layout.png.${quote.layout === null ? " The picture shows the shapes; slab layout needs the slab size." : ""}`, ...quote.blanks.map(b => b.question), ...quote.warnings].join("\n")
    }),
    next: Effect.fn("Workflow.next")(function* (jobDir: string) {
      const dir = yield* privateDir(jobDir)
      const step = Effect.gen(function* () {
        const preflightHash = yield* preflightState(dir)
        if (!(yield* exists(path.join(dir, "job.json")))) return "Read the checked pictures and save Dad's facts in job.json."
        const { job, jobHash } = yield* jobState(dir)
        yield* currentCheck(dir, jobHash, preflightHash)
        yield* confirmation(dir, jobHash, preflightHash)
        const quotedFile = path.join(dir, "quoted.json")
        if (!(yield* exists(quotedFile))) return "Run quote to calculate the takeoff and draw the slab layout."
        const quoted = yield* saved(Quoted, quotedFile, "Run quote to refresh the takeoff.")
        if (quoted.jobHash !== jobHash || quoted.preflightHash !== preflightHash || !(yield* exists(path.join(dir, "quote.json"))) || !(yield* exists(path.join(dir, "layout.png"))) || quoted.quoteHash !== (yield* fingerprint(path.join(dir, "quote.json"))) || quoted.layoutHash !== (yield* fingerprint(path.join(dir, "layout.png")))) return "Run quote to refresh the takeoff."
        const quote = yield* saved(Quote, path.join(dir, "quote.json"), "Run quote to refresh the takeoff.")
        return quote.blanks[0]?.question ?? `Show Dad the ${job.material.name} quote and layout.png; the invoice is ready to prepare.`
      })
      return yield* step.pipe(Effect.catch(error => Effect.succeed(error.message)))
    }),
  }
})
