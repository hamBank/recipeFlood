import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const invoke = vi.fn()
const openUrl = vi.fn()
const desktopExchange = vi.fn()
const setToken = vi.fn()

vi.mock('@tauri-apps/api/core', () => ({ invoke }))
vi.mock('@tauri-apps/plugin-opener', () => ({ openUrl }))
vi.mock('./api', () => ({ desktopExchange, setToken }))

async function load() {
  vi.resetModules()
  vi.stubEnv('VITE_TARGET', 'desktop')
  vi.stubEnv('VITE_DEFAULT_SERVER_URL', 'https://rf.example')
  return import('./desktop')
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

afterEach(() => {
  vi.unstubAllEnvs()
  document.body.innerHTML = ''
})

describe('browserSignIn', () => {
  it('runs the loopback login against the server, exchanges the code and stores the token', async () => {
    invoke.mockResolvedValue({ code: 'c0de', state: 's7ate' })
    desktopExchange.mockResolvedValue({ token: 't0k3n', user: { id: 1 } })
    const { browserSignIn } = await load()

    const user = await browserSignIn()

    expect(invoke).toHaveBeenCalledWith('start_login', { serverUrl: 'https://rf.example' })
    expect(desktopExchange).toHaveBeenCalledWith({ code: 'c0de', state: 's7ate' })
    expect(setToken).toHaveBeenCalledWith('t0k3n')
    expect(user).toEqual({ id: 1 })
  })

  it('stores no token when the login is cancelled or times out', async () => {
    invoke.mockRejectedValue('Timed out waiting for sign-in')
    const { browserSignIn } = await load()
    await expect(browserSignIn()).rejects.toBe('Timed out waiting for sign-in')
    expect(desktopExchange).not.toHaveBeenCalled()
    expect(setToken).not.toHaveBeenCalled()
  })
})

describe('installExternalLinkHandler', () => {
  async function clickLink(href) {
    const { installExternalLinkHandler } = await load()
    installExternalLinkHandler()
    const link = document.createElement('a')
    link.setAttribute('href', href)
    document.body.appendChild(link)
    const event = new MouseEvent('click', { bubbles: true, cancelable: true })
    link.dispatchEvent(event)
    return event
  }

  it('opens a cross-origin link in the system browser instead of the webview', async () => {
    const event = await clickLink('https://www.taste.com.au/recipes/x')
    expect(event.defaultPrevented).toBe(true)
    expect(openUrl).toHaveBeenCalledWith('https://www.taste.com.au/recipes/x')
  })

  it('leaves relative, hash and same-origin links alone', async () => {
    for (const href of ['/recipes/x', '#/pantry', `${window.location.origin}/x`]) {
      const event = await clickLink(href)
      expect(event.defaultPrevented).toBe(false)
    }
    expect(openUrl).not.toHaveBeenCalled()
  })

  it('ignores non-http links such as mailto:', async () => {
    const event = await clickLink('mailto:cook@example.com')
    expect(event.defaultPrevented).toBe(false)
    expect(openUrl).not.toHaveBeenCalled()
  })

  it('ignores clicks that are not on a link', async () => {
    const { installExternalLinkHandler } = await load()
    installExternalLinkHandler()
    const button = document.createElement('button')
    document.body.appendChild(button)
    const event = new MouseEvent('click', { bubbles: true, cancelable: true })
    button.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(false)
  })
})
