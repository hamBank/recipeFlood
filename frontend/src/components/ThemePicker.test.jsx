import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import ThemePicker from './ThemePicker'
import { THEMES } from '../themes'

beforeEach(() => {
  localStorage.clear()
  document.documentElement.dataset.theme = ''
})

describe('ThemePicker', () => {
  it('renders one button per theme', () => {
    render(<ThemePicker />)
    THEMES.forEach((option) => {
      expect(screen.getByRole('button', { name: `${option.label} theme` })).toBeDefined()
    })
  })

  it('marks light as pressed by default', () => {
    render(<ThemePicker />)
    expect(screen.getByRole('button', { name: 'Light theme' }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('button', { name: 'Dark theme' }).getAttribute('aria-pressed')).toBe('false')
  })

  it('applies and persists the chosen theme on click', () => {
    render(<ThemePicker />)
    fireEvent.click(screen.getByRole('button', { name: 'Herb theme' }))

    expect(screen.getByRole('button', { name: 'Herb theme' }).getAttribute('aria-pressed')).toBe('true')
    expect(document.documentElement.dataset.theme).toBe('herb')
    expect(localStorage.getItem('rf_theme')).toBe('herb')
  })

  it('starts from whatever theme was already saved', () => {
    localStorage.setItem('rf_theme', 'berry')
    render(<ThemePicker />)
    expect(screen.getByRole('button', { name: 'Berry theme' }).getAttribute('aria-pressed')).toBe('true')
  })
})
