import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import Layout from './Layout'

const renderLayout = (props = {}) =>
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route element={<Layout {...props} />}>
          <Route index element={<div>Recipe list</div>} />
        </Route>
      </Routes>
    </MemoryRouter>
  )

describe('Layout', () => {
  it('shows only the Recipes tab and a Sign in link for a guest', () => {
    renderLayout({ user: null })
    expect(screen.getByRole('link', { name: 'Recipes' })).toBeDefined()
    expect(screen.queryByRole('link', { name: 'Add' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Import' })).toBeNull()
    expect(screen.getByRole('link', { name: 'Sign in' })).toBeDefined()
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull()
  })

  it('renders the routed page content', () => {
    renderLayout({ user: null })
    expect(screen.getByText('Recipe list')).toBeDefined()
  })

  it('shows the full nav and the signed-in user for a member', () => {
    renderLayout({ user: { name: 'Foobie', email: 'foobie@example.com' } })
    ;['Recipes', 'Add', 'Import', 'Pantry', 'Cooking', 'Shopping'].forEach((label) => {
      expect(screen.getByRole('link', { name: label })).toBeDefined()
    })
    expect(screen.getByText('Foobie')).toBeDefined()
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeDefined()
  })

  it('falls back to the email when the user has no name', () => {
    renderLayout({ user: { name: null, email: 'foobie@example.com' } })
    expect(screen.getByText('foobie@example.com')).toBeDefined()
  })

  it('calls onSignOut when the button is clicked', () => {
    const onSignOut = vi.fn()
    renderLayout({ user: { name: 'Foobie', email: 'foobie@example.com' }, onSignOut })
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(onSignOut).toHaveBeenCalledTimes(1)
  })
})
