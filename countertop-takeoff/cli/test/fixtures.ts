import { Effect, Schema } from "effect"
import { writeFile } from "node:fs/promises"
import { prepare } from "../src/core"
import { KernelError } from "../src/errors"
import { kernelLayer, Kernels } from "../src/kernels"
import { Assessment, Job, Layout, LayoutInput, PlanReply } from "../src/schema"

export const facts = { insideCornerRadiusMm: null, sourceArrangement: null, conditions: [] } as const
export const job = Schema.decodeUnknownSync(Job)({ version: 2,
  material: { name: "Synthetic stone", vendor: "Test supplier", pricePerSf: "10", markupPercent: "0", slab: { lengthIn: 120, widthIn: 60 }, profileId: "silestone-2024-02", profileProvenance: "Explicit synthetic product selection", nominalThicknessMm: "20" },
  laborPerSf: "7.50", installations: [{ id: "island", label: "Island", shape: { kind: "rect", lengthIn: 60, depthIn: 24 }, cutouts: [], ...facts }], settings: {},
})
export type Installation = Job["installations"][number]
export const rectangle = (x0: number, y0: number, x1: number, y1: number): Layout["pieces"][number]["outline"] => [[x0,y0],[x1,y0],[x1,y1],[x0,y1]]
export const layout: Layout = { pieces: [{ id: "p1", installationId: "island", outline: rectangle(0,0,60,24), cutouts: [] }], joins: [],
  slabs: [{ index: 1, placements: [{ pieceId: "p1", x: 0, y: 0, quarterTurns: 0 }] }], slabCount: 1, lowerBound: 1, provenOptimal: true, footprintMode: "gross-polygons", warnings: [] }

// A transport fixture without a manufacturer model. Python and T1 own physical rules.
export function assessment(input: LayoutInput): Assessment {
  const unresolved = [
    { field: "material.profileId", value: input.material.profileId }, { field: "material.profileProvenance", value: input.material.profileProvenance },
    { field: "material.nominalThicknessMm", value: input.material.nominalThicknessMm }, { field: "material.slab", value: input.slab },
  ].filter(x => x.value === null).map(x => ({ field: x.field, question: `Please supply ${x.field}.` }))
  const planning = input.phase === "plan" && unresolved.length === 0
  return { status: unresolved.length ? "unresolved" : "assessed", geometry: "valid",
    profile: { id: input.material.profileId, provenance: input.material.profileProvenance, nominalThicknessMm: input.material.nominalThicknessMm },
    checks: [{ id: "fixture", ruleId: "fixture-geometry", installationId: null, cutoutIndex: null, joinId: null, status: "pass", operator: "applicable", actual: null, required: null, source: null, explanation: "Synthetic boundary fixture only", fields: [] }],
    conditions: [], unresolved, handling: "not-evaluated", limitations: ["Synthetic fixture, no physical evaluation"],
    installations: input.installations.map(i => ({ id: i.id, seamNecessity: "undetermined", explanation: "Synthetic fixture" })),
    search: { status: planning ? "complete" : "not-run", candidateFamilies: planning ? ["whole"] : [], candidateCount: planning ? 1 : 0, qualifyingCount: planning ? 1 : 0, packing: planning ? "polygon-cells" : "not-run", optimality: planning ? "global-slab-bound" : "not-proven", limits: [] } }
}
export function response(input: LayoutInput, candidate: Layout = layout): PlanReply {
  const a = assessment(input)
  return { ok: true, version: 2, assessment: a, layout: input.phase === "plan" && a.status === "assessed" ? candidate : null }
}
export const transport: Parameters<typeof kernelLayer>[0] = (name, args, stdin) => {
  if (args.includes("--selfcheck")) return Effect.succeed('{"ok":true}')
  if (name === "layout") return Effect.succeed(JSON.stringify(response(Schema.decodeUnknownSync(LayoutInput)(JSON.parse(stdin)))))
  if (name === "inspect_input") return Effect.succeed(JSON.stringify({ files: args.map(path => ({ path, ok: true, kind: "image", pages: 1, previews: [path], problem: null })) }))
  const out = args[args.indexOf("--out") + 1]
  return Effect.tryPromise({ try: async () => { if (!out) throw new Error("missing test path"); await writeFile(out, "synthetic PNG"); return JSON.stringify({ ok: true, path: out }) }, catch: () => new KernelError({ message: "Test drawing failed" }) })
}
export const fake = kernelLayer(transport)
export const run = <A, E>(effect: Effect.Effect<A, E, Kernels>) => Effect.runPromise(effect.pipe(Effect.provide(fake)))
export const withShape = (shape: Installation["shape"], cutouts: Installation["cutouts"] = []): Job => ({ ...job, installations: [{ id: "island", label: "Island", shape, cutouts, ...facts }] })
export const opening = { kind: "sink", wIn: 20, hIn: 16, radiusMm: null, mount: null } as const
export async function request(j: Job = job): Promise<LayoutInput> {
  const p = await Effect.runPromise(prepare(j))
  const { profileId, profileProvenance, nominalThicknessMm } = j.material
  return { version: 2, mode: "assessment", phase: "plan", material: { profileId, profileProvenance, nominalThicknessMm }, slab: j.material.slab, settings: p.settings, installations: p.kernelInstallations }
}
