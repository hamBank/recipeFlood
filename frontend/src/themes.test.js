import { beforeEach, describe, expect, it } from 'vitest'
import { applyTheme, currentTheme, THEMES } from './themes'

describe('themes', () => {
  beforeEach(() => {
    localStorage.clear()
    delete document.documentElement.dataset.theme
  })

  it('defaults to light', () => {
    expect(currentTheme()).toBe('light')
  })

  it('round-trips a chosen theme through localStorage', () => {
    applyTheme('herb')
    expect(currentTheme()).toBe('herb')
    expect(document.documentElement.dataset.theme).toBe('herb')
  })

  it('ignores a stored theme that no longer exists', () => {
    localStorage.setItem('rf_theme', 'neon')
    expect(currentTheme()).toBe('light')
  })

  it('every theme has a swatch for the picker', () => {
    THEMES.forEach((theme) => {
      expect(theme.swatch).toMatch(/^#[0-9a-f]{6}$/i)
      expect(theme.label).toBeTruthy()
    })
  })
})
