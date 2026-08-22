import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getImportConfig, importImage, importPaste } from '../api'

/**
 * AI import: paste a recipe, or photograph one.
 *
 * Neither path saves anything. Both produce a draft that is handed to the
 * normal entry form for a human to check — a model misreading "1/4 tsp" as
 * "1/4 cup" should cost a correction, not a ruined recipe.
 */
export default function ImportPage() {
  const navigate = useNavigate()
  const [mode, setMode] = useState('paste')
  const [text, setText] = useState('')
  const [file, setFile] = useState(null)
  const [titleHint, setTitleHint] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [config, setConfig] = useState(null)

  useEffect(() => {
    getImportConfig()
      .then(setConfig)
      .catch(() => setConfig({ ai_available: false }))
  }, [])

  const run = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const draft =
        mode === 'paste'
          ? await importPaste(text, titleHint || null)
          : await importImage(file, titleHint || null)
      navigate('/new', { state: { draft } })
    } catch (caught) {
      setError(caught.message)
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-ink">Import a recipe</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Paste a recipe or photograph one. You get a filled-in entry form to
          check and save — nothing is stored until you do.
        </p>
      </div>

      {config && !config.ai_available && (
        <p className="rounded-lg bg-soft p-4 text-sm text-ink-muted">
          AI import is not configured on this server. Set{' '}
          <code className="rounded bg-card px-1">ANTHROPIC_API_KEY</code> in the
          environment file and restart (see DEPLOYMENT.md). You can still{' '}
          <a href="/new" className="text-accent hover:underline">
            add a recipe by hand
          </a>
          .
        </p>
      )}

      <div className="flex rounded-lg border border-edge bg-card p-1 text-sm">
        {[
          ['paste', 'Paste text'],
          ['image', 'From a photo'],
        ].map(([value, label]) => (
          <button
            key={value}
            onClick={() => setMode(value)}
            className={`flex-1 rounded px-3 py-1.5 ${
              mode === value
                ? 'bg-accent text-[color:var(--accent-ink)]'
                : 'text-ink-muted hover:bg-soft'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <form onSubmit={run} className="space-y-3 rounded-xl border border-edge bg-card p-5">
        <label className="block">
          <span className="text-sm font-medium text-ink">Title hint (optional)</span>
          <input
            value={titleHint}
            onChange={(event) => setTitleHint(event.target.value)}
            placeholder="Nana's lemon slice"
            className="mt-1 w-full rounded-lg border border-edge bg-card px-3 py-2 text-sm text-ink placeholder:text-ink-faint"
          />
        </label>

        {mode === 'paste' ? (
          <label className="block">
            <span className="text-sm font-medium text-ink">Recipe text</span>
            <textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              rows={14}
              placeholder="Paste the whole thing — ingredients, method, notes. Formatting doesn't matter."
              className="mt-1 w-full rounded-lg border border-edge bg-card px-3 py-2 font-mono text-sm text-ink placeholder:text-ink-faint"
            />
          </label>
        ) : (
          <label className="block">
            <span className="text-sm font-medium text-ink">Photo of the recipe</span>
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp,image/gif"
              onChange={(event) => setFile(event.target.files?.[0] || null)}
              className="mt-1 w-full text-sm text-ink-muted"
            />
            <span className="mt-1 block text-xs text-ink-faint">
              A cookbook page, a handwritten card, a screenshot. JPEG, PNG, WebP
              or GIF, up to 8MB.
            </span>
          </label>
        )}

        {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}

        <button
          type="submit"
          disabled={busy || (mode === 'paste' ? !text.trim() : !file)}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-[color:var(--accent-ink)] disabled:opacity-50"
        >
          {busy ? 'Reading it…' : 'Import'}
        </button>
      </form>
    </div>
  )
}
