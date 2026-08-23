import { useCallback, useEffect, useState } from 'react'
import {
  createIngredient,
  listIngredients,
  mergeIngredients,
  updateIngredient,
} from '../api'
import { useSession } from '../App'
import { formatCents, formatCostPerKg, formatCostPerLitre, SOURCE_LABEL } from '../format'
import IngredientEditor from '../components/IngredientEditor'

const PAGE_SIZE = 50

/**
 * The master ingredient list.
 *
 * The blog import creates one row per distinct ingredient phrase, which
 * means this page opens with hundreds of nameless-but-priceless stubs. The
 * two filters at the top — "missing cost" and "missing nutrition" — are the
 * work queues that turn that into a useful lookup table, and the merge
 * control is how near-duplicates ("onion" / "red onion" / "onions") get
 * folded together.
 */
export default function PantryPage() {
  const { config } = useSession()
  const symbol = config?.currency_symbol || '$'

  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [q, setQ] = useState('')
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('')
  const [sort, setSort] = useState('usage')
  const [editing, setEditing] = useState(null)
  const [mergeSource, setMergeSource] = useState(null)
  const [adding, setAdding] = useState(false)
  const [newName, setNewName] = useState('')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await listIngredients({
        q,
        sort,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
        missing_cost: filter === 'cost' ? 'true' : '',
        missing_nutrition: filter === 'nutrition' ? 'true' : '',
        // The work queues are about ingredients, so they exclude the
        // non-food items the shopping-list import flagged; there is no
        // point being nagged to price the cat litter.
        is_food:
          filter === 'nonfood' ? 'false' : filter === 'cost' || filter === 'nutrition' ? 'true' : '',
      })
      setItems(result.items)
      setTotal(result.total)
      setError(null)
    } catch (caught) {
      setError(caught.message)
    }
    setLoading(false)
  }, [q, sort, page, filter])

  useEffect(() => {
    load()
  }, [load])

  const save = async (key, patch) => {
    await updateIngredient(key, patch)
    setEditing(null)
    await load()
  }

  const add = async (event) => {
    event.preventDefault()
    if (!newName.trim()) return
    try {
      await createIngredient({ name: newName.trim() })
      setNewName('')
      setAdding(false)
      await load()
    } catch (caught) {
      setError(caught.message)
    }
  }

  const merge = async (target) => {
    if (!mergeSource || mergeSource.id === target.id) {
      setMergeSource(null)
      return
    }
    if (
      !window.confirm(
        `Merge “${mergeSource.name}” into “${target.name}”? ` +
          `${mergeSource.name} is deleted and its ${mergeSource.recipe_count} recipe(s) ` +
          `point at ${target.name} instead.`,
      )
    ) {
      return
    }
    try {
      await mergeIngredients(target.slug, mergeSource.slug)
      setMergeSource(null)
      await load()
    } catch (caught) {
      setError(caught.message)
    }
  }

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-ink">Pantry</h1>
          <p className="text-sm text-ink-muted">
            Prices and nutrition live here once, and every recipe that uses the
            ingredient picks them up.
          </p>
        </div>
        <button
          onClick={() => setAdding((value) => !value)}
          className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-[color:var(--accent-ink)]"
        >
          {adding ? 'Cancel' : '+ New ingredient'}
        </button>
      </div>

      {adding && (
        <form onSubmit={add} className="flex gap-2 rounded-xl border border-edge bg-card p-4">
          <input
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
            placeholder="Ingredient name"
            className="flex-1 rounded-lg border border-edge bg-card px-3 py-2 text-sm text-ink"
          />
          <button
            type="submit"
            className="rounded-lg bg-accent px-3 py-2 text-sm font-medium text-[color:var(--accent-ink)]"
          >
            Add
          </button>
        </form>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault()
          setQ(search.trim())
          setPage(1)
        }}
        className="flex flex-wrap items-center gap-2"
      >
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search the pantry…"
          className="min-w-0 flex-1 rounded-lg border border-edge bg-card px-3 py-2 text-sm text-ink placeholder:text-ink-faint"
        />
        <select
          value={filter}
          onChange={(event) => {
            setFilter(event.target.value)
            setPage(1)
          }}
          className="rounded-lg border border-edge bg-card px-3 py-2 text-sm text-ink"
        >
          <option value="">Everything</option>
          <option value="cost">Missing a price</option>
          <option value="nutrition">Missing nutrition</option>
          <option value="nonfood">Not food</option>
        </select>
        <select
          value={sort}
          onChange={(event) => setSort(event.target.value)}
          className="rounded-lg border border-edge bg-card px-3 py-2 text-sm text-ink"
        >
          <option value="usage">Most used</option>
          <option value="name">A–Z</option>
          <option value="cost">Cheapest</option>
          <option value="updated">Recently updated</option>
        </select>
      </form>

      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      {mergeSource && (
        <p className="rounded-lg bg-accent-soft px-3 py-2 text-sm text-accent">
          Merging <strong>{mergeSource.name}</strong> — now pick the row to keep.{' '}
          <button onClick={() => setMergeSource(null)} className="underline">
            Cancel
          </button>
        </p>
      )}

      <p className="text-sm text-ink-muted">
        {loading ? 'Loading…' : `${total} ingredient${total === 1 ? '' : 's'}`}
      </p>

      <div className="overflow-x-auto rounded-xl border border-edge bg-card">
        <table className="w-full min-w-3xl text-sm">
          <thead className="border-b border-edge text-left text-xs uppercase tracking-wide text-ink-faint">
            <tr>
              <th className="px-3 py-2">Ingredient</th>
              <th className="px-3 py-2">Used in</th>
              <th className="px-3 py-2">Package</th>
              <th className="px-3 py-2">Cost</th>
              <th className="px-3 py-2">Per pack</th>
              <th className="px-3 py-2">Source</th>
              <th className="px-3 py-2">Nutrition</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id} className="border-b border-edge/60 last:border-0">
                <td className="px-3 py-2 font-medium text-ink">
                  {item.name}
                  {!item.is_food && (
                    <span
                      title="Not a recipe ingredient — flagged on import from the shopping list"
                      className="ml-1.5 rounded bg-soft px-1.5 py-0.5 text-[11px] text-ink-muted"
                    >
                      not food
                    </span>
                  )}
                  {item.aliases?.length > 0 && (
                    <span className="ml-1 text-xs text-ink-faint">
                      ({item.aliases.join(', ')})
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-ink-muted">{item.recipe_count}</td>
                <td className="px-3 py-2 text-ink-muted">
                  {item.measure_kind === 'volume'
                    ? item.package_size_ml
                      ? `${item.package_size_ml} mL`
                      : '—'
                    : item.package_size_grams
                      ? `${item.package_size_grams} g`
                      : '—'}
                </td>
                <td className="px-3 py-2 text-ink-muted">
                  {(item.measure_kind === 'volume'
                    ? formatCostPerLitre(item.cost_per_litre_cents, symbol)
                    : formatCostPerKg(item.cost_per_kg_cents, symbol)) || '—'}
                  {item.cost_source && (
                    <span
                      title={item.cost_source}
                      className={`ml-1 text-[10px] ${
                        item.cost_source.startsWith('AI estimate')
                          ? 'text-ink-faint italic'
                          : 'text-ink-faint'
                      }`}
                    >
                      {item.cost_source.startsWith('AI estimate') ? '~' : ''}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-ink-muted">
                  {formatCents(item.package_cost_cents, symbol) || '—'}
                </td>
                <td className="px-3 py-2 text-ink-muted">
                  {SOURCE_LABEL[item.source] || item.source}
                </td>
                <td className="px-3 py-2">
                  {item.has_nutrition ? (
                    <span
                      title={item.nutrition_source || 'nutrition recorded'}
                      className={
                        item.nutrition_source?.startsWith('AI estimate')
                          ? 'text-ink-faint italic'
                          : 'text-accent'
                      }
                    >
                      {item.nutrition_source?.startsWith('AI estimate') ? '~' : '✓'}
                    </span>
                  ) : (
                    <span className="text-ink-faint">—</span>
                  )}
                </td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  {mergeSource ? (
                    <button
                      onClick={() => merge(item)}
                      className="rounded border border-accent px-2 py-1 text-xs text-accent"
                    >
                      Keep this
                    </button>
                  ) : (
                    <>
                      <button
                        onClick={() => setEditing(item)}
                        className="rounded border border-edge px-2 py-1 text-xs text-ink-muted hover:bg-soft"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => setMergeSource(item)}
                        title="Fold this row into another"
                        className="ml-1 rounded border border-edge px-2 py-1 text-xs text-ink-muted hover:bg-soft"
                      >
                        Merge
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-center gap-3">
          <button
            disabled={page <= 1}
            onClick={() => setPage((value) => value - 1)}
            className="rounded-lg border border-edge px-3 py-1.5 text-sm text-ink-muted disabled:opacity-40"
          >
            Previous
          </button>
          <span className="text-sm text-ink-muted">
            Page {page} of {pages}
          </span>
          <button
            disabled={page >= pages}
            onClick={() => setPage((value) => value + 1)}
            className="rounded-lg border border-edge px-3 py-1.5 text-sm text-ink-muted disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}

      {editing && (
        <IngredientEditor
          ingredient={editing}
          symbol={symbol}
          onClose={() => setEditing(null)}
          onSave={(patch) => save(editing.slug, patch)}
        />
      )}
    </div>
  )
}
