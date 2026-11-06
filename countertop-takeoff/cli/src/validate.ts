import type { Layout, LayoutInput, PlanReply } from "./schema"

type Point = readonly [bigint, bigint]
type Polygon = readonly Point[]
type Cell = { readonly x0: bigint; readonly y0: bigint; readonly x1: bigint; readonly y1: bigint }
const ticks = (n: number) => BigInt(n * 16)
const polygon = (p: readonly (readonly [number, number])[]): Polygon => p.map(([x, y]) => [ticks(x), ticks(y)])
const min = (a: bigint, b: bigint) => a < b ? a : b
const max = (a: bigint, b: bigint) => a > b ? a : b
const unique = <A>(xs: readonly A[]) => new Set(xs).size === xs.length
const sorted = (xs: readonly bigint[]) => [...new Set(xs)].sort((a, b) => a < b ? -1 : a > b ? 1 : 0)
const edges = (p: Polygon) => p.flatMap((a, i) => { const b = p[(i + 1) % p.length]; return b ? [{ a, b }] : [] })
function inside(p: Polygon, x2: bigint, y2: bigint) {
  let result = false
  for (const { a, b } of edges(p)) if ((a[1] * 2n > y2) !== (b[1] * 2n > y2) && a[0] * 2n > x2) result = !result
  return result
}
function valid(p: Polygon) {
  const boundary = edges(p)
  if (p.length < 4 || boundary.reduce((n, { a, b }) => n + a[0] * b[1] - b[0] * a[1], 0n) <= 0n) return false
  for (const [i, { a, b }] of boundary.entries()) {
    if ((a[0] === b[0]) === (a[1] === b[1])) return false
    for (const [j, { a: c, b: d }] of boundary.entries()) {
      if (j <= i + 1 || (i === 0 && j === boundary.length - 1)) continue
      if (max(min(a[0], b[0]), min(c[0], d[0])) <= min(max(a[0], b[0]), max(c[0], d[0])) && max(min(a[1], b[1]), min(c[1], d[1])) <= min(max(a[1], b[1]), max(c[1], d[1]))) return false
    }
  }
  return true
}
function connected(indices: readonly number[], columns: number) {
  const remaining = new Set(indices)
  const start = indices[0]
  if (start === undefined) return false
  const queue = [start]; remaining.delete(start)
  for (let i = 0; i < queue.length; i++) {
    const current = queue[i]
    if (current === undefined) continue
    for (const neighbor of [current - columns, current + columns, ...(current % columns ? [current - 1] : []), ...(current % columns < columns - 1 ? [current + 1] : [])]) {
      if (remaining.delete(neighbor)) queue.push(neighbor)
    }
  }
  return remaining.size === 0
}
function rotated([x, y]: Point, turns: number): Point {
  switch (turns) { case 1: return [-y, x]; case 2: return [-x, -y]; case 3: return [y, -x]; default: return [x, y] }
}
function transformed(cells: readonly Cell[], outline: Polygon, placement: Layout["slabs"][number]["placements"][number]) {
  const points = outline.map(p => rotated(p, placement.quarterTurns))
  const ox = points.reduce((n, [x]) => min(n, x), points[0]?.[0] ?? 0n)
  const oy = points.reduce((n, [, y]) => min(n, y), points[0]?.[1] ?? 0n)
  return cells.map(c => {
    const corners: readonly Point[] = [[c.x0, c.y0], [c.x1, c.y0], [c.x1, c.y1], [c.x0, c.y1]]
    const r = corners.map(p => rotated(p, placement.quarterTurns))
    return { x0: r.reduce((n, [x]) => min(n, x), r[0]?.[0] ?? 0n) - ox + ticks(placement.x), x1: r.reduce((n, [x]) => max(n, x), r[0]?.[0] ?? 0n) - ox + ticks(placement.x),
      y0: r.reduce((n, [, y]) => min(n, y), r[0]?.[1] ?? 0n) - oy + ticks(placement.y), y1: r.reduce((n, [, y]) => max(n, y), r[0]?.[1] ?? 0n) - oy + ticks(placement.y) }
  })
}

