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

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  setOnline(true)
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
