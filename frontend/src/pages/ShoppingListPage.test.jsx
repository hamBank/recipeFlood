import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
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

describe('ShoppingListPage printing', () => {
  beforeEach(() => {
    window.print = vi.fn()
  })

  it('has no Print button when the list is empty', async () => {
    api.getShoppingList.mockResolvedValue(baseList([]))
    render(<ShoppingListPage />)
    await screen.findByText('Nothing on the list. Add something above, or send a cooking list here.')
    expect(screen.queryByRole('button', { name: 'Print' })).toBeNull()
  })

  it('is not in the DOM until printing starts', async () => {
    api.getShoppingList.mockResolvedValue(baseList([item()]))
    render(<ShoppingListPage />)
    await screen.findByRole('button', { name: 'Print' })
    // "Milk" only appears once — the on-screen row — not a second,
    // always-present copy in a print-only wrapper.
    expect(screen.getAllByText('Milk')).toHaveLength(1)
  })

  it('shows every item grouped by shop, including ones Show ticked is hiding, with full details, and calls window.print', async () => {
    api.getShoppingList.mockResolvedValue(
      baseList([
        item({
          id: 1,
          name: 'Milk',
          shop: 'supermarket',
          amount_text: '2 L',
          cost_cents: 350,
          contributions: [{ recipe: 'Pancakes', amount: '500 ml' }],
        }),
        item({ id: 2, name: 'Salmon', shop: 'butcher', is_checked: true, amount_text: '400 g' }),
      ]),
    )
    render(<ShoppingListPage />)
    await screen.findByText('Milk')

    // Hide ticked items on screen — the print view should ignore this.
    fireEvent.click(screen.getByRole('checkbox', { name: 'Show ticked' }))
    expect(screen.queryByText('Salmon')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Print' }))

    expect(window.print).toHaveBeenCalledTimes(1)
    expect(screen.getByText('Shopping list')).toBeDefined()
    // "Supermarket" and "2 L" etc. now legitimately appear twice — the
    // normal on-screen row plus the printable copy, both really in the
    // DOM at once (only CSS decides which one paper sees).
    expect(screen.getAllByText('Supermarket').length).toBeGreaterThan(0)
    expect(screen.getByText('Butcher')).toBeDefined() // Butcher only on the print side — Salmon was hidden on screen
    expect(screen.getAllByText('Salmon')).toHaveLength(1) // back, for print
    expect(screen.getAllByText('2 L').length).toBeGreaterThan(0)
    expect(screen.getAllByText('$3.50').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Pancakes (500 ml)').length).toBeGreaterThan(0)
  })

  it('drops the printable list again once the print dialog closes', async () => {
    api.getShoppingList.mockResolvedValue(baseList([item()]))
    render(<ShoppingListPage />)
    await screen.findByText('Milk')

    fireEvent.click(screen.getByRole('button', { name: 'Print' }))
    expect(screen.getByText('Shopping list')).toBeDefined()

    fireEvent(window, new Event('afterprint'))
    expect(screen.queryByText('Shopping list')).toBeNull()
  })
})

describe('ShoppingListPage editing', () => {
  it('edits a bare item into a quantity, and can be cancelled without saving', async () => {
    api.getShoppingList.mockResolvedValue(baseList([item()]))
    render(<ShoppingListPage />)
    await screen.findByText('Milk')

    fireEvent.click(screen.getByRole('button', { name: 'Edit Milk' }))
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDefined()

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(api.updateShoppingItem).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Edit Milk' })).toBeDefined()
  })

  it('overrides a weight amount', async () => {
    api.getShoppingList.mockResolvedValue(baseList([item({ weight_grams: 500, amount_text: '500 g' })]))
    api.updateShoppingItem.mockResolvedValue({})
    render(<ShoppingListPage />)
    await screen.findByText('Milk')

    fireEvent.click(screen.getByRole('button', { name: 'Edit Milk' }))
    const weightInput = screen.getByLabelText('Weight')
    expect(weightInput.value).toBe('500')

    fireEvent.change(weightInput, { target: { value: '750' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(api.updateShoppingItem).toHaveBeenCalledWith(1, { shop_override: null, weight_grams: 750 }),
    )
  })

  it('sets a quantity and unit on a bare item', async () => {
    api.getShoppingList.mockResolvedValue(baseList([item()]))
    api.updateShoppingItem.mockResolvedValue({})
    render(<ShoppingListPage />)
    await screen.findByText('Milk')

    fireEvent.click(screen.getByRole('button', { name: 'Edit Milk' }))
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText('Unit'), { target: { value: 'piece' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(api.updateShoppingItem).toHaveBeenCalledWith(1, {
        shop_override: null,
        quantity: 3,
        unit: 'piece',
      }),
    )
  })

  it('moves an item to a different shop, and shows it was moved by hand', async () => {
    api.getShoppingList.mockResolvedValue(baseList([item()]))
    api.updateShoppingItem.mockResolvedValue({})
    render(<ShoppingListPage />)
    await screen.findByText('Milk')

    fireEvent.click(screen.getByRole('button', { name: 'Edit Milk' }))
    fireEvent.change(screen.getByLabelText('Shop'), { target: { value: 'butcher' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(api.updateShoppingItem).toHaveBeenCalledWith(1, {
        shop_override: 'butcher',
        quantity: null,
        unit: null,
      }),
    )
  })

  it('shows a "(moved)" marker for an item with an active override', async () => {
    api.getShoppingList.mockResolvedValue(baseList([item({ shop_override: 'butcher' })]))
    render(<ShoppingListPage />)
    expect(await screen.findByText('(moved)')).toBeDefined()
  })

  it('does not offer editing while offline', async () => {
    setOnline(false)
    saveCachedList(baseList([item()]))
    api.getShoppingList.mockRejectedValue(offlineError())
    render(<ShoppingListPage />)
    await screen.findByText('Milk')

    expect(screen.getByRole('button', { name: 'Edit Milk' }).disabled).toBe(true)
  })
})

describe('ShoppingListPage reconnecting', () => {
  it('retries a stuck offline queue on its own, without a real online event', async () => {
    // Genuinely online throughout (navigator.onLine never flips) — this
    // covers a transient failure, like a deploy restarting the backend
    // mid-request, that latches `offline` without a real connectivity
    // drop, so the browser's own 'online' event never fires to clear it.
    vi.useFakeTimers()
    try {
      api.getShoppingList.mockResolvedValueOnce(baseList([item()]))
      render(<ShoppingListPage />)
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0)
      })
      expect(screen.getByText('Milk')).toBeDefined()

      // The backend stays unreachable (network-level failures) through the
      // tick, the reload it triggers, and the immediate re-attempt the
      // queue update itself provokes.
      api.updateShoppingItem.mockRejectedValue(offlineError())
      api.getShoppingList.mockRejectedValue(offlineError())
      await act(async () => {
        fireEvent.click(screen.getByLabelText('Tick off Milk'))
        await vi.advanceTimersByTimeAsync(0)
      })
      expect(screen.getByText(/Offline/)).toBeDefined()

      // The UI reverted to the (unticked) cached copy, so tapping it again
      // now goes through the offline path and queues the tick locally.
      await act(async () => {
        fireEvent.click(screen.getByLabelText('Tick off Milk'))
        await vi.advanceTimersByTimeAsync(0)
      })
      expect(loadQueue()).toEqual([{ type: 'check', itemId: 1 }])

      // The backend is reachable again by the time the automatic retry
      // fires — no page reload, and no real online event, involved.
      api.updateShoppingItem.mockResolvedValue({})
      api.getShoppingList.mockResolvedValue(baseList([item({ is_checked: true })]))
      await act(async () => {
        await vi.advanceTimersByTimeAsync(20000)
      })

      expect(api.updateShoppingItem).toHaveBeenLastCalledWith(1, { is_checked: true })
      expect(loadQueue()).toEqual([])
      expect(screen.queryByText(/Offline/)).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })

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
