import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api'
import RecipeFormPage from './RecipeFormPage'

// Field wraps its input in a <label> alongside a hint <span>, so the
// label's full text isn't just the field name for fields with a hint —
// look the input up by its label's own span instead of an exact match.
const inputForLabel = (text) => screen.getByText(text).closest('label').querySelector('input, select, textarea')

vi.mock('../api', () => ({
  createRecipe: vi.fn(),
  getRecipe: vi.fn(),
  listSections: vi.fn(),
  updateRecipe: vi.fn(),
  uploadRecipeImage: vi.fn(),
}))

function RecipeStub() {
  const location = useLocation()
  return <div>Landed on {location.pathname}</div>
}

const renderNewForm = (draft) =>
  render(
    <MemoryRouter initialEntries={[{ pathname: '/new', state: draft ? { draft } : undefined }]}>
      <Routes>
        <Route path="/new" element={<RecipeFormPage />} />
        <Route path="/recipes/:slug" element={<RecipeStub />} />
      </Routes>
    </MemoryRouter>
  )

const renderEditForm = (slug = 'flax-bread') =>
  render(
    <MemoryRouter initialEntries={[`/recipes/${slug}/edit`]}>
      <Routes>
        <Route path="/recipes/:slug/edit" element={<RecipeFormPage />} />
        <Route path="/recipes/:slug" element={<RecipeStub />} />
      </Routes>
    </MemoryRouter>
  )

const existingRecipe = (overrides = {}) => ({
  slug: 'flax-bread',
  title: 'Flax Bread',
  description: 'A low-carb loaf.',
  prep_minutes: 10,
  cook_minutes: 45,
  total_minutes_override: null,
  servings: 8,
  servings_note: '',
  storage: '',
  nutrition_note: '',
  source_url: '',
  source_name: '',
  is_published: true,
  sections: ['Bread'],
  tags: ['Bread', 'low-carb'],
  ingredients: [
    { name: 'Flax meal', quantity: 200, quantity_max: null, unit: 'g', note: '', optional: false, group: '', ingredient_id: 5 },
  ],
  steps: [{ text: 'Mix everything.' }],
  ...overrides,
})

beforeEach(() => {
  vi.clearAllMocks()
  api.listSections.mockResolvedValue([
    { slug: 'bread', name: 'Bread', description: null },
    { slug: 'mains', name: 'Mains', description: null },
  ])
})

