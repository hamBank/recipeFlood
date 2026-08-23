import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { createCookList, listCookLists } from '../api'
import { formatDate } from '../format'

const PAGE_SIZE = 30

/**
 * Cooking lists — what we're making, and when.
 *
 * A flat, newest-first list of dates rather than a calendar: the history
 * runs back years (the original CSV import goes back to 2009), and a
 * calendar view of that is mostly empty months. A search box can follow if
 * the list ever gets hard to scan.
 */
export default function CookListsPage() {
  const [lists, setLists] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await listCookLists({
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      })
      setLists(result.items)
      setTotal(result.total)
      setError(null)
    } catch (caught) {
      setError(caught.message)
    }
    setLoading(false)
  }, [page])

  useEffect(() => {
    load()
  }, [load])

  const createToday = async () => {
    setCreating(true)
    try {
      const created = await createCookList({})
      window.location.assign(`/cooking/${created.id}`)
    } catch (caught) {
      setError(caught.message)
      setCreating(false)
    }
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold text-ink">Cooking lists</h1>
        <button
          onClick={createToday}
          disabled={creating}
          className="ml-auto rounded-lg bg-accent px-4 py-2 text-sm font-medium text-[color:var(--accent-ink)] disabled:opacity-50"
        >
          New list
        </button>
      </header>

      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      {loading ? (
        <p className="text-ink-muted">Loading…</p>
      ) : lists.length === 0 ? (
        <p className="rounded-xl border border-edge bg-card p-6 text-center text-ink-muted">
          {"No cooking lists yet. Start one to plan what you're making and send it "}
          straight to the shopping list.
        </p>
      ) : (
        <ul className="divide-y divide-edge overflow-hidden rounded-xl border border-edge bg-card">
          {lists.map((row) => (
            <li key={row.id}>
              <Link
                to={`/cooking/${row.id}`}
                className="flex items-center gap-3 px-4 py-3 hover:bg-soft"
              >
                <span className="w-28 shrink-0 text-sm font-medium text-ink">
                  {formatDate(row.cook_date)}
                </span>
                <span className="min-w-0 flex-1 truncate text-ink">
                  {row.description || (
                    <span className="text-ink-muted">
                      {row.recipe_count} recipe{row.recipe_count === 1 ? '' : 's'}
                    </span>
                  )}
                </span>
                {row.description && (
                  <span className="shrink-0 text-sm text-ink-muted">
                    {row.recipe_count} recipe{row.recipe_count === 1 ? '' : 's'}
                  </span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-center gap-3 text-sm">
          <button
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
            className="rounded-lg border border-edge px-3 py-1 text-ink-muted hover:bg-soft disabled:opacity-40"
          >
            Newer
          </button>
          <span className="text-ink-muted">
            {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total}
          </span>
          <button
            disabled={page * PAGE_SIZE >= total}
            onClick={() => setPage((p) => p + 1)}
            className="rounded-lg border border-edge px-3 py-1 text-ink-muted hover:bg-soft disabled:opacity-40"
          >
            Older
          </button>
        </div>
      )}
    </div>
  )
}
