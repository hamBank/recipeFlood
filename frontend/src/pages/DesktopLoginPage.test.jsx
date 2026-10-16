import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api'
import { useSession } from '../App'
import DesktopLoginPage from './DesktopLoginPage'

vi.mock('../api', () => ({
  desktopHandoff: vi.fn(),
  loginWithGoogle: vi.fn(),
  setToken: vi.fn(),
}))

vi.mock('../App', () => ({ useSession: vi.fn() }))

const STATE = 'a'.repeat(43)
const config = { auth_enabled: true, google_client_id: 'client-123' }
const user = { id: 1, email: 'cook@example.com' }

const renderPage = (search = `?port=53123&state=${STATE}`) =>
  render(
    <MemoryRouter initialEntries={[`/desktop-login${search}`]}>
      <Routes>
        <Route path="/desktop-login" element={<DesktopLoginPage />} />
        <Route path="/" element={<div>Home page</div>} />
      </Routes>
    </MemoryRouter>
  )

const realLocation = window.location

beforeEach(() => {
  vi.clearAllMocks()
  useSession.mockReturnValue({ config, user, setUser: vi.fn() })
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { ...realLocation, assign: vi.fn() },
  })
})

afterEach(() => {
  Object.defineProperty(window, 'location', { configurable: true, value: realLocation })
  delete window.google
  document.querySelectorAll('script[src*="gsi/client"]').forEach((el) => el.remove())
})

describe('DesktopLoginPage', () => {
  it.each([
    ['no params', ''],
    ['no state', '?port=53123'],
    ['no port', `?state=${STATE}`],
    ['a privileged port', `?port=80&state=${STATE}`],
    ['an out-of-range port', `?port=70000&state=${STATE}`],
    ['a non-numeric port', `?port=abc&state=${STATE}`],
    ['a short state', '?port=53123&state=abc'],
    ['an illegal state', `?port=53123&state=${'a'.repeat(40)}!!!`],
  ])('shows an error for %s', (_name, search) => {
    renderPage(search)
    expect(screen.getByText(/sign-in link is invalid/)).toBeDefined()
    expect(screen.queryByText('Continue')).toBeNull()
  })

  it('renders the login when signed out', () => {
    useSession.mockReturnValue({ config, user: null, setUser: vi.fn() })
    renderPage()
    expect(document.querySelector('script[src*="gsi/client"]')).not.toBeNull()
    expect(screen.queryByText('Continue')).toBeNull()
  })

  it('asks the signed-in user to confirm, naming the account', () => {
    renderPage()
    expect(screen.getByText('cook@example.com')).toBeDefined()
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDefined()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDefined()
    expect(api.desktopHandoff).not.toHaveBeenCalled()
  })

  it('hands off and navigates to the returned loopback URL on Continue', async () => {
    const url = `http://127.0.0.1:53123/callback?code=abc&state=${STATE}`
    api.desktopHandoff.mockResolvedValue({ redirect_url: url })
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))

    await waitFor(() => expect(window.location.assign).toHaveBeenCalledWith(url))
    expect(api.desktopHandoff).toHaveBeenCalledWith({ port: 53123, state: STATE })
    expect(screen.getByText(/Handing off to the desktop app/)).toBeDefined()
  })

  it('shows the error and lets the user retry when the handoff fails', async () => {
    api.desktopHandoff.mockRejectedValue(new Error('Not authenticated'))
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))

    await waitFor(() => expect(screen.getByText('Not authenticated')).toBeDefined())
    expect(window.location.assign).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDefined()
  })

  it('goes home on Cancel without handing off', () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.getByText('Home page')).toBeDefined()
    expect(api.desktopHandoff).not.toHaveBeenCalled()
    expect(window.location.assign).not.toHaveBeenCalled()
  })
})
