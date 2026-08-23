import { useCallback, useEffect, useState } from 'react'
import {
  addShoppingItem,
  clearCheckedShopping,
  deleteShoppingItem,
  getShoppingList,
  uncheckAllShopping,
  updateShoppingItem,
} from '../api'
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
 */
export default function ShoppingListPage() {
  const { config } = useSession()
  const symbol = config?.currency_symbol || '$'

  const [list, setList] = useState(null)
  const [newName, setNewName] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [showChecked, setShowChecked] = useState(true)

  const load = useCallback(async () => {
    try {
      setList(await getShoppingList())
      setError(null)
    } catch (caught) {
      setError(caught.message)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const toggle = async (item) => {
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

  const add = async (event) => {
    event.preventDefault()
    const name = newName.trim()
    if (!name) return
    setBusy(true)
    try {
      await addShoppingItem({ name })
      setNewName('')
      await load()
    } catch (caught) {
      setError(caught.message)
    }
    setBusy(false)
  }

  const remove = async (item) => {
    await deleteShoppingItem(item.id)
    await load()
  }

  const clear = async () => {
    if (!window.confirm(`Remove ${list.checked_count} ticked item(s) from the list?`)) return
    setBusy(true)
    try {
      setList(await clearCheckedShopping())
    } catch (caught) {
      setError(caught.message)
    }
    setBusy(false)
  }

  const uncheck = async () => {
    setBusy(true)
    try {
      setList(await uncheckAllShopping())
    } catch (caught) {
      setError(caught.message)
    }
    setBusy(false)
  }

  if (error && !list) return <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>
  if (!list) return <p className="text-ink-muted">Loading…</p>

  const visible = showChecked ? list.items : list.items.filter((i) => !i.is_checked)
  const remaining = list.total_count - list.checked_count

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h1 className="text-2xl font-bold text-ink">Shopping</h1>
        <p className="text-sm text-ink-muted">
          {remaining} to buy
          {list.checked_count > 0 && ` · ${list.checked_count} ticked off`}
        </p>
        {list.total_cents !== null && remaining > 0 && (
          <p className="ml-auto text-sm text-ink-muted">
            <span className="font-medium text-ink">
              {formatCents(list.total_cents, symbol)}
            </span>{' '}
            {/* Same honesty rule as the recipe cost panel: say how much of
                the list the total actually covers rather than presenting a
                confident-looking undercount. */}
            <span title="Share of the unticked items that have a price in the pantry">
              ({formatPercent(list.priced_fraction)} priced)
            </span>
          </p>
        )}
      </header>

      <form onSubmit={add} className="flex gap-2">
        <input
          value={newName}
          onChange={(event) => setNewName(event.target.value)}
          placeholder="Add something…"
          className="flex-1 rounded-lg border border-edge bg-card px-3 py-2 text-ink placeholder:text-ink-muted"
        />
        <button
          type="submit"
          disabled={busy || !newName.trim()}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-[color:var(--accent-ink)] disabled:opacity-50"
        >
          Add
        </button>
      </form>

      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      {list.total_count === 0 ? (
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
            {list.checked_count > 0 && (
              <>
                <button
                  onClick={clear}
                  disabled={busy}
                  className="rounded-lg border border-edge px-3 py-1 text-ink-muted hover:bg-soft disabled:opacity-50"
                >
                  Clear {list.checked_count} ticked
                </button>
                <button
                  onClick={uncheck}
                  disabled={busy}
                  className="rounded-lg border border-edge px-3 py-1 text-ink-muted hover:bg-soft disabled:opacity-50"
                >
                  Untick all
                </button>
              </>
            )}
          </div>

          {list.shops.map((shop) => {
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

function Row({ item, symbol, onToggle, onRemove }) {
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
        className="shrink-0 rounded px-2 py-1 text-sm text-ink-muted hover:bg-soft"
        aria-label={`Remove ${item.name}`}
      >
        ✕
      </button>
    </li>
  )
}
