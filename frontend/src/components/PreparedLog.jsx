import { useState } from 'react'
import { formatDate, formatRelative } from '../format'

/**
 * "Last Prepared Date" as a log rather than a single field: each cook is an
 * entry, so the newest one is the last-prepared date and the history stays
 * around to answer "have we made this before, and was it any good?".
 */
export default function PreparedLog({ recipe, canEdit, onMark, onDelete }) {
  const [open, setOpen] = useState(false)
  const [preparedOn, setPreparedOn] = useState(() => new Date().toISOString().slice(0, 10))
  const [rating, setRating] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    await onMark({
      prepared_on: preparedOn,
      rating: rating ? Number(rating) : null,
      note: note.trim() || null,
    })
    setBusy(false)
    setOpen(false)
    setNote('')
    setRating('')
  }

  return (
    <div className="rounded-xl border border-edge bg-card p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold text-ink">Cooked</h2>
        {canEdit && (
          <button
            onClick={() => setOpen((value) => !value)}
            className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-[color:var(--accent-ink)]"
          >
            {open ? 'Cancel' : 'I made this'}
          </button>
        )}
      </div>

      <p className="mt-2 text-sm text-ink-muted">
        {recipe.last_prepared_on
          ? `Last made ${formatRelative(recipe.last_prepared_on)} · ${recipe.prepared_count} time${recipe.prepared_count === 1 ? '' : 's'} in total`
          : 'Never recorded as made.'}
      </p>

      {open && (
        <form onSubmit={submit} className="mt-3 space-y-2">
          <div className="flex flex-wrap gap-2">
            <input
              type="date"
              value={preparedOn}
              onChange={(event) => setPreparedOn(event.target.value)}
              className="rounded-lg border border-edge bg-card px-3 py-1.5 text-sm text-ink"
            />
            <select
              value={rating}
              onChange={(event) => setRating(event.target.value)}
              className="rounded-lg border border-edge bg-card px-3 py-1.5 text-sm text-ink"
            >
              <option value="">No rating</option>
              {[5, 4, 3, 2, 1].map((value) => (
                <option key={value} value={value}>
                  {'★'.repeat(value)}
                </option>
              ))}
            </select>
          </div>
          <input
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Note (halved the sugar, needs more chilli…)"
            className="w-full rounded-lg border border-edge bg-card px-3 py-1.5 text-sm text-ink placeholder:text-ink-faint"
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-[color:var(--accent-ink)] disabled:opacity-50"
          >
            {busy ? 'Saving…' : 'Record it'}
          </button>
        </form>
      )}

      {recipe.prepared_events?.length > 0 && (
        <ul className="mt-3 space-y-1.5 text-sm">
          {recipe.prepared_events.map((event) => (
            <li key={event.id} className="flex items-start gap-2 border-t border-edge/60 pt-1.5">
              <span className="text-ink-muted">{formatDate(event.prepared_on)}</span>
              {event.rating && <span className="text-accent">{'★'.repeat(event.rating)}</span>}
              {event.note && <span className="flex-1 text-ink-muted">{event.note}</span>}
              {canEdit && (
                <button
                  onClick={() => onDelete(event.id)}
                  title="Remove this entry"
                  className="ml-auto text-xs text-ink-faint hover:text-red-600"
                >
                  ✕
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
