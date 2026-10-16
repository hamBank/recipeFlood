import { act, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('./api', () => ({
  getAuthConfig: vi.fn().mockResolvedValue({ auth_enabled: false, public_read: true }),
  getMe: vi.fn().mockResolvedValue({ id: 1, email: 'dev@example.com' }),
  getToken: vi.fn(),
  setToken: vi.fn(),
}))
vi.mock('./pages/RecipeListPage', () => ({ default: () => <div>Recipe list</div> }))
vi.mock('./pages/SettingsPage', () => ({ default: () => <div>Server settings</div> }))
vi.mock('./pages/LoginPage', () => ({ default: () => <div>Sign-in</div> }))

// IS_DESKTOP is fixed when platform.js loads, so each test stubs the env and
// imports a fresh App.
async function renderAt(target, path, { config } = {}) {
  vi.resetModules()
  vi.stubEnv('VITE_TARGET', target)
  if (config) {
    const api = await import('./api')
    config(api)
  }
  const { default: App } = await import('./App')
  await act(async () => {
    render(
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>,
    )
  })
}

afterEach(() => vi.unstubAllEnvs())

describe('the settings route', () => {
  it('exists on desktop', async () => {
    await renderAt('desktop', '/settings')
    await waitFor(() => expect(screen.getByText('Server settings')).toBeDefined())
  })

  it('does not exist on the web: it falls through to the home page', async () => {
    await renderAt('web', '/settings')
    await waitFor(() => expect(screen.getByText('Recipe list')).toBeDefined())
    expect(screen.queryByText('Server settings')).toBeNull()
  })
})

describe('a server the app cannot use', () => {
  const unreachable = (api) => api.getAuthConfig.mockRejectedValueOnce(
    Object.assign(new Error('502 Bad Gateway'), { status: 502 }),
  )
  const privateSite = (api) =>
    api.getAuthConfig.mockResolvedValueOnce({ auth_enabled: true, public_read: false })

  it('offers the server setting on the unreachable screen on desktop', async () => {
    await renderAt('desktop', '/', { config: unreachable })
    await waitFor(() => expect(screen.getByText('Backend unreachable')).toBeDefined())
    expect(screen.getByText('Server settings')).toBeDefined()
  })

  it('offers the server setting beside a private site\'s sign-in on desktop', async () => {
    await renderAt('desktop', '/', { config: privateSite })
    await waitFor(() => expect(screen.getByText('Sign-in')).toBeDefined())
    expect(screen.getByText('Server settings')).toBeDefined()
  })

  it('shows neither extra on the web', async () => {
    await renderAt('web', '/', { config: unreachable })
    await waitFor(() => expect(screen.getByText('Backend unreachable')).toBeDefined())
    expect(screen.queryByText('Server settings')).toBeNull()
  })
})
