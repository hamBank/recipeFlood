import { beforeEach, describe, expect, it, vi } from 'vitest'
import { addShoppingItem, updateShoppingItem } from './api'
import { applyQueue, drainQueue, nextTempId } from './offlineQueue'

vi.mock('./api', () => ({
  addShoppingItem: vi.fn(),
  updateShoppingItem: vi.fn(),
}))

const list = (items, shops = ['supermarket']) => ({
  items,
  shops,
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

beforeEach(() => {
  vi.clearAllMocks()
})

describe('nextTempId', () => {
  it('starts at -1 for an empty list', () => {
    expect(nextTempId(list([]))).toBe(-1)
  })

  it('goes below every real id already on the list', () => {
    expect(nextTempId(list([item({ id: 1 }), item({ id: 7 })]))).toBe(-1)
  })

  it('goes below an earlier not-yet-synced item too', () => {
    expect(nextTempId(list([item({ id: -1 }), item({ id: -2 })]))).toBe(-3)
  })

  it('copes with no list at all', () => {
    expect(nextTempId(null)).toBe(-1)
  })
})

describe('applyQueue', () => {
  it('passes null through unchanged', () => {
    expect(applyQueue(null, [{ type: 'check', itemId: 1 }])).toBeNull()
  })

  it('leaves the list alone with an empty queue', () => {
    const base = list([item()])
    expect(applyQueue(base, [])).toEqual(base)
  })

  it('a "check" entry flips only the matching item', () => {
    const base = list([item({ id: 1 }), item({ id: 2 })])
    const result = applyQueue(base, [{ type: 'check', itemId: 1 }])
    expect(result.items.find((i) => i.id === 1).is_checked).toBe(true)
    expect(result.items.find((i) => i.id === 2).is_checked).toBe(false)
    expect(result.checked_count).toBe(1)
  })

  it('a checked item sinks below the still-unchecked ones, like the server sorts it', () => {
    const base = list([
      item({ id: 1, name: 'Apples' }),
      item({ id: 2, name: 'Bread' }),
      item({ id: 3, name: 'Carrots' }),
    ])
    const result = applyQueue(base, [{ type: 'check', itemId: 1 }])
    expect(result.items.map((i) => i.name)).toEqual(['Bread', 'Carrots', 'Apples'])
  })

  it('an "add" entry appends a pending row under "other"', () => {
    const base = list([item()])
    const result = applyQueue(base, [{ type: 'add', name: 'Tofu', tempId: -1 }])
    expect(result.items).toHaveLength(2)
    const added = result.items.find((i) => i.id === -1)
    expect(added).toMatchObject({ name: 'Tofu', shop: 'other', is_checked: false, pendingSync: true })
    expect(result.shops).toContain('other')
    expect(result.total_count).toBe(2)
  })

  it('does not duplicate "other" in shops when it is already there', () => {
    const base = list([item({ shop: 'other' })], ['other'])
    const result = applyQueue(base, [{ type: 'add', name: 'Tofu', tempId: -1 }])
    expect(result.shops.filter((s) => s === 'other')).toHaveLength(1)
  })

  it('applies several queued entries in order', () => {
    const base = list([item({ id: 1 })])
    const result = applyQueue(base, [
      { type: 'add', name: 'Tofu', tempId: -1 },
      { type: 'check', itemId: -1 },
      { type: 'check', itemId: 1 },
    ])
    expect(result.items.find((i) => i.id === -1).is_checked).toBe(true)
    expect(result.items.find((i) => i.id === 1).is_checked).toBe(true)
    expect(result.checked_count).toBe(2)
  })
})

describe('drainQueue', () => {
  it('returns an empty queue untouched', async () => {
    expect(await drainQueue([])).toEqual([])
  })

  it('replays a "check" entry against the real API', async () => {
    updateShoppingItem.mockResolvedValue({})
    const remaining = await drainQueue([{ type: 'check', itemId: 5 }])
    expect(remaining).toEqual([])
    expect(updateShoppingItem).toHaveBeenCalledWith(5, { is_checked: true })
  })

  it('replays an "add" entry, then resolves a later check on its temp id', async () => {
    addShoppingItem.mockResolvedValue({ id: 42 })
    updateShoppingItem.mockResolvedValue({})
    const remaining = await drainQueue([
      { type: 'add', name: 'Tofu', tempId: -1 },
      { type: 'check', itemId: -1 },
    ])
    expect(remaining).toEqual([])
    expect(addShoppingItem).toHaveBeenCalledWith({ name: 'Tofu' })
    expect(updateShoppingItem).toHaveBeenCalledWith(42, { is_checked: true })
  })

  it('stops on a network failure, leaving that entry and the rest queued', async () => {
    updateShoppingItem.mockRejectedValueOnce(new Error('Failed to fetch'))
    const queue = [{ type: 'check', itemId: 1 }, { type: 'check', itemId: 2 }]
    const remaining = await drainQueue(queue)
    expect(remaining).toEqual(queue)
    expect(updateShoppingItem).toHaveBeenCalledTimes(1)
  })

  it('drops a server-rejected entry and keeps going', async () => {
    const gone = Object.assign(new Error('No such shopping item'), { status: 404 })
    updateShoppingItem.mockRejectedValueOnce(gone).mockResolvedValueOnce({})
    const remaining = await drainQueue([
      { type: 'check', itemId: 1 },
      { type: 'check', itemId: 2 },
    ])
    expect(remaining).toEqual([])
    expect(updateShoppingItem).toHaveBeenCalledTimes(2)
  })
})
