import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const browserSignIn = vi.fn()

vi.mock('../api', () => ({ loginWithGoogle: vi.fn(), setToken: vi.fn() }))
vi.mock('../desktop', () => ({ browserSignIn }))

// IS_DESKTOP is fixed when platform.js loads, so stub the env first and
// import a fresh LoginPage.
async function renderDesktopLogin(onSignedIn = vi.fn()) {
  vi.resetModules()
  vi.stubEnv('VITE_TARGET', 'desktop')
  const { default: LoginPage } = await import('./LoginPage')
  render(<LoginPage config={{ auth_enabled: true, google_client_id: 'client-123' }} onSignedIn={onSignedIn} />)
  return onSignedIn
}

beforeEach(() => vi.clearAllMocks())

afterEach(() => {
  vi.unstubAllEnvs()
  document.querySelectorAll('script[src*="gsi/client"]').forEach((el) => el.remove())
})

describe('LoginPage on desktop', () => {
  it('offers browser sign-in and never loads Google Identity Services', async () => {
    await renderDesktopLogin()
    expect(screen.getByRole('button', { name: 'Sign in with your browser' })).toBeDefined()
    expect(screen.getByText(/Your browser will open Recipe Flood/)).toBeDefined()
    expect(document.querySelector('script[src*="gsi/client"]')).toBeNull()
  })

  it('shows waiting text, then hands the user to onSignedIn', async () => {
    let finish
    browserSignIn.mockReturnValue(new Promise((resolve) => (finish = resolve)))
    const onSignedIn = await renderDesktopLogin()

    fireEvent.click(screen.getByRole('button', { name: 'Sign in with your browser' }))
    await waitFor(() =>
      expect(screen.getByText(/Waiting for you to finish signing in in your browser/)).toBeDefined(),
    )

    await act(async () => finish({ id: 1, email: 'cook@example.com' }))
    expect(onSignedIn).toHaveBeenCalledWith({ id: 1, email: 'cook@example.com' })
  })

  it('shows the error and lets the user try again', async () => {
    browserSignIn.mockRejectedValue('Timed out waiting for sign-in')
    const onSignedIn = await renderDesktopLogin()

    fireEvent.click(screen.getByRole('button', { name: 'Sign in with your browser' }))

    await waitFor(() => expect(screen.getByText('Timed out waiting for sign-in')).toBeDefined())
    expect(onSignedIn).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Sign in with your browser' }).disabled).toBe(false)
  })
})
