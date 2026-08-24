import { useState } from 'react'
import { formatMinutes, formatQuantity, groupIngredients } from '../format'

/**
 * A stripped-down, one-handed-friendly view of a recipe for actually
 * cooking from — ingredients you can tick off, a numbered method, and
 * nothing else. No photo (a counter covered in flour is not the moment
 * for a hero image), no cost, no nutrition, no edit controls.
 *
 * Ticked ingredients are local-only state: there's no "half-measured"
 * concept worth persisting, and leaving cooking mode resets it, same as
 * closing a paper recipe card.
 */
export default function CookingModeView({ recipe, onExit }) {
  const [checked, setChecked] = useState(() => new Set())

  const toggle = (id) => {
    setChecked((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div className="flex items-start justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight text-ink sm:text-3xl">
          {recipe.title}
        </h1>
        <button
          onClick={onExit}
          className="shrink-0 rounded-lg border border-edge px-3 py-1.5 text-sm text-ink-muted hover:bg-soft"
        >
          Exit
        </button>
      </div>

      {(recipe.servings || formatMinutes(recipe.total_minutes)) && (
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-ink-muted">
          {recipe.servings && <span>Serves {recipe.servings_note || recipe.servings}</span>}
          {formatMinutes(recipe.total_minutes) && <span>{formatMinutes(recipe.total_minutes)}</span>}
        </div>
      )}

      <section>
        <h2 className="text-lg font-semibold text-ink">Ingredients</h2>
        {recipe.ingredients.length === 0 ? (
          <p className="mt-2 text-ink-muted">No ingredients recorded.</p>
        ) : (
          groupIngredients(recipe.ingredients).map(([group, items]) => (
            <div key={group} className="mt-3">
              {group && <h3 className="mb-1 font-semibold text-ink-muted">{group}</h3>}
              <ul className="divide-y divide-edge/50">
                {items.map((item) => {
                  const isChecked = checked.has(item.id)
                  return (
                    <li key={item.id}>
                      <label className="flex cursor-pointer items-start gap-3 py-2.5 text-base leading-snug">
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => toggle(item.id)}
                          className="mt-1 h-5 w-5 shrink-0 accent-accent"
                        />
                        <span className={isChecked ? 'text-ink-faint line-through' : 'text-ink'}>
                          <span className="font-medium">
                            {item.quantity !== null && item.quantity !== undefined && (
                              <>
                                {formatQuantity(item.quantity)}
                                {item.quantity_max ? `–${formatQuantity(item.quantity_max)}` : ''}{' '}
                              </>
                            )}
                            {item.unit && item.unit !== 'piece' ? `${item.unit} ` : ''}
                          </span>
                          {item.name}
                          {item.note && <span className="text-ink-faint">, {item.note}</span>}
                          {item.optional && <span className="text-ink-faint"> (optional)</span>}
                        </span>
                      </label>
                    </li>
                  )
                })}
              </ul>
            </div>
          ))
        )}
      </section>

      <section>
        <h2 className="text-lg font-semibold text-ink">Method</h2>
        {recipe.steps.length === 0 ? (
          <p className="mt-2 text-ink-muted">No method recorded.</p>
        ) : (
          <ol className="mt-3 space-y-4">
            {recipe.steps.map((step) => (
              <li key={step.id} className="flex gap-3 text-base leading-relaxed text-ink">
                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-soft text-sm font-semibold text-accent">
                  {step.position + 1}
                </span>
                <span>{step.text}</span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  )
}
