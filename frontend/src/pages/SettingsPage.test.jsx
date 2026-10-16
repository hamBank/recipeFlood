import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const setToken = vi.fn()

vi.mock('../api', () => ({ setToken }))
vi.mock('../App', () => ({ CONFIG_CACHE_KEY: 'rf_auth_config', USER_CACHE_KEY: 'rf_auth_user' }))

const realLocation = window.location
const reload = vi.fn()

async function renderSettings() {
  vi.resetModules()
  vi.stubEnv('VITE_TARGET', 'desktop')
  vi.stubEnv('VITE_DEFAULT_SERVER_URL', 'https://rf.example')
  const { default: SettingsPage } = await import('./SettingsPage')
  render(<SettingsPage />)
}

const save = (value) => {
  fireEvent.change(screen.getByLabelText('Server'), { target: { value } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { ...realLocation, reload },
  })
})

afterEach(() => {
  vi.unstubAllEnvs()
  Object.defineProperty(window, 'location', { configurable: true, value: realLocation })
})

describe('SettingsPage', () => {
  it('starts with the current server', async () => {
    await renderSettings()
    expect(screen.getByLabelText('Server').value).toBe('https://rf.example')
  })

  it('rejects an insecure or malformed address and changes nothing', async () => {
    await renderSettings()
    save('http://example.com')
    expect(screen.getByText(/must start with https:\/\//)).toBeDefined()
    expect(localStorage.getItem('rf_server_url')).toBeNull()
    expect(setToken).not.toHaveBeenCalled()
    expect(reload).not.toHaveBeenCalled()
  })

  it('is blocked while shopping changes are waiting to sync', async () => {
    localStorage.setItem(
      'rf_shopping_queue',
      JSON.stringify([{ type: 'check', itemId: 1 }, { type: 'add', tempId: -1, name: 'milk' }]),
    )
    await renderSettings()
    save('https://other.example')
    expect(screen.getByText(/You have 2 unsynced shopping changes\. Go back online/)).toBeDefined()
    expect(localStorage.getItem('rf_server_url')).toBeNull()
    expect(setToken).not.toHaveBeenCalled()
    expect(reload).not.toHaveBeenCalled()
  })

  it('saves the server, clears the token and caches, and reloads', async () => {
    localStorage.setItem('rf_auth_config', '{"auth_enabled":true}')
    localStorage.setItem('rf_auth_user', '{"id":1}')
    localStorage.setItem('rf_shopping_cache', '{"items":[]}')
    await renderSettings()

    save('https://other.example/')

    expect(localStorage.getItem('rf_server_url')).toBe('https://other.example')
    expect(setToken).toHaveBeenCalledWith(null)
    expect(localStorage.getItem('rf_auth_config')).toBeNull()
    expect(localStorage.getItem('rf_auth_user')).toBeNull()
    expect(localStorage.getItem('rf_shopping_cache')).toBeNull()
    expect(reload).toHaveBeenCalledTimes(1)
  })
})
