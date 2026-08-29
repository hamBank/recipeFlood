import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import CostPanel from './CostPanel'

describe('CostPanel', () => {
  it('renders nothing when there is no cost (guest view)', () => {
    const { container } = render(<CostPanel cost={null} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows the total and priced-ingredient fraction', () => {
    render(
      <CostPanel
        cost={{
          total_cents: 1234,
          per_serving_cents: null,
          priced_count: 3,
          ingredient_count: 5,
          known_fraction: 0.6,
        }}
      />
    )
    expect(screen.getByText(/\$12\.34/)).toBeDefined()
    expect(screen.getByText(/3 of 5 ingredients priced/)).toBeDefined()
    expect(screen.getByText(/Add prices on the Pantry page to complete this\./)).toBeDefined()
  })

  it('marks the total as "at least" when incomplete, and drops the hint once complete', () => {
    const { rerender } = render(
      <CostPanel
        cost={{ total_cents: 500, per_serving_cents: null, priced_count: 1, ingredient_count: 2, known_fraction: 0.5 }}
      />
    )
    expect(screen.getByText(/at least/)).toBeDefined()

    rerender(
      <CostPanel
        cost={{ total_cents: 500, per_serving_cents: null, priced_count: 2, ingredient_count: 2, known_fraction: 1 }}
      />
    )
    expect(screen.queryByText(/at least/)).toBeNull()
    expect(screen.queryByText(/Add prices/)).toBeNull()
  })

  it('shows per-serving cost when present, using the given currency symbol', () => {
    render(
      <CostPanel
        symbol="€"
        cost={{ total_cents: 2000, per_serving_cents: 500, priced_count: 4, ingredient_count: 4, known_fraction: 1 }}
      />
    )
    expect(screen.getByText('€20.00')).toBeDefined()
    expect(screen.getByText(/€5.00 per serving/)).toBeDefined()
  })
})
