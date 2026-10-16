import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// IS_DESKTOP is fixed when the module loads, so each test stubs the env and
// then imports a fresh copy.
async function load(target, defaultUrl) {
  vi.resetModules()
  if (target) vi.stubEnv('VITE_TARGET', target)
  if (defaultUrl) vi.stubEnv('VITE_DEFAULT_SERVER_URL', defaultUrl)
  return import('./platform')
}

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.restoreAllMocks()
})

describe('web build', () => {
  it('uses same-origin paths, ignoring any saved server', async () => {
    localStorage.setItem('rf_server_url', 'https://elsewhere.example')
    const { IS_DESKTOP, getServerUrl, apiUrl, mediaUrl } = await load('web', 'https://x.example')
    expect(IS_DESKTOP).toBe(false)
    expect(getServerUrl()).toBe('')
    expect(apiUrl('/recipes')).toBe('/recipes')
    expect(mediaUrl('recipes/a.jpg')).toBe('/media/recipes/a.jpg')
  })
})

describe('desktop build', () => {
  it('falls back to the default server when nothing is saved', async () => {
    const { IS_DESKTOP, getServerUrl, apiUrl, mediaUrl } = await load(
      'desktop',
      'https://default.example',
    )
    expect(IS_DESKTOP).toBe(true)
    expect(getServerUrl()).toBe('https://default.example')
    expect(apiUrl('/recipes')).toBe('https://default.example/recipes')
    expect(mediaUrl('recipes/a.jpg')).toBe('https://default.example/media/recipes/a.jpg')
  })

  it('prefers a saved server and strips a trailing slash', async () => {
    localStorage.setItem('rf_server_url', 'https://saved.example/')
    const { getServerUrl } = await load('desktop', 'https://default.example')
    expect(getServerUrl()).toBe('https://saved.example')
  })

  it('does not crash when localStorage throws', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    const { getServerUrl } = await load('desktop', 'https://default.example')
    expect(getServerUrl()).toBe('https://default.example')
  })

  it('setServerUrl saves a normalised https or localhost URL', async () => {
    const { setServerUrl, getServerUrl } = await load('desktop', 'https://default.example')
    setServerUrl('  https://x/  ')
    expect(getServerUrl()).toBe('https://x')
    setServerUrl('http://localhost:8000')
    expect(getServerUrl()).toBe('http://localhost:8000')
    setServerUrl('http://127.0.0.1:8000/')
    expect(getServerUrl()).toBe('http://127.0.0.1:8000')
  })

  it.each(['http://example.com', 'ftp://example.com', '', '   ', 'https://'])(
    'setServerUrl rejects %j',
    async (bad) => {
      const { setServerUrl, getServerUrl } = await load('desktop', 'https://default.example')
      expect(() => setServerUrl(bad)).toThrow()
      expect(getServerUrl()).toBe('https://default.example')
    },
  )
})
