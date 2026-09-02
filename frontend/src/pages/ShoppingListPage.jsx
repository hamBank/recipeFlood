import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
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

//: Units for the plain "quantity" line ("3 lemons", "1 bunch") — weight
//: and volume have their own dedicated fields (weight_grams/volume_ml),
//: so those units aren't offered here; see Row's editor below.
const QUANTITY_UNITS = ['', 'piece', 'slice', 'clove', 'bunch', 'sprig', 'can', 'pinch', 'to_taste']

/**
 * The shopping list — one permanent list, grouped by shop.
 *
 * This is the page that gets used one-handed in a supermarket, so the
 * whole design is about tap targets and glanceability: big rows, the
 * shop as the heading, checked items greyed and pushed to the bottom of
 * their group rather than vanishing.
 *
 * Grouping normally follows the pantry's `source` for each ingredient, so
 * the list doubles as a route — and a line's own `shop_override` (Row's
 * editor) wins over that when someone sets one, for the one-off "not from
 * the usual place this time" case. The order is a walking order, not
 * alphabetical — the backend decides it (see backend/shopping.py) and
 * this page just renders `shops` in the order it is given.
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

  // The printable layout (see PrintableList below) only exists in the DOM
  // while actually printing — not just CSS-hidden the rest of the time —
  // so it can show every item, untruncated, without a second copy of the
  // same names/amounts sitting in the page for no reason the rest of the
  // time. `beforeprint`/`afterprint` cover every way to print (the button
  // below, Ctrl/Cmd+P, a browser menu); the button also flushes the state
  // update synchronously first, since printing can start before a normal
  // (batched) re-render would otherwise have committed it.
  const [printing, setPrinting] = useState(false)

  useEffect(() => {
    const before = () => setPrinting(true)
    const after = () => setPrinting(false)
    window.addEventListener('beforeprint', before)
    window.addEventListener('afterprint', after)
    return () => {
      window.removeEventListener('beforeprint', before)
      window.removeEventListener('afterprint', after)
    }
  }, [])

  const print = () => {
    flushSync(() => setPrinting(true))
    window.print()
  }

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

  // `offline` can go stuck true from a transient failure that isn't a real
  // connectivity drop — a deploy restarting the backend mid-request, say —
  // and the browser never fires its own 'online' event to clear it, since
  // the network interface was fine the whole time. Left alone, a tick made
  // in that state sits in the local-only queue for the rest of the tab's
  // life, invisible to every other device until this one happens to
  // reload. Retrying periodically closes that gap without waiting on it.
  useEffect(() => {
    if (!offline) return
    const id = setInterval(() => {
      if (queue.length) drain()
      else load()
    }, 20000)
    return () => clearInterval(id)
  }, [offline, queue.length, drain, load])

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

  /** Quantity edits and a manual shop move both go through here — see
   * Row's editor below. Both need the network (the offline queue only
   * ever replays a tick or a brand-new line, see offlineQueue.js), same
   * as remove/clear/untick above. */
  const update = async (item, patch) => {
    if (offline) return
    setBusy(true)
    try {
      await updateShoppingItem(item.id, patch)
      await load()
    } catch (caught) {
      setError(caught.message)
    }
    setBusy(false)
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
      <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1 print:hidden">
        <h1 className="text-2xl font-bold text-ink">Shopping</h1>
        <p className="text-sm text-ink-muted">
          {remaining} to buy
          {displayList.checked_count > 0 && ` · ${displayList.checked_count} ticked off`}
        </p>
        {displayList.total_count > 0 && (
          <button
            type="button"
            onClick={print}
            className="rounded-lg border border-edge px-3 py-1 text-sm text-ink-muted hover:bg-soft"
          >
            Print
          </button>
        )}
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
        <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800 print:hidden">
          Offline — ticking things off and adding new items still works and will sync once
          you&apos;re back online. Unticking, editing and removing are paused until then.
        </p>
      )}

      <form ref={formRef} onSubmit={onSubmit} className="relative flex gap-2 print:hidden">
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

      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700 print:hidden">{error}</p>}

      {displayList.total_count === 0 ? (
        <p className="rounded-xl border border-edge bg-card p-6 text-center text-ink-muted print:hidden">
          Nothing on the list. Add something above, or send a cooking list here.
        </p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3 text-sm print:hidden">
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

          <div className="print:hidden">
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
                        onSave={(patch) => update(item, patch)}
                      />
                    ))}
                  </ul>
                </section>
              )
            })}
          </div>

          {printing && <PrintableList displayList={displayList} symbol={symbol} />}
        </>
      )}
    </div>
  )
}

