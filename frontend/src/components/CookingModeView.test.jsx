import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import CookingModeView from './CookingModeView'

const recipe = {
  title: 'French Toast',
  servings: 2,
  servings_note: null,
  total_minutes: 10,
  ingredients: [
    { id: 1, name: 'bread', quantity: 6, quantity_max: null, unit: 'slice', note: null, optional: false, group: null },
    { id: 2, name: 'vanilla extract', quantity: 1, quantity_max: null, unit: 'tsp', note: null, optional: true, group: null },
  ],
  steps: [
    { id: 1, position: 0, text: 'Whisk milk and eggs.' },
    { id: 2, position: 1, text: 'Dunk bread and fry.' },
  ],
}

describe('CookingModeView', () => {
  it('shows the title, serves and total time', () => {
    render(<CookingModeView recipe={recipe} onExit={() => {}} />)
    expect(screen.getByText('French Toast')).toBeDefined()
    expect(screen.getByText('Serves 2')).toBeDefined()
    expect(screen.getByText('10 min')).toBeDefined()
  })

  it('lists every ingredient and every step', () => {
    render(<CookingModeView recipe={recipe} onExit={() => {}} />)
    expect(screen.getByText('vanilla extract')).toBeDefined()
    expect(screen.getByText('Whisk milk and eggs.')).toBeDefined()
    expect(screen.getByText('Dunk bread and fry.')).toBeDefined()
  })

  it('marks an optional ingredient', () => {
    render(<CookingModeView recipe={recipe} onExit={() => {}} />)
    expect(screen.getByText('(optional)')).toBeDefined()
  })

  it('never renders a photo, even when the recipe has one', () => {
    const { container } = render(
      <CookingModeView recipe={{ ...recipe, image_path: 'recipes/toast.jpg' }} onExit={() => {}} />,
    )
    expect(container.querySelector('img')).toBeNull()
  })

  it('ticking an ingredient checks it without affecting the others', () => {
    render(<CookingModeView recipe={recipe} onExit={() => {}} />)
    const boxes = screen.getAllByRole('checkbox')
    expect(boxes.every((box) => !box.checked)).toBe(true)
    fireEvent.click(boxes[0])
    expect(boxes[0].checked).toBe(true)
    expect(boxes[1].checked).toBe(false)
  })

  it('calls onExit when Exit is clicked', () => {
    const onExit = vi.fn()
    render(<CookingModeView recipe={recipe} onExit={onExit} />)
    fireEvent.click(screen.getByText('Exit'))
    expect(onExit).toHaveBeenCalledOnce()
  })

  it('shows notes at the bottom when the recipe has any', () => {
    render(
      <CookingModeView
        recipe={{ ...recipe, nutrition_note: 'Halved the sugar, still plenty sweet.' }}
        onExit={() => {}}
      />,
    )
    expect(screen.getByText('Notes')).toBeDefined()
    expect(screen.getByText('Halved the sugar, still plenty sweet.')).toBeDefined()
  })

  it('omits the notes section when the recipe has none', () => {
    render(<CookingModeView recipe={recipe} onExit={() => {}} />)
    expect(screen.queryByText('Notes')).toBeNull()
  })
})
