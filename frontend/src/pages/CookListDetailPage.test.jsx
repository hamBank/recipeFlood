import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api'
import CookListDetailPage from './CookListDetailPage'

vi.mock('../api', () => ({
  getCookList: vi.fn(),
  createCookList: vi.fn(),
  updateCookList: vi.fn(),
  deleteCookList: vi.fn(),
  addRecipeToCookList: vi.fn(),
  removeRecipeFromCookList: vi.fn(),
  updateCookListRecipe: vi.fn(),
  addCookListToShopping: vi.fn(),
  listRecipes: vi.fn().mockResolvedValue({ items: [] }),
}))

const recipeRow = (overrides = {}) => ({
  id: 1,
  recipe_id: 1,
  position: 0,
  servings: null,
  note: null,
  completed: false,
  slug: 'soup',
  title: 'Soup',
  image_path: null,
  base_servings: 4,
  scalable: true,
  scale_factor: 1,
  ...overrides,
})

const cookList = (recipes) => ({
  id: 1,
  cook_date: '2026-08-24',
  description: null,
  notes: null,
  completed: false,
  created_at: '2026-08-24T00:00:00Z',
  updated_at: '2026-08-24T00:00:00Z',
  recipe_count: recipes.length,
  recipes,
})

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/cooking/1']}>
      <Routes>
        <Route path="/cooking/:id" element={<CookListDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('CookListDetailPage completing a recipe', () => {
  it('renders an unchecked, non-struck-through recipe by default', async () => {
    api.getCookList.mockResolvedValue(cookList([recipeRow()]))
    renderPage()
    const checkbox = await screen.findByLabelText('Mark Soup cooked')
    expect(checkbox.checked).toBe(false)
    expect(screen.getByText('Soup').className).not.toContain('line-through')
  })

  it('renders a completed recipe checked and struck through', async () => {
    api.getCookList.mockResolvedValue(cookList([recipeRow({ completed: true })]))
    renderPage()
    const checkbox = await screen.findByLabelText('Mark Soup cooked')
    expect(checkbox.checked).toBe(true)
    expect(screen.getByText('Soup').className).toContain('line-through')
  })

  it('ticking a recipe calls the API with completed: true', async () => {
    api.getCookList.mockResolvedValue(cookList([recipeRow()]))
    api.updateCookListRecipe.mockResolvedValue(cookList([recipeRow({ completed: true })]))
    renderPage()
    fireEvent.click(await screen.findByLabelText('Mark Soup cooked'))
    await waitFor(() =>
      expect(api.updateCookListRecipe).toHaveBeenCalledWith('1', 1, { completed: true }),
    )
    await waitFor(() => expect(api.getCookList).toHaveBeenCalledTimes(2))
  })

  it('unticking an already-completed recipe calls the API with completed: false', async () => {
    api.getCookList.mockResolvedValue(cookList([recipeRow({ completed: true })]))
    api.updateCookListRecipe.mockResolvedValue(cookList([recipeRow({ completed: false })]))
    renderPage()
    fireEvent.click(await screen.findByLabelText('Mark Soup cooked'))
    await waitFor(() =>
      expect(api.updateCookListRecipe).toHaveBeenCalledWith('1', 1, { completed: false }),
    )
    await waitFor(() => expect(api.getCookList).toHaveBeenCalledTimes(2))
  })

  it('renders whatever order the server returns, completed last', async () => {
    // Sorting itself is the backend's job (backend/cook_lists.py) — this
    // page just renders list.recipes in order, so a completed-last
    // response should render completed-last.
    api.getCookList.mockResolvedValue(
      cookList([
        recipeRow({ id: 2, recipe_id: 2, slug: 'stew', title: 'Stew' }),
        recipeRow({ id: 1, recipe_id: 1, title: 'Soup', completed: true }),
      ]),
    )
    renderPage()
    await screen.findByText('Stew')
    const titles = screen
      .getAllByRole('link')
      .map((el) => el.textContent)
      .filter((text) => text === 'Stew' || text === 'Soup')
    expect(titles).toEqual(['Stew', 'Soup'])
  })
})
