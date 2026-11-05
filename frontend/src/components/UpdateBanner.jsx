import { useEffect, useState } from 'react'
import { getHealth } from '../api'

/** The frontend commit this bundle was built from (see vite.config.js). */
const BUILT_FROM = import.meta.env.VITE_FRONTEND_SHA || ''

//: How often an open tab asks the server which frontend it is serving. Also
//: asked whenever the tab comes back into view, at most this often.
const CHECK_EVERY_MS = 10 * 60 * 1000

/**
 * "A newer version is available" for a tab left open across a deploy (fleet
 * spec BLD-5). Compares the bundle's own frontend_sha with /health's: that
 * only changes when the frontend did, so a backend-only deploy never asks
 * anyone to reload. Web only — the desktop app's bundle ships with the
 * installer, not the server. Any failure to ask (offline, server down) shows
 * nothing.
 */
export default function UpdateBanner({ builtFrom = BUILT_FROM, check = getHealth }) {
  const [stale, setStale] = useState(false)

  useEffect(() => {
    if (!builtFrom) return undefined
    let cancelled = false
    let lastAsked = 0
    const ask = async () => {
      if (Date.now() - lastAsked < CHECK_EVERY_MS) return
      lastAsked = Date.now()
      try {
        const health = await check()
        if (!cancelled && health?.frontend_sha && health.frontend_sha !== builtFrom) setStale(true)
      } catch {
        // Can't tell right now; ask again later.
      }
    }
    const onVisible = () => {
      if (document.visibilityState === 'visible') ask()
    }
    ask()
    const timer = setInterval(ask, CHECK_EVERY_MS)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      cancelled = true
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [builtFrom, check])

  if (!stale) return null
  return (
    <div role="status" className="bg-accent px-4 py-2 text-center text-sm text-[color:var(--accent-ink)] print:hidden">
      A newer version of Recipe Flood is available.{' '}
      <button type="button" onClick={() => window.location.reload()} className="font-semibold underline">
        Reload
      </button>
    </div>
  )
}