describe('RecipeFormPage — creating', () => {
  it('requires a title before submitting', async () => {
    renderNewForm()
    await waitFor(() => expect(api.listSections).toHaveBeenCalled())

    // The Title input has `required`, so a real click would be blocked by
    // the browser's own constraint validation before React ever sees it —
    // fire the submit event directly to exercise the app's own check.
    fireEvent.submit(document.querySelector('form'))
    await waitFor(() => expect(screen.getByText('A title is required')).toBeDefined())
    expect(api.createRecipe).not.toHaveBeenCalled()
  })

  it('creates a recipe from a minimal form and navigates to it', async () => {
    api.createRecipe.mockResolvedValue({ slug: 'new-recipe' })
    renderNewForm()
    await waitFor(() => expect(api.listSections).toHaveBeenCalled())

    fireEvent.change(inputForLabel('Title'), { target: { value: 'New Recipe' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Create recipe' })[0])

    await waitFor(() => expect(screen.getByText('Landed on /recipes/new-recipe')).toBeDefined())
    expect(api.createRecipe).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'New Recipe', tags: [], ingredients: [], steps: [] })
    )
    expect(api.uploadRecipeImage).not.toHaveBeenCalled()
  })

  it('toggles a section chip and includes it first in tags on submit', async () => {
    api.createRecipe.mockResolvedValue({ slug: 'new-recipe' })
    renderNewForm()
    await waitFor(() => expect(screen.getByText('Bread')).toBeDefined())

    fireEvent.change(inputForLabel('Title'), { target: { value: 'New Recipe' } })
    fireEvent.click(screen.getByRole('button', { name: 'Bread' }))
    expect(screen.getByRole('button', { name: 'Bread' }).getAttribute('aria-pressed')).toBe('true')

    fireEvent.change(inputForLabel('Tags'), { target: { value: 'quick' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Create recipe' })[0])

    await waitFor(() => expect(api.createRecipe).toHaveBeenCalled())
    expect(api.createRecipe.mock.calls[0][0].tags).toEqual(['bread', 'quick'])
  })

  it('adds and removes ingredient rows, only submitting the ones with a name', async () => {
    api.createRecipe.mockResolvedValue({ slug: 'new-recipe' })
    renderNewForm()
    await waitFor(() => expect(api.listSections).toHaveBeenCalled())

    fireEvent.change(inputForLabel('Title'), { target: { value: 'New Recipe' } })
    fireEvent.click(screen.getByRole('button', { name: '+ Add' }))
    expect(screen.getAllByPlaceholderText('Ingredient')).toHaveLength(2)

    fireEvent.change(screen.getAllByPlaceholderText('Ingredient')[0], { target: { value: 'Flour' } })
    fireEvent.click(screen.getAllByLabelText('Remove ingredient')[1])
    expect(screen.getAllByPlaceholderText('Ingredient')).toHaveLength(1)

    fireEvent.click(screen.getAllByRole('button', { name: 'Create recipe' })[0])
    await waitFor(() => expect(api.createRecipe).toHaveBeenCalled())
    expect(api.createRecipe.mock.calls[0][0].ingredients).toEqual([
      expect.objectContaining({ name: 'Flour' }),
    ])
  })

  it('adds and removes method steps', async () => {
    api.createRecipe.mockResolvedValue({ slug: 'new-recipe' })
    renderNewForm()
    await waitFor(() => expect(api.listSections).toHaveBeenCalled())

    fireEvent.change(inputForLabel('Title'), { target: { value: 'New Recipe' } })
    fireEvent.click(screen.getByRole('button', { name: '+ Add step' }))
    const textareas = document.querySelectorAll('ol textarea')
    expect(textareas).toHaveLength(2)

    fireEvent.change(textareas[0], { target: { value: 'Preheat the oven.' } })
    fireEvent.click(screen.getAllByLabelText('Remove step')[1])

    fireEvent.click(screen.getAllByRole('button', { name: 'Create recipe' })[0])
    await waitFor(() => expect(api.createRecipe).toHaveBeenCalled())
    expect(api.createRecipe.mock.calls[0][0].steps).toEqual([{ text: 'Preheat the oven.' }])
  })

  it('uploads the chosen photo after a successful save', async () => {
    api.createRecipe.mockResolvedValue({ slug: 'new-recipe' })
    renderNewForm()
    await waitFor(() => expect(api.listSections).toHaveBeenCalled())

    fireEvent.change(inputForLabel('Title'), { target: { value: 'New Recipe' } })
    const file = new File(['fake'], 'recipe.jpg', { type: 'image/jpeg' })
    fireEvent.change(document.querySelector('input[type="file"]'), { target: { files: [file] } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Create recipe' })[0])

    await waitFor(() => expect(api.uploadRecipeImage).toHaveBeenCalledWith('new-recipe', file))
  })

  it('shows an error and re-enables the form when creation fails', async () => {
    api.createRecipe.mockRejectedValue(new Error('title already exists'))
    renderNewForm()
    await waitFor(() => expect(api.listSections).toHaveBeenCalled())

    fireEvent.change(inputForLabel('Title'), { target: { value: 'New Recipe' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Create recipe' })[0])

    await waitFor(() => expect(screen.getByText('title already exists')).toBeDefined())
    expect(screen.getAllByRole('button', { name: 'Create recipe' })[0].disabled).toBe(false)
  })

  it('pre-fills the form from an AI-import draft and shows the confidence note', async () => {
    renderNewForm({
      title: 'Draft Title',
      section: 'bread',
      tags: ['bread', 'quick'],
      confidence: 0.82,
      uncertain: ['prep time'],
      ingredients: [{ name: 'Flour', quantity: 200, unit: 'g' }],
      steps: [{ text: 'Mix it.' }],
    })
    await waitFor(() => expect(screen.getByDisplayValue('Draft Title')).toBeDefined())

    expect(screen.getByText(/Pre-filled from an AI import/)).toBeDefined()
    expect(screen.getByText(/confidence 82%/)).toBeDefined()
    expect(screen.getByText(/Flagged: prep time\./)).toBeDefined()
    // The draft's section shouldn't also show up in the free-text tags field.
    expect(inputForLabel('Tags').value).toBe('quick')
  })
})

describe('RecipeFormPage — editing', () => {
  it('loads the existing recipe and pre-fills the form', async () => {
    api.getRecipe.mockResolvedValue(existingRecipe())
    renderEditForm()

    expect(screen.getByText('Loading…')).toBeDefined()
    await waitFor(() => expect(screen.getByDisplayValue('Flax Bread')).toBeDefined())
    expect(api.getRecipe).toHaveBeenCalledWith('flax-bread')
    expect(screen.getByRole('heading', { name: 'Edit recipe' })).toBeDefined()
    expect(screen.getByPlaceholderText('Ingredient').value).toBe('Flax meal')
  })

  it('saves changes, marking the recipe as reviewed', async () => {
    api.getRecipe.mockResolvedValue(existingRecipe())
    api.updateRecipe.mockResolvedValue({ slug: 'flax-bread' })
    renderEditForm()
    await waitFor(() => expect(screen.getByDisplayValue('Flax Bread')).toBeDefined())

    fireEvent.click(screen.getAllByRole('button', { name: 'Save changes' })[0])
    await waitFor(() => expect(api.updateRecipe).toHaveBeenCalled())
    expect(api.updateRecipe).toHaveBeenCalledWith('flax-bread', expect.objectContaining({ needs_review: false }))
  })

  it('shows an error when the recipe fails to load', async () => {
    api.getRecipe.mockRejectedValue(new Error('not found'))
    renderEditForm()
    await waitFor(() => expect(screen.getByText('not found')).toBeDefined())
  })
})
