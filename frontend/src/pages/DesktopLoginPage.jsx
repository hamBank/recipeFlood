import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useSession } from '../App'
import { desktopHandoff } from '../api'
import LoginPage from './LoginPage'

// Same rules as the backend (DesktopHandoffRequest), so a bad link fails
// here with a plain message instead of as a 422 after the user has clicked.
const STATE_PATTERN = /^[A-Za-z0-9_-]{32,128}$/
const PORT_PATTERN = /^\d{4,5}$/

function validPort(raw) {
  if (!PORT_PATTERN.test(raw || '')) return null
  const port = Number(raw)
  return port >= 1024 && port <= 65535 ? port : null
}

/**
 * The website half of the desktop app's sign-in. The app opens this page
 * in the user's normal browser (where Google sign-in works), and once
 * they're signed in and confirm, the backend gives back a loopback URL
 * carrying a single-use code for the app to collect. See SPEC.md
 * "Desktop app sign-in".
 */
export default function DesktopLoginPage() {
  const { config, user, setUser } = useSession()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const port = validPort(params.get('port'))
  const state = params.get('state') || ''

  if (port === null || !STATE_PATTERN.test(state)) {
    return (
      <div className="mx-auto max-w-md rounded-xl border border-edge bg-card p-8 text-center shadow-sm">
        <p className="text-sm text-red-600">
          This sign-in link is invalid. Start again from the Recipe Flood desktop app.
        </p>
      </div>
    )
  }

  if (!user) return <LoginPage config={config} onSignedIn={setUser} embedded />

  const onContinue = async () => {
    setBusy(true)
    setError(null)
    try {
      const { redirect_url } = await desktopHandoff({ port, state })
      // The one deliberate full-page navigation in the app: out to the
      // desktop app's loopback listener (always 127.0.0.1), which a
      // router navigation couldn't do.
      window.location.assign(redirect_url)
    } catch (caught) {
      setError(caught.message)
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-md rounded-xl border border-edge bg-card p-8 text-center shadow-sm">
      <h1 className="text-xl font-bold text-ink">
        Recipe<span className="text-accent">Flood</span>
      </h1>
      {busy ? (
        <p className="mt-4 text-sm text-ink-muted">Handing off to the desktop app…</p>
      ) : (
        <>
          <p className="mt-2 text-sm text-ink-muted">
            Sign in to the Recipe Flood desktop app as <strong>{user.email}</strong>?
          </p>
          <div className="mt-6 flex justify-center gap-3">
            <button
              type="button"
              onClick={onContinue}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-[color:var(--accent-ink)]"
            >
              Continue
            </button>
            <button
              type="button"
              onClick={() => navigate('/')}
              className="rounded-lg border border-edge px-4 py-2 text-sm text-ink"
            >
              Cancel
            </button>
          </div>
        </>
      )}
      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
    </div>
  )
}
