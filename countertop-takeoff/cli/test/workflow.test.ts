import { afterEach, expect, test } from "bun:test"
import { BunServices } from "@effect/platform-bun"
import { Effect, Schema } from "effect"
import { mkdtemp, readFile, rm, writeFile, symlink } from "node:fs/promises"
import { tmpdir } from "node:os"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { kernelLayer } from "../src/kernels"
import { DrawInput, Job, Quote } from "../src/schema"
import { workflow } from "../src/workflow"
import { fake, job, opening, run, transport, withShape } from "./fixtures"

const skillDir = resolve(dirname(fileURLToPath(import.meta.url)), "../..")
const scratch: string[] = []
afterEach(async () => { await Promise.all(scratch.splice(0).map(dir => rm(dir, { recursive: true, force: true }))) })
async function fixture(layer = fake) {
  const root = await mkdtemp(join(tmpdir(), "takeoff-cli-test-"))
  scratch.push(root)
  const dir = join(root, "job"), input = join(root, "sketch.png")
  await writeFile(input, "synthetic input")
  const w = await Effect.runPromise(workflow(skillDir).pipe(Effect.provide(layer), Effect.provide(BunServices.layer)))
  return { root, dir, input, w }
}

test("preflight, checked preview and exact current confirmation remain mandatory", async () => {
  const { dir, input, w } = await fixture()
  await expect(run(w.quote(dir))).rejects.toThrow("preflight")
  await run(w.preflight(dir, [input]))
  await writeFile(join(dir, "job.json"), JSON.stringify(job))
  await expect(run(w.confirm(dir))).rejects.toThrow("preview")
  expect(await run(w.check(dir))).toContain("Handling")
  await expect(run(w.quote(dir))).rejects.toThrow("Dad")
  await run(w.confirm(dir)); await run(w.quote(dir))
  expect(await run(w.next(dir))).toContain("assessed scope")
  await writeFile(join(dir, "job.json"), JSON.stringify(job) + "\n")
  await expect(run(w.quote(dir))).rejects.toThrow("changed since Dad")
})

test("copied-input edits invalidate preflight; failed reruns clear old success", async () => {
  const { dir, input, w } = await fixture()
  await run(w.preflight(dir, [input]))
  await writeFile(join(dir, "job.json"), JSON.stringify(job))
  await run(w.check(dir)); await run(w.confirm(dir))
  await writeFile(join(dir, "inputs", "1-sketch.png"), "edited")
  await expect(run(w.quote(dir))).rejects.toThrow("input picture changed")
  await run(w.preflight(dir, [input]))
  await expect(run(w.preflight(dir, [join(dir, "missing.png")]))).rejects.toThrow("couldn't copy")
  await expect(run(w.quote(dir))).rejects.toThrow("preflight")
})

test("private jobs are refused inside any checkout, including junctions", async () => {
  const { root, input, w } = await fixture()
  await expect(run(w.preflight(join(skillDir, "private-job"), [input]))).rejects.toThrow("Keep plans outside")
  const link = join(root, "code-link")
  await symlink(skillDir, link, "junction")
  await expect(run(w.preflight(join(link, "private-job"), [input]))).rejects.toThrow("Keep plans outside")
  await writeFile(join(root, ".git"), await readFile(resolve(skillDir, "..", ".git")))
  await expect(run(w.preflight(join(root, "other-checkout-job"), [input]))).rejects.toThrow("Keep plans outside")
})

test("unresolved workflow preserves assessment and estimated rectangles in both drawing modes", async () => {
  const drawings: DrawInput[] = []
  const observed = kernelLayer((name, args, stdin) => {
    if (name === "draw_layout" && !args.includes("--selfcheck")) drawings.push(Schema.decodeUnknownSync(DrawInput)(JSON.parse(stdin)))
    return transport(name, args, stdin)
  })
  const { dir, input, w } = await fixture(observed)
  const j = { ...withShape({ kind: "rect", lengthIn: 60, depthIn: 24 }, [{ ...opening, at: { xIn: 20, yIn: 4 }, estimate: { fields: ["at"], note: "Authorized synthetic estimate" } }]), material: { ...job.material, slab: null } } satisfies Job
  await run(w.preflight(dir, [input]))
  await writeFile(join(dir, "job.json"), JSON.stringify(j))
  expect(await run(w.check(dir))).toContain("Preliminary: estimated geometry")
  await run(w.confirm(dir))
  expect(await run(w.quote(dir))).toContain("unresolved")
  const q = Schema.decodeUnknownSync(Quote)(JSON.parse(await readFile(join(dir, "quote.json"), "utf8")))
  expect(q.layout).toBeNull(); expect(q.pricing.materialCost).toBeNull()
  expect(drawings).toHaveLength(2)
  expect(drawings.every(d => d.assessment.status === "unresolved" && d.geometryEstimates.length === 1)).toBe(true)
})
