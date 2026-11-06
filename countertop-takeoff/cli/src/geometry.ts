import { Effect } from "effect"
import { JobError } from "./errors"
import type { Job, LayoutInput, Quote } from "./schema"

type Point = readonly [bigint, bigint]
const point = (x: bigint, y: bigint): Point => [x, y]
const ticks = (inches: number) => BigInt(inches * 16)
const inches = (n: bigint) => Number(n) / 16
const min = (a: bigint, b: bigint) => a < b ? a : b
const max = (a: bigint, b: bigint) => a > b ? a : b

function edges(points: readonly Point[]) {
  return points.flatMap((a, i) => {
    const b = points[(i + 1) % points.length]
    return b ? [{ a, b }] : []
  })
}

function intersects(a: Point, b: Point, c: Point, d: Point) {
  return max(min(a[0], b[0]), min(c[0], d[0])) <= min(max(a[0], b[0]), max(c[0], d[0])) &&
    max(min(a[1], b[1]), min(c[1], d[1])) <= min(max(a[1], b[1]), max(c[1], d[1]))
}

function contains(points: readonly Point[], x2: bigint, y2: bigint) {
  let inside = false
  for (const { a, b } of edges(points)) {
    if ((a[1] * 2n > y2) !== (b[1] * 2n > y2) && a[0] * 2n > x2) inside = !inside
  }
  return inside
}

// Partition at polygon corners: every open cell of the cutout must be inside.
function containsRectangle(points: readonly Point[], x: bigint, y: bigint, w: bigint, h: bigint) {
  const xs = [...new Set([x, x + w, ...points.map(p => p[0]).filter(v => v > x && v < x + w)])].sort((a, b) => a < b ? -1 : a > b ? 1 : 0)
  const ys = [...new Set([y, y + h, ...points.map(p => p[1]).filter(v => v > y && v < y + h)])].sort((a, b) => a < b ? -1 : a > b ? 1 : 0)
  return xs.slice(1).every((right, i) => ys.slice(1).every((bottom, j) => {
    const left = xs[i], top = ys[j]
    return left !== undefined && top !== undefined && contains(points, left + right, top + bottom)
  }))
}

