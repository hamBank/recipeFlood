import { afterEach, describe, expect, it, vi } from 'vitest'

const installExternalLinkHandler = vi.fn()
const installDropGuard = vi.fn()

vi.mock('./desktop', () => ({ installExternalLinkHandler, installDropGuard }))
vi.mock('./App.jsx', () => ({ default: () => null }))
vi.mock('virtual:pwa-register', () => ({ registerSW: vi.fn() }))

async function boot(target) {
  vi.resetModules()
  vi.clearAllMocks()
  if (target) vi.stubEnv('VITE_TARGET', target)
  document.body.innerHTML = '<div id="root"></div>'
  await import('./main.jsx')
  await new Promise((resolve) => setTimeout(resolve, 0))
}

afterEach(() => vi.unstubAllEnvs())

describe('main', () => {
  it('installs the link handler and the drop guard in the desktop build', async () => {
    await boot('desktop')
    expect(installExternalLinkHandler).toHaveBeenCalled()
    expect(installDropGuard).toHaveBeenCalled()
  })

  it('loads neither in the web build, so browsers keep their own drop behaviour', async () => {
    await boot()
    expect(installExternalLinkHandler).not.toHaveBeenCalled()
    expect(installDropGuard).not.toHaveBeenCalled()
  })
})
