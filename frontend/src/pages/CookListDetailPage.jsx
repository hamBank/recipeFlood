import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  addCookListToShopping,
  addRecipeToCookList,
  deleteCookList,
  getCookList,
  listRecipes,
  removeRecipeFromCookList,
  updateCookList,
  updateCookListRecipe,
} from '../api'
import { formatDate } from '../format'

/**
 * One cooking list: a date, a description, and the recipes planned for it.
 *
 * The recipe picker is a plain search-and-add rather than the full grid on
 * the recipe list page — this is a small, frequent action ("add the soup"),
 * not browsing.
 *
 * Servings is the phase-2 scaling hook: typing a number here doesn't touch
 * the recipe, it just tells "add to shopping" how much of it to buy.
 * `scalable: false` on a row means the recipe itself has no serving size to
 * scale from, and the UI says so rather than silently using 1x.
 *
 * Ticking a recipe off (once it's been made) strikes it through and sinks
 * it below the rest — display-only, same idea as a shopping list item, and
 * the sort itself happens server-side (backend/cook_lists.py) so this page
 * doesn't need its own ordering logic. It doesn't log a prepared event or
 * touch "last cooked"; that's a separate, deliberate action from the
 * recipe page.
 */
export default function CookListDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()

  const [list, setList] = useState(null)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [addResult, setAddResult] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setList(await getCookList(id))
      setError(null)
    } catch (caught) {
      setError(caught.message)
    }
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    const term = search.trim()
    if (!term) {
      setResults([])
      return
    }
    setSearching(true)
    const timer = setTimeout(async () => {
      try {
        // include_empty: a book-citation stub (no ingredients/steps yet,
        // just a title and where it came from) is still worth planning a
        // cook date around, even though it's hidden from normal browsing.
        const found = await listRecipes({ q: term, limit: 8, include_empty: 'true' })
        setResults(found.items)
      } catch {
        // A failed search just leaves the list empty; typing is not worth
        // surfacing an error banner for.
      }
      setSearching(false)
    }, 250)
    return () => clearTimeout(timer)
  }, [search])

  const addRecipe = async (recipe) => {
    setSearch('')
    setResults([])
    try {
      setList(await addRecipeToCookList(id, { recipe_id: recipe.id }))
    } catch (caught) {
      setError(caught.message)
    }
  }

  const toggleCompleted = async (row) => {
    // Optimistic, same pattern as the shopping list's toggle: flip in place
    // first for an instant response, then reload — which is also what
    // actually sinks it to the bottom, since the server does that sort
    // (backend/cook_lists.py), not this page.
    setList((current) => ({
      ...current,
      recipes: current.recipes.map((r) =>
        r.recipe_id === row.recipe_id ? { ...r, completed: !r.completed } : r,
      ),
    }))
    try {
      await updateCookListRecipe(id, row.recipe_id, { completed: !row.completed })
      await load()
    } catch (caught) {
      setError(caught.message)
      await load()
    }
  }

  const removeRecipe = async (recipeId) => {
    try {
      setList(await removeRecipeFromCookList(id, recipeId))
    } catch (caught) {
      setError(caught.message)
    }
  }

  const setServings = async (recipeId, value) => {
    const servings = value === '' ? null : Number(value)
    setList((current) => ({
      ...current,
      recipes: current.recipes.map((r) =>
        r.recipe_id === recipeId ? { ...r, servings } : r,
      ),
    }))
    try {
      await addRecipeToCookList(id, { recipe_id: recipeId, servings })
      await load()
    } catch (caught) {
      setError(caught.message)
      await load()
    }
  }

  const saveField = async (field, value) => {
    try {
      setList(await updateCookList(id, { [field]: value }))
    } catch (caught) {
      setError(caught.message)
    }
  }

  const sendToShopping = async () => {
    setBusy(true)
    try {
      const result = await addCookListToShopping(id)
      setAddResult(result)
    } catch (caught) {
      setError(caught.message)
    }
    setBusy(false)
  }

  const remove = async () => {
    if (!window.confirm('Delete this cooking list? Anything already sent to the shopping list stays there.')) return
    try {
      await deleteCookList(id)
      navigate('/cooking')
    } catch (caught) {
      setError(caught.message)
    }
  }

  if (error && !list) return <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>
  if (!list) return <p className="text-ink-muted">Loading…</p>

  return (
    <div className="max-w-2xl space-y-5">
      <div className="flex items-center gap-2 text-sm">
        <Link to="/cooking/all" className="text-ink-muted hover:underline">
          Cooking lists
        </Link>
        <span className="text-ink-muted">/</span>
        <span className="text-ink">{formatDate(list.cook_date)}</span>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <input
          type="date"
          value={list.cook_date}
          onChange={(event) => saveField('cook_date', event.target.value)}
          className="rounded-lg border border-edge bg-card px-3 py-1.5 text-ink"
        />
        <input
          value={list.description || ''}
          onChange={(event) =>
            setList((current) => ({ ...current, description: event.target.value }))
          }
          onBlur={(event) => saveField('description', event.target.value)}
          placeholder="Add a name…"
          className="min-w-0 flex-1 rounded-lg border border-edge bg-card px-3 py-1.5 text-ink placeholder:text-ink-muted"
        />
        <label className="flex shrink-0 items-center gap-1.5 rounded-lg border border-edge bg-card px-3 py-1.5 text-sm text-ink-muted">
          <input
            type="checkbox"
            checked={list.completed}
            onChange={(event) => saveField('completed', event.target.checked)}
          />
          Completed
        </label>
        <button
          onClick={remove}
          className="rounded-lg border border-edge px-3 py-1.5 text-sm text-ink-muted hover:bg-soft"
        >
          Delete
        </button>
      </div>

      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      <section className="space-y-2">
        <div className="relative">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Add a recipe…"
            className="w-full rounded-lg border border-edge bg-card px-3 py-2 text-ink placeholder:text-ink-muted"
          />
          {(results.length > 0 || searching) && (
            <ul className="absolute z-10 mt-1 w-full overflow-hidden rounded-lg border border-edge bg-card shadow-lg">
              {searching && (
                <li className="px-3 py-2 text-sm text-ink-muted">Searching…</li>
              )}
              {results.map((recipe) => (
                <li key={recipe.id}>
                  <button
                    onClick={() => addRecipe(recipe)}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-ink hover:bg-soft"
                  >
                    {recipe.title}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {list.recipes.length === 0 ? (
          <p className="rounded-xl border border-edge bg-card p-6 text-center text-ink-muted">
            No recipes yet. Search above to add some.
          </p>
        ) : (
          <ul className="divide-y divide-edge overflow-hidden rounded-xl border border-edge bg-card">
            {list.recipes.map((row) => (
              <li
                key={row.id}
                className={`flex items-center gap-3 px-3 py-2.5 ${row.completed ? 'opacity-50' : ''}`}
              >
                <input
                  type="checkbox"
                  checked={row.completed}
                  onChange={() => toggleCompleted(row)}
                  className="h-5 w-5 shrink-0"
                  aria-label={`Mark ${row.title} cooked`}
                />
                <Link
                  to={`/recipes/${row.slug}`}
                  className={`min-w-0 flex-1 truncate text-ink hover:underline ${row.completed ? 'line-through' : ''}`}
                >
                  {row.title}
                </Link>
                <ServingsInput row={row} onChange={(value) => setServings(row.recipe_id, value)} />
                <button
                  onClick={() => removeRecipe(row.recipe_id)}
                  className="shrink-0 rounded px-2 py-1 text-sm text-ink-muted hover:bg-soft"
                  aria-label={`Remove ${row.title}`}
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {list.recipes.length > 0 && (
        <section className="space-y-2 rounded-xl border border-edge bg-card p-4">
          <button
            onClick={sendToShopping}
            disabled={busy}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-[color:var(--accent-ink)] disabled:opacity-50"
          >
            Add ingredients to shopping list
          </button>
          {addResult && (
            <div className="text-sm text-ink-muted">
              <p>
                {addResult.added} new, {addResult.merged} merged into existing items.
              </p>
              {addResult.skipped.length > 0 && (
                <p className="mt-1">
                  {"Couldn't tell what to buy for: " + addResult.skipped.join('; ')}
                </p>
              )}
              <Link to="/groceries" className="mt-1 inline-block text-accent hover:underline">
                View shopping list →
              </Link>
            </div>
          )}
        </section>
      )}
    </div>
  )
}

function ServingsInput({ row, onChange }) {
  return (
    <div className="flex shrink-0 items-center gap-1.5 text-sm">
      <input
        type="number"
        min={1}
        value={row.servings ?? ''}
        placeholder={row.base_servings ? `${row.base_servings}` : 'serves'}
        onChange={(event) => onChange(event.target.value)}
        className="w-16 rounded-lg border border-edge bg-card px-2 py-1 text-ink"
      />
      {row.servings != null && !row.scalable && (
        <span
          className="text-amber-600 dark:text-amber-400"
          title="This recipe has no serving size recorded, so its amounts can't be scaled — the base amounts will be used instead."
        >
          {"can't scale"}
        </span>
      )}
      {row.servings != null && row.scalable && row.scale_factor !== 1 && (
        <span className="text-ink-muted">×{row.scale_factor}</span>
      )}
    </div>
  )
}
