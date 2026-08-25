import { addShoppingItem, updateShoppingItem } from './api'

/**
 * Offline support for the shopping list: a localStorage-backed outbox of
 * queued mutations, plus a cached copy of the last-fetched list so the
 * page still has something to render with no network at all.
 *
 * The scope is deliberately narrow. Only two mutation types are ever
 * queued, and both are safe to replay blind — neither can conflict with a
 * change made elsewhere while this device was offline:
 *
 *   - "check": unchecked -> checked, one direction only. Unticking,
 *     editing and deleting all stay online-only, so the queue never has
 *     to reconcile two different opinions about an item's state.
 *   - "add": a brand new line. If the same ingredient also got added on
 *     another device in the meantime, syncing both is allowed to produce
 *     two rows rather than one — merging them isn't worth the complexity
 *     for something a "Merge" click on the pantry page already fixes.
 */

const QUEUE_KEY = 'rf_shopping_queue'
const CACHE_KEY = 'rf_shopping_cache'

function readJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : fallback
  } catch {
    return fallback
  }
}

function writeJSON(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Storage full, or unavailable (private browsing) — offline support
    // just degrades to "doesn't survive a reload" rather than throwing.
  }
}

export const loadQueue = () => readJSON(QUEUE_KEY, [])
export const saveQueue = (queue) => writeJSON(QUEUE_KEY, queue)
export const loadCachedList = () => readJSON(CACHE_KEY, null)
export const saveCachedList = (list) => writeJSON(CACHE_KEY, list)

/** A fresh negative id for an offline-added row — distinct from every id
 * the server has ever handed out (those start at 1) and from every other
 * row already on screen, including earlier not-yet-synced ones. */
export function nextTempId(displayList) {
  const ids = (displayList?.items || []).map((item) => item.id)
  return Math.min(0, ...ids) - 1
}

/** What the page renders: the last-known list with the queue laid on top,
 * so a queued check or add shows up immediately — including on a cold
 * reload, before any fetch has even run. */
export function applyQueue(list, queue) {
  if (!list) return list
  let items = list.items
  let shops = list.shops
  for (const entry of queue) {
    if (entry.type === 'check') {
      items = items.map((item) =>
        item.id === entry.itemId ? { ...item, is_checked: true } : item,
      )
    } else if (entry.type === 'add') {
      items = [
        ...items,
        {
          id: entry.tempId,
          name: entry.name,
          shop: 'other',
          is_checked: false,
          amount_text: '',
          cost_cents: null,
          contributions: [],
          pendingSync: true,
        },
      ]
      if (!shops.includes('other')) shops = [...shops, 'other']
    }
  }
  const checked_count = items.filter((item) => item.is_checked).length
  return { ...list, items, shops, total_count: items.length, checked_count }
}

/** Replay the queue against the server, in order, stopping at the first
 * entry that can't be applied. "add" is always resolved before any "check"
 * that targets its temp id, because nothing can queue a check on a row
 * before queuing the add that created it.
 *
 * A network failure (no `.status` on the error — fetch itself rejected)
 * stops the drain so the rest is retried next time. A real server
 * rejection (e.g. the item was deleted from another device while this one
 * was offline) drops just that entry and keeps going, since retrying it
 * later wouldn't fix anything either.
 *
 * Returns whatever's left in the queue — empty on full success. */
export async function drainQueue(queue) {
  const remaining = [...queue]
  const idMap = new Map()
  while (remaining.length) {
    const entry = remaining[0]
    try {
      if (entry.type === 'add') {
        const created = await addShoppingItem({ name: entry.name })
        idMap.set(entry.tempId, created.id)
      } else if (entry.type === 'check') {
        const itemId = idMap.has(entry.itemId) ? idMap.get(entry.itemId) : entry.itemId
        await updateShoppingItem(itemId, { is_checked: true })
      }
    } catch (caught) {
      if (caught.status) {
        remaining.shift()
        continue
      }
      break
    }
    remaining.shift()
  }
  return remaining
}
