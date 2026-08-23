import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { listCookLists, listRecipes, listSections, listTags } from '../api'
import { useSession } from '../App'
import RecipeCard from '../components/RecipeCard'

const PAGE_SIZE = 24

const SORTS = [
  { value: 'added', label: 'Recently added' },
  { value: 'title', label: 'A–Z' },
  { value: 'last_prepared', label: 'Recently cooked' },
  { value: 'total_time', label: 'Quickest' },
]

export default function RecipeListPage() {
  const { user } = useSession()
  // Filters live in the URL so a filtered view is a shareable link and the
  // back button steps through searches the way people expect.
  const [params, setParams] = useSearchParams()
  const [sections, setSections] = useState([])
  const [tags, setTags] = useState([])
  const [recipes, setRecipes] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState(params.get('q') || '')
  // Fetched once, signed-in only — the quick-add button on each card
  // needs to know (and update) the same list, not a copy per card.
  const [cookList, setCookList] = useState(null)

  const q = params.get('q') || ''
  // Sections and free tags both filter through the same `tag` parameter —
  // a section is a tag. They stay separate in the URL only so the select
  // and the chip row don't fight over one value.
  const section = params.get('section') || ''
  const tag = params.get('tag') || ''
  const sort = params.get('sort') || 'added'
  const order = params.get('order') || (sort === 'title' ? 'asc' : 'desc')
  const page = Number(params.get('page') || 1)
  const reviewOnly = params.get('needs_review') === 'true'

  const update = useCallback(
    (changes) => {
      const next = new URLSearchParams(params)
      Object.entries(changes).forEach(([key, value]) => {
        if (value === '' || value === null || value === undefined) next.delete(key)
        else next.set(key, value)
      })
      if (!('page' in changes)) next.delete('page')
      setParams(next)
    },
    [params, setParams],
  )

  useEffect(() => {
    ;(async () => {
      try {
        const [sectionList, tagList] = await Promise.all([listSections(), listTags(2)])
        setSections(sectionList.filter((s) => s.recipe_count > 0))
        setTags(tagList.slice(0, 30))
      } catch {
        // Filters are a convenience; the grid below still works without them.
      }
    })()
  }, [])

  useEffect(() => {
    if (!user) {
      setCookList(null)
      return
    }
    ;(async () => {
      try {
        const { items } = await listCookLists({ limit: 1, exclude_imported: true })
        setCookList(items[0] || null)
      } catch {
        // Quick-add is a convenience; the grid works fine without it.
      }
    })()
  }, [user])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    ;(async () => {
      try {
        const result = await listRecipes({
          q,
          // Both narrow by tag slug; sending both intersects them.
          tag: tag || section,
          sort,
          order,
          limit: PAGE_SIZE,
          offset: (page - 1) * PAGE_SIZE,
          needs_review: reviewOnly ? 'true' : '',
          include_unpublished: user ? 'true' : '',
          // Recipes with no ingredients, no method and no notes (a book
          // citation from the history import, typically) are hidden from
          // normal browsing — but "Needs review" is exactly where they
          // should surface, since an empty recipe needs the most work.
          include_empty: reviewOnly ? 'true' : '',
        })
        if (cancelled) return
        setRecipes(result.items)
        setTotal(result.total)
        setError(null)
      } catch (caught) {
        if (!cancelled) setError(caught.message)
      }
      if (!cancelled) setLoading(false)
    })()
    return () => {
      cancelled = true
    }
  }, [q, section, tag, sort, order, page, reviewOnly, user])

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="space-y-5">
      <form
        onSubmit={(event) => {
          event.preventDefault()
          update({ q: search.trim() })
        }}
        className="flex flex-wrap items-center gap-2"
      >
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search recipes…"
          className="min-w-0 flex-1 rounded-lg border border-edge bg-card px-3 py-2 text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
        />
        <select
          value={section}
          onChange={(event) => update({ section: event.target.value, tag: '' })}
          className="rounded-lg border border-edge bg-card px-3 py-2 text-sm text-ink"
        >
          <option value="">All sections</option>
          {sections.map((s) => (
            <option key={s.slug} value={s.slug}>
              {s.name} ({s.recipe_count})
            </option>
          ))}
        </select>
        <select
          value={sort}
          onChange={(event) =>
            update({
              sort: event.target.value,
              order: event.target.value === 'title' || event.target.value === 'total_time' ? 'asc' : 'desc',
            })
          }
          className="rounded-lg border border-edge bg-card px-3 py-2 text-sm text-ink"
        >
          {SORTS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        {user && (
          <label className="flex items-center gap-1.5 rounded-lg border border-edge bg-card px-3 py-2 text-sm text-ink-muted">
            <input
              type="checkbox"
              checked={reviewOnly}
              onChange={(event) => update({ needs_review: event.target.checked ? 'true' : '' })}
            />
            Needs review
          </label>
        )}
      </form>

      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {tag && (
            <button
              onClick={() => update({ tag: '' })}
              className="rounded-full bg-accent px-2.5 py-1 text-xs text-[color:var(--accent-ink)]"
            >
              {tag} ✕
            </button>
          )}
          {tags
            .filter((t) => t.slug !== tag)
            .map((t) => (
              <button
                key={t.slug}
                onClick={() => update({ tag: t.slug })}
                className="rounded-full border border-edge px-2.5 py-1 text-xs text-ink-muted hover:bg-soft"
              >
                {t.name}
                <span className="ml-1 text-ink-faint">{t.recipe_count}</span>
              </button>
            ))}
        </div>
      )}

      <p className="text-sm text-ink-muted">
        {loading ? 'Loading…' : `${total} recipe${total === 1 ? '' : 's'}`}
        {(q || section || tag) && !loading && ' matching your filters'}
      </p>

      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      {!loading && recipes.length === 0 && !error && (
        <div className="rounded-xl border border-dashed border-edge p-10 text-center text-ink-muted">
          Nothing here yet.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {recipes.map((recipe) => (
          <RecipeCard
            key={recipe.id}
            recipe={recipe}
            cookList={cookList}
            onCookListChange={setCookList}
          />
        ))}
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-center gap-3 pt-2">
          <button
            disabled={page <= 1}
            onClick={() => update({ page: page - 1 })}
            className="rounded-lg border border-edge px-3 py-1.5 text-sm text-ink-muted disabled:opacity-40"
          >
            Previous
          </button>
          <span className="text-sm text-ink-muted">
            Page {page} of {pages}
          </span>
          <button
            disabled={page >= pages}
            onClick={() => update({ page: page + 1 })}
            className="rounded-lg border border-edge px-3 py-1.5 text-sm text-ink-muted disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
