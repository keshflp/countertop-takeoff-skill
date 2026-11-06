import { afterEach, expect, test } from "bun:test"
import { BunServices } from "@effect/platform-bun"
import { Effect, Schema } from "effect"
import { mkdtemp, readFile, rm, writeFile, symlink } from "node:fs/promises"
import { tmpdir } from "node:os"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { createHash } from "node:crypto"
import { calculate, prepare, resolveSettings } from "../src/core"
import { decimal, rounded } from "../src/exact"
import { KernelError } from "../src/errors"
import { kernelLayer, Kernels } from "../src/kernels"
import { Job, Layout, Quote } from "../src/schema"
import { takeoff } from "../src/takeoff"
import { workflow } from "../src/workflow"

const skillDir = resolve(dirname(fileURLToPath(import.meta.url)), "../..")
const job = Schema.decodeUnknownSync(Job)({
  version: 1, material: { name: "Quartz", vendor: "Vendor", pricePerSf: "10", slab: { lengthIn: 120, widthIn: 60 } },
  laborPerSf: "7.50", installations: [{ id: "island", label: "Island", shape: { kind: "rect", lengthIn: 60, depthIn: 24 }, cutouts: [] }], settings: {},
})
const layout: Layout = {
  ok: true, pieces: [{ id: "p1", installationId: "island", outline: [[0, 0], [60, 0], [60, 24], [0, 24]] }],
  seams: [], slabs: [{ index: 1, placements: [{ pieceId: "p1", x: 0, y: 0, rotated: false }] }],
  slabCount: 1, lowerBound: 1, provenOptimal: true, warnings: [],
}
const fake = kernelLayer((name, args) => {
  if (args.includes("--selfcheck")) return Effect.succeed('{"ok":true}')
  if (name === "layout") return Effect.succeed(JSON.stringify(layout))
  if (name === "inspect_input") return Effect.succeed(JSON.stringify({ files: args.map(path => ({ path, ok: true, kind: "image", pages: 1, previews: [path], problem: null })) }))
  const out = args[args.indexOf("--out") + 1]
  return Effect.tryPromise({
    try: async () => { if (!out) throw new Error("missing test output path"); await writeFile(out, "fake PNG"); return JSON.stringify({ ok: true, path: out }) },
    catch: () => new KernelError({ message: "Test drawing failed" }),
  })
})
const run = <A, E>(effect: Effect.Effect<A, E, Kernels>) => Effect.runPromise(effect.pipe(Effect.provide(fake)))
function withShape(shape: Job["installations"][number]["shape"], cutouts: Job["installations"][number]["cutouts"] = []): Job {
  return { ...job, installations: [{ id: "perimeter", label: "Perimeter", shape, cutouts }] }
}

test("rect, L on both sides, and U expand into the clockwise outer outlines", async () => {
  const cases = [
    { shape: { kind: "rect", lengthIn: 60, depthIn: 24 }, area: 1440n, outline: [[0, 0], [60, 0], [60, 24], [0, 24]] },
    { shape: { kind: "L", backIn: 120, sideIn: 72, depthIn: 24, side: "left" }, area: 4032n, outline: [[0, 0], [120, 0], [120, 24], [24, 24], [24, 72], [0, 72]] },
    { shape: { kind: "L", backIn: 120, sideIn: 72, depthIn: 24, side: "right" }, area: 4032n, outline: [[0, 0], [120, 0], [120, 72], [96, 72], [96, 24], [0, 24]] },
    { shape: { kind: "U", backIn: 120, leftIn: 72, rightIn: 84, depthIn: 24 }, area: 5472n, outline: [[0, 0], [120, 0], [120, 84], [96, 84], [96, 24], [24, 24], [24, 72], [0, 72]] },
  ] satisfies readonly { shape: Job["installations"][number]["shape"]; area: bigint; outline: readonly (readonly [number, number])[] }[]
  for (const item of cases) {
    const result = await Effect.runPromise(prepare(withShape(item.shape)))
    expect(result.installations[0]?.outline).toEqual(item.outline)
    expect(result.installations[0]?.areaTicks).toBe(item.area * 256n)
  }
})

test("cutouts use outer-start centers on main, back, left, and right legs", async () => {
  const cases = [
    { shape: { kind: "rect", lengthIn: 120, depthIn: 24 }, leg: "main", x: 30, y: 4 },
    { shape: { kind: "L", backIn: 120, sideIn: 72, depthIn: 24, side: "left" }, leg: "back", x: 30, y: 4 },
    { shape: { kind: "L", backIn: 120, sideIn: 72, depthIn: 24, side: "left" }, leg: "left", x: 2, y: 32 },
    { shape: { kind: "L", backIn: 120, sideIn: 72, depthIn: 24, side: "right" }, leg: "right", x: 98, y: 32 },
  ] satisfies readonly { shape: Job["installations"][number]["shape"]; leg: "main" | "back" | "left" | "right"; x: number; y: number }[]
  for (const c of cases) {
    const result = await Effect.runPromise(prepare(withShape(c.shape, [{ kind: "sink", wIn: 20, hIn: 16, at: { leg: c.leg, centerFromStartIn: 40 } }])))
    expect(result.installations[0]?.cutouts[0]).toEqual({ kind: "sink", x: c.x, y: c.y, w: 20, h: 16 })
  }
})

