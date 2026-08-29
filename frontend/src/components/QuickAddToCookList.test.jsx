import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api'
import QuickAddToCookList, { describeCookList } from './QuickAddToCookList'

vi.mock('../api', () => ({
  addRecipeToCookList: vi.fn(),
  removeRecipeFromCookList: vi.fn(),
}))

const cookList = (overrides = {}) => ({
  id: 1,
  description: null,
  cook_date: '2026-01-05T00:00:00Z',
  recipes: [],
  ...overrides,
})

beforeEach(() => {
  vi.clearAllMocks()
})

describe('describeCookList', () => {
  it('prefers the description when one is set', () => {
    expect(describeCookList(cookList({ description: 'Meal prep week' }))).toBe('Meal prep week')
  })

  it('falls back to the formatted cook date', () => {
    expect(describeCookList(cookList())).not.toBe(null)
    expect(describeCookList(cookList())).not.toBe('')
  })
})

describe('QuickAddToCookList (full)', () => {
  it('offers to add when the recipe is not on the list', () => {
    render(<QuickAddToCookList recipeId={5} cookList={cookList()} onChange={vi.fn()} />)
    expect(screen.getByRole('button', { name: /Add to/ })).toBeDefined()
  })

  it('offers to remove when the recipe is already on the list', () => {
    render(
      <QuickAddToCookList
        recipeId={5}
        cookList={cookList({ recipes: [{ recipe_id: 5 }] })}
        onChange={vi.fn()}
      />
    )
    expect(screen.getByRole('button', { name: /Remove from/ })).toBeDefined()
  })

  it('adds the recipe and reports the updated list', async () => {
    const updated = cookList({ recipes: [{ recipe_id: 5 }] })
    api.addRecipeToCookList.mockResolvedValue(updated)
    const onChange = vi.fn()

    render(<QuickAddToCookList recipeId={5} cookList={cookList()} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: /Add to/ }))

    await waitFor(() => expect(onChange).toHaveBeenCalledWith(updated))
    expect(api.addRecipeToCookList).toHaveBeenCalledWith(1, { recipe_id: 5 })
  })

  it('removes the recipe when already on the list', async () => {
    const updated = cookList()
    api.removeRecipeFromCookList.mockResolvedValue(updated)
    const onChange = vi.fn()

    render(
      <QuickAddToCookList
        recipeId={5}
        cookList={cookList({ recipes: [{ recipe_id: 5 }] })}
        onChange={onChange}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: /Remove from/ }))

    await waitFor(() => expect(onChange).toHaveBeenCalledWith(updated))
    expect(api.removeRecipeFromCookList).toHaveBeenCalledWith(1, 5)
  })

  it('shows an error message when the request fails', async () => {
    api.addRecipeToCookList.mockRejectedValue(new Error('network down'))
    render(<QuickAddToCookList recipeId={5} cookList={cookList()} onChange={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: /Add to/ }))
    await waitFor(() => expect(screen.getByText('network down')).toBeDefined())
  })
})

describe('QuickAddToCookList (compact)', () => {
  it('shows a compact toggle reflecting whether the recipe is on the list', () => {
    const { rerender } = render(
      <QuickAddToCookList recipeId={5} cookList={cookList()} onChange={vi.fn()} compact />
    )
    expect(screen.getByRole('button', { name: '+ Cook list' })).toBeDefined()

    rerender(
      <QuickAddToCookList
        recipeId={5}
        cookList={cookList({ recipes: [{ recipe_id: 5 }] })}
        onChange={vi.fn()}
        compact
      />
    )
    expect(screen.getByRole('button', { name: '✓ Added' })).toBeDefined()
  })

  it('does not navigate the surrounding link when clicked', async () => {
    api.addRecipeToCookList.mockResolvedValue(cookList({ recipes: [{ recipe_id: 5 }] }))
    render(<QuickAddToCookList recipeId={5} cookList={cookList()} onChange={vi.fn()} compact />)
    const button = screen.getByRole('button')
    const event = new MouseEvent('click', { bubbles: true, cancelable: true })
    const preventDefault = vi.spyOn(event, 'preventDefault')
    fireEvent(button, event)
    expect(preventDefault).toHaveBeenCalled()
    await waitFor(() => expect(api.addRecipeToCookList).toHaveBeenCalled())
  })
})
