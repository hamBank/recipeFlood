import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  addShoppingItem,
  clearCheckedShopping,
  deleteShoppingItem,
  getShoppingList,
  listIngredients,
  uncheckAllShopping,
  updateShoppingItem,
} from '../api'
import {
  applyQueue,
  drainQueue,
  loadCachedList,
  loadQueue,
  nextTempId,
  saveCachedList,
  saveQueue,
} from '../offlineQueue'
import { useSession } from '../App'
import { formatCents, formatPercent, SOURCE_LABEL } from '../format'

/**
 * The shopping list — one permanent list, grouped by shop.
 *
 * This is the page that gets used one-handed in a supermarket, so the
 * whole design is about tap targets and glanceability: big rows, the
 * shop as the heading, checked items greyed and pushed to the bottom of
 * their group rather than vanishing.
 *
 * Grouping comes from the pantry's `source` for each ingredient, so the
 * list doubles as a route. The order is a walking order, not alphabetical
 * — the backend decides it (see backend/shopping.py) and this page just
 * renders `shops` in the order it is given.
 *
 * It also works with no connection at all — see offlineQueue.js. `list`
 * here is the last-known truth from the server (or, offline, from a
 * localStorage cache of it); `queue` is what's pending; `displayList` is
 * the two combined, and is what actually renders.
 */