/** The on-screen list above is filtered (Show ticked), truncated (the
 * "why" line) and full of tap targets — none of which belongs on paper.
 * This renders separately (only while `printing`, see above) with
 * everything: every item regardless of the Show ticked toggle, grouped by
 * shop in the same walking order, with amount, price and the full
 * "why is this here" line spelled out. */
function PrintableList({ displayList, symbol }) {
  return (
    <div>
      <h1 className="text-xl font-bold text-black">Shopping list</h1>
      <p className="mt-1 text-sm text-black">
        Printed {new Date().toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })}
        {' · '}
        {displayList.total_count} item{displayList.total_count === 1 ? '' : 's'}
        {displayList.total_cents !== null && (
          <> · {formatCents(displayList.total_cents, symbol)} ({formatPercent(displayList.priced_fraction)} priced)</>
        )}
      </p>

      {/* Two columns so the page isn't mostly empty margin either side of
          one narrow list. column-fill:auto (Tailwind's columns-2 leaves
          the default, "balance") — balance sizes each column from the
          *whole* list's height rather than what's left of the current
          page, so on a long list Chrome would rather leave a page almost
          empty than start a column it can't finish there. Auto just fills
          each page in turn. */}
      <div className="mt-4 columns-2 gap-8 [column-fill:auto]">
        {displayList.shops.map((shop) => {
          const rows = displayList.items.filter((item) => item.shop === shop)
          if (!rows.length) return null
          return (
            // Not break-inside-avoid on the whole section: a shop with
            // more lines than fit in what's left of a column is *supposed*
            // to spill onto the next one — the same list this heading
            // introduces just continues under a repeated cue rather than
            // stranding an entire page blank because the group as a whole
            // didn't fit. break-after-avoid on the heading below is the
            // part that actually matters: it stops the heading itself
            // from being orphaned with its first item pushed over.
            <section key={shop} className="mb-4">
              <h2 className="break-after-avoid border-b border-black text-sm font-bold uppercase tracking-wide text-black">
                {SOURCE_LABEL[shop] || shop}
              </h2>
              <ul>
                {rows.map((item) => {
                  const why = (item.contributions || [])
                    .map((c) => `${c.recipe}${c.amount ? ` (${c.amount})` : ''}`)
                    .join(' · ')
                  return (
                    <li key={item.id} className="flex items-start gap-2 border-b border-black/20 py-1.5 text-sm">
                      <span aria-hidden="true">{item.is_checked ? '☑' : '☐'}</span>
                      <span className="flex-1">
                        <span className={item.is_checked ? 'text-black/60 line-through' : 'text-black'}>
                          {item.name}
                        </span>
                        {item.amount_text && <span className="ml-2 text-black/70">{item.amount_text}</span>}
                        {why && <span className="block text-xs text-black/60">{why}</span>}
                      </span>
                      {item.cost_cents !== null && item.cost_cents !== undefined && (
                        <span className="shrink-0 tabular-nums text-black/70">
                          {formatCents(item.cost_cents, symbol)}
                        </span>
                      )}
                    </li>
                  )
                })}
              </ul>
            </section>
          )
        })}
      </div>
    </div>
  )
}