/** Structural evidence validation only: no manufacturer distance/radius rules live here. */
export function replyIssue(request: LayoutInput, reply: PlanReply): string | null {
  const a = reply.assessment, layout = reply.layout
  if (a.profile.id !== request.material.profileId || a.profile.provenance !== request.material.profileProvenance || a.profile.nominalThicknessMm !== request.material.nominalThicknessMm) return "the assessment changed the supplied material profile facts"
  const installations = new Map(request.installations.map(i => [i.id, i]))
  if (!unique(a.installations.map(i => i.id)) || a.installations.length !== installations.size || a.installations.some(i => !installations.has(i.id))) return "the assessment omitted or duplicated an installation"
  if (!unique(a.checks.map(c => c.id)) || !unique(a.conditions.map(c => c.id)) || !unique(a.unresolved.map(f => f.field))) return "the assessment duplicated evidence or missing facts"
  const sourceRegistry = {
    S1: { hash: "56535666e6ed4e33ea1bc452968ea1b7922abd13c57d98fff40312c0aa24794a", url: "https://assetstools.cosentino.com/api/v1/bynder/doc/0B425745-8BAC-4A87-9D7B54DA7AC39A1D/silestone-installation-manual.pdf" },
    S2: { hash: "8b9011f17cf55712fc17a4b2aecc40a87cbf2d9f30b6bfe00803c56c425a4074", url: "https://cdn.msisurfaces.com/files/downloads/quartz-installation-guidelines.pdf" },
  }
  for (const e of [...a.checks, ...a.conditions]) {
    const installation = e.installationId === null ? undefined : installations.get(e.installationId)
    if (e.installationId !== null && installation === undefined) return "evidence refers to an unknown installation"
    if (e.cutoutIndex !== null && (installation === undefined || installation.cutouts[e.cutoutIndex] === undefined)) return "evidence refers to an unknown opening"
    if (e.joinId !== null && !layout?.joins.some(j => j.id === e.joinId && j.installationId === e.installationId)) return "evidence refers to an unknown joint"
    if (e.source !== null && (e.source.sha256 !== sourceRegistry[e.source.id].hash || e.source.url !== sourceRegistry[e.source.id].url)) return "source evidence does not identify the pinned document"
  }
  if (a.checks.some(c => (c.status === "pass" || c.status === "fail") && c.required !== null && c.source === null)) return "a dimensional rule result omitted its source evidence"
  const failed = a.geometry === "invalid" || a.checks.some(c => c.status === "fail") || a.conditions.some(c => c.status === "failed")
  if ((a.status === "assessed" || a.status === "conditional") && failed) return "a rejected condition was admitted as an assessed candidate"
  if (a.status === "assessed" && (a.checks.length === 0 || a.checks.some(c => c.status === "unknown" || c.status === "unsupported") || a.conditions.some(c => c.status !== "satisfied") || a.unresolved.length > 0)) return "an incomplete assessment was labelled fully assessed"
  if (request.mode === "assessment") {
    const missing = [
      ["material.profileId", request.material.profileId], ["material.profileProvenance", request.material.profileProvenance],
      ["material.nominalThicknessMm", request.material.nominalThicknessMm], ["material.slab", request.slab],
    ] as const
    if (missing.some(([field, value]) => value === null && !a.unresolved.some(b => b.field === field))) return "the assessment omitted a question for a missing material or stock fact"
    if ((a.status === "unresolved" || a.status === "conflict" || a.status === "search-incomplete") && layout !== null) return "a final layout was returned for an unresolved or rejected assessment"
    if (layout !== null && (request.material.profileId === null || request.material.profileProvenance === null || request.material.nominalThicknessMm === null || request.slab === null)) return "a layout was returned without the required profile, thickness or stock facts"
    if (request.phase === "plan" && (a.status === "assessed" || a.status === "conditional") && layout === null) return "a planned candidate omitted its actual layout"
  } else if (a.status !== "unresolved" || !a.limitations.some(s => s.includes("geometry-replay"))) return "development replay was not marked unassessed"
  if (request.phase === "assess" && (layout !== null || a.search.status !== "not-run")) return "the input-only assessment returned a planned layout"
  if (a.search.qualifyingCount > a.search.candidateCount) return "search counts disagree"
  if (a.search.status === "not-run" && (a.search.candidateCount !== 0 || a.search.qualifyingCount !== 0 || a.search.packing !== "not-run" || a.search.optimality !== "not-proven")) return "an unrun search claimed candidates or packing proof"
  if (a.search.status === "capped" && a.search.limits.length === 0) return "a capped search omitted its limits"
  if (a.status === "search-incomplete" && (a.search.status !== "capped" || a.search.qualifyingCount !== 0)) return "the incomplete search outcome disagrees with its candidate evidence"
  if (a.search.optimality === "global-slab-bound" && (layout === null || !layout.provenOptimal)) return "global slab proof has no matching layout evidence"
  if (layout === null) return null
  if (a.search.status === "not-run" || a.search.qualifyingCount === 0 || (a.search.status === "capped" && layout.provenOptimal)) return "layout proof disagrees with the search limits"
  if (layout.provenOptimal && layout.lowerBound !== layout.slabCount) return "slab optimality was claimed without reaching the exact area bound"
  if (layout.footprintMode === "bounding-box" && a.search.packing !== "bounding-box") return "the conservative packing fallback was not disclosed"
  return layoutIssue(request, layout)
}

