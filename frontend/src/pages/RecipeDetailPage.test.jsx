import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api'
import RecipeDetailPage from './RecipeDetailPage'

vi.mock('../api', () => ({
  getRecipe: vi.fn(),
  deleteRecipe: vi.fn(),
  markPrepared: vi.fn(),
  deletePrepared: vi.fn(),
  generateRecipeImage: vi.fn(),
  listCookLists: vi.fn().mockResolvedValue({ items: [] }),
}))

let sessionUser = { id: 1, name: 'Dev Admin', role: 'admin' }
vi.mock('../App', () => ({
  useSession: () => ({ user: sessionUser, config: { currency_symbol: '$' } }),
}))

const recipe = (overrides = {}) => ({
  id: 1,
  slug: 'soup',
  title: 'Soup',
  description: null,
  image_path: null,
  image_generated: false,
  sections: [],
  tags: [],
  needs_review: false,
  review_note: null,
  prep_minutes: null,
  cook_minutes: null,
  total_minutes: null,
  servings: null,
  servings_note: null,
  added_date: null,
  last_prepared_on: null,
  prepared_count: 0,
  prepared_events: [],
  ingredients: [],
  steps: [],
  storage: null,
  nutrition_note: null,
  cost: null,
  nutrition: null,
  nutrition_per_serving: null,
  source_url: null,
  source_name: null,
  ...overrides,
})

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/recipes/soup']}>
      <Routes>
        <Route path="/recipes/:slug" element={<RecipeDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  api.listCookLists.mockResolvedValue({ items: [] })
  sessionUser = { id: 1, name: 'Dev Admin', role: 'admin' }
})

describe('RecipeDetailPage generate image button', () => {
  it('shows the button when the recipe has no photo', async () => {
    api.getRecipe.mockResolvedValue(recipe())
    renderPage()
    expect(await screen.findByText('Generate image')).toBeDefined()
  })

  it('does not show the button once the recipe has a photo', async () => {
    api.getRecipe.mockResolvedValue(recipe({ image_path: 'recipes/soup.jpg' }))
    renderPage()
    await screen.findByText('Soup')
    expect(screen.queryByText('Generate image')).toBeNull()
  })

  it('does not show the button to a signed-out visitor', async () => {
    sessionUser = null
    api.getRecipe.mockResolvedValue(recipe())
    renderPage()
    await screen.findByText('Soup')
    expect(screen.queryByText('Generate image')).toBeNull()
  })

  it('clicking it calls the API and replaces the recipe with the response', async () => {
    api.getRecipe.mockResolvedValue(recipe())
    api.generateRecipeImage.mockResolvedValue(
      recipe({ image_path: 'recipes/soup.png', image_generated: true }),
    )
    renderPage()
    fireEvent.click(await screen.findByText('Generate image'))

    expect(await screen.findByAltText('')).toHaveProperty('src', expect.stringContaining('/media/recipes/soup.png'))
    expect(screen.queryByText('Generate image')).toBeNull()
    expect(api.generateRecipeImage).toHaveBeenCalledWith('soup')
  })

  it('shows an error message and keeps the button when generation fails', async () => {
    api.getRecipe.mockResolvedValue(recipe())
    api.generateRecipeImage.mockRejectedValue(new Error('OPENAI_API_KEY is not set'))
    renderPage()
    fireEvent.click(await screen.findByText('Generate image'))

    expect(await screen.findByText('OPENAI_API_KEY is not set')).toBeDefined()
    expect(screen.getByText('Generate image')).toBeDefined()
  })

  it('disables the button while a generation is in flight', async () => {
    api.getRecipe.mockResolvedValue(recipe())
    let resolveGenerate
    api.generateRecipeImage.mockReturnValue(
      new Promise((resolve) => {
        resolveGenerate = resolve
      }),
    )
    renderPage()
    fireEvent.click(await screen.findByText('Generate image'))
    const button = await screen.findByText('Generating…')
    expect(button.closest('button').disabled).toBe(true)

    resolveGenerate(recipe({ image_path: 'recipes/soup.png' }))
    await waitFor(() => expect(screen.queryByText('Generating…')).toBeNull())
  })
})
