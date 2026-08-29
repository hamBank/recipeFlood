import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api'
import LoginPage from './LoginPage'

vi.mock('../api', () => ({
  loginWithGoogle: vi.fn(),
  setToken: vi.fn(),
}))

const config = { auth_enabled: true, google_client_id: 'client-123' }

afterEach(() => {
  delete window.google
  document.querySelectorAll('script[src*="gsi/client"]').forEach((el) => el.remove())
  vi.clearAllMocks()
})

describe('LoginPage', () => {
  it('shows the local-dev notice when auth is disabled', () => {
    render(<LoginPage config={{ auth_enabled: false }} onSignedIn={vi.fn()} />)
    expect(screen.getByText(/already signed in as the local dev admin/)).toBeDefined()
  })

  it('does not touch window.google when there is no client id', () => {
    render(<LoginPage config={{ auth_enabled: true, google_client_id: null }} onSignedIn={vi.fn()} />)
    expect(document.querySelector('script[src*="gsi/client"]')).toBeNull()
  })

  it('loads the Google script and initializes the button once available', async () => {
    render(<LoginPage config={config} onSignedIn={vi.fn()} />)
    const script = document.querySelector('script[src*="gsi/client"]')
    expect(script).not.toBeNull()

    const initialize = vi.fn()
    const renderButton = vi.fn()
    window.google = { accounts: { id: { initialize, renderButton } } }
    script.onload()

    expect(initialize).toHaveBeenCalledWith(expect.objectContaining({ client_id: 'client-123' }))
    expect(renderButton).toHaveBeenCalled()
  })

  it('reuses window.google immediately when it is already loaded', () => {
    const initialize = vi.fn()
    const renderButton = vi.fn()
    window.google = { accounts: { id: { initialize, renderButton } } }

    render(<LoginPage config={config} onSignedIn={vi.fn()} />)
    expect(initialize).toHaveBeenCalled()
    expect(renderButton).toHaveBeenCalled()
  })

  it('signs the user in when Google calls back with a credential', async () => {
    const onSignedIn = vi.fn()
    api.loginWithGoogle.mockResolvedValue({ token: 't0k3n', user: { id: 1, name: 'Foobie' } })

    let callback
    window.google = {
      accounts: {
        id: {
          initialize: ({ callback: cb }) => {
            callback = cb
          },
          renderButton: vi.fn(),
        },
      },
    }

    render(<LoginPage config={config} onSignedIn={onSignedIn} />)
    await act(() => callback({ credential: 'a-google-credential' }))

    expect(api.loginWithGoogle).toHaveBeenCalledWith('a-google-credential')
    expect(api.setToken).toHaveBeenCalledWith('t0k3n')
    expect(onSignedIn).toHaveBeenCalledWith({ id: 1, name: 'Foobie' })
  })

  it('shows an error message when sign-in fails', async () => {
    api.loginWithGoogle.mockRejectedValue(new Error('bad credential'))

    let callback
    window.google = {
      accounts: {
        id: {
          initialize: ({ callback: cb }) => {
            callback = cb
          },
          renderButton: vi.fn(),
        },
      },
    }

    render(<LoginPage config={config} onSignedIn={vi.fn()} />)
    await act(() => callback({ credential: 'a-google-credential' }))

    await waitFor(() => expect(screen.getByText('bad credential')).toBeDefined())
  })

  it('shows an error when the Google script itself fails to load', () => {
    render(<LoginPage config={config} onSignedIn={vi.fn()} />)
    const script = document.querySelector('script[src*="gsi/client"]')
    act(() => script.onerror())
    expect(screen.getByText('Could not load Google sign-in')).toBeDefined()
  })
})
