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
import { DrawInput, Job, Layout, LayoutInput, Quote } from "../src/schema"
import { takeoff } from "../src/takeoff"
import { workflow } from "../src/workflow"

const skillDir = resolve(dirname(fileURLToPath(import.meta.url)), "../..")
const job = Schema.decodeUnknownSync(Job)({
  version: 1, material: { name: "Quartz", vendor: "Vendor", pricePerSf: "10", markupPercent: "0", slab: { lengthIn: 120, widthIn: 60 } },
  laborPerSf: "7.50", installations: [{ id: "island", label: "Island", shape: { kind: "rect", lengthIn: 60, depthIn: 24 }, cutouts: [] }], settings: {},
})
const layout: Layout = {
  ok: true, pieces: [{ id: "p1", installationId: "island", outline: [[0, 0], [60, 0], [60, 24], [0, 24]] }],
  seams: [], slabs: [{ index: 1, placements: [{ pieceId: "p1", x: 0, y: 0, rotated: false }] }],
  slabCount: 1, lowerBound: 1, provenOptimal: true, warnings: [],
}
const fakeTransport: Parameters<typeof kernelLayer>[0] = (name, args) => {
  if (args.includes("--selfcheck")) return Effect.succeed('{"ok":true}')
  if (name === "layout") return Effect.succeed(JSON.stringify(layout))
  if (name === "inspect_input") return Effect.succeed(JSON.stringify({ files: args.map(path => ({ path, ok: true, kind: "image", pages: 1, previews: [path], problem: null })) }))
  const out = args[args.indexOf("--out") + 1]
  return Effect.tryPromise({
    try: async () => { if (!out) throw new Error("missing test output path"); await writeFile(out, "fake PNG"); return JSON.stringify({ ok: true, path: out }) },
    catch: () => new KernelError({ message: "Test drawing failed" }),
  })
}
const fake = kernelLayer(fakeTransport)
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
  expect(quote.pricing).toEqual({ materialCost: "500.00", markupPercent: "0", materialCharge: "500.00", materialRatePerSf: "50.00", laborPerSf: "7.50", ratePerSf: "57.50" })
  expect(quote.invoice[0]?.amount).toBe("575.00")
  expect(rounded(decimal("1.005"))).toBe("1.01")
  const precise = { ...job, installations: [{ id: "a", label: "A", shape: { kind: "rect", lengthIn: 1, depthIn: 1 }, cutouts: [] }, { id: "b", label: "B", shape: { kind: "rect", lengthIn: 1, depthIn: 1 }, cutouts: [] }] } satisfies Job
  const q = calculate(precise, await Effect.runPromise(prepare(precise)), layout)
  expect(q.installations.map(i => i.sf)).toEqual(["0.01", "0.01"])
  expect(q.totalSf).toBe("0.01")
  expect(q.pricing.materialRatePerSf).toBe("36000.00")
})

test("every null fact produces one question and only its dependents become null", async () => {
  const missing = { ...job, material: { name: null, vendor: null, pricePerSf: null, markupPercent: null, slab: null }, laborPerSf: null }
  const quote = await run(takeoff(missing))
  expect(quote.blanks.map(b => b.field)).toEqual(["material.name", "material.vendor", "material.pricePerSf", "material.markupPercent", "material.slab", "laborPerSf"])
  expect(new Set(quote.blanks.map(b => b.field)).size).toBe(6)
  expect(quote.totalSf).toBe("10.00")
  expect(quote.slabCount).toBeNull()
  expect(quote.pricing).toEqual({ materialCost: null, markupPercent: null, materialCharge: null, materialRatePerSf: null, laborPerSf: null, ratePerSf: null })
  expect(quote.invoice[0]?.amount).toBeNull()
  const laborMissing = await run(takeoff({ ...job, laborPerSf: null }))
  expect(laborMissing.pricing.materialCost).toBe("500.00")
  expect(laborMissing.pricing.ratePerSf).toBeNull()
  expect(laborMissing.blanks).toEqual([{ field: "laborPerSf", question: "What is the labor price per square foot?" }])
})

