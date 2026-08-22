import { createContext, useContext, useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { getAuthConfig, getMe, getToken, setToken } from './api'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import RecipeListPage from './pages/RecipeListPage'
import RecipeDetailPage from './pages/RecipeDetailPage'
import RecipeFormPage from './pages/RecipeFormPage'
import ImportPage from './pages/ImportPage'
import PantryPage from './pages/PantryPage'

const SessionContext = createContext({ config: null, user: null })

/** Config + signed-in user, read by any component that needs to know
 *  whether to show cost figures or edit controls. */
export function useSession() {
  return useContext(SessionContext)
}

function Centered({ children }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-page">
      <div className="rounded-xl bg-card p-8 text-ink-muted shadow">{children}</div>
    </div>
  )
}

/** Wraps routes that require a signed-in user. */
function RequireAuth({ user, children }) {
  if (!user) return <Navigate to="/sign-in" replace />
  return children
}

export default function App() {
  const [config, setConfig] = useState(null)
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    ;(async () => {
      try {
        const cfg = await getAuthConfig()
        setConfig(cfg)
        if (!cfg.auth_enabled || getToken()) {
          try {
            setUser(await getMe())
          } catch {
            setToken(null) // expired/invalid token — browse as a guest
          }
        }
      } catch {
        setError('Backend unreachable')
      }
      setLoading(false)
    })()
  }, [])

  const signOut = () => {
    setToken(null)
    setUser(null)
  }

  if (loading) return <Centered>Loading…</Centered>
  if (error) return <Centered>{error}</Centered>

  // With PUBLIC_READ off the whole site is allowlist-only, so an anonymous
  // visitor gets the sign-in page instead of an empty recipe grid.
  if (!user && config && !config.public_read) {
    return <LoginPage config={config} onSignedIn={setUser} />
  }

  return (
    <SessionContext.Provider value={{ config, user }}>
      <Routes>
        <Route element={<Layout user={user} onSignOut={signOut} />}>
          <Route index element={<RecipeListPage />} />
          <Route path="recipes/:slug" element={<RecipeDetailPage />} />
          <Route
            path="recipes/:slug/edit"
            element={
              <RequireAuth user={user}>
                <RecipeFormPage />
              </RequireAuth>
            }
          />
          <Route
            path="new"
            element={
              <RequireAuth user={user}>
                <RecipeFormPage />
              </RequireAuth>
            }
          />
          <Route
            path="import"
            element={
              <RequireAuth user={user}>
                <ImportPage />
              </RequireAuth>
            }
          />
          <Route
            path="pantry"
            element={
              <RequireAuth user={user}>
                <PantryPage />
              </RequireAuth>
            }
          />
          <Route
            path="sign-in"
            element={
              user ? <Navigate to="/" replace /> : <LoginPage config={config} onSignedIn={setUser} embedded />
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </SessionContext.Provider>
  )
}
