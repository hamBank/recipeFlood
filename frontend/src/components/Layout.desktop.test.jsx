import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

// IS_DESKTOP is fixed when platform.js loads, so each test stubs the env and
// imports a fresh Layout.
async function renderLayout(target) {
  vi.resetModules()
  vi.stubEnv('VITE_TARGET', target)
  const { default: Layout } = await import('./Layout')
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route element={<Layout user={null} />}>
          <Route index element={<div>Recipe list</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllEnvs())

describe('Layout settings link', () => {
  it('is in the nav on desktop, even for a guest', async () => {
    await renderLayout('desktop')
    expect(screen.getByRole('link', { name: 'Settings' }).getAttribute('href')).toBe('/settings')
  })

  it('is absent on the web', async () => {
    await renderLayout('web')
    expect(screen.queryByRole('link', { name: 'Settings' })).toBeNull()
  })
})
