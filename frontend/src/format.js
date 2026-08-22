// Display formatting. Everything here is presentation only — the backend
// stores grams as floats and money as integer cents per kilogram, and none
// of these helpers are ever used for arithmetic that goes back to it.

/** 95 -> "1 hr 35 min". Null/0 -> null so callers can omit the row. */
export function formatMinutes(minutes) {
  if (minutes === null || minutes === undefined || minutes <= 0) return null
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (!hours) return `${rest} min`
  if (!rest) return `${hours} hr`
  return `${hours} hr ${rest} min`
}

/** 1234.5 -> "1.23 kg"; 62.4 -> "62 g"; 0.8 -> "0.8 g". */
export function formatGrams(grams) {
  if (grams === null || grams === undefined) return null
  if (grams >= 1000) return `${(grams / 1000).toFixed(2)} kg`
  if (grams >= 10) return `${Math.round(grams)} g`
  return `${Number(grams.toFixed(1))} g`
}

/** Integer cents -> "$4.30". */
export function formatCents(cents, symbol = '$') {
  if (cents === null || cents === undefined) return null
  const sign = cents < 0 ? '-' : ''
  return `${sign}${symbol}${(Math.abs(cents) / 100).toFixed(2)}`
}

/**
 * Cost per gram needs more than two decimals to say anything — most
 * pantry items are a fraction of a cent per gram. Show cents-per-100g
 * instead, which is both readable and comparable across items.
 */
export function formatCostPerKg(centsPerKg, symbol = '$') {
  if (centsPerKg === null || centsPerKg === undefined) return null
  return `${symbol}${(centsPerKg / 100).toFixed(2)}/kg`
}

export function formatDate(value) {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

/** "2 years ago", "3 days ago" — for the Last Prepared line. */
export function formatRelative(value) {
  if (!value) return null
  const then = new Date(value)
  if (Number.isNaN(then.getTime())) return null
  const days = Math.floor((Date.now() - then.getTime()) / 86_400_000)
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 30) return `${days} days ago`
  const months = Math.round(days / 30)
  if (months < 18) return `${months} month${months === 1 ? '' : 's'} ago`
  return `${Math.round(days / 365)} years ago`
}

/** 0.4 -> "40%" */
export function formatPercent(fraction) {
  if (fraction === null || fraction === undefined) return '0%'
  return `${Math.round(fraction * 100)}%`
}

/** Turn 0.3333 back into something a cook can read. */
export function formatQuantity(quantity) {
  if (quantity === null || quantity === undefined) return ''
  const fractions = [
    [1 / 8, '⅛'], [1 / 4, '¼'], [1 / 3, '⅓'], [1 / 2, '½'],
    [2 / 3, '⅔'], [3 / 4, '¾'],
  ]
  const whole = Math.floor(quantity)
  const remainder = quantity - whole
  for (const [value, glyph] of fractions) {
    if (Math.abs(remainder - value) < 0.02) {
      return whole ? `${whole}${glyph}` : glyph
    }
  }
  return `${Number(quantity.toFixed(2))}`
}

export const WEIGHT_SOURCE_LABEL = {
  explicit: 'as written in the recipe',
  converted: 'converted using this ingredient’s density',
  estimated: 'estimated from a typical density — check before relying on it',
  unknown: 'not convertible to a weight',
}

export const SOURCE_LABEL = {
  markets: 'Markets',
  supermarket: 'Supermarket',
  butcher: 'Butcher',
  nut_shop: 'Nut shop',
  deli: 'Deli',
  asian_grocery: 'Asian grocery',
  fishmonger: 'Fishmonger',
  bakery: 'Bakery',
  bottle_shop: 'Bottle shop',
  cake_supplies: 'Cake supplies',
  chemist: 'Chemist',
  hardware: 'Hardware',
  newsagent: 'Newsagent',
  other: 'Other',
}
