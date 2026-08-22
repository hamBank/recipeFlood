import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  createRecipe,
  getRecipe,
  listCategories,
  updateRecipe,
  uploadRecipeImage,
} from '../api'

const UNITS = [
  '', 'g', 'kg', 'ml', 'l', 'cup', 'tbsp', 'dsp', 'tsp', 'piece', 'slice',
  'clove', 'bunch', 'sprig', 'can', 'pinch', 'to_taste',
]

const EMPTY_INGREDIENT = {
  name: '',
  quantity: '',
  quantity_max: '',
  unit: '',
  note: '',
  optional: false,
  group: '',
}

function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-ink">{label}</span>
      {children}
      {hint && <span className="mt-0.5 block text-xs text-ink-faint">{hint}</span>}
    </label>
  )
}

const inputClass =
  'mt-1 w-full rounded-lg border border-edge bg-card px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none'

/**
 * Manual entry and editing, and the landing place for an AI import: the
 * Import page navigates here with a draft in router state so every
 * machine-generated recipe is reviewed in the same form a human types into,
 * and nothing reaches the database unread.
 */
export default function RecipeFormPage() {
  const { slug } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const draft = location.state?.draft
  const editing = Boolean(slug)

  const [categories, setCategories] = useState([])
  const [form, setForm] = useState(() => ({
    title: draft?.title || '',
    description: draft?.description || '',
    category_slug: draft?.category_slug || '',
    prep_minutes: draft?.prep_minutes ?? '',
    cook_minutes: draft?.cook_minutes ?? '',
    total_minutes_override: '',
    servings: draft?.servings ?? '',
    servings_note: draft?.servings_note || '',
    storage: draft?.storage || '',
    nutrition_note: draft?.notes || '',
    source_url: draft?.source_url || '',
    source_name: draft?.source_name || '',
    is_published: true,
    tags: (draft?.tags || []).join(', '),
  }))
  const [ingredients, setIngredients] = useState(() =>
    draft?.ingredients?.length
      ? draft.ingredients.map((item) => ({
          ...EMPTY_INGREDIENT,
          ...item,
          quantity: item.quantity ?? '',
          quantity_max: item.quantity_max ?? '',
          unit: item.unit || '',
          note: item.note || '',
          group: item.group || '',
        }))
      : [{ ...EMPTY_INGREDIENT }],
  )
  const [steps, setSteps] = useState(() =>
    draft?.steps?.length ? draft.steps.map((step) => step.text ?? step) : [''],
  )
  const [imageFile, setImageFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(editing)

  useEffect(() => {
    listCategories().then(setCategories).catch(() => {})
  }, [])

  useEffect(() => {
    if (!editing) return
    let cancelled = false
    ;(async () => {
      try {
        const recipe = await getRecipe(slug)
        if (cancelled) return
        setForm({
          title: recipe.title,
          description: recipe.description || '',
          category_slug:
            categories.find((c) => c.id === recipe.category_id)?.slug || '',
          prep_minutes: recipe.prep_minutes ?? '',
          cook_minutes: recipe.cook_minutes ?? '',
          total_minutes_override: recipe.total_minutes_override ?? '',
          servings: recipe.servings ?? '',
          servings_note: recipe.servings_note || '',
          storage: recipe.storage || '',
          nutrition_note: recipe.nutrition_note || '',
          source_url: recipe.source_url || '',
          source_name: recipe.source_name || '',
          is_published: recipe.is_published,
          tags: recipe.tags.join(', '),
          _category_id: recipe.category_id,
        })
        setIngredients(
          recipe.ingredients.length
            ? recipe.ingredients.map((item) => ({
                name: item.name,
                quantity: item.quantity ?? '',
                quantity_max: item.quantity_max ?? '',
                unit: item.unit || '',
                note: item.note || '',
                optional: item.optional,
                group: item.group || '',
                ingredient_id: item.ingredient_id,
              }))
            : [{ ...EMPTY_INGREDIENT }],
        )
        setSteps(recipe.steps.length ? recipe.steps.map((step) => step.text) : [''])
      } catch (caught) {
        if (!cancelled) setError(caught.message)
      }
      if (!cancelled) setLoading(false)
    })()
    return () => {
      cancelled = true
    }
  }, [slug, editing, categories])

  const set = (key, value) => setForm((previous) => ({ ...previous, [key]: value }))

  const setIngredient = (index, key, value) =>
    setIngredients((previous) =>
      previous.map((item, i) => (i === index ? { ...item, [key]: value } : item)),
    )

  const number = (value) => (value === '' || value === null ? null : Number(value))

  const submit = async (event) => {
    event.preventDefault()
    if (!form.title.trim()) {
      setError('A title is required')
      return
    }
    setBusy(true)
    setError(null)

    const payload = {
      title: form.title.trim(),
      description: form.description.trim() || null,
      category_slug: form.category_slug || null,
      category_id: form.category_slug ? null : form._category_id ?? null,
      prep_minutes: number(form.prep_minutes),
      cook_minutes: number(form.cook_minutes),
      total_minutes_override: number(form.total_minutes_override),
      servings: number(form.servings),
      servings_note: form.servings_note.trim() || null,
      storage: form.storage.trim() || null,
      nutrition_note: form.nutrition_note.trim() || null,
      source_url: form.source_url.trim() || null,
      source_name: form.source_name.trim() || null,
      is_published: form.is_published,
      tags: form.tags
        .split(',')
        .map((tag) => tag.trim())
        .filter(Boolean),
      ingredients: ingredients
        .filter((item) => item.name.trim())
        .map((item) => ({
          ingredient_id: item.ingredient_id ?? null,
          name: item.name.trim(),
          quantity: number(item.quantity),
          quantity_max: number(item.quantity_max),
          unit: item.unit || null,
          note: item.note.trim() || null,
          optional: Boolean(item.optional),
          group: item.group.trim() || null,
        })),
      steps: steps.filter((text) => text.trim()).map((text) => ({ text: text.trim() })),
    }
    // Saving is the human review: an edited recipe is no longer unchecked.
    if (editing) payload.needs_review = false

    try {
      const saved = editing
        ? await updateRecipe(slug, payload)
        : await createRecipe(payload)
      if (imageFile) await uploadRecipeImage(saved.slug, imageFile)
      navigate(`/recipes/${saved.slug}`)
    } catch (caught) {
      setError(caught.message)
      setBusy(false)
    }
  }

  if (loading) return <p className="text-ink-muted">Loading…</p>

  return (
    <form onSubmit={submit} className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-ink">
          {editing ? 'Edit recipe' : 'Add a recipe'}
        </h1>
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-[color:var(--accent-ink)] disabled:opacity-50"
        >
          {busy ? 'Saving…' : editing ? 'Save changes' : 'Create recipe'}
        </button>
      </div>

      {draft && (
        <p className="rounded-lg bg-accent-soft px-3 py-2 text-sm text-accent">
          Pre-filled from an AI import
          {draft.confidence ? ` (confidence ${Math.round(draft.confidence * 100)}%)` : ''}.
          Check everything before saving.
          {draft.uncertain?.length > 0 && (
            <> Flagged: {draft.uncertain.join('; ')}.</>
          )}
        </p>
      )}

      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      <section className="grid gap-4 rounded-xl border border-edge bg-card p-5 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Field label="Title">
            <input
              value={form.title}
              onChange={(event) => set('title', event.target.value)}
              className={inputClass}
              required
            />
          </Field>
        </div>
        <div className="sm:col-span-2">
          <Field label="Description">
            <textarea
              value={form.description}
              onChange={(event) => set('description', event.target.value)}
              rows={2}
              className={inputClass}
            />
          </Field>
        </div>

        <Field label="Type">
          <select
            value={form.category_slug}
            onChange={(event) => set('category_slug', event.target.value)}
            className={inputClass}
          >
            <option value="">— none —</option>
            {categories.map((category) => (
              <option key={category.slug} value={category.slug}>
                {category.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Tags" hint="Comma separated">
          <input
            value={form.tags}
            onChange={(event) => set('tags', event.target.value)}
            placeholder="baking, chocolate, christmas"
            className={inputClass}
          />
        </Field>

        <Field label="Prep time (minutes)">
          <input
            type="number"
            min="0"
            value={form.prep_minutes}
            onChange={(event) => set('prep_minutes', event.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Cooking time (minutes)">
          <input
            type="number"
            min="0"
            value={form.cook_minutes}
            onChange={(event) => set('cook_minutes', event.target.value)}
            className={inputClass}
          />
        </Field>
        <Field
          label="Total time override (minutes)"
          hint="Leave blank to use prep + cooking. Set it when there's proving or chilling too."
        >
          <input
            type="number"
            min="0"
            value={form.total_minutes_override}
            onChange={(event) => set('total_minutes_override', event.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Servings" hint="A number — used for per-serve cost and nutrition">
          <input
            type="number"
            min="1"
            value={form.servings}
            onChange={(event) => set('servings', event.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Servings note">
          <input
            value={form.servings_note}
            onChange={(event) => set('servings_note', event.target.value)}
            placeholder="makes 24 biscuits"
            className={inputClass}
          />
        </Field>
        <Field label="Storage">
          <input
            value={form.storage}
            onChange={(event) => set('storage', event.target.value)}
            placeholder="Airtight container, 5 days"
            className={inputClass}
          />
        </Field>

        <Field label="Source name">
          <input
            value={form.source_name}
            onChange={(event) => set('source_name', event.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Source link">
          <input
            type="url"
            value={form.source_url}
            onChange={(event) => set('source_url', event.target.value)}
            className={inputClass}
          />
        </Field>

        <Field label="Photo">
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp,image/gif"
            onChange={(event) => setImageFile(event.target.files?.[0] || null)}
            className="mt-1 w-full text-sm text-ink-muted"
          />
        </Field>
        <label className="flex items-center gap-2 self-end text-sm text-ink">
          <input
            type="checkbox"
            checked={form.is_published}
            onChange={(event) => set('is_published', event.target.checked)}
          />
          Published (visible to everyone)
        </label>
      </section>

      <section className="rounded-xl border border-edge bg-card p-5">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-ink">Ingredients</h2>
          <button
            type="button"
            onClick={() => setIngredients((previous) => [...previous, { ...EMPTY_INGREDIENT }])}
            className="rounded-lg border border-edge px-3 py-1 text-sm text-ink-muted hover:bg-soft"
          >
            + Add
          </button>
        </div>
        <p className="mt-1 text-xs text-ink-faint">
          Leave the weight to us — amounts in cups, spoons or counts are converted
          to grams using the master ingredient list (Australian measures: 1 cup =
          250ml, 1 tbsp = 20ml).
        </p>

        <div className="mt-3 space-y-2">
          {ingredients.map((item, index) => (
            <div key={index} className="flex flex-wrap items-center gap-2">
              <input
                type="number"
                step="any"
                value={item.quantity}
                onChange={(event) => setIngredient(index, 'quantity', event.target.value)}
                placeholder="Qty"
                className="w-20 rounded-lg border border-edge bg-card px-2 py-1.5 text-sm text-ink"
              />
              <select
                value={item.unit}
                onChange={(event) => setIngredient(index, 'unit', event.target.value)}
                className="w-24 rounded-lg border border-edge bg-card px-2 py-1.5 text-sm text-ink"
              >
                {UNITS.map((unit) => (
                  <option key={unit} value={unit}>
                    {unit || '—'}
                  </option>
                ))}
              </select>
              <input
                value={item.name}
                onChange={(event) => setIngredient(index, 'name', event.target.value)}
                placeholder="Ingredient"
                className="min-w-40 flex-1 rounded-lg border border-edge bg-card px-2 py-1.5 text-sm text-ink"
              />
              <input
                value={item.note}
                onChange={(event) => setIngredient(index, 'note', event.target.value)}
                placeholder="finely chopped"
                className="min-w-32 flex-1 rounded-lg border border-edge bg-card px-2 py-1.5 text-sm text-ink"
              />
              <input
                value={item.group}
                onChange={(event) => setIngredient(index, 'group', event.target.value)}
                placeholder="Group"
                className="w-28 rounded-lg border border-edge bg-card px-2 py-1.5 text-sm text-ink"
              />
              <label className="flex items-center gap-1 text-xs text-ink-muted">
                <input
                  type="checkbox"
                  checked={item.optional}
                  onChange={(event) => setIngredient(index, 'optional', event.target.checked)}
                />
                opt
              </label>
              <button
                type="button"
                onClick={() =>
                  setIngredients((previous) => previous.filter((_, i) => i !== index))
                }
                className="px-1 text-ink-faint hover:text-red-600"
                aria-label="Remove ingredient"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-xl border border-edge bg-card p-5">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-ink">Method</h2>
          <button
            type="button"
            onClick={() => setSteps((previous) => [...previous, ''])}
            className="rounded-lg border border-edge px-3 py-1 text-sm text-ink-muted hover:bg-soft"
          >
            + Add step
          </button>
        </div>
        <ol className="mt-3 space-y-2">
          {steps.map((text, index) => (
            <li key={index} className="flex items-start gap-2">
              <span className="mt-2 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent">
                {index + 1}
              </span>
              <textarea
                value={text}
                rows={2}
                onChange={(event) =>
                  setSteps((previous) =>
                    previous.map((step, i) => (i === index ? event.target.value : step)),
                  )
                }
                className="flex-1 rounded-lg border border-edge bg-card px-3 py-1.5 text-sm text-ink"
              />
              <button
                type="button"
                onClick={() => setSteps((previous) => previous.filter((_, i) => i !== index))}
                className="mt-2 px-1 text-ink-faint hover:text-red-600"
                aria-label="Remove step"
              >
                ✕
              </button>
            </li>
          ))}
        </ol>
      </section>

      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="rounded-lg border border-edge px-4 py-2 text-sm text-ink-muted hover:bg-soft"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-[color:var(--accent-ink)] disabled:opacity-50"
        >
          {busy ? 'Saving…' : editing ? 'Save changes' : 'Create recipe'}
        </button>
      </div>
    </form>
  )
}
