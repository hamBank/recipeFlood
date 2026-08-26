import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api'
import PantryPage from './PantryPage'

vi.mock('../api', () => ({
  listIngredients: vi.fn(),
  createIngredient: vi.fn(),
  updateIngredient: vi.fn(),
  mergeIngredients: vi.fn(),
}))

let sessionConfig = { currency_symbol: '$', pantry_multi_merge: false }
vi.mock('../App', () => ({
  useSession: () => ({ config: sessionConfig }),
}))

const item = (overrides = {}) => ({
  id: 1,
  slug: 'onion',
  name: 'Onion',
  is_food: true,
  aliases: [],
  recipe_count: 0,
  measure_kind: 'weight',
  package_size_grams: null,
  package_size_ml: null,
  cost_per_kg_cents: null,
  cost_per_litre_cents: null,
  cost_source: null,
  package_cost_cents: null,
  source: 'supermarket',
  has_nutrition: false,
  nutrition_source: null,
  ...overrides,
})

beforeEach(() => {
  vi.clearAllMocks()
  sessionConfig = { currency_symbol: '$', pantry_multi_merge: false }
})

describe('PantryPage multi-merge (flag off)', () => {
  it('shows no checkboxes when the flag is off', async () => {
    api.listIngredients.mockResolvedValue({ items: [item()], total: 1 })
    render(<PantryPage />)
    await screen.findByText('Onion')
    expect(screen.queryByLabelText('Select Onion for merging')).toBeNull()
  })
})

describe('PantryPage multi-merge (flag on)', () => {
  beforeEach(() => {
    sessionConfig = { currency_symbol: '$', pantry_multi_merge: true }
  })

  it('shows a checkbox per row', async () => {
    api.listIngredients.mockResolvedValue({ items: [item()], total: 1 })
    render(<PantryPage />)
    expect(await screen.findByLabelText('Select Onion for merging')).toBeDefined()
  })

  it('selecting one item shows the count but no merge button yet', async () => {
    api.listIngredients.mockResolvedValue({ items: [item()], total: 1 })
    render(<PantryPage />)
    fireEvent.click(await screen.findByLabelText('Select Onion for merging'))
    expect(await screen.findByText(/1 selected/)).toBeDefined()
    expect(screen.queryByText(/Keep this \(merge/)).toBeNull()
  })

  it('selecting two items shows a "Keep this" merge button on each', async () => {
    const rows = [item(), item({ id: 2, slug: 'onions', name: 'Onions' })]
    api.listIngredients.mockResolvedValue({ items: rows, total: 2 })
    render(<PantryPage />)
    fireEvent.click(await screen.findByLabelText('Select Onion for merging'))
    fireEvent.click(await screen.findByLabelText('Select Onions for merging'))

    expect(await screen.findByText(/2 selected/)).toBeDefined()
    expect(screen.getAllByText('Keep this (merge 1)')).toHaveLength(2)
  })

  it('confirming the merge calls mergeIngredients with the right target and reloads', async () => {
    const rows = [item(), item({ id: 2, slug: 'onions', name: 'Onions' })]
    api.listIngredients.mockResolvedValue({ items: rows, total: 2 })
    api.mergeIngredients.mockResolvedValue(item())
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<PantryPage />)
    fireEvent.click(await screen.findByLabelText('Select Onion for merging'))
    fireEvent.click(await screen.findByLabelText('Select Onions for merging'))
    fireEvent.click(screen.getAllByText('Keep this (merge 1)')[0])

    await waitFor(() =>
      expect(api.mergeIngredients).toHaveBeenCalledWith('onion', 'onions'),
    )
    await waitFor(() => expect(api.listIngredients).toHaveBeenCalledTimes(2))
    // Selection clears once the merge completes.
    expect(screen.queryByText(/selected/)).toBeNull()
  })

  it('declining the confirmation does not merge anything', async () => {
    const rows = [item(), item({ id: 2, slug: 'onions', name: 'Onions' })]
    api.listIngredients.mockResolvedValue({ items: rows, total: 2 })
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    render(<PantryPage />)
    fireEvent.click(await screen.findByLabelText('Select Onion for merging'))
    fireEvent.click(await screen.findByLabelText('Select Onions for merging'))
    fireEvent.click(screen.getAllByText('Keep this (merge 1)')[0])

    expect(api.mergeIngredients).not.toHaveBeenCalled()
  })
})