export default function ShoppingListPage() {
  const { config } = useSession()
  const symbol = config?.currency_symbol || '$'

  const [list, setList] = useState(null)
  const [queue, setQueue] = useState(() => loadQueue())
  const [offline, setOffline] = useState(() => typeof navigator !== 'undefined' && !navigator.onLine)
  const [newName, setNewName] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [showChecked, setShowChecked] = useState(true)

  // Pantry search-as-you-type, so a name already in the pantry (with a
  // shop and a price) can be added in one tap instead of typed out and
  // left for the backend's own fuzzy match to reconcile later.
  const [suggestions, setSuggestions] = useState([])
  const [suggestionsOpen, setSuggestionsOpen] = useState(false)
  const [highlighted, setHighlighted] = useState(-1)
  const formRef = useRef(null)

  useEffect(() => {
    saveQueue(queue)
  }, [queue])

  useEffect(() => {
    const trimmed = newName.trim()
    if (offline || !trimmed) {
      setSuggestions([])
      setSuggestionsOpen(false)
      return
    }
    let cancelled = false
    const timer = setTimeout(async () => {
      try {
        const { items } = await listIngredients({ q: trimmed, sort: 'usage', limit: 8 })
        if (cancelled) return
        setSuggestions(items)
        setSuggestionsOpen(items.length > 0)
        setHighlighted(-1)
      } catch {
        // Suggestions are a convenience; typing a free-text name and
        // hitting Add still works without them.
      }
    }, 250)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [newName, offline])

  useEffect(() => {
    if (!suggestionsOpen) return
    const closeIfOutside = (event) => {
      if (formRef.current && !formRef.current.contains(event.target)) setSuggestionsOpen(false)
    }
    document.addEventListener('mousedown', closeIfOutside)
    return () => document.removeEventListener('mousedown', closeIfOutside)
  }, [suggestionsOpen])

  const displayList = useMemo(() => applyQueue(list, queue), [list, queue])

  const load = useCallback(async () => {
    try {
      const fresh = await getShoppingList()
      setList(fresh)
      saveCachedList(fresh)
      setOffline(false)
      setError(null)
    } catch (caught) {
      if (caught.status) {
        // A real server response (e.g. signed out) — not a connectivity
        // problem, so it shouldn't fall back to a stale offline view.
        setError(caught.message)
        return
      }
      setOffline(true)
      const cached = loadCachedList()
      if (cached) {
        setList(cached)
        setError(null)
      } else {
        setError("Offline, and nothing cached yet — reconnect once to load the list.")
      }
    }
  }, [])

  const drain = useCallback(async () => {
    if (!queue.length) return
    const remaining = await drainQueue(queue)
    if (remaining.length === queue.length) return // no progress — still actually offline
    setQueue(remaining)
    await load()
  }, [queue, load])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    const goOnline = () => {
      setOffline(false)
      drain()
    }
    const goOffline = () => setOffline(true)
    window.addEventListener('online', goOnline)
    window.addEventListener('offline', goOffline)
    // Covers a reconnect the app never saw fire, and a queue left over
    // from being closed while offline last time.
    if (typeof navigator === 'undefined' || navigator.onLine) drain()
    return () => {
      window.removeEventListener('online', goOnline)
      window.removeEventListener('offline', goOffline)
    }
  }, [drain])

  const toggle = async (item) => {
    if (offline || item.pendingSync) {
      // Only unchecked -> checked is safe to queue blind — see
      // offlineQueue.js — so unticking simply isn't offered here.
      if (item.is_checked) return
      setQueue((current) => [...current, { type: 'check', itemId: item.id }])
      return
    }
    // Optimistic: ticking things off should feel instant with a trolley in
    // one hand. A failure re-reads the server's version.
    setList((current) => ({
      ...current,
      items: current.items.map((row) =>
        row.id === item.id ? { ...row, is_checked: !row.is_checked } : row,
      ),
    }))
    try {
      await updateShoppingItem(item.id, { is_checked: !item.is_checked })
      await load()
    } catch (caught) {
      setError(caught.message)
      await load()
    }
  }

  /** `ingredient` is set when the line comes from a picked suggestion, so
   * it lands on the list already matched to a shop and a price instead of
   * going through the backend's own (fuzzier) name lookup. */
  const add = async (name, ingredient) => {
    setSuggestionsOpen(false)
    setSuggestions([])
    if (offline) {
      const tempId = nextTempId(displayList)
      setQueue((current) => [...current, { type: 'add', name, tempId }])
      setNewName('')
      return
    }
    setBusy(true)
    try {
      await addShoppingItem({ name, ingredient_id: ingredient?.id })
      setNewName('')
      await load()
    } catch (caught) {
      setError(caught.message)
    }
    setBusy(false)
  }

  const onSubmit = (event) => {
    event.preventDefault()
    if (highlighted >= 0 && suggestions[highlighted]) {
      const picked = suggestions[highlighted]
      add(picked.name, picked)
      return
    }
    const name = newName.trim()
    if (name) add(name)
  }

  const onInputKeyDown = (event) => {
    if (!suggestionsOpen || suggestions.length === 0) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setHighlighted((current) => (current + 1) % suggestions.length)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setHighlighted((current) => (current - 1 + suggestions.length) % suggestions.length)
    } else if (event.key === 'Escape') {
      setSuggestionsOpen(false)
    }
  }

  const remove = async (item) => {
    if (offline) return
    await deleteShoppingItem(item.id)
    await load()
  }

  const clear = async () => {
    if (offline) return
    if (!window.confirm(`Remove ${displayList.checked_count} ticked item(s) from the list?`)) return
    setBusy(true)
    try {
      setList(await clearCheckedShopping())
    } catch (caught) {
      setError(caught.message)
    }
    setBusy(false)
  }

  const uncheck = async () => {
    if (offline) return
    setBusy(true)
    try {
      setList(await uncheckAllShopping())
    } catch (caught) {
      setError(caught.message)
    }
    setBusy(false)
  }

  if (error && !displayList) return <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>
  if (!displayList) return <p className="text-ink-muted">Loading…</p>

  const visible = showChecked ? displayList.items : displayList.items.filter((i) => !i.is_checked)
  const remaining = displayList.total_count - displayList.checked_count

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h1 className="text-2xl font-bold text-ink">Shopping</h1>
        <p className="text-sm text-ink-muted">
          {remaining} to buy
          {displayList.checked_count > 0 && ` · ${displayList.checked_count} ticked off`}
        </p>
        {displayList.total_cents !== null && remaining > 0 && (
          <p className="ml-auto text-sm text-ink-muted">
            <span className="font-medium text-ink">
              {formatCents(displayList.total_cents, symbol)}
            </span>{' '}
            {/* Same honesty rule as the recipe cost panel: say how much of
                the list the total actually covers rather than presenting a
                confident-looking undercount. */}
            <span title="Share of the unticked items that have a price in the pantry">
              ({formatPercent(displayList.priced_fraction)} priced)
            </span>
          </p>
        )}
      </header>

      {offline && (
        <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
          Offline — ticking things off and adding new items still works and will sync once
          you&apos;re back online. Unticking, editing and removing are paused until then.
        </p>
      )}

      <form ref={formRef} onSubmit={onSubmit} className="relative flex gap-2">
        <input
          value={newName}
          onChange={(event) => setNewName(event.target.value)}
          onKeyDown={onInputKeyDown}
          onFocus={() => setSuggestionsOpen(suggestions.length > 0)}
          placeholder="Add something…"
          role="combobox"
          aria-expanded={suggestionsOpen}
          aria-autocomplete="list"
          autoComplete="off"
          className="flex-1 rounded-lg border border-edge bg-card px-3 py-2 text-ink placeholder:text-ink-muted"
        />
        <button
          type="submit"
          disabled={busy || !newName.trim()}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-[color:var(--accent-ink)] disabled:opacity-50"
        >
          Add
        </button>

        {suggestionsOpen && (
          <ul
            role="listbox"
            className="absolute left-0 right-14 top-full z-10 mt-1 max-h-64 overflow-y-auto rounded-lg border border-edge bg-card shadow-lg"
          >
            {suggestions.map((ingredient, index) => (
              <li key={ingredient.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={index === highlighted}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => add(ingredient.name, ingredient)}
                  onMouseEnter={() => setHighlighted(index)}
                  className={`flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm ${
                    index === highlighted ? 'bg-soft' : ''
                  }`}
                >
                  <span className="min-w-0 truncate text-ink">{ingredient.name}</span>
                  <span className="shrink-0 text-xs text-ink-muted">
                    {SOURCE_LABEL[ingredient.source] || ingredient.source}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </form>

      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      {displayList.total_count === 0 ? (
        <p className="rounded-xl border border-edge bg-card p-6 text-center text-ink-muted">
          Nothing on the list. Add something above, or send a cooking list here.
        </p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <label className="flex items-center gap-2 text-ink-muted">
              <input
                type="checkbox"
                checked={showChecked}
                onChange={(event) => setShowChecked(event.target.checked)}
              />
              Show ticked
            </label>
            {displayList.checked_count > 0 && (
              <>
                <button
                  onClick={clear}
                  disabled={busy || offline}
                  className="rounded-lg border border-edge px-3 py-1 text-ink-muted hover:bg-soft disabled:opacity-50"
                >
                  Clear {displayList.checked_count} ticked
                </button>
                <button
                  onClick={uncheck}
                  disabled={busy || offline}
                  className="rounded-lg border border-edge px-3 py-1 text-ink-muted hover:bg-soft disabled:opacity-50"
                >
                  Untick all
                </button>
              </>
            )}
          </div>

          {displayList.shops.map((shop) => {
            const rows = visible.filter((item) => item.shop === shop)
            if (!rows.length) return null
            return (
              <section key={shop} className="space-y-1">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                  {SOURCE_LABEL[shop] || shop}
                </h2>
                <ul className="divide-y divide-edge overflow-hidden rounded-xl border border-edge bg-card">
                  {rows.map((item) => (
                    <Row
                      key={item.id}
                      item={item}
                      symbol={symbol}
                      offline={offline}
                      onToggle={() => toggle(item)}
                      onRemove={() => remove(item)}
                    />
                  ))}
                </ul>
              </section>
            )
          })}
        </>
      )}
    </div>
  )
}

function Row({ item, symbol, offline, onToggle, onRemove }) {
  // "why is 400g of onion on my list" — answerable without re-running the
  // aggregation, because each merge recorded what it came from.
  const why = (item.contributions || [])
    .map((c) => `${c.recipe}${c.amount ? ` (${c.amount})` : ''}`)
    .join(' · ')

  return (
    <li className={`flex items-center gap-3 px-3 py-3 ${item.is_checked ? 'opacity-50' : ''}`}>
      <input
        type="checkbox"
        checked={item.is_checked}
        onChange={onToggle}
        disabled={offline && item.is_checked}
        className="h-5 w-5 shrink-0"
        aria-label={`Tick off ${item.name}`}
      />
      <button onClick={onToggle} className="min-w-0 flex-1 text-left">
        <span className={`text-ink ${item.is_checked ? 'line-through' : ''}`}>
          {item.name}
        </span>
        {item.amount_text && (
          <span className="ml-2 text-sm text-ink-muted">{item.amount_text}</span>
        )}
        {item.pendingSync && (
          <span className="ml-2 text-xs italic text-ink-muted">not yet synced</span>
        )}
        {why && (
          <span className="block truncate text-xs text-ink-muted" title={why}>
            {why}
          </span>
        )}
      </button>
      {item.cost_cents !== null && item.cost_cents !== undefined && (
        <span className="shrink-0 text-sm tabular-nums text-ink-muted">
          {formatCents(item.cost_cents, symbol)}
        </span>
      )}
      <button
        onClick={onRemove}
        disabled={offline}
        className="shrink-0 rounded px-2 py-1 text-sm text-ink-muted hover:bg-soft disabled:opacity-30"
        aria-label={`Remove ${item.name}`}
      >
        ✕
      </button>
    </li>
  )
}
