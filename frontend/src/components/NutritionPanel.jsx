import { useState } from 'react'
import { formatGrams, formatPercent } from '../format'

const ROWS = [
  { key: 'energy_kj', label: 'Energy', unit: 'kJ', decimals: 0 },
  { key: 'calories_kcal', label: 'Calories', unit: 'kcal', decimals: 0 },
  { key: 'protein_g', label: 'Protein', unit: 'g', decimals: 1 },
  { key: 'fat_g', label: 'Fat, total', unit: 'g', decimals: 1 },
  { key: 'saturated_fat_g', label: '— saturated', unit: 'g', decimals: 1 },
  { key: 'carbs_g', label: 'Carbohydrate', unit: 'g', decimals: 1 },
  { key: 'sugars_g', label: '— sugars', unit: 'g', decimals: 1 },
  { key: 'fibre_g', label: 'Fibre', unit: 'g', decimals: 1 },
  { key: 'sodium_mg', label: 'Sodium', unit: 'mg', decimals: 0 },
]

/**
 * Nutrition is summed from the master ingredient list on every read, so a
 * panel is only ever as complete as the pantry behind it. Rather than
 * present a confident-looking undercount, the panel leads with how much of
 * the recipe's weight it could actually account for.
 */
export default function NutritionPanel({ whole, perServing }) {
  const [perServe, setPerServe] = useState(Boolean(perServing))
  const data = perServe && perServing ? perServing : whole
  if (!data) return null

  const anyValues = ROWS.some((row) => data[row.key] !== null && data[row.key] !== undefined)

  if (!anyValues) {
    return (
      <div className="rounded-xl border border-edge bg-card p-5">
        <h2 className="font-semibold text-ink">Nutrition</h2>
        <p className="mt-2 text-sm text-ink-muted">
          Nothing to show yet — nutrition is computed from the master ingredient
          list, and none of this recipe’s ingredients have figures entered.
          Fill them in on the Pantry page and this panel fills itself in.
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-edge bg-card p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold text-ink">Nutrition</h2>
        {perServing && (
          <div className="flex rounded-lg border border-edge text-xs">
            <button
              onClick={() => setPerServe(true)}
              className={`rounded-l-lg px-2.5 py-1 ${perServe ? 'bg-accent text-[color:var(--accent-ink)]' : 'text-ink-muted'}`}
            >
              Per serving
            </button>
            <button
              onClick={() => setPerServe(false)}
              className={`rounded-r-lg px-2.5 py-1 ${!perServe ? 'bg-accent text-[color:var(--accent-ink)]' : 'text-ink-muted'}`}
            >
              Whole recipe
            </button>
          </div>
        )}
      </div>

      <table className="mt-3 w-full text-sm">
        <tbody>
          {ROWS.filter((row) => data[row.key] !== null && data[row.key] !== undefined).map(
            (row) => (
              <tr key={row.key} className="border-b border-edge/60 last:border-0">
                <td className="py-1.5 text-ink-muted">{row.label}</td>
                <td className="py-1.5 text-right font-medium text-ink">
                  {data[row.key].toFixed(row.decimals)}
                  <span className="ml-1 text-xs font-normal text-ink-faint">{row.unit}</span>
                </td>
              </tr>
            ),
          )}
        </tbody>
      </table>

      <p className="mt-3 text-xs text-ink-faint">
        Covers {formatPercent(data.coverage)} of the recipe by weight
        {' '}({formatGrams(data.covered_grams)} of {formatGrams(data.total_grams)}).
        {data.coverage < 0.9 && ' Add data for the remaining ingredients for a complete panel.'}
      </p>
    </div>
  )
}
