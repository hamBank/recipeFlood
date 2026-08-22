import { useState } from 'react'
import { SOURCE_LABEL } from '../format'

const NUTRIENTS = [
  ['energy_kj', 'Energy (kJ)'],
  ['calories_kcal', 'Calories (kcal)'],
  ['protein_g', 'Protein (g)'],
  ['fat_g', 'Fat (g)'],
  ['saturated_fat_g', 'Saturated fat (g)'],
  ['carbs_g', 'Carbohydrate (g)'],
  ['sugars_g', 'Sugars (g)'],
  ['fibre_g', 'Fibre (g)'],
  ['sodium_mg', 'Sodium (mg)'],
]

const inputClass =
  'mt-1 w-full rounded-lg border border-edge bg-card px-3 py-2 text-sm text-ink'

function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-ink">{label}</span>
      {children}
      {hint && <span className="mt-0.5 block text-xs text-ink-faint">{hint}</span>}
    </label>
  )
}

/**
 * Edit one pantry item.
 *
 * Two fields here are quietly the most valuable on the whole page:
 * **density** turns every "1 cup" of this ingredient into grams across the
 * collection, and **grams per piece** does the same for "2 onions". Saving
 * either one re-derives the weights of every recipe line that uses it.
 */
export default function IngredientEditor({ ingredient, symbol, onClose, onSave }) {
  const [form, setForm] = useState(() => ({
    name: ingredient.name,
    aliases: (ingredient.aliases || []).join(', '),
    package_size_grams: ingredient.package_size_grams ?? '',
    // Prices are entered per kilogram — nobody knows a price per gram, and
    // the backend stores cents/kg anyway.
    cost_per_kg: ingredient.cost_per_kg_cents !== null && ingredient.cost_per_kg_cents !== undefined
      ? (ingredient.cost_per_kg_cents / 100).toFixed(2)
      : '',
    source: ingredient.source,
    density_g_per_ml: ingredient.density_g_per_ml ?? '',
    grams_per_piece: ingredient.grams_per_piece ?? '',
    nutrition_source: ingredient.nutrition_source || '',
    is_food: ingredient.is_food,
    notes: ingredient.notes || '',
    ...Object.fromEntries(NUTRIENTS.map(([key]) => [key, ingredient[key] ?? ''])),
  }))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const set = (key, value) => setForm((previous) => ({ ...previous, [key]: value }))
  const number = (value) => (value === '' ? null : Number(value))

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await onSave({
        name: form.name.trim(),
        aliases: form.aliases
          .split(',')
          .map((alias) => alias.trim())
          .filter(Boolean),
        package_size_grams: number(form.package_size_grams),
        cost_per_kg_cents:
          form.cost_per_kg === '' ? null : Math.round(Number(form.cost_per_kg) * 100),
        source: form.source,
        is_food: form.is_food,
        density_g_per_ml: number(form.density_g_per_ml),
        grams_per_piece: number(form.grams_per_piece),
        nutrition_source: form.nutrition_source.trim() || null,
        notes: form.notes.trim() || null,
        ...Object.fromEntries(NUTRIENTS.map(([key]) => [key, number(form[key])])),
      })
    } catch (caught) {
      setError(caught.message)
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4"
      onClick={onClose}
    >
      <form
        onClick={(event) => event.stopPropagation()}
        onSubmit={submit}
        className="my-8 w-full max-w-2xl space-y-4 rounded-xl bg-card p-6 shadow-xl"
      >
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-ink">{ingredient.name}</h2>
          <button type="button" onClick={onClose} className="text-ink-faint hover:text-ink">
            ✕
          </button>
        </div>
        <p className="text-xs text-ink-faint">
          Used in {ingredient.recipe_count} recipe
          {ingredient.recipe_count === 1 ? '' : 's'}.
        </p>

        {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name">
            <input value={form.name} onChange={(e) => set('name', e.target.value)} className={inputClass} />
          </Field>
          <Field label="Also known as" hint="Comma separated — used when matching recipes">
            <input value={form.aliases} onChange={(e) => set('aliases', e.target.value)} className={inputClass} />
          </Field>

          <Field label="Usual package size (g)">
            <input type="number" step="any" min="0" value={form.package_size_grams}
              onChange={(e) => set('package_size_grams', e.target.value)} className={inputClass} />
          </Field>
          <Field label={`Cost per kg (${symbol})`} hint="Stored as cents per kg — plenty of resolution for a per-gram price">
            <input type="number" step="0.01" min="0" value={form.cost_per_kg}
              onChange={(e) => set('cost_per_kg', e.target.value)} className={inputClass} />
          </Field>

          <Field label="Bought from">
            <select value={form.source} onChange={(e) => set('source', e.target.value)} className={inputClass}>
              {Object.entries(SOURCE_LABEL).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </Field>
          <Field label="Notes">
            <input value={form.notes} onChange={(e) => set('notes', e.target.value)} className={inputClass} />
          </Field>
          <label className="flex items-center gap-2 self-end text-sm text-ink">
            <input
              type="checkbox"
              checked={form.is_food}
              onChange={(e) => set('is_food', e.target.checked)}
            />
            It&rsquo;s food
            <span className="text-xs text-ink-faint">
              (uncheck for batteries, shampoo and the like)
            </span>
          </label>
        </div>

        <fieldset className="rounded-lg border border-edge p-4">
          <legend className="px-1 text-sm font-semibold text-ink">Weight conversion</legend>
          <p className="mb-2 text-xs text-ink-faint">
            Saving either of these re-derives the weight of every recipe line that
            uses this ingredient.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Density (g per ml)" hint="1 AU cup = 250ml, so flour at 0.6 = 150g per cup">
              <input type="number" step="any" min="0" value={form.density_g_per_ml}
                onChange={(e) => set('density_g_per_ml', e.target.value)} className={inputClass} />
            </Field>
            <Field label="Grams per piece" hint="For countable things — 1 egg = 50g">
              <input type="number" step="any" min="0" value={form.grams_per_piece}
                onChange={(e) => set('grams_per_piece', e.target.value)} className={inputClass} />
            </Field>
          </div>
        </fieldset>

        <fieldset className="rounded-lg border border-edge p-4">
          <legend className="px-1 text-sm font-semibold text-ink">Nutrition per 100 g</legend>
          <div className="grid gap-3 sm:grid-cols-3">
            {NUTRIENTS.map(([key, label]) => (
              <Field key={key} label={label}>
                <input type="number" step="any" min="0" value={form[key]}
                  onChange={(e) => set(key, e.target.value)} className={inputClass} />
              </Field>
            ))}
            <div className="sm:col-span-3">
              <Field label="Where these figures came from" hint="e.g. the packet, AUSNUT, a brand website">
                <input value={form.nutrition_source}
                  onChange={(e) => set('nutrition_source', e.target.value)} className={inputClass} />
              </Field>
            </div>
          </div>
        </fieldset>

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose}
            className="rounded-lg border border-edge px-4 py-2 text-sm text-ink-muted hover:bg-soft">
            Cancel
          </button>
          <button type="submit" disabled={busy}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-[color:var(--accent-ink)] disabled:opacity-50">
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </div>
  )
}
