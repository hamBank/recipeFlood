import { formatCents, formatPercent } from '../format'

/** Signed-in only — the backend omits `cost` entirely for guests. */
export default function CostPanel({ cost, symbol = '$' }) {
  if (!cost) return null
  const complete = cost.known_fraction >= 0.999

  return (
    <div className="rounded-xl border border-edge bg-card p-5">
      <h2 className="font-semibold text-ink">Cost</h2>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-2xl font-bold text-ink">
          {complete ? '' : 'at least '}
          {formatCents(cost.total_cents, symbol)}
        </span>
        {cost.per_serving_cents !== null && cost.per_serving_cents !== undefined && (
          <span className="text-sm text-ink-muted">
            · {formatCents(cost.per_serving_cents, symbol)} per serving
          </span>
        )}
      </div>
      <p className="mt-2 text-xs text-ink-faint">
        {cost.priced_count} of {cost.ingredient_count} ingredients priced
        {' '}({formatPercent(cost.known_fraction)}).
        {!complete && ' Add prices on the Pantry page to complete this.'}
      </p>
    </div>
  )
}