test("outline cutouts use explicit top-left coordinates and must stay inside", async () => {
  const shape = { kind: "outline", points: [[0, 0], [60, 0], [60, 24], [0, 24]] } satisfies Job["installations"][number]["shape"]
  const result = await Effect.runPromise(prepare(withShape(shape, [{ kind: "sink", wIn: 20, hIn: 16, at: { xIn: 10, yIn: 4 } }])))
  expect(result.installations[0]?.cutouts[0]?.x).toBe(10)
  await expect(Effect.runPromise(prepare(withShape(shape, [{ kind: "sink", wIn: 20, hIn: 16, at: { leg: "main", centerFromStartIn: 30 } }])))).rejects.toThrow("xIn and yIn")
  await expect(Effect.runPromise(prepare(withShape({ kind: "rect", lengthIn: 60, depthIn: 24 }, [{ kind: "sink", wIn: 20, hIn: 16, at: { xIn: 50, yIn: 4 } }])))).rejects.toThrow("outside")
  const exact = await Effect.runPromise(prepare(withShape({ kind: "rect", lengthIn: 1.0625, depthIn: 1.0625 })))
  expect(calculate(job, exact, null).installations[0]?.areaSqIn).toBe("1.12890625")
})

test("pricing follows nominal slabs and exact gross SF, with half-up line rounding", async () => {
  // Hand arithmetic: 60*24/144=10 SF. One 120*60/144=50 SF slab at $10
  // costs $500; $500/10=$50 material/SF; +$7.50 labor = $57.50; line=$575.
  const quote = await run(takeoff(job))
  expect(quote.totalSf).toBe("10.00")
  expect(quote.pricing).toEqual({ materialCost: "500.00", materialRatePerSf: "50.00", laborPerSf: "7.50", ratePerSf: "57.50" })
  expect(quote.invoice[0]?.amount).toBe("575.00")
  expect(rounded(decimal("1.005"))).toBe("1.01")
  const precise = { ...job, installations: [{ id: "a", label: "A", shape: { kind: "rect", lengthIn: 1, depthIn: 1 }, cutouts: [] }, { id: "b", label: "B", shape: { kind: "rect", lengthIn: 1, depthIn: 1 }, cutouts: [] }] } satisfies Job
  const q = calculate(precise, await Effect.runPromise(prepare(precise)), layout)
  expect(q.installations.map(i => i.sf)).toEqual(["0.01", "0.01"])
  expect(q.totalSf).toBe("0.01")
  expect(q.pricing.materialRatePerSf).toBe("36000.00")
})

test("every null fact produces one question and only its dependents become null", async () => {
  const missing = { ...job, material: { name: null, vendor: null, pricePerSf: null, slab: null }, laborPerSf: null }
  const quote = await run(takeoff(missing))
  expect(quote.blanks.map(b => b.field)).toEqual(["material.name", "material.vendor", "material.pricePerSf", "material.slab", "laborPerSf"])
  expect(new Set(quote.blanks.map(b => b.field)).size).toBe(5)
  expect(quote.totalSf).toBe("10.00")
  expect(quote.slabCount).toBeNull()
  expect(quote.pricing).toEqual({ materialCost: null, materialRatePerSf: null, laborPerSf: null, ratePerSf: null })
  expect(quote.invoice[0]?.amount).toBeNull()
  const laborMissing = await run(takeoff({ ...job, laborPerSf: null }))
  expect(laborMissing.pricing.materialCost).toBe("500.00")
  expect(laborMissing.pricing.ratePerSf).toBeNull()
  expect(laborMissing.blanks).toEqual([{ field: "laborPerSf", question: "What is the labor price per square foot?" }])
})

test("each omitted setting appears once as assumed; explicit false and zero are retained", () => {
  expect(resolveSettings(job).assumptions).toHaveLength(5)
  expect(resolveSettings(job).assumptions.every(a => a.note === "assumed, confirm with Dad")).toBe(true)
  const resolved = resolveSettings({ ...job, settings: { slabTrimIn: 0, allowRotate: false } })
  expect(resolved.assumptions).toHaveLength(3)
  expect(resolved.settings.slabTrimIn).toBe(0)
  expect(resolved.settings.allowRotate).toBe(false)
})

test("malformed kernel stdout fails at the kernel boundary", async () => {
  for (const reply of ['{"ok":true}', 'not json', '{"ok":true,"slabCount":"1"}']) {
    const broken = kernelLayer(() => Effect.succeed(reply))
    const result = await Effect.runPromise(takeoff(job).pipe(Effect.provide(broken), Effect.flip))
    expect(result._tag).toBe("KernelError")
    expect(result.message).toContain("unreadable reply")
  }
  const broken = kernelLayer(() => Effect.succeed("{}"))
  for (const operation of [
    Kernels.use(k => k.selfcheck()),
    Kernels.use(k => k.inspect(["sketch.png"])),
    Kernels.use(k => k.draw({ slab: null, settings: resolveSettings(job).settings, installations: [] }, "preview.png", true)),
  ]) {
    const failure = await Effect.runPromise(operation.pipe(Effect.provide(broken), Effect.flip))
    expect(failure._tag).toBe("KernelError")
  }
})

