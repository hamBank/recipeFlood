import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api'
import { loadQueue, saveCachedList, saveQueue } from '../offlineQueue'
import ShoppingListPage from './ShoppingListPage'

vi.mock('../api', () => ({
  getShoppingList: vi.fn(),
  addShoppingItem: vi.fn(),
  updateShoppingItem: vi.fn(),
  deleteShoppingItem: vi.fn(),
  clearCheckedShopping: vi.fn(),
  uncheckAllShopping: vi.fn(),
  listIngredients: vi.fn(),
}))

const baseList = (items) => ({
  items,
  shops: [...new Set(items.map((i) => i.shop))],
  total_count: items.length,
  checked_count: items.filter((i) => i.is_checked).length,
  total_cents: null,
  priced_fraction: 0,
})

const item = (overrides = {}) => ({
  id: 1,
  name: 'Milk',
  shop: 'supermarket',
  is_checked: false,
  amount_text: '',
  cost_cents: null,
  contributions: [],
  ...overrides,
})

/** A rejection shaped like a network failure — no `.status`, same as what
 * `fetch` itself throws with no connection (see api.js's apiFetch). */
const offlineError = () => new Error('Failed to fetch')

function setOnline(value) {
  Object.defineProperty(navigator, 'onLine', { value, configurable: true, writable: true })
}

const ingredient = (overrides = {}) => ({
  id: 10,
  name: 'Milk',
  source: 'supermarket',
  ...overrides,
})

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  setOnline(true)
  api.listIngredients.mockResolvedValue({ items: [], total: 0 })
})

describe('ShoppingListPage online', () => {
  it('renders items from the server', async () => {
    api.getShoppingList.mockResolvedValue(baseList([item()]))
    render(<ShoppingListPage />)
    expect(await screen.findByText('Milk')).toBeDefined()
  })

  it('ticking an item calls the API and is not queued', async () => {
    api.getShoppingList.mockResolvedValue(baseList([item()]))
    api.updateShoppingItem.mockResolvedValue({})
    render(<ShoppingListPage />)
    fireEvent.click(await screen.findByLabelText('Tick off Milk'))
    await waitFor(() => expect(api.updateShoppingItem).toHaveBeenCalledWith(1, { is_checked: true }))
    expect(loadQueue()).toEqual([])
  })
})

describe('ShoppingListPage offline', () => {
  beforeEach(() => setOnline(false))

  it('falls back to the cached list and shows the offline banner', async () => {
    saveCachedList(baseList([item()]))
    api.getShoppingList.mockRejectedValue(offlineError())
    render(<ShoppingListPage />)
    expect(await screen.findByText('Milk')).toBeDefined()
    expect(screen.getByText(/Offline/)).toBeDefined()
  })

  it('renders a queue left over from a previous offline session', async () => {
    saveCachedList(baseList([item()]))
    saveQueue([{ type: 'add', name: 'Tofu', tempId: -1 }])
    api.getShoppingList.mockRejectedValue(offlineError())
    render(<ShoppingListPage />)
    expect(await screen.findByText('Tofu')).toBeDefined()
    expect(screen.getByText('not yet synced')).toBeDefined()
  })

  it('queues a tick instead of calling the API', async () => {
    saveCachedList(baseList([item()]))
    api.getShoppingList.mockRejectedValue(offlineError())
    render(<ShoppingListPage />)
    fireEvent.click(await screen.findByLabelText('Tick off Milk'))
    expect(api.updateShoppingItem).not.toHaveBeenCalled()
    expect(loadQueue()).toEqual([{ type: 'check', itemId: 1 }])
    expect((await screen.findByLabelText('Tick off Milk')).checked).toBe(true)
  })

  it('will not queue unticking an already-checked item', async () => {
    saveCachedList(baseList([item({ is_checked: true })]))
    api.getShoppingList.mockRejectedValue(offlineError())
    render(<ShoppingListPage />)
    const checkbox = await screen.findByLabelText('Tick off Milk')
    expect(checkbox.disabled).toBe(true)
    fireEvent.click(checkbox)
    expect(loadQueue()).toEqual([])
  })

  it('queues a new item as a pending row instead of calling the API', async () => {
    saveCachedList(baseList([item()]))
    api.getShoppingList.mockRejectedValue(offlineError())
    render(<ShoppingListPage />)
    await screen.findByText('Milk')
    fireEvent.change(screen.getByPlaceholderText('Add something…'), { target: { value: 'Tofu' } })
    fireEvent.click(screen.getByText('Add'))
    expect(api.addShoppingItem).not.toHaveBeenCalled()
    expect(await screen.findByText('Tofu')).toBeDefined()
    expect(screen.getByText('not yet synced')).toBeDefined()
    expect(loadQueue()).toEqual([{ type: 'add', name: 'Tofu', tempId: -1 }])
  })

  it('disables removing an item', async () => {
    saveCachedList(baseList([item()]))
    api.getShoppingList.mockRejectedValue(offlineError())
    render(<ShoppingListPage />)
    expect((await screen.findByLabelText('Remove Milk')).disabled).toBe(true)
  })

  it('disables the bulk clear/untick controls', async () => {
    saveCachedList(baseList([item({ is_checked: true })]))
    api.getShoppingList.mockRejectedValue(offlineError())
    render(<ShoppingListPage />)
    expect((await screen.findByText(/Clear 1 ticked/)).disabled).toBe(true)
    expect(screen.getByText('Untick all').disabled).toBe(true)
  })
})