test("markup uses unrounded purchased material before the rate, and never marks up labor", async () => {
  // 50 slab SF * $1.0011 = $50.055 supplier cost. At 12.5%: $56.311875;
  // /10 job SF = $5.6311875 -> $5.63, +$7.50 labor = $13.13, line=$131.30.
  // Marking up the rounded $5.01 material rate would wrongly produce $5.64.
  const marked = { ...job, material: { ...job.material, pricePerSf: "1.0011", markupPercent: "12.5" } }
  const quote = await run(takeoff(marked))
  expect(quote.pricing).toEqual({ materialCost: "50.06", markupPercent: "12.5", materialCharge: "56.31", materialRatePerSf: "5.63", laborPerSf: "7.50", ratePerSf: "13.13" })
  expect(quote.invoice[0]?.amount).toBe("131.30")
  const blank = await run(takeoff({ ...marked, material: { ...marked.material, markupPercent: null } }))
  expect(blank.pricing).toEqual({ materialCost: "50.06", markupPercent: null, materialCharge: null, materialRatePerSf: null, laborPerSf: "7.50", ratePerSf: null })
  expect(blank.invoice[0]?.amount).toBeNull()
  expect(blank.totalSf).toBe("10.00")
  expect(blank.slabCount).toBe(1)
  expect(blank.blanks.map(b => b.field)).toEqual(["material.markupPercent"])
  const { markupPercent: _omitted, ...oldMaterial } = marked.material
  expect(() => Schema.decodeUnknownSync(Job)({ ...marked, material: oldMaterial })).toThrow()
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

test("centered estimates survive quote and drawing while exact cut-piece counts are enforced", async () => {
  const estimate = { fields: ["wIn", "hIn", "at"], note: "Owner authorized these synthetic opening estimates for this test." } satisfies NonNullable<Job["installations"][number]["cutouts"][number]["estimate"]>
  const centered = { ...job, installations: [{ id: "island", label: "Island", shape: { kind: "rect", lengthIn: 100, depthIn: 24 }, requiredPieceCount: 2, seam: { kind: "center-through-cutout", cutoutIndex: 0 },
    cutouts: [{ kind: "sink", wIn: 20, hIn: 16, at: { leg: "main", centerFromStartIn: "center" }, estimate }] }] } satisfies Job
  const expected = [{ installationId: "island", cutoutIndex: 0, ...estimate, xIn: 40, yIn: 4, wIn: 20, hIn: 16 }]
  const prepared = await Effect.runPromise(prepare(centered))
  expect(prepared.geometryEstimates).toEqual(expected)
  const numeric = { ...centered, installations: centered.installations.map(i => ({ ...i, cutouts: i.cutouts.map(c => ({ ...c, at: { leg: "main", centerFromStartIn: 50 } })) })) } satisfies Job
  expect((await Effect.runPromise(prepare(numeric))).kernelInstallations).toEqual(prepared.kernelInstallations)
  const twoPieces: Layout = { ...layout,
    pieces: [{ id: "p1", installationId: "island", outline: [[0, 0], [50, 0], [50, 24], [0, 24]] }, { id: "p2", installationId: "island", outline: [[50, 0], [100, 0], [100, 24], [50, 24]] }],
    seams: [{ installationId: "island", x0: 50, y0: 0, x1: 50, y1: 24 }],
    slabs: [{ index: 1, placements: [{ pieceId: "p1", x: 0, y: 0, rotated: false }, { pieceId: "p2", x: 50.25, y: 0, rotated: false }] }],
  }
  const drawings: DrawInput[] = []
  const observed = kernelLayer((name, args, stdin) => {
    if (name === "layout" && !args.includes("--selfcheck")) {
      const request = Schema.decodeUnknownSync(LayoutInput)(JSON.parse(stdin))
      expect(request.installations[0]?.requiredPieceCount).toBe(2)
      expect(request.installations[0]?.seam).toEqual({ kind: "center-through-cutout", cutoutIndex: 0 })
      return Effect.succeed(JSON.stringify(twoPieces))
    }
    if (name === "draw_layout" && !args.includes("--selfcheck")) drawings.push(Schema.decodeUnknownSync(DrawInput)(JSON.parse(stdin)))
    return fakeTransport(name, args, stdin)
  })
  const { dir, input } = await fixture()
  const w = await Effect.runPromise(workflow(skillDir).pipe(Effect.provide(observed), Effect.provide(BunServices.layer)))
  await run(w.preflight(dir, [input]))
  await writeFile(join(dir, "job.json"), JSON.stringify(centered))
  const readback = await run(w.check(dir))
  expect(readback).toContain("Preliminary: estimated geometry")
  expect(readback).toContain("join two equal halves through cutout 1")
  expect(readback).toContain("material markup: 0% on cost")
  await run(w.confirm(dir))
  expect(await Effect.runPromise(w.quote(dir).pipe(Effect.provide(observed)))).toContain("Preliminary: estimated geometry")
  const quote = Schema.decodeUnknownSync(Quote)(JSON.parse(await readFile(join(dir, "quote.json"), "utf8")))
  expect(quote.geometryEstimates).toEqual(expected)
  expect(quote.installations[0]?.requiredPieceCount).toBe(2)
  expect(quote.installations[0]?.seam).toEqual(centered.installations[0]?.seam)
  expect(quote.invoice).toHaveLength(1)
  expect(drawings.map(d => d.geometryEstimates)).toEqual([expected, expected])
  expect(drawings.every(d => d.installations[0]?.requiredPieceCount === 2)).toBe(true)
  expect(drawings.every(d => d.installations[0]?.seam?.kind === "center-through-cutout")).toBe(true)
  expect(quote.assumptions).toEqual((await run(takeoff(job))).assumptions)
  await expect(run(takeoff(centered))).rejects.toThrow("exactly 2")
  expect((await run(takeoff(job))).geometryEstimates).toEqual([])
  const invalidEstimate = { ...centered, installations: centered.installations.map(i => ({ ...i, cutouts: i.cutouts.map(c => ({ ...c, estimate: { ...estimate, fields: ["wIn", "wIn"] } })) })) }
  expect(() => Schema.decodeUnknownSync(Job)(invalidEstimate)).toThrow()
})

test("center uses each full outer leg and refuses off-grid resulting rectangles", async () => {
  const u = { kind: "U", backIn: 120, leftIn: 80, rightIn: 100, depthIn: 24 } satisfies Job["installations"][number]["shape"]
  for (const [leg, center] of [["back", 60], ["left", 40], ["right", 50]] as const) {
    const base = { kind: "sink", wIn: 20, hIn: 16 } as const
    const symbolic = await Effect.runPromise(prepare(withShape(u, [{ ...base, at: { leg, centerFromStartIn: "center" } }])))
    const numeric = await Effect.runPromise(prepare(withShape(u, [{ ...base, at: { leg, centerFromStartIn: center } }])))
    expect(symbolic.kernelInstallations).toEqual(numeric.kernelInstallations)
    expect(symbolic.geometryEstimates).toEqual([])
  }
  const offGrid = withShape({ kind: "rect", lengthIn: 100.0625, depthIn: 24 }, [{ kind: "sink", wIn: 20, hIn: 16, at: { leg: "main", centerFromStartIn: "center" } }])
  await expect(Effect.runPromise(prepare(offGrid))).rejects.toThrow("sixteenth-inch marks")
  const exactHalfTickCenter = withShape({ kind: "rect", lengthIn: 100.0625, depthIn: 24 }, [{ kind: "sink", wIn: 20.0625, hIn: 16, at: { leg: "main", centerFromStartIn: "center" } }])
  expect((await Effect.runPromise(prepare(exactHalfTickCenter))).kernelInstallations[0]?.cutouts[0]?.x).toBe(40)
})

test("center joins reject unsupported requests and independently reject plausible wrong kernel joins", async () => {
  const installation = { id: "island", label: "Island", shape: { kind: "rect", lengthIn: 60, depthIn: 24 },
    cutouts: [{ kind: "sink", wIn: 20, hIn: 16, at: { xIn: 20, yIn: 4 } }] as const,
    seam: { kind: "center-through-cutout", cutoutIndex: 0 } } satisfies Job["installations"][number]
  const joined = { ...job, installations: [installation] }
  const equal: Layout = { ...layout,
    pieces: [{ id: "a", installationId: "island", outline: [[0, 0], [30, 0], [30, 24], [0, 24]] }, { id: "b", installationId: "island", outline: [[30, 0], [60, 0], [60, 24], [30, 24]] }],
    seams: [{ installationId: "island", x0: 30, y0: 0, x1: 30, y1: 24 }],
    slabs: [{ index: 1, placements: [{ pieceId: "a", x: 0, y: 0, rotated: false }, { pieceId: "b", x: 30.25, y: 0, rotated: false }] }],
  }
  const quoteWith = (candidate: Job, result: Layout) => Effect.runPromise(takeoff(candidate).pipe(Effect.provide(kernelLayer(() => Effect.succeed(JSON.stringify(result))))))
  expect((await quoteWith(joined, equal)).installations[0]?.seam).toEqual(installation.seam)
  const badRequests = [
    { ...installation, requiredPieceCount: 3 },
    { ...installation, seam: { ...installation.seam, cutoutIndex: 1 } },
    { ...installation, cutouts: [{ ...installation.cutouts[0], at: { xIn: 19, yIn: 4 } }] },
    { ...installation, shape: { kind: "L", backIn: 60, sideIn: 48, depthIn: 24, side: "left" } },
    { ...installation, shape: { kind: "rect", lengthIn: 60.0625, depthIn: 24 }, cutouts: [{ ...installation.cutouts[0], wIn: 20.0625 }] },
  ] satisfies Job["installations"]
  for (const candidate of badRequests) await expect(Effect.runPromise(prepare({ ...job, installations: [candidate] }))).rejects.toThrow()
  for (const cutoutIndex of [-1, 0.5]) expect(() => Schema.decodeUnknownSync(Job)({ ...joined, installations: [{ ...installation, seam: { ...installation.seam, cutoutIndex } }] })).toThrow()
  const rectangularOutline = { ...installation, shape: { kind: "outline", points: [[0, 0], [60, 0], [60, 24], [0, 24]] } } satisfies Job["installations"][number]
  expect((await quoteWith({ ...job, installations: [rectangularOutline] }, equal)).totalSf).toBe("10.00")
  const wrongLayouts: Layout[] = [
    { ...equal, seams: [] },
    { ...equal, seams: [{ installationId: "island", x0: 29, y0: 0, x1: 29, y1: 24 }] },
    { ...equal, seams: [{ installationId: "island", x0: 30, y0: 0, x1: 30, y1: 23 }] },
    { ...equal, pieces: [{ id: "a", installationId: "island", outline: [[0, 0], [29, 0], [29, 24], [0, 24]] }, { id: "b", installationId: "island", outline: [[29, 0], [60, 0], [60, 24], [29, 24]] }] },
  ]
  for (const wrong of wrongLayouts) await expect(quoteWith(joined, wrong)).rejects.toThrow("requested center join")
  const otherOpening = { kind: "other", wIn: 4, hIn: 2, at: { xIn: 28, yIn: 0 } } as const
  await expect(quoteWith({ ...joined, installations: [{ ...installation, cutouts: [...installation.cutouts, otherOpening] }] }, equal)).rejects.toThrow("another opening")
  expect((await quoteWith({ ...joined, installations: [{ ...installation, cutouts: [...installation.cutouts, { ...otherOpening, at: { xIn: 5, yIn: 10 } }] }] }, equal)).slabCount).toBe(1)
  const narrow = { ...joined, material: { ...job.material, slab: null }, installations: [{ ...installation, cutouts: [{ ...installation.cutouts[0], hIn: 20, at: { xIn: 20, yIn: 2 } }] }] }
  expect((await run(takeoff(narrow))).warnings[0]).toContain("original countertop edge")
})

test("known original-edge clearance warns without a slab on a concave outline", async () => {
  const outline = { kind: "outline", points: [[0, 0], [100, 0], [100, 24], [24, 24], [24, 80], [0, 80]] } satisfies Job["installations"][number]["shape"]
  const narrow = { ...withShape(outline, [{ kind: "sink", wIn: 20, hIn: 20, at: { xIn: 40, yIn: 2 } }]), material: { ...job.material, slab: null } }
  const quote = await run(takeoff(narrow))
  expect(quote.layout).toBeNull()
  expect(quote.warnings).toHaveLength(1)
  expect(quote.warnings[0]).toContain("sink cutout 1")
  expect(quote.warnings[0]).toContain("original countertop edge")
  const justEnough = { ...narrow, settings: { minMaterialBesideCutoutIn: 2 } }
  expect((await run(takeoff(justEnough))).warnings).toEqual([])
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