const scratch: string[] = []
afterEach(async () => { await Promise.all(scratch.splice(0).map(dir => rm(dir, { recursive: true, force: true }))) })
async function fixture() {
  const root = await mkdtemp(join(tmpdir(), "takeoff-cli-test-"))
  scratch.push(root)
  const dir = join(root, "job")
  const input = join(root, "sketch.png")
  await writeFile(input, "synthetic input")
  const w = await Effect.runPromise(workflow(skillDir).pipe(Effect.provide(fake), Effect.provide(BunServices.layer)))
  return { root, dir, input, w }
}
const execute = <A, E>(effect: Effect.Effect<A, E, Kernels>) => run(effect)

test("quote requires preflight, checked preview and Dad's current confirmation", async () => {
  const { dir, input, w } = await fixture()
  await expect(execute(w.quote(dir))).rejects.toThrow("preflight")
  await execute(w.preflight(dir, [input]))
  await writeFile(join(dir, "job.json"), JSON.stringify(job))
  await expect(execute(w.confirm(dir))).rejects.toThrow("preview")
  await execute(w.check(dir))
  await expect(execute(w.quote(dir))).rejects.toThrow("Dad")
  await execute(w.confirm(dir))
  await execute(w.quote(dir))
  expect(JSON.parse(await readFile(join(dir, "quote.json"), "utf8")).totalSf).toBe("10.00")
  expect(await execute(w.next(dir))).toContain("invoice is ready")
  await writeFile(join(dir, "job.json"), `${JSON.stringify(job)}\n`)
  await expect(execute(w.quote(dir))).rejects.toThrow("changed since Dad")
})

test("changing copied inputs invalidates preflight, and failed reruns clear old success", async () => {
  const { dir, input, w } = await fixture()
  await execute(w.preflight(dir, [input]))
  await writeFile(join(dir, "job.json"), JSON.stringify(job))
  await execute(w.check(dir)); await execute(w.confirm(dir))
  await writeFile(join(dir, "inputs", "1-sketch.png"), "edited")
  await expect(execute(w.quote(dir))).rejects.toThrow("input picture changed")
  await execute(w.preflight(dir, [input]))
  await expect(execute(w.preflight(dir, [join(dir, "missing.png")]))).rejects.toThrow("couldn't copy")
  await expect(execute(w.quote(dir))).rejects.toThrow("preflight")
})

test("private job folders cannot be in the skill repository, including through a junction", async () => {
  const { root, input, w } = await fixture()
  await expect(execute(w.preflight(join(skillDir, "private-job-must-not-be-created"), [input]))).rejects.toThrow("Keep plans outside")
  await expect(execute(w.preflight(join(skillDir, "..", "private-job-must-not-be-created"), [input]))).rejects.toThrow("Keep plans outside")
  const link = join(root, "linked-code")
  await symlink(skillDir, link, "junction")
  await expect(execute(w.preflight(join(link, "private-job-must-not-be-created"), [input]))).rejects.toThrow("Keep plans outside")
  // A separate checkout of the same public repo is equally unsafe for private plans.
  await writeFile(join(root, ".git"), await readFile(resolve(skillDir, "..", ".git")))
  await expect(execute(w.preflight(join(root, "another-checkout-job"), [input]))).rejects.toThrow("Keep plans outside")
})

test("null slabs still save a quote with blanks and a shapes-only picture", async () => {
  const { dir, input, w } = await fixture()
  await execute(w.preflight(dir, [input]))
  await writeFile(join(dir, "job.json"), JSON.stringify({ ...job, material: { ...job.material, slab: null } }))
  await execute(w.check(dir)); await execute(w.confirm(dir)); await execute(w.quote(dir))
  const result = Schema.decodeUnknownSync(Quote)(JSON.parse(await readFile(join(dir, "quote.json"), "utf8")))
  expect(result.layout).toBeNull()
  expect(result.pricing.materialCost).toBeNull()
  expect(result.blanks).toHaveLength(1)
})

test("the committed standalone bundle matches its source", async () => {
  const cliDir = resolve(dirname(fileURLToPath(import.meta.url)), "..")
  const built = await Bun.build({ entrypoints: [join(cliDir, "src", "main.ts")], target: "bun", minify: true })
  expect(built.success).toBe(true)
  const output = built.outputs[0]
  expect(output).toBeDefined()
  if (!output) return
  const digest = (text: string) => createHash("sha256").update(text.replaceAll("\r\n", "\n")).digest("hex")
  expect(digest(await Bun.file(join(cliDir, "takeoff.js")).text())).toBe(digest(await output.text()))
})
