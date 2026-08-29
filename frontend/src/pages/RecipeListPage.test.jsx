import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api'
import RecipeListPage from './RecipeListPage'

vi.mock('../api', () => ({
  listCookLists: vi.fn(),
  listRecipes: vi.fn(),
  listSections: vi.fn(),
  listTags: vi.fn(),
}))

let sessionUser = null
vi.mock('../App', () => ({
  useSession: () => ({ user: sessionUser }),
}))

const recipe = (overrides = {}) => ({
  id: 1,
  slug: 'flax-bread',
  title: 'Flax Bread',
  description: '',
  image_path: null,
  added_date: '2014-01-11T00:00:00Z',
  total_minutes: 45,
  servings: 8,
  tags: [],
  sections: [],
  last_prepared_on: null,
  prepared_count: 0,
  needs_review: false,
  is_published: true,
  ...overrides,
})

const renderPage = (initialEntry = '/') =>
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <RecipeListPage />
    </MemoryRouter>
  )

beforeEach(() => {
  vi.clearAllMocks()
  sessionUser = null
  api.listSections.mockResolvedValue([])
  api.listTags.mockResolvedValue([])
  api.listCookLists.mockResolvedValue({ items: [] })
  api.listRecipes.mockResolvedValue({ items: [recipe()], total: 1 })
})

describe('RecipeListPage', () => {
  it('loads recipes and shows the count', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('Flax Bread')).toBeDefined())
    expect(screen.getByText('1 recipe')).toBeDefined()
  })

  it('shows the empty state when there are no results', async () => {
    api.listRecipes.mockResolvedValue({ items: [], total: 0 })
    renderPage()
    await waitFor(() => expect(screen.getByText('Nothing here yet.')).toBeDefined())
  })

  it('surfaces an error from the recipe fetch', async () => {
    api.listRecipes.mockRejectedValue(new Error('server down'))
    renderPage()
    await waitFor(() => expect(screen.getByText('server down')).toBeDefined())
  })

  it('does not fetch a cook list for a guest', async () => {
    renderPage()
    await waitFor(() => expect(api.listRecipes).toHaveBeenCalled())
    expect(api.listCookLists).not.toHaveBeenCalled()
  })

  it('fetches the most recent cook list once signed in', async () => {
    sessionUser = { id: 1, name: 'Foobie' }
    renderPage()
    await waitFor(() => expect(api.listCookLists).toHaveBeenCalled())
  })

  it('only shows the Needs review checkbox to a signed-in user', async () => {
    renderPage()
    await waitFor(() => expect(api.listRecipes).toHaveBeenCalled())
    expect(screen.queryByText('Needs review')).toBeNull()

    sessionUser = { id: 1, name: 'Foobie' }
    renderPage()
    await waitFor(() => expect(screen.getByText('Needs review')).toBeDefined())
  })

  it('searches by updating the URL, which re-fetches with q', async () => {
    renderPage()
    await waitFor(() => expect(api.listRecipes).toHaveBeenCalledTimes(1))

    fireEvent.change(screen.getByPlaceholderText('Search recipes…'), { target: { value: 'bread' } })
    fireEvent.submit(screen.getByPlaceholderText('Search recipes…').closest('form'))

    await waitFor(() => expect(api.listRecipes).toHaveBeenCalledTimes(2))
    expect(api.listRecipes.mock.calls[1][0]).toMatchObject({ q: 'bread' })
  })

  it('filters by section', async () => {
    api.listSections.mockResolvedValue([{ slug: 'bread', name: 'Bread', recipe_count: 3 }])
    renderPage()
    await waitFor(() => expect(screen.getByText('Bread (3)')).toBeDefined())

    fireEvent.change(screen.getByDisplayValue('All sections'), { target: { value: 'bread' } })
    await waitFor(() => expect(api.listRecipes).toHaveBeenCalledTimes(2))
    expect(api.listRecipes.mock.calls[1][0]).toMatchObject({ tag: 'bread' })
  })

  it('adds a tag filter from the chip row and can clear it', async () => {
    api.listTags.mockResolvedValue([{ slug: 'low-carb', name: 'Low carb', recipe_count: 5 }])
    renderPage()
    await waitFor(() => expect(screen.getByText('Low carb')).toBeDefined())

    fireEvent.click(screen.getByText('Low carb'))
    await waitFor(() => expect(api.listRecipes).toHaveBeenCalledTimes(2))
    expect(api.listRecipes.mock.calls[1][0]).toMatchObject({ tag: 'low-carb' })

    await waitFor(() => expect(screen.getByText('low-carb ✕')).toBeDefined())
    fireEvent.click(screen.getByText('low-carb ✕'))
    await waitFor(() => expect(api.listRecipes).toHaveBeenCalledTimes(3))
    expect(api.listRecipes.mock.calls[2][0]).toMatchObject({ tag: '' })
  })

  it('changes sort and resets order to ascending for title', async () => {
    renderPage()
    await waitFor(() => expect(api.listRecipes).toHaveBeenCalledTimes(1))

    fireEvent.change(screen.getByDisplayValue('Recently added'), { target: { value: 'title' } })
    await waitFor(() => expect(api.listRecipes).toHaveBeenCalledTimes(2))
    expect(api.listRecipes.mock.calls[1][0]).toMatchObject({ sort: 'title', order: 'asc' })
  })

  it('pages forward, resetting when a filter changes', async () => {
    api.listRecipes.mockResolvedValue({ items: [recipe()], total: 100 })
    renderPage()
    await waitFor(() => expect(screen.getByText('Page 1 of 5')).toBeDefined())

    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(screen.getByText('Page 2 of 5')).toBeDefined())
    expect(api.listRecipes.mock.calls.at(-1)[0]).toMatchObject({ offset: 24 })
  })
})