/** Expand confirmed shapes and cutouts; all geometry arithmetic uses 1/16-inch integers. */
export const expand = Effect.fn("Geometry.expand")(function* (job: Job) {
  const ids = new Set<string>()
  return yield* Effect.forEach(job.installations, (installation) => Effect.gen(function* () {
    const invalid = (reason: string) => new JobError({ message: `${installation.label}: ${reason}` })
    if (ids.has(installation.id)) return yield* Effect.fail(invalid("give each installation a different id."))
    ids.add(installation.id)
    const shape = installation.shape
    let polygon: readonly Point[]
    switch (shape.kind) {
      case "rect": {
        const l = ticks(shape.lengthIn), d = ticks(shape.depthIn)
        polygon = [point(0n, 0n), point(l, 0n), point(l, d), point(0n, d)]
        break
      }
      case "L": {
        const b = ticks(shape.backIn), s = ticks(shape.sideIn), d = ticks(shape.depthIn)
        if (b <= d || s <= d) return yield* Effect.fail(invalid("each L leg must be longer than its depth. Please check the sketch."))
        polygon = shape.side === "left"
          ? [point(0n, 0n), point(b, 0n), point(b, d), point(d, d), point(d, s), point(0n, s)]
          : [point(0n, 0n), point(b, 0n), point(b, s), point(b - d, s), point(b - d, d), point(0n, d)]
        break
      }
      case "U": {
        const l = ticks(shape.leftIn), b = ticks(shape.backIn), r = ticks(shape.rightIn), d = ticks(shape.depthIn)
        if (b <= 2n * d || l <= d || r <= d) return yield* Effect.fail(invalid("the U needs room between its sides, and each side must extend past the back leg. Please check the sketch."))
        polygon = [point(0n, 0n), point(b, 0n), point(b, r), point(b - d, r), point(b - d, d), point(d, d), point(d, l), point(0n, l)]
        break
      }
      case "outline": {
        polygon = shape.points.map(([x, y]) => point(ticks(x), ticks(y)))
        const first = polygon[0], last = polygon.at(-1)
        if (first && last && first[0] === last[0] && first[1] === last[1]) polygon = polygon.slice(0, -1)
        break
      }
    }
    const boundary = edges(polygon)
    const twiceArea = boundary.reduce((sum, { a, b }) => sum + a[0] * b[1] - b[0] * a[1], 0n)
    if (polygon.length < 4 || twiceArea <= 0n || !polygon.some(p => p[0] === 0n) || !polygon.some(p => p[1] === 0n)) {
      return yield* Effect.fail(invalid("the outline must run clockwise from an outer top-left origin and enclose an area."))
    }
    for (const [i, { a, b }] of boundary.entries()) {
      if ((a[0] === b[0]) === (a[1] === b[1])) return yield* Effect.fail(invalid("outline edges must be horizontal or vertical, with no repeated corners."))
      for (const [j, { a: c, b: d }] of boundary.entries()) {
        if (j <= i + 1 || (i === 0 && j === boundary.length - 1)) continue
        if (intersects(a, b, c, d)) return yield* Effect.fail(invalid("the outline crosses or touches itself. Please check its corners."))
      }
    }
    const cutouts = yield* Effect.forEach(installation.cutouts, (cutout) => Effect.gen(function* () {
      const w = ticks(cutout.wIn), h = ticks(cutout.hIn)
      let x: bigint, y: bigint
      if ("xIn" in cutout.at) {
        x = ticks(cutout.at.xIn); y = ticks(cutout.at.yIn)
      } else {
        const { leg, centerFromStartIn } = cutout.at
        if (shape.kind === "outline") return yield* Effect.fail(invalid("place outline cutouts with xIn and yIn."))
        const d = ticks(shape.depthIn)
        const horizontal = leg === "main" || leg === "back"
        const valid = shape.kind === "rect" ? leg === "main"
          : shape.kind === "L" ? leg === "back" || leg === shape.side
          : leg === "back" || leg === "left" || leg === "right"
        if (!valid) return yield* Effect.fail(invalid(`there is no ${leg} leg for this cutout.`))
        const legLength = shape.kind === "rect" ? shape.lengthIn : leg === "back" ? shape.backIn
          : shape.kind === "L" ? shape.sideIn : leg === "left" ? shape.leftIn : shape.rightIn
        // Twice the center stays integral even when the leg's midpoint is a half tick.
        const center2 = centerFromStartIn === "center" ? ticks(legLength) : 2n * ticks(centerFromStartIn)
        const x2 = horizontal ? center2 - w : leg === "left" ? d - w : 2n * ticks(shape.kind === "rect" ? shape.lengthIn : shape.backIn) - d - w
        const y2 = horizontal ? d - h : center2 - h
        if (x2 % 2n !== 0n || y2 % 2n !== 0n) return yield* Effect.fail(invalid("centering this cutout falls between sixteenth-inch marks. Supply its top-left xIn and yIn instead."))
        x = x2 / 2n; y = y2 / 2n
      }
      if (x < 0n || y < 0n || !containsRectangle(polygon, x, y, w, h)) return yield* Effect.fail(invalid(`the ${cutout.kind} cutout extends outside the countertop. Please check its size and position.`))
      return { kind: cutout.kind, x: inches(x), y: inches(y), w: inches(w), h: inches(h) }
    }))
    const geometryEstimates: Quote["geometryEstimates"] = installation.cutouts.flatMap((cutout, cutoutIndex) => {
      const rectangle = cutouts[cutoutIndex]
      return cutout.estimate && rectangle ? [{ installationId: installation.id, cutoutIndex,
        ...cutout.estimate, xIn: rectangle.x, yIn: rectangle.y, wIn: rectangle.w, hIn: rectangle.h }] : []
    })
    const wire: LayoutInput["installations"][number] = { id: installation.id, outline: polygon.map(([x, y]): readonly [number, number] => [inches(x), inches(y)]), cutouts,
      ...(installation.requiredPieceCount === undefined ? {} : { requiredPieceCount: installation.requiredPieceCount }) }
    return { ...wire, label: installation.label, areaTicks: twiceArea / 2n, geometryEstimates }
  }))
})
