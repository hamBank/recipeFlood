export const THEMES = [
  { id: 'light', label: 'Light', swatch: '#faf7f2' },
  { id: 'dark', label: 'Dark', swatch: '#1c1917' },
  { id: 'herb', label: 'Herb', swatch: '#dcf0e3' },
  { id: 'berry', label: 'Berry', swatch: '#fbe0e7' },
]

const STORAGE_KEY = 'rf_theme'

export function currentTheme() {
  const saved = localStorage.getItem(STORAGE_KEY)
  return THEMES.some((t) => t.id === saved) ? saved : 'light'
}

export function applyTheme(id) {
  document.documentElement.dataset.theme = id
  localStorage.setItem(STORAGE_KEY, id)
}

export function initTheme() {
  document.documentElement.dataset.theme = currentTheme()
}
