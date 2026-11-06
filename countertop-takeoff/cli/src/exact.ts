/** Exact nonnegative rational used for areas, SF, and decimal money. */
export interface Fraction { readonly n: bigint; readonly d: bigint }

/** Parse a schema-checked decimal without passing through floating point. */
export function decimal(text: string): Fraction {
  const [whole = "0", fraction = ""] = text.split(".")
  return { n: BigInt(whole + fraction), d: 10n ** BigInt(fraction.length) }
}

/** Round a nonnegative rational half-up, with exactly the requested decimals. */
export function rounded(value: Fraction, places = 2): string {
  const scale = 10n ** BigInt(places)
  const units = (2n * value.n * scale + value.d) / (2n * value.d)
  if (places === 0) return String(units)
  return `${units / scale}.${String(units % scale).padStart(places, "0")}`
}

/** Add two exact decimals/rationals. */
export function add(a: Fraction, b: Fraction): Fraction {
  return { n: a.n * b.d + b.n * a.d, d: a.d * b.d }
}

/** Multiply two exact decimals/rationals. */
export function multiply(a: Fraction, b: Fraction): Fraction {
  return { n: a.n * b.n, d: a.d * b.d }
}

/** Render finite area decimals exactly; recurring slab SF uses 18 decimal places. */
export function areaDecimal(value: Fraction): string {
  let rest = value.n % value.d
  let tail = ""
  for (let i = 0; rest !== 0n && i < 18; i++) {
    rest *= 10n
    tail += String(rest / value.d)
    rest %= value.d
  }
  return `${value.n / value.d}${tail ? `.${tail}` : ""}`
}
