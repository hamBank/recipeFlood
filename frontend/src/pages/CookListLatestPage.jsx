import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { listCookLists } from '../api'

/**
 * Landing view for "Cooking": jumps straight to the most recent list
 * (what's cooking *now*) instead of the full history. `CookListsPage`,
 * at /cooking/all, is still there for browsing older lists — reached via
 * the "Cooking lists" link on the detail page.
 */
export default function CookListLatestPage() {
  const [target, setTarget] = useState(undefined) // undefined = loading, null = none found

  useEffect(() => {
    let cancelled = false
    listCookLists({ limit: 1, offset: 0 })
      .then((result) => {
        if (!cancelled) setTarget(result.items[0]?.id ?? null)
      })
      .catch(() => {
        if (!cancelled) setTarget(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (target === undefined) return <p className="text-ink-muted">Loading…</p>
  return <Navigate to={target === null ? '/cooking/all' : `/cooking/${target}`} replace />
}