function layoutIssue(request: LayoutInput, layout: Layout): string | null {
  if (request.slab === null) return "a stock layout has no slab dimensions"
  const pieces = new Map(layout.pieces.map(p => [p.id, p]))
  if (pieces.size > 12) return "the layout exceeds the supported twelve fabrication pieces"
  const placed = layout.slabs.flatMap(s => s.placements.map(p => p.pieceId))
  if (pieces.size !== layout.pieces.length || !unique(layout.joins.map(j => j.id)) || placed.length !== pieces.size || !unique(placed) || placed.some(id => !pieces.has(id))) return "pieces or placements are missing, duplicated or unknown"
  if (layout.slabCount !== layout.slabs.length || layout.lowerBound > layout.slabCount || layout.slabs.some((s, i) => s.index !== i + 1 || s.placements.length === 0)) return "slab counts or indices disagree"
  if (layout.pieces.some(p => !request.installations.some(i => i.id === p.installationId))) return "a piece belongs to an unknown installation"
  if (layout.joins.some(j => !request.installations.some(i => i.id === j.installationId) || !unique(j.pieceIds) || j.pieceIds.some(id => pieces.get(id)?.installationId !== j.installationId))) return "a joint references unknown or unrelated pieces"
  const grossCells = new Map<string, readonly Cell[]>()
  let totalArea = 0n
  for (const inst of request.installations) {
    const original = polygon(inst.outline)
    const ps = layout.pieces.filter(p => p.installationId === inst.id)
    const js = layout.joins.filter(j => j.installationId === inst.id)
    if (ps.length === 0 || (inst.requiredPieceCount !== undefined && ps.length !== inst.requiredPieceCount)) return `${inst.id}: the requested fabrication-piece count was not preserved`
    const shapes = ps.map(p => polygon(p.outline))
    const holes = inst.cutouts.map(c => polygon([[c.x, c.y], [c.x + c.w, c.y], [c.x + c.w, c.y + c.h], [c.x, c.y + c.h]]))
    const clips = ps.map(p => p.cutouts.map(c => ({ index: c.cutoutIndex, shape: polygon(c.outline) })))
    if (!valid(original) || shapes.some(p => !valid(p)) || clips.some(cs => cs.some(c => !valid(c.shape) || c.index >= holes.length))) return "a piece or clipped opening is not a simple clockwise orthogonal polygon"
    const all = [original, ...shapes, ...holes, ...clips.flatMap(cs => cs.map(c => c.shape))]
    const xs = sorted([...all.flatMap(p => p.map(([x]) => x)), ...js.flatMap(j => j.axis === "x" ? [ticks(j.offsetIn)] : [ticks(j.startIn), ticks(j.endIn), ...j.segments.flatMap(s => [ticks(s.x0), ticks(s.x1)])])])
    const ys = sorted([...all.flatMap(p => p.map(([, y]) => y)), ...js.flatMap(j => j.axis === "y" ? [ticks(j.offsetIn)] : [ticks(j.startIn), ticks(j.endIn), ...j.segments.flatMap(s => [ticks(s.y0), ticks(s.y1)])])])
    const columns = xs.length - 1, rows = ys.length - 1
    if (columns * rows > 100000) return "this layout is too complex for the CLI's independent geometry check"
    const owners = new Map<number, number>(), solids = new Set<number>()
    const cells: Cell[][] = ps.map(() => []), solidIndices: number[][] = ps.map(() => [])
    for (let y = 0; y < rows; y++) for (let x = 0; x < columns; x++) {
      const x0 = xs[x], x1 = xs[x + 1], y0 = ys[y], y1 = ys[y + 1]
      if (x0 === undefined || x1 === undefined || y0 === undefined || y1 === undefined) return "geometry grid is incomplete"
      const x2 = x0 + x1, y2 = y0 + y1, index = y * columns + x
      const insideOriginal = inside(original, x2, y2)
      const occupied = shapes.flatMap((p, i) => inside(p, x2, y2) ? [i] : [])
      if (occupied.length !== (insideOriginal ? 1 : 0)) return "fabrication footprints do not tile the original installation exactly"
      const owner = occupied[0]
      for (const [i, cs] of clips.entries()) for (const c of cs) {
        const hole = holes[c.index]
        if (inside(c.shape, x2, y2) && (owner !== i || hole === undefined || !inside(hole, x2, y2))) return "a clipped opening extends outside its piece or original opening"
      }
      if (owner === undefined) continue
      owners.set(index, owner); cells[owner]?.push({ x0, x1, y0, y1 }); totalArea += (x1 - x0) * (y1 - y0)
      const originalHole = holes.some(h => inside(h, x2, y2))
      const clippedHole = clips[owner]?.some(c => inside(c.shape, x2, y2)) ?? false
      if (originalHole !== clippedHole) return "opening attribution changed or filled an original void"
      if (holes.some((h, cutoutIndex) => (clips[owner]?.filter(c => c.index === cutoutIndex && inside(c.shape, x2, y2)).length ?? 0) !== (inside(h, x2, y2) ? 1 : 0))) return "an opening was omitted, duplicated or attributed to another opening"
      if (!originalHole) { solids.add(index); solidIndices[owner]?.push(index) }
    }
    for (const [i, p] of ps.entries()) {
      if (!connected(solidIndices[i] ?? [], columns)) return "a fabrication piece contains no stone or has disconnected stone"
      grossCells.set(p.id, cells[i] ?? [])
    }
    for (const j of js) {
      if (j.startIn >= j.endIn || j.segments.length === 0) return "a logical joint has no positive stone segments"
      if (j.cutoutIndex !== null && inst.cutouts[j.cutoutIndex] === undefined) return "a joint refers to an unknown opening"
      if (j.segments.some(s => j.axis === "x" ? s.x0 !== j.offsetIn || s.x1 !== j.offsetIn || s.y0 >= s.y1 || s.y0 < j.startIn || s.y1 > j.endIn : s.y0 !== j.offsetIn || s.y1 !== j.offsetIn || s.x0 >= s.x1 || s.x0 < j.startIn || s.x1 > j.endIn)) return "stone segments disagree with their logical joint"
    }
    // Every actual stone boundary between two pieces needs exactly one logical joint.
    for (const [index, owner] of owners) for (const [neighbor, axis] of [[index + 1, "x"], [index + columns, "y"]] as const) {
      if ((axis === "x" && index % columns === columns - 1) || !solids.has(index) || !solids.has(neighbor)) continue
      const other = owners.get(neighbor)
      if (other === undefined || other === owner) continue
      const col = index % columns, row = Math.floor(index / columns)
      const offset = axis === "x" ? xs[col + 1] : ys[row + 1]
      const start = axis === "x" ? ys[row] : xs[col], end = axis === "x" ? ys[row + 1] : xs[col + 1]
      if (offset === undefined || start === undefined || end === undefined) return "joint grid is incomplete"
      const p = ps[owner], q = ps[other]
      const covering = js.filter(j => j.axis === axis && ticks(j.offsetIn) === offset && p && q && j.pieceIds.includes(p.id) && j.pieceIds.includes(q.id) && j.segments.some(s => axis === "x" ? ticks(s.y0) <= start && ticks(s.y1) >= end : ticks(s.x0) <= start && ticks(s.x1) >= end))
      if (covering.length !== 1) return "an actual stone joint is missing, duplicated or misattributed"
    }
    // A reported stone segment cannot cross empty space or a piece's uncut interior.
    for (const j of js) for (const s of j.segments) {
      const offsets = j.axis === "x" ? xs : ys, along = j.axis === "x" ? ys : xs
      const at = offsets.indexOf(ticks(j.offsetIn))
      for (let n = 0; n < along.length - 1; n++) {
        const lo = along[n], hi = along[n + 1]
        if (lo === undefined || hi === undefined) continue
        const begin = ticks(j.axis === "x" ? s.y0 : s.x0), finish = ticks(j.axis === "x" ? s.y1 : s.x1)
        if (lo < begin || hi > finish) continue
        const left = j.axis === "x" ? n * columns + at - 1 : (at - 1) * columns + n
        const right = j.axis === "x" ? n * columns + at : at * columns + n
        const a = owners.get(left), b = owners.get(right)
        if (at <= 0 || !solids.has(left) || !solids.has(right) || a === undefined || b === undefined || a === b || !j.pieceIds.includes(ps[a]?.id ?? "") || !j.pieceIds.includes(ps[b]?.id ?? "")) return "a reported joint bridges a void or is not an actual piece boundary"
      }
    }
    if (inst.seam && inst.seam.kind !== "tangent-cutout") {
      const cutout = inst.cutouts[inst.seam.cutoutIndex]
      const axis = inst.seam.kind === "center-through-cutout" ? "x" : inst.sourceArrangement?.axis
      const expected = cutout === undefined ? undefined : axis === "x" ? 2n * ticks(cutout.x) + ticks(cutout.w) : 2n * ticks(cutout.y) + ticks(cutout.h)
      if (inst.seam.kind === "center-through-cutout" && (ps.length !== 2 || js.length !== 1)) return "the equal-halves join did not produce exactly two fabrication pieces"
      if (axis === undefined || expected === undefined || !js.some(j => j.kind === "inside-opening" && j.axis === axis && 2n * ticks(j.offsetIn) === expected && j.cutoutIndex === inst.seam?.cutoutIndex && j.origin === "supplied" && j.reason === "supplied-join")) return "the supplied opening join was moved, omitted or described as automatic"
    } else if (inst.seam?.kind === "tangent-cutout") return "an unsupported tangent request was admitted"
  }
  const trim = 2n * ticks(request.settings.slabTrimIn)
  const width = ticks(request.slab.lengthIn) - trim, height = ticks(request.slab.widthIn) - trim
  if (width <= 0n || height <= 0n || layout.lowerBound !== Number((totalArea + width * height - 1n) / (width * height))) return "the reported area lower bound is not exact"
  for (const slab of layout.slabs) {
    const packed = []
    for (const placement of slab.placements) {
      const piece = pieces.get(placement.pieceId)
      if (!piece || (!request.settings.allowRotate && placement.quarterTurns !== 0)) return "a piece used an unpermitted rotation"
      const transformedCells = transformed(grossCells.get(piece.id) ?? [], polygon(piece.outline), placement)
      if (transformedCells.some(c => c.x0 < 0n || c.y0 < 0n || c.x1 > width || c.y1 > height)) return "a placed polygon does not fit the usable slab"
      const k = ticks(request.settings.kerfIn)
      for (const previous of packed) for (const a of previous) for (const b of transformedCells) if (a.x1 + k > b.x0 && b.x1 + k > a.x0 && a.y1 + k > b.y0 && b.y1 + k > a.y0) return "placed pieces overlap or violate the required kerf"
      packed.push(transformedCells)
    }
  }
  return null
}
