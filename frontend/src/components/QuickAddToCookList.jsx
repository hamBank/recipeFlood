import { useState } from 'react'
import { addRecipeToCookList, removeRecipeFromCookList } from '../api'
import { formatDate } from '../format'

/** A cooking list's own name, for anywhere this button needs to say which
 *  one it means — most lists never get a description, so the date is the
 *  fallback identity (see backend/models.py CookList). */
export function describeCookList(cookList) {
  return cookList.description || formatDate(cookList.cook_date)
}

/**
 * One-click add/remove of a recipe on the most recent cooking list —
 * "most recent" being whatever `GET /cook-lists` already considers newest
 * (cook_date desc, so a list dated for an upcoming week beats an older one
 * regardless of which was created first).
 *
 * `cookList` is the caller's copy of that list, kept in sync via `onChange`
 * so a grid of many cards and a detail page's own instance never disagree
 * about which recipes are currently on it.
 */
export default function QuickAddToCookList({ recipeId, cookList, onChange, compact }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const onList = cookList.recipes.some((r) => r.recipe_id === recipeId)

  const toggle = async (event) => {
    event.preventDefault() // the card is a <Link>; don't navigate on click
    event.stopPropagation()
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      const updated = onList
        ? await removeRecipeFromCookList(cookList.id, recipeId)
        : await addRecipeToCookList(cookList.id, { recipe_id: recipeId })
      onChange(updated)
    } catch (caught) {
      setError(caught.message)
    }
    setBusy(false)
  }

  if (compact) {
    return (
      <button
        type="button"
        onClick={toggle}
        disabled={busy}
        title={
          onList
            ? `On ${describeCookList(cookList)} — click to remove`
            : `Add to ${describeCookList(cookList)}`
        }
        className={`absolute right-2 top-2 rounded-full px-2 py-1 text-xs font-medium shadow-sm backdrop-blur transition disabled:opacity-60 ${
          onList
            ? 'bg-accent text-[color:var(--accent-ink)]'
            : 'bg-card/90 text-ink-muted hover:bg-card'
        }`}
      >
        {onList ? '✓ Added' : '+ Cook list'}
      </button>
    )
  }

  return (
    <div>
      <button
        type="button"
        onClick={toggle}
        disabled={busy}
        className={`w-full rounded-lg px-3 py-1.5 text-sm font-medium disabled:opacity-60 ${
          onList
            ? 'border border-edge text-ink-muted hover:bg-soft hover:text-red-600'
            : 'bg-accent text-[color:var(--accent-ink)]'
        }`}
      >
        {busy
          ? 'Saving…'
          : onList
            ? `Remove from ${describeCookList(cookList)}`
            : `Add to ${describeCookList(cookList)}`}
      </button>
      {error && <p className="mt-1 text-xs text-red-700">{error}</p>}
    </div>
  )
}
