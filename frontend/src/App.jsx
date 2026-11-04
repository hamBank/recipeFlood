import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { getAuthConfig, getMe, getToken, setSessionExpiredHandler, setToken } from './api'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import DesktopLoginPage from './pages/DesktopLoginPage'
import RecipeListPage from './pages/RecipeListPage'
import RecipeDetailPage from './pages/RecipeDetailPage'
import RecipeFormPage from './pages/RecipeFormPage'
import ImportPage from './pages/ImportPage'
import PantryPage from './pages/PantryPage'
import CookListsPage from './pages/CookListsPage'
import CookListLatestPage from './pages/CookListLatestPage'
import CookListDetailPage from './pages/CookListDetailPage'
import ShoppingListPage from './pages/ShoppingListPage'
import SettingsPage from './pages/SettingsPage'
import { IS_DESKTOP } from './platform'

const SessionContext = createContext({ config: null, user: null, setUser: () => {} })

export const CONFIG_CACHE_KEY = 'rf_auth_config'
export const USER_CACHE_KEY = 'rf_auth_user'

const EXPIRED_NOTICE = 'Your session has expired. Please sign in again.'

function cacheGet(key) {
  try {
    return JSON.parse(localStorage.getItem(key) || 'null')
  } catch {
    return null
  }
}

function cacheSet(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Storage full/unavailable — the app still works, it just has nothing
    // to fall back on if the very next load happens to be offline.
  }
}

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
  const location = useLocation()
  // `from` brings the user back here once signed in (see the sign-in route).
  if (!user) return <Navigate to="/sign-in" replace state={{ from: location }} />
  return children
}

export default function App() {
  const [config, setConfig] = useState(null)
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  // Set when a signed-in request came back 401, so the sign-in page can say
  // why it's there; cleared by the next sign-in.
  const [expired, setExpired] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  // The handler below is registered once, so it reads these through refs.
  const userRef = useRef(user)
  const locationRef = useRef(location)
  userRef.current = user
  locationRef.current = location

  useEffect(() => {
    // api.js has already dropped the token. Only a session that was live
    // ends here: the startup check below handles a token that was already
    // dead on arrival by quietly browsing as a guest.
    setSessionExpiredHandler(() => {
      if (!userRef.current) return
      cacheSet(USER_CACHE_KEY, null)
      setUser(null)
      setExpired(true)
      navigate('/sign-in', { state: { from: locationRef.current }, replace: true })
    })
    return () => setSessionExpiredHandler(null)
  }, [navigate])

  useEffect(() => {
    ;(async () => {
      let cfg
      try {
        cfg = await getAuthConfig()
        cacheSet(CONFIG_CACHE_KEY, cfg)
      } catch (caught) {
        // No `.status`: the fetch itself failed rather than the server
        // rejecting it — i.e. no network, not "backend unreachable" in
        // the usual sense. Fall back to the last config seen so a cold
        // offline load still reaches the app shell (and anything in it,
        // like the shopping list, that caches its own data) instead of
        // dead-ending here.
        cfg = !caught.status && cacheGet(CONFIG_CACHE_KEY)
        if (!cfg) {
          setError('Backend unreachable')
          setLoading(false)
          return
        }
      }
      setConfig(cfg)
      if (!cfg.auth_enabled || getToken()) {
        try {
          const me = await getMe()
          setUser(me)
          cacheSet(USER_CACHE_KEY, me)
        } catch (caught) {
          if (caught.status) {
            setToken(null) // expired/invalid token — browse as a guest
          } else {
            // Offline: the token might be perfectly valid, there's just
            // no way to ask right now. Trust it and use the last-known
            // user rather than bouncing a signed-in user to the sign-in
            // page just because the network dropped.
            setUser(cacheGet(USER_CACHE_KEY))
          }
        }
      }
      setLoading(false)
    })()
  }, [])

  const signOut = () => {
    setToken(null)
    setUser(null)
  }

  // Stable, since LoginPage re-renders Google's button whenever it changes.
  const signedIn = useCallback((next) => {
    setExpired(false)
    setUser(next)
  }, [])

  // Back to the page the session expired on, once signed in again.
  const from = location.state?.from
  const afterSignIn = from ? `${from.pathname}${from.search || ''}` : '/'
  const notice = expired ? EXPIRED_NOTICE : null

  // Wraps setUser so a preference update (see ShoppingListPage's "Show
  // ticked" toggle) also updates the offline cache, not just React state.
  const updateUser = (next) => {
    setUser(next)
    cacheSet(USER_CACHE_KEY, next)
  }

  // Desktop app only: a mistyped or unreachable server would otherwise
  // strand the user on a screen with no way back to Settings, since the
  // saved server survives restarts.
  const changeServer = IS_DESKTOP ? (
    <div className="mt-6">
      <SettingsPage />
    </div>
  ) : null

  if (loading) return <Centered>Loading…</Centered>
  if (error)
    return (
      <Centered>
        {error}
        {changeServer}
      </Centered>
    )

  // With PUBLIC_READ off the whole site is allowlist-only, so an anonymous
  // visitor gets the sign-in page instead of an empty recipe grid.
  if (!user && config && !config.public_read) {
    if (!IS_DESKTOP) return <LoginPage config={config} onSignedIn={signedIn} notice={notice} />
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-page p-4">
        <LoginPage config={config} onSignedIn={signedIn} notice={notice} embedded />
        {changeServer}
      </div>
    )
  }

  return (
    <SessionContext.Provider value={{ config, user, setUser: updateUser }}>
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
          {/* "cooking" / "groceries", not "cook-lists" / "shopping": those are
              the API's own path prefixes. In production the routers are
              mounted ahead of the SPA catch-all (see main.py), so a same-
              named frontend route would make a direct visit or refresh hit
              the API instead of the app shell. And in dev, Vite's proxy
              matches by string prefix rather than exact path, so even a
              route merely *starting with* an API prefix (e.g.
              "/shopping-list") gets swallowed the same way. */}
          <Route
            path="cooking"
            element={
              <RequireAuth user={user}>
                <CookListLatestPage />
              </RequireAuth>
            }
          />
          <Route
            path="cooking/all"
            element={
              <RequireAuth user={user}>
                <CookListsPage />
              </RequireAuth>
            }
          />
          <Route
            path="cooking/:id"
            element={
              <RequireAuth user={user}>
                <CookListDetailPage />
              </RequireAuth>
            }
          />
          <Route
            path="groceries"
            element={
              <RequireAuth user={user}>
                <ShoppingListPage />
              </RequireAuth>
            }
          />
          <Route
            path="sign-in"
            element={
              user ? (
                <Navigate to={afterSignIn} replace />
              ) : (
                <LoginPage config={config} onSignedIn={signedIn} notice={notice} embedded />
              )
            }
          />
          {/* Not behind RequireAuth: it renders the sign-in itself, so the
              ?port=&state= query survives the sign-in (no redirect to
              /sign-in), including on a private site, where the gate above
              shows the login at this same URL until the user is set. */}
          <Route path="desktop-login" element={<DesktopLoginPage />} />
          {/* Desktop app only: which server to talk to. */}
          {IS_DESKTOP && <Route path="settings" element={<SettingsPage />} />}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </SessionContext.Provider>
  )
}
