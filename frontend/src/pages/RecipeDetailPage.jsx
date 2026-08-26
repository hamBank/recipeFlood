import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  deletePrepared,
  deleteRecipe,
  generateRecipeImage,
  getRecipe,
  listCookLists,
  markPrepared,
} from '../api'
import { useSession } from '../App'
import CookingModeView from '../components/CookingModeView'
import CostPanel from '../components/CostPanel'
import NutritionPanel from '../components/NutritionPanel'
import PreparedLog from '../components/PreparedLog'
import QuickAddToCookList from '../components/QuickAddToCookList'
import {
  formatCents,
  formatDate,
  formatGrams,
  formatMinutes,
  formatQuantity,
  groupIngredients,
  WEIGHT_SOURCE_LABEL,
} from '../format'

function Meta({ label, children }) {
  if (!children) return null
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-ink-faint">{label}</dt>
      <dd className="text-sm text-ink">{children}</dd>
    </div>
  )
}

/** Mirrors backend/slugs.py well enough for a filter link. */
const slugify = (text) =>
  text
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')

export default function RecipeDetailPage() {
  const { slug } = useParams()
  const navigate = useNavigate()
  const { user, config } = useSession()
  const [recipe, setRecipe] = useState(null)
  const [error, setError] = useState(null)
  const [cookList, setCookList] = useState(null)
  const [generatingImage, setGeneratingImage] = useState(false)
  const [imageError, setImageError] = useState(null)
  const [params, setParams] = useSearchParams()
  const symbol = config?.currency_symbol || '$'
  // In the URL rather than plain state: a link to "cooking mode" survives
  // a reload and can be shared/bookmarked — handy for propping a phone up
  // at the counter open to exactly this view.
  const cookingMode = params.get('cooking') === 'true'
  const setCookingMode = (value) => {
    const next = new URLSearchParams(params)
    if (value) next.set('cooking', 'true')
    else next.delete('cooking')
    setParams(next)
  }

  const load = async () => {
    try {
      setRecipe(await getRecipe(slug))
      setError(null)
    } catch (caught) {
      setError(caught.message)
    }
  }

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const data = await getRecipe(slug)
        if (!cancelled) {
          setRecipe(data)
          setError(null)
        }
      } catch (caught) {
        if (!cancelled) setError(caught.message)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [slug])

  useEffect(() => {
    if (!user) {
      setCookList(null)
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const { items } = await listCookLists({ limit: 1, exclude_imported: true })
        if (!cancelled) setCookList(items[0] || null)
      } catch {
        // Quick-add is a convenience; the rest of the page works without it.
      }
    })()
    return () => {
      cancelled = true
    }
  }, [user])

  if (error) return <p className="rounded-lg bg-red-50 p-4 text-red-700">{error}</p>
  if (!recipe) return <p className="text-ink-muted">Loading…</p>

  // Sections already show as badges under the title; don't repeat them.
  const freeTags = recipe.tags.filter((tag) => !recipe.sections?.includes(tag))

  const remove = async () => {
    if (!window.confirm(`Delete “${recipe.title}”? This cannot be undone.`)) return
    await deleteRecipe(recipe.slug)
    navigate('/')
  }

  const generateImage = async () => {
    setGeneratingImage(true)
    setImageError(null)
    try {
      setRecipe(await generateRecipeImage(recipe.slug))
    } catch (caught) {
      setImageError(caught.message)
    }
    setGeneratingImage(false)
  }

  if (cookingMode) {
    return <CookingModeView recipe={recipe} onExit={() => setCookingMode(false)} />
  }

  return (
    <article className="space-y-6">
      <header className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-ink sm:text-3xl">
              {recipe.title}
            </h1>
            {recipe.sections?.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1.5">
                {recipe.sections.map((section) => (
                  <Link
                    key={section}
                    to={`/?tag=${encodeURIComponent(slugify(section))}`}
                    className="rounded bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent"
                  >
                    {section}
                  </Link>
                ))}
              </div>
            )}
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setCookingMode(true)}
              className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-[color:var(--accent-ink)]"
            >
              Cooking mode
            </button>
            {user && (
              <>
                <Link
                  to={`/recipes/${recipe.slug}/edit`}
                  className="rounded-lg border border-edge px-3 py-1.5 text-sm text-ink-muted hover:bg-soft"
                >
                  Edit
                </Link>
                {user.role === 'admin' && (
                  <button
                    onClick={remove}
                    className="rounded-lg border border-edge px-3 py-1.5 text-sm text-ink-muted hover:bg-soft hover:text-red-600"
                  >
                    Delete
                  </button>
                )}
              </>
            )}
          </div>
        </div>

        {recipe.needs_review && user && (
          <p className="rounded-lg bg-soft px-3 py-2 text-sm text-ink-muted">
            <strong className="text-ink">Imported automatically.</strong>{' '}
            {recipe.review_note || 'Check the ingredients and method against the source.'}
            {' '}Edit and save to clear this flag.
          </p>
        )}

        {recipe.description && <p className="text-ink-muted">{recipe.description}</p>}

        {recipe.image_path ? (
          <div className="relative">
            <img
              src={`/media/${recipe.image_path}`}
              alt=""
              className="max-h-96 w-full rounded-xl object-cover"
            />
            {recipe.image_generated && (
              <span
                title="An AI-generated illustration, not a photo of this actual dish"
                className="absolute bottom-2 left-2 rounded-full bg-black/25 px-2 py-0.5 text-[10px] font-normal text-white/70 backdrop-blur-sm"
              >
                AI-generated photo
              </span>
            )}
          </div>
        ) : (
          user && (
            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={generateImage}
                disabled={generatingImage}
                className="rounded-lg border border-edge px-3 py-1.5 text-sm text-ink-muted hover:bg-soft disabled:opacity-50"
              >
                {generatingImage ? 'Generating…' : 'Generate image'}
              </button>
              {imageError && <p className="text-sm text-red-700">{imageError}</p>}
            </div>
          )
        )}

        <dl className="grid grid-cols-2 gap-4 rounded-xl border border-edge bg-card p-4 sm:grid-cols-3 lg:grid-cols-6">
          <Meta label="Prep">{formatMinutes(recipe.prep_minutes)}</Meta>
          <Meta label="Cooking">{formatMinutes(recipe.cook_minutes)}</Meta>
          <Meta label="Total">{formatMinutes(recipe.total_minutes)}</Meta>
          <Meta label="Serves">{recipe.servings_note || recipe.servings}</Meta>
          <Meta label="Added">{formatDate(recipe.added_date)}</Meta>
          <Meta label="Last made">{formatDate(recipe.last_prepared_on)}</Meta>
        </dl>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="space-y-6">
          <section className="rounded-xl border border-edge bg-card p-5">
            <h2 className="font-semibold text-ink">Ingredients</h2>
            {recipe.ingredients.length === 0 ? (
              <p className="mt-2 text-sm text-ink-muted">No ingredients recorded.</p>
            ) : (
              groupIngredients(recipe.ingredients).map(([group, items]) => (
                <div key={group} className="mt-3">
                  {group && (
                    <h3 className="mb-1 text-sm font-semibold text-ink-muted">{group}</h3>
                  )}
                  <ul className="space-y-1.5">
                    {items.map((item) => (
                      <li
                        key={item.id}
                        className="flex flex-wrap items-baseline gap-x-2 border-b border-edge/50 pb-1.5 text-sm last:border-0"
                      >
                        <span className="font-medium text-ink">
                          {formatQuantity(item.quantity)}
                          {item.quantity_max ? `–${formatQuantity(item.quantity_max)}` : ''}
                          {item.unit && item.unit !== 'piece' ? ` ${item.unit}` : ''}
                        </span>
                        <span className="text-ink">{item.name}</span>
                        {item.note && <span className="text-ink-faint">, {item.note}</span>}
                        {item.optional && (
                          <span className="text-xs text-ink-faint">(optional)</span>
                        )}
                        <span className="ml-auto flex items-baseline gap-2 text-xs">
                          {item.weight_grams && (
                            <span
                              title={WEIGHT_SOURCE_LABEL[item.weight_source]}
                              className={
                                item.weight_source === 'estimated'
                                  ? 'text-ink-faint italic'
                                  : 'text-ink-muted'
                              }
                            >
                              {formatGrams(item.weight_grams)}
                              {item.weight_source === 'estimated' && '*'}
                            </span>
                          )}
                          {item.cost_cents !== null && item.cost_cents !== undefined && (
                            <span className="text-ink-faint">
                              {formatCents(item.cost_cents, symbol)}
                            </span>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))
            )}
            {recipe.ingredients.some((i) => i.weight_source === 'estimated') && (
              <p className="mt-3 text-xs text-ink-faint">
                * estimated from a typical density, not stated by the recipe. Add a
                density on the Pantry page to make it exact.
              </p>
            )}
          </section>

          <section className="rounded-xl border border-edge bg-card p-5">
            <h2 className="font-semibold text-ink">Method</h2>
            {recipe.steps.length === 0 ? (
              <p className="mt-2 text-sm text-ink-muted">No method recorded.</p>
            ) : (
              <ol className="mt-3 space-y-3">
                {recipe.steps.map((step) => (
                  <li key={step.id} className="flex gap-3 text-sm leading-relaxed text-ink">
                    <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent">
                      {step.position + 1}
                    </span>
                    <span>{step.text}</span>
                  </li>
                ))}
              </ol>
            )}
          </section>

          {(recipe.storage || recipe.nutrition_note) && (
            <section className="rounded-xl border border-edge bg-card p-5 text-sm">
              {recipe.storage && (
                <>
                  <h2 className="font-semibold text-ink">Storage</h2>
                  <p className="mt-1 text-ink-muted">{recipe.storage}</p>
                </>
              )}
              {recipe.nutrition_note && (
                <>
                  <h2 className="mt-4 font-semibold text-ink">Notes</h2>
                  <p className="mt-1 whitespace-pre-line text-ink-muted">
                    {recipe.nutrition_note}
                  </p>
                </>
              )}
            </section>
          )}
        </div>

        <aside className="space-y-6">
          {user && (
            <div className="rounded-xl border border-edge bg-card p-5">
              <h2 className="font-semibold text-ink">Cooking list</h2>
              {cookList ? (
                <div className="mt-2">
                  <QuickAddToCookList
                    recipeId={recipe.id}
                    cookList={cookList}
                    onChange={setCookList}
                  />
                </div>
              ) : (
                <p className="mt-2 text-sm text-ink-muted">
                  No cooking list yet.{' '}
                  <Link to="/cooking" className="text-accent hover:underline">
                    Start one
                  </Link>
                  .
                </p>
              )}
            </div>
          )}

          <PreparedLog
            recipe={recipe}
            canEdit={Boolean(user)}
            onMark={async (data) => {
              await markPrepared(recipe.slug, data)
              await load()
            }}
            onDelete={async (id) => {
              await deletePrepared(recipe.slug, id)
              await load()
            }}
          />

          {user && <CostPanel cost={recipe.cost} symbol={symbol} />}

          <NutritionPanel
            whole={recipe.nutrition}
            perServing={recipe.nutrition_per_serving}
          />

          {freeTags.length > 0 && (
            <div className="rounded-xl border border-edge bg-card p-5">
              <h2 className="font-semibold text-ink">Tags</h2>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {freeTags.map((tag) => (
                  <Link
                    key={tag}
                    to={`/?tag=${encodeURIComponent(slugify(tag))}`}
                    className="rounded-full border border-edge px-2.5 py-1 text-xs text-ink-muted hover:bg-soft"
                  >
                    {tag}
                  </Link>
                ))}
              </div>
            </div>
          )}

          {recipe.source_url && (
            <div className="rounded-xl border border-edge bg-card p-5 text-sm">
              <h2 className="font-semibold text-ink">Source</h2>
              <a
                href={recipe.source_url}
                target="_blank"
                rel="noreferrer noopener"
                className="mt-1 block break-words text-accent hover:underline"
              >
                {recipe.source_name || recipe.source_url}
              </a>
            </div>
          )}
        </aside>
      </div>
    </article>
  )
}
