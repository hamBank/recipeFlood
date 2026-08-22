import { NavLink, Outlet, Link } from 'react-router-dom'
import ThemePicker from './ThemePicker'

function Tab({ to, children, end = false }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `rounded-lg px-3 py-1.5 text-sm font-medium transition ${
          isActive
            ? 'bg-accent text-[color:var(--accent-ink)]'
            : 'text-ink-muted hover:bg-soft'
        }`
      }
    >
      {children}
    </NavLink>
  )
}

export default function Layout({ user, onSignOut }) {
  return (
    <div className="min-h-screen bg-page">
      <header className="border-b border-edge bg-card">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-6">
          <Link to="/" className="text-lg font-bold tracking-tight text-ink">
            Recipe<span className="text-accent">Flood</span>
          </Link>

          <nav className="flex flex-wrap items-center gap-1">
            <Tab to="/" end>
              Recipes
            </Tab>
            {user && <Tab to="/new">Add</Tab>}
            {user && <Tab to="/import">Import</Tab>}
            {user && <Tab to="/pantry">Pantry</Tab>}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <ThemePicker />
            {user ? (
              <>
                {user.avatar_url && (
                  <img src={user.avatar_url} alt="" className="h-7 w-7 rounded-full" />
                )}
                <span className="hidden text-sm text-ink-muted sm:inline">
                  {user.name || user.email}
                </span>
                <button
                  onClick={onSignOut}
                  className="rounded-lg border border-edge px-3 py-1 text-sm text-ink-muted hover:bg-soft"
                >
                  Sign out
                </button>
              </>
            ) : (
              <Link
                to="/sign-in"
                className="rounded-lg border border-edge px-3 py-1 text-sm text-ink-muted hover:bg-soft"
              >
                Sign in
              </Link>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
        <Outlet />
      </main>
    </div>
  )
}
