import { Link } from 'react-router-dom'
import { formatMinutes, formatRelative } from '../format'
import QuickAddToCookList from './QuickAddToCookList'

/** Placeholder for the ~99% of scraped recipes with no usable photo:
 *  the first letter over a hue derived from the title, so the grid stays
 *  varied and each card is still recognisable at a glance. */
function Placeholder({ title }) {
  let hash = 0
  for (let i = 0; i < title.length; i += 1) hash = (hash * 31 + title.charCodeAt(i)) % 360
  return (
    <div
      className="flex h-40 items-center justify-center text-4xl font-bold text-white/90"
      style={{ backgroundColor: `hsl(${hash} 38% 55%)` }}
      aria-hidden="true"
    >
      {title.trim().charAt(0).toUpperCase() || '?'}
    </div>
  )
}

export default function RecipeCard({ recipe, cookList, onCookListChange }) {
  const time = formatMinutes(recipe.total_minutes)
  const lastMade = formatRelative(recipe.last_prepared_on)

  return (
    <Link
      to={`/recipes/${recipe.slug}`}
      className="group flex flex-col overflow-hidden rounded-xl border border-edge bg-card shadow-sm transition hover:shadow-md"
    >
      <div className="relative">
        {cookList && (
          <QuickAddToCookList
            recipeId={recipe.id}
            cookList={cookList}
            onChange={onCookListChange}
            compact
          />
        )}

        {recipe.image_path ? (
          <img
            src={`/media/${recipe.image_path}`}
            alt=""
            loading="lazy"
            className="h-40 w-full object-cover"
          />
        ) : (
          <Placeholder title={recipe.title} />
        )}

        {recipe.image_generated && (
          <span
            title="An AI-generated illustration, not a photo of this actual dish"
            className="absolute bottom-1.5 left-1.5 rounded-full bg-black/25 px-1.5 py-0.5 text-[9px] font-normal text-white/70 backdrop-blur-sm"
          >
            AI photo
          </span>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-2 p-4">
        <div className="flex items-start justify-between gap-2">
          <h3 className="font-semibold leading-snug text-ink group-hover:text-accent">
            {recipe.title}
          </h3>
          {recipe.needs_review && (
            <span
              title="Imported automatically — not yet checked by a human"
              className="shrink-0 rounded bg-soft px-1.5 py-0.5 text-[11px] text-ink-muted"
            >
              review
            </span>
          )}
        </div>

        {recipe.description && (
          <p className="line-clamp-2 text-sm text-ink-muted">{recipe.description}</p>
        )}

        <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-faint">
          {recipe.sections?.[0] && (
            <span className="rounded bg-accent-soft px-1.5 py-0.5 text-[11px] font-medium text-accent">
              {recipe.sections[0]}
            </span>
          )}
          {time && <span>{time}</span>}
          {recipe.servings && <span>serves {recipe.servings}</span>}
          {lastMade && <span>made {lastMade}</span>}
        </div>
      </div>
    </Link>
  )
}
