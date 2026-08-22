import { useEffect, useRef, useState } from 'react'
import { loginWithGoogle, setToken } from '../api'

/**
 * Google Identity Services sign-in.
 *
 * The GIS script is loaded on demand rather than in index.html: most
 * visitors never sign in (the site is publicly readable), so there is no
 * reason to make every one of them fetch Google's script.
 */
export default function LoginPage({ config, onSignedIn, embedded = false }) {
  const buttonRef = useRef(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!config?.auth_enabled || !config?.google_client_id) return
    let cancelled = false

    const render = () => {
      if (cancelled || !window.google || !buttonRef.current) return
      window.google.accounts.id.initialize({
        client_id: config.google_client_id,
        callback: async ({ credential }) => {
          setBusy(true)
          setError(null)
          try {
            const result = await loginWithGoogle(credential)
            setToken(result.token)
            onSignedIn(result.user)
          } catch (caught) {
            setError(caught.message)
          }
          setBusy(false)
        },
      })
      window.google.accounts.id.renderButton(buttonRef.current, {
        theme: 'outline',
        size: 'large',
        text: 'signin_with',
      })
    }

    if (window.google) {
      render()
    } else {
      const script = document.createElement('script')
      script.src = 'https://accounts.google.com/gsi/client'
      script.async = true
      script.onload = render
      script.onerror = () => setError('Could not load Google sign-in')
      document.head.appendChild(script)
    }
    return () => {
      cancelled = true
    }
  }, [config, onSignedIn])

  const body = (
    <div className="mx-auto max-w-md rounded-xl border border-edge bg-card p-8 text-center shadow-sm">
      <h1 className="text-xl font-bold text-ink">
        Recipe<span className="text-accent">Flood</span>
      </h1>
      <p className="mt-2 text-sm text-ink-muted">
        Sign in to add recipes, record what you cooked, and see ingredient costs.
      </p>

      {config?.auth_enabled === false && (
        <p className="mt-6 rounded-lg bg-soft p-3 text-sm text-ink-muted">
          Auth is disabled in this environment — reload and you are already signed
          in as the local dev admin.
        </p>
      )}

      <div ref={buttonRef} className="mt-6 flex justify-center" />
      {busy && <p className="mt-4 text-sm text-ink-muted">Signing in…</p>}
      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
    </div>
  )

  if (embedded) return body
  return <div className="flex min-h-screen items-center justify-center bg-page p-4">{body}</div>
}
