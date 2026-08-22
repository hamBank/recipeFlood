import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import RecipeCard from './RecipeCard'

const base = {
  id: 1,
  slug: 'flax-bread',
  title: 'Flax Bread',
  description: 'A low-carb loaf.',
  image_path: null,
  category_name: 'Bread',
  added_date: '2014-01-11T00:00:00Z',
  total_minutes: 45,
  servings: 8,
  tags: ['low-carb'],
  last_prepared_on: null,
  prepared_count: 0,
  needs_review: false,
  is_published: true,
}

const renderCard = (overrides = {}) =>
  render(
    <MemoryRouter>
      <RecipeCard recipe={{ ...base, ...overrides }} />
    </MemoryRouter>,
  )

describe('RecipeCard', () => {
  it('shows the title, category and time', () => {
    renderCard()
    expect(screen.getByText('Flax Bread')).toBeDefined()
    expect(screen.getByText('Bread')).toBeDefined()
    expect(screen.getByText('45 min')).toBeDefined()
  })

  it('links to the recipe by slug', () => {
    renderCard()
    expect(screen.getByRole('link').getAttribute('href')).toBe('/recipes/flax-bread')
  })

  it('falls back to a lettered placeholder when there is no photo', () => {
    // 99% of the scraped collection has no usable image, so this is the
    // normal case rather than the edge case.
    const { container } = renderCard()
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByText('F')).toBeDefined()
  })

  it('uses the self-hosted media path when there is a photo', () => {
    // alt="" makes the image presentational, so query the DOM directly.
    const { container } = renderCard({ image_path: 'recipes/flax-bread.jpg' })
    expect(container.querySelector('img').getAttribute('src')).toBe(
      '/media/recipes/flax-bread.jpg',
    )
  })

  it('flags recipes that still need a human to check them', () => {
    renderCard({ needs_review: true })
    expect(screen.getByText('review')).toBeDefined()
  })

  it('says when it was last cooked', () => {
    const yesterday = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10)
    renderCard({ last_prepared_on: yesterday })
    expect(screen.getByText('made yesterday')).toBeDefined()
  })
})
