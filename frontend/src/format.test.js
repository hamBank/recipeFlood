import { describe, expect, it } from 'vitest'
import {
  formatCents,
  formatCostPerKg,
  formatGrams,
  formatMinutes,
  formatPercent,
  formatQuantity,
  formatRelative,
} from './format'

describe('formatMinutes', () => {
  it('splits into hours and minutes', () => {
    expect(formatMinutes(95)).toBe('1 hr 35 min')
    expect(formatMinutes(60)).toBe('1 hr')
    expect(formatMinutes(20)).toBe('20 min')
  })

  it('returns null for nothing, so callers can omit the row', () => {
    expect(formatMinutes(null)).toBeNull()
    expect(formatMinutes(0)).toBeNull()
    expect(formatMinutes(undefined)).toBeNull()
  })
})

describe('formatGrams', () => {
  it('switches to kilograms past 1000g', () => {
    expect(formatGrams(1500)).toBe('1.50 kg')
  })

  it('rounds whole grams but keeps a decimal for tiny amounts', () => {
    expect(formatGrams(62.4)).toBe('62 g')
    expect(formatGrams(0.8)).toBe('0.8 g')
  })

  it('passes null through', () => {
    expect(formatGrams(null)).toBeNull()
  })
})

describe('money', () => {
  it('formats cents as dollars', () => {
    expect(formatCents(430)).toBe('$4.30')
    expect(formatCents(0)).toBe('$0.00')
    expect(formatCents(-250)).toBe('-$2.50')
  })

  it('shows a price per kilogram, not per gram', () => {
    // A per-gram figure rounds to $0.00 for almost everything in the pantry.
    expect(formatCostPerKg(250)).toBe('$2.50/kg')
    expect(formatCostPerKg(null)).toBeNull()
  })
})

describe('formatQuantity', () => {
  it('renders thirds and halves as fractions a cook can read', () => {
    expect(formatQuantity(0.5)).toBe('½')
    expect(formatQuantity(1 / 3)).toBe('⅓')
    expect(formatQuantity(1.5)).toBe('1½')
  })

  it('falls back to a trimmed decimal', () => {
    expect(formatQuantity(2)).toBe('2')
    expect(formatQuantity(1.75)).toBe('1¾')
    expect(formatQuantity(null)).toBe('')
  })
})

describe('formatRelative', () => {
  const daysAgo = (n) => new Date(Date.now() - n * 86_400_000).toISOString().slice(0, 10)

  it('describes recent dates in days', () => {
    expect(formatRelative(daysAgo(0))).toBe('today')
    expect(formatRelative(daysAgo(1))).toBe('yesterday')
    expect(formatRelative(daysAgo(5))).toBe('5 days ago')
  })

  it('switches to months and years', () => {
    expect(formatRelative(daysAgo(90))).toBe('3 months ago')
    expect(formatRelative(daysAgo(800))).toBe('2 years ago')
  })

  it('handles nothing and nonsense', () => {
    expect(formatRelative(null)).toBeNull()
    expect(formatRelative('not a date')).toBeNull()
  })
})

describe('formatPercent', () => {
  it('rounds a fraction', () => {
    expect(formatPercent(0.756)).toBe('76%')
    expect(formatPercent(0)).toBe('0%')
    expect(formatPercent(null)).toBe('0%')
  })
})
