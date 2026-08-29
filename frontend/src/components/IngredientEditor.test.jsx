import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import IngredientEditor from './IngredientEditor'

// Field wraps its <input> in a <label> alongside a hint <span>, so the
// label's full text isn't just the field name — look the input up by its
// label's own span instead of the (unsupported) exact-text match.
const inputForLabel = (text) => screen.getByText(text).closest('label').querySelector('input, select')

const ingredient = (overrides = {}) => ({
  id: 1,
  name: 'Onion',
  aliases: ['brown onion'],
  measure_kind: 'weight',
  package_size_grams: 150,
  package_size_ml: null,
  cost_per_kg_cents: 250,
  cost_per_litre_cents: null,
  cost_source: 'supermarket',
  cost_updated_at: null,
  source: 'supermarket',
  density_g_per_ml: null,
  grams_per_piece: 150,
  nutrition_source: null,
  is_food: true,
  notes: '',
  recipe_count: 4,
  energy_kj: null,
  calories_kcal: null,
  protein_g: null,
  fat_g: null,
  saturated_fat_g: null,
  carbs_g: null,
  sugars_g: null,
  fibre_g: null,
  sodium_mg: null,
  ...overrides,
})

const renderEditor = (props = {}) =>
  render(
    <IngredientEditor
      ingredient={ingredient()}
      symbol="$"
      onClose={vi.fn()}
      onSave={vi.fn()}
      {...props}
    />
  )

describe('IngredientEditor', () => {
  it('pre-fills the form from the given ingredient', () => {
    renderEditor()
    expect(screen.getByDisplayValue('Onion')).toBeDefined()
    expect(screen.getByDisplayValue('brown onion')).toBeDefined()
    expect(inputForLabel('Usual package size (g)').value).toBe('150')
    expect(inputForLabel('Grams per piece').value).toBe('150')
    // cost_per_kg_cents 250 -> $2.50
    expect(screen.getByDisplayValue('2.50')).toBeDefined()
    expect(screen.getByText('Used in 4 recipes.')).toBeDefined()
  })

  it('uses the singular for a single recipe', () => {
    renderEditor({ ingredient: ingredient({ recipe_count: 1 }) })
    expect(screen.getByText('Used in 1 recipe.')).toBeDefined()
  })

  it('shows weight fields by default and switches to volume fields', () => {
    renderEditor()
    expect(screen.getByText('Usual package size (g)')).toBeDefined()
    expect(screen.queryByText('Usual package size (mL)')).toBeNull()

    fireEvent.change(screen.getByDisplayValue('Weight'), { target: { value: 'volume' } })
    expect(screen.getByText('Usual package size (mL)')).toBeDefined()
    expect(screen.queryByText('Usual package size (g)')).toBeNull()
  })

  it('calls onClose from the header button, the cancel button, and the backdrop', () => {
    const onClose = vi.fn()
    const { container } = renderEditor({ onClose })

    fireEvent.click(screen.getByRole('button', { name: '✕' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    fireEvent.click(container.firstChild)
    expect(onClose).toHaveBeenCalledTimes(3)
  })

  it('does not close when clicking inside the form itself', () => {
    const onClose = vi.fn()
    renderEditor({ onClose })
    fireEvent.click(screen.getByText('Weight conversion'))
    expect(onClose).not.toHaveBeenCalled()
  })

  it('submits the edited form, converting money fields to cents and splitting aliases', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined)
    renderEditor({ onSave })

    fireEvent.change(screen.getByDisplayValue('Onion'), { target: { value: 'Red onion' } })
    fireEvent.change(screen.getByDisplayValue('brown onion'), { target: { value: 'red onion, spanish onion' } })
    fireEvent.change(screen.getByDisplayValue('2.50'), { target: { value: '3.10' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(onSave).toHaveBeenCalled())
    expect(onSave.mock.calls[0][0]).toMatchObject({
      name: 'Red onion',
      aliases: ['red onion', 'spanish onion'],
      cost_per_kg_cents: 310,
      grams_per_piece: 150,
    })
  })

  it('sends null for numeric fields left blank', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined)
    renderEditor({ onSave })

    fireEvent.change(inputForLabel('Grams per piece'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(onSave).toHaveBeenCalled())
    expect(onSave.mock.calls[0][0].grams_per_piece).toBeNull()
  })

  it('shows an error and re-enables Save when the save fails', async () => {
    const onSave = vi.fn().mockRejectedValue(new Error('name already taken'))
    renderEditor({ onSave })

    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(screen.getByText('name already taken')).toBeDefined())
    expect(screen.getByRole('button', { name: 'Save' }).disabled).toBe(false)
  })
})