function Row({ item, symbol, offline, onToggle, onRemove, onSave }) {
  const [editing, setEditing] = useState(false)

  // "why is 400g of onion on my list" — answerable without re-running the
  // aggregation, because each merge recorded what it came from.
  const why = (item.contributions || [])
    .map((c) => `${c.recipe}${c.amount ? ` (${c.amount})` : ''}`)
    .join(' · ')

  if (editing) {
    return (
      <li className="px-3 py-3">
        <EditRow
          item={item}
          onCancel={() => setEditing(false)}
          onSave={async (patch) => {
            await onSave(patch)
            setEditing(false)
          }}
        />
      </li>
    )
  }

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
        {item.shop_override && (
          <span
            className="ml-2 text-xs text-ink-faint"
            title={`Moved to ${SOURCE_LABEL[item.shop_override] || item.shop_override} by hand`}
          >
            (moved)
          </span>
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
        onClick={() => setEditing(true)}
        disabled={offline}
        className="shrink-0 rounded px-2 py-1 text-sm text-ink-muted hover:bg-soft disabled:opacity-30"
        aria-label={`Edit ${item.name}`}
      >
        ✎
      </button>
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

const KIND_LABEL = { weight: 'Weight', volume: 'Volume', quantity: 'Count', bare: 'No amount' }

/** Quantity and shop both edit here. Kind (weight/volume/count/no amount)
 * is itself switchable — a line typed in with no amount at all ("garlic",
 * just a name) is the main reason to edit a line in the first place, and
 * it starts with nothing to pick a kind *from*, so kind can't be fixed to
 * whatever the item already happens to be. Switching kind sends the other
 * kind-fields as explicit nulls (see `submit`) so the item only ever ends
 * up with the one kind of amount that `backend/shopping.py` expects. */
function EditRow({ item, onCancel, onSave }) {
  const initialKind =
    item.weight_grams != null ? 'weight' : item.volume_ml != null ? 'volume' : item.quantity != null ? 'quantity' : 'bare'
  const [kind, setKind] = useState(initialKind)
  const [weight, setWeight] = useState(item.weight_grams ?? '')
  const [weightUnit, setWeightUnit] = useState('g')
  const [volume, setVolume] = useState(item.volume_ml ?? '')
  const [quantity, setQuantity] = useState(item.quantity ?? '')
  const [unit, setUnit] = useState(item.unit || '')
  const [shopOverride, setShopOverride] = useState(item.shop_override || '')
  const [saving, setSaving] = useState(false)

  const submit = async (event) => {
    event.preventDefault()
    setSaving(true)
    const patch = {
      shop_override: shopOverride || null,
      // Every kind-field goes in every save, even when it's null: a
      // partial PATCH only touches fields it's actually given, so
      // switching kind has to say "and clear the others" explicitly or
      // the item would end up with two kinds of amount set at once.
      weight_grams:
        kind === 'weight' && weight !== '' ? Number(weight) * (weightUnit === 'kg' ? 1000 : 1) : null,
      volume_ml: kind === 'volume' && volume !== '' ? Number(volume) : null,
      quantity: kind === 'quantity' && quantity !== '' ? Number(quantity) : null,
      unit: kind === 'quantity' ? unit || null : null,
    }
    await onSave(patch)
    setSaving(false)
  }

  return (
    <form onSubmit={submit} className="space-y-2 text-sm">
      <div className="font-medium text-ink">{item.name}</div>

      <label className="flex items-center gap-1.5 text-ink-muted">
        Amount
        <select
          aria-label="Amount kind"
          value={kind}
          onChange={(event) => setKind(event.target.value)}
          className="rounded-lg border border-edge bg-card px-2 py-1 text-ink"
        >
          {Object.entries(KIND_LABEL).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>

      <div className="flex flex-wrap items-center gap-2">
        {kind === 'weight' && (
          <label className="flex items-center gap-1.5 text-ink-muted">
            Weight
            <input
              aria-label="Weight"
              type="number"
              step="any"
              min="0"
              value={weight}
              onChange={(event) => setWeight(event.target.value)}
              className="w-24 rounded-lg border border-edge bg-card px-2 py-1 text-ink"
            />
            <select
              aria-label="Weight unit"
              value={weightUnit}
              onChange={(event) => setWeightUnit(event.target.value)}
              className="rounded-lg border border-edge bg-card px-2 py-1 text-ink"
            >
              <option value="g">g</option>
              <option value="kg">kg</option>
            </select>
          </label>
        )}
        {kind === 'volume' && (
          <label className="flex items-center gap-1.5 text-ink-muted">
            Volume
            <input
              aria-label="Volume"
              type="number"
              step="any"
              min="0"
              value={volume}
              onChange={(event) => setVolume(event.target.value)}
              className="w-24 rounded-lg border border-edge bg-card px-2 py-1 text-ink"
            />
            mL
          </label>
        )}
        {kind === 'quantity' && (
          <>
            <label className="flex items-center gap-1.5 text-ink-muted">
              Quantity
              <input
                type="number"
                step="any"
                min="0"
                value={quantity}
                onChange={(event) => setQuantity(event.target.value)}
                className="w-20 rounded-lg border border-edge bg-card px-2 py-1 text-ink"
              />
            </label>
            <select
              aria-label="Unit"
              value={unit}
              onChange={(event) => setUnit(event.target.value)}
              className="rounded-lg border border-edge bg-card px-2 py-1 text-ink"
            >
              {QUANTITY_UNITS.map((value) => (
                <option key={value} value={value}>
                  {value ? value.replace('_', ' ') : '—'}
                </option>
              ))}
            </select>
          </>
        )}
      </div>

      <label className="flex items-center gap-1.5 text-ink-muted">
        Shop
        <select
          value={shopOverride}
          onChange={(event) => setShopOverride(event.target.value)}
          className="rounded-lg border border-edge bg-card px-2 py-1 text-ink"
        >
          {/* Not "…(currently: X)" — once an override is set, item.shop
              *is* the override, not the pantry's own default, so there's
              no value here that's safe to show without a second request. */}
          <option value="">Use pantry default</option>
          {Object.entries(SOURCE_LABEL).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>

      <div className="flex justify-end gap-2 pt-1">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg border border-edge px-3 py-1 text-ink-muted hover:bg-soft"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="rounded-lg bg-accent px-3 py-1 font-medium text-[color:var(--accent-ink)] disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  )
}
