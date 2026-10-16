import { useState } from 'react'
import { setToken } from '../api'
import { CONFIG_CACHE_KEY, USER_CACHE_KEY } from '../App'
import { clearCachedList, loadQueue } from '../offlineQueue'
import { getServerUrl, setServerUrl } from '../platform'

/**
 * Desktop app only: which Recipe Flood server to talk to. Everything the app
 * has cached or signed in with belongs to the old server, so a change wipes
 * it and reloads.
 */
export default function SettingsPage() {
  const [server, setServer] = useState(getServerUrl())
  const [error, setError] = useState(null)

  const onSave = (event) => {
    event.preventDefault()
    setError(null)
    // Replaying queued shopping changes against a different server would
    // add and tick things on the wrong list.
    const pending = loadQueue().length
    if (pending > 0) {
      setError(
        `You have ${pending} unsynced shopping ${pending === 1 ? 'change' : 'changes'}. ` +
          'Go back online and let them sync first.',
      )
      return
    }
    try {
      setServerUrl(server)
    } catch (caught) {
      setError(caught.message)
      return
    }
    setToken(null)
    clearCachedList()
    try {
      localStorage.removeItem(CONFIG_CACHE_KEY)
      localStorage.removeItem(USER_CACHE_KEY)
    } catch {
      // storage unavailable: nothing cached to clear
    }
    window.location.reload()
  }

  return (
    <form onSubmit={onSave} className="mx-auto max-w-md rounded-xl border border-edge bg-card p-6 shadow-sm">
      <h1 className="text-xl font-bold text-ink">Settings</h1>
      <label className="mt-4 block text-sm font-medium text-ink" htmlFor="server-url">
        Server
      </label>
      <input
        id="server-url"
        type="text"
        value={server}
        onChange={(event) => setServer(event.target.value)}
        className="mt-1 w-full rounded-lg border border-edge bg-page px-3 py-2 text-sm text-ink"
      />
      <p className="mt-2 text-xs text-ink-muted">
        Changing the server signs you out. Use https://, or http://localhost for development.
      </p>
      <button
        type="submit"
        className="mt-4 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-[color:var(--accent-ink)]"
      >
        Save
      </button>
      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
    </form>
  )
}
