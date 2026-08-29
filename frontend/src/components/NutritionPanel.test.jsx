import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import NutritionPanel from './NutritionPanel'

const whole = {
  energy_kj: 4200,
  calories_kcal: 1000,
  protein_g: 20.4,
  fat_g: 10,
  saturated_fat_g: null,
  carbs_g: 50.25,
  sugars_g: null,
  fibre_g: 5,
  sodium_mg: 300,
  coverage: 0.95,
  covered_grams: 950,
  total_grams: 1000,
}

const perServing = { ...whole, calories_kcal: 250, coverage: 0.95, covered_grams: 237.5, total_grams: 250 }

describe('NutritionPanel', () => {
  it('renders nothing when there is no data at all', () => {
    const { container } = render(<NutritionPanel whole={null} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows a fallback message when every field is empty', () => {
    render(<NutritionPanel whole={{ coverage: 0, covered_grams: 0, total_grams: 100 }} />)
    expect(screen.getByText(/Nothing to show yet/)).toBeDefined()
  })

  it('renders whole-recipe rows and coverage, with no toggle when there is no per-serving data', () => {
    render(<NutritionPanel whole={whole} />)
    expect(screen.getByText('Protein')).toBeDefined()
    expect(screen.getByText('20.4')).toBeDefined()
    expect(screen.queryByText('Per serving')).toBeNull()
    expect(screen.getByText(/Covers 95% of the recipe by weight/)).toBeDefined()
  })

  it('omits rows with no value for that ingredient set', () => {
    render(<NutritionPanel whole={whole} />)
    expect(screen.queryByText('— saturated')).toBeNull()
    expect(screen.queryByText('— sugars')).toBeNull()
  })

  it('shows the low-coverage hint under 90%, and hides it at or above', () => {
    const { rerender } = render(<NutritionPanel whole={{ ...whole, coverage: 0.5 }} />)
    expect(screen.getByText(/Add data for the remaining ingredients/)).toBeDefined()

    rerender(<NutritionPanel whole={{ ...whole, coverage: 0.9 }} />)
    expect(screen.queryByText(/Add data for the remaining ingredients/)).toBeNull()
  })

  it('toggles between per-serving and whole-recipe figures when both are given', () => {
    render(<NutritionPanel whole={whole} perServing={perServing} />)
    // Defaults to per-serving.
    expect(screen.getByText('250')).toBeDefined()

    fireEvent.click(screen.getByRole('button', { name: 'Whole recipe' }))
    expect(screen.getByText('1000')).toBeDefined()

    fireEvent.click(screen.getByRole('button', { name: 'Per serving' }))
    expect(screen.getByText('250')).toBeDefined()
  })
})
