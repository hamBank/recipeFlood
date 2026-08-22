import { useState } from 'react'
import { applyTheme, currentTheme, THEMES } from '../themes'

export default function ThemePicker() {
  const [theme, setTheme] = useState(currentTheme)

  const choose = (id) => {
    applyTheme(id)
    setTheme(id)
  }

  return (
    <div className="flex items-center gap-1.5">
      {THEMES.map((option) => (
        <button
          key={option.id}
          onClick={() => choose(option.id)}
          title={option.label}
          aria-label={`${option.label} theme`}
          aria-pressed={theme === option.id}
          className={`h-5 w-5 rounded-full border-2 transition ${
            theme === option.id ? 'border-accent' : 'border-edge'
          }`}
          style={{ backgroundColor: option.swatch }}
        />
      ))}
    </div>
  )
}