describe('ShoppingListPage pantry search', () => {
  it('searches the pantry as the user types and shows matches in a dropdown', async () => {
    api.getShoppingList.mockResolvedValue(baseList([]))
    api.listIngredients.mockResolvedValue({ items: [ingredient()], total: 1 })
    render(<ShoppingListPage />)
    await screen.findByPlaceholderText('Add something…')

    fireEvent.change(screen.getByPlaceholderText('Add something…'), { target: { value: 'mil' } })

    await waitFor(() => expect(api.listIngredients).toHaveBeenCalledWith({ q: 'mil', sort: 'usage', limit: 8 }))
    expect(await screen.findByRole('option', { name: /Milk/ })).toBeDefined()
  })

  it('clicking a suggestion adds it immediately, matched to its pantry ingredient', async () => {
    api.getShoppingList.mockResolvedValue(baseList([]))
    api.listIngredients.mockResolvedValue({ items: [ingredient()], total: 1 })
    api.addShoppingItem.mockResolvedValue({})
    render(<ShoppingListPage />)
    await screen.findByPlaceholderText('Add something…')

    fireEvent.change(screen.getByPlaceholderText('Add something…'), { target: { value: 'mil' } })
    fireEvent.click(await screen.findByRole('option', { name: /Milk/ }))

    await waitFor(() =>
      expect(api.addShoppingItem).toHaveBeenCalledWith({ name: 'Milk', ingredient_id: 10 }),
    )
    expect(screen.getByPlaceholderText('Add something…').value).toBe('')
    expect(screen.queryByRole('listbox')).toBeNull()
  })

  it('picks the arrow-key-highlighted suggestion on Enter', async () => {
    api.getShoppingList.mockResolvedValue(baseList([]))
    api.listIngredients.mockResolvedValue({ items: [ingredient(), ingredient({ id: 11, name: 'Oat milk' })], total: 2 })
    api.addShoppingItem.mockResolvedValue({})
    render(<ShoppingListPage />)
    const input = await screen.findByPlaceholderText('Add something…')

    fireEvent.change(input, { target: { value: 'mil' } })
    await screen.findByRole('option', { name: /Oat milk/ })

    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.submit(input.closest('form'))

    await waitFor(() =>
      expect(api.addShoppingItem).toHaveBeenCalledWith({ name: 'Oat milk', ingredient_id: 11 }),
    )
  })

  it('closes the dropdown on Escape without adding anything', async () => {
    api.getShoppingList.mockResolvedValue(baseList([]))
    api.listIngredients.mockResolvedValue({ items: [ingredient()], total: 1 })
    render(<ShoppingListPage />)
    const input = await screen.findByPlaceholderText('Add something…')

    fireEvent.change(input, { target: { value: 'mil' } })
    await screen.findByRole('option', { name: /Milk/ })
    fireEvent.keyDown(input, { key: 'Escape' })

    expect(screen.queryByRole('listbox')).toBeNull()
  })

  it('does not search the pantry while offline', async () => {
    setOnline(false)
    saveCachedList(baseList([]))
    api.getShoppingList.mockRejectedValue(offlineError())
    render(<ShoppingListPage />)
    await screen.findByPlaceholderText('Add something…')

    fireEvent.change(screen.getByPlaceholderText('Add something…'), { target: { value: 'mil' } })
    await new Promise((resolve) => setTimeout(resolve, 300))

    expect(api.listIngredients).not.toHaveBeenCalled()
  })
})

describe('ShoppingListPage reconnecting', () => {
  it('drains the queue and reloads once back online', async () => {
    setOnline(false)
    saveCachedList(baseList([item()]))
    saveQueue([{ type: 'check', itemId: 1 }])
    api.getShoppingList.mockRejectedValue(offlineError())
    render(<ShoppingListPage />)
    await screen.findByText('Milk')

    api.getShoppingList.mockResolvedValue(baseList([item({ is_checked: true })]))
    api.updateShoppingItem.mockResolvedValue({})
    setOnline(true)
    fireEvent(window, new Event('online'))

    await waitFor(() => expect(api.updateShoppingItem).toHaveBeenCalledWith(1, { is_checked: true }))
    await waitFor(() => expect(loadQueue()).toEqual([]))
  })
})
