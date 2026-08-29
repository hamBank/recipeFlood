import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api'
import CookListsPage from './CookListsPage'

vi.mock('../api', () => ({
  createCookList: vi.fn(),
  listCookLists: vi.fn(),
}))

const row = (overrides = {}) => ({
  id: 1,
  cook_date: '2026-01-05T00:00:00Z',
  description: null,
  recipe_count: 2,
  completed: false,
  ...overrides,
})

const renderPage = () =>
  render(
    <MemoryRouter>
      <CookListsPage />
    </MemoryRouter>
  )

const originalLocation = window.location
let assignSpy

beforeEach(() => {
  vi.clearAllMocks()
  api.listCookLists.mockResolvedValue({ items: [], total: 0 })
  assignSpy = vi.fn()
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { ...originalLocation, assign: assignSpy },
  })
})

afterEach(() => {
  Object.defineProperty(window, 'location', { configurable: true, value: originalLocation })
})

describe('CookListsPage', () => {
  it('shows the empty state when there are no lists', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText(/No cooking lists yet/)).toBeDefined())
  })

  it('lists cooking lists by date, with a recipe count when there is no description', async () => {
    api.listCookLists.mockResolvedValue({ items: [row()], total: 1 })
    renderPage()
    await waitFor(() => expect(screen.getByText('2 recipes')).toBeDefined())
    expect(screen.getByRole('link').getAttribute('href')).toBe('/cooking/1')
  })

  it('shows the description instead of the count when one is set, plus the count alongside it', async () => {
    api.listCookLists.mockResolvedValue({ items: [row({ description: 'Meal prep week' })], total: 1 })
    renderPage()
    await waitFor(() => expect(screen.getByText('Meal prep week')).toBeDefined())
    expect(screen.getByText('2 recipes')).toBeDefined()
  })

  it('flags a completed list', async () => {
    api.listCookLists.mockResolvedValue({ items: [row({ completed: true })], total: 1 })
    renderPage()
    await waitFor(() => expect(screen.getByText('completed')).toBeDefined())
  })

  it('re-fetches with include_completed when the checkbox is toggled', async () => {
    renderPage()
    await waitFor(() => expect(api.listCookLists).toHaveBeenCalledTimes(1))
    expect(api.listCookLists.mock.calls[0][0]).toMatchObject({ include_completed: '' })

    fireEvent.click(screen.getByRole('checkbox', { name: 'Show completed' }))
    await waitFor(() => expect(api.listCookLists).toHaveBeenCalledTimes(2))
    expect(api.listCookLists.mock.calls[1][0]).toMatchObject({ include_completed: 'true' })
  })

  it('shows pagination only once there is more than one page', async () => {
    api.listCookLists.mockResolvedValue({ items: [row()], total: 1 })
    renderPage()
    await waitFor(() => expect(screen.getByText('2 recipes')).toBeDefined())
    expect(screen.queryByRole('button', { name: 'Newer' })).toBeNull()
  })

  it('pages forward and back, disabling at the edges', async () => {
    api.listCookLists.mockResolvedValue({ items: [row()], total: 60 })
    renderPage()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Newer' })).toBeDefined())

    expect(screen.getByRole('button', { name: 'Newer' }).disabled).toBe(true)
    expect(screen.getByRole('button', { name: 'Older' }).disabled).toBe(false)

    fireEvent.click(screen.getByRole('button', { name: 'Older' }))
    await waitFor(() => expect(api.listCookLists).toHaveBeenCalledTimes(2))
    expect(api.listCookLists.mock.calls[1][0]).toMatchObject({ offset: 30 })
  })

  it('creates a new list and navigates to it', async () => {
    api.createCookList.mockResolvedValue({ id: 99 })
    renderPage()
    await waitFor(() => expect(api.listCookLists).toHaveBeenCalled())

    fireEvent.click(screen.getByRole('button', { name: 'New list' }))
    await waitFor(() => expect(assignSpy).toHaveBeenCalledWith('/cooking/99'))
  })

  it('shows an error and re-enables the button when creation fails', async () => {
    api.createCookList.mockRejectedValue(new Error('server down'))
    renderPage()
    await waitFor(() => expect(api.listCookLists).toHaveBeenCalled())

    fireEvent.click(screen.getByRole('button', { name: 'New list' }))
    await waitFor(() => expect(screen.getByText('server down')).toBeDefined())
    expect(screen.getByRole('button', { name: 'New list' }).disabled).toBe(false)
  })
})
