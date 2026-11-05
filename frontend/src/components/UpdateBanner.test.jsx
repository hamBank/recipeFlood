import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import UpdateBanner from './UpdateBanner'

afterEach(() => vi.useRealTimers())

async function renderWith(props) {
  await act(async () => {
    render(<UpdateBanner {...props} />)
  })
}

describe('UpdateBanner', () => {
  it('offers a reload when the server is serving a newer frontend', async () => {
    const check = vi.fn().mockResolvedValue({ frontend_sha: 'new1234' })
    await renderWith({ builtFrom: 'old1234', check })
    expect(screen.getByText(/A newer version of Recipe Flood is available/)).toBeDefined()
    const reload = vi.fn()
    vi.stubGlobal('location', { ...window.location, reload })
    fireEvent.click(screen.getByText('Reload'))
    expect(reload).toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it('stays hidden while the frontend is current', async () => {
    await renderWith({ builtFrom: 'abc1234', check: vi.fn().mockResolvedValue({ frontend_sha: 'abc1234' }) })
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('stays hidden when the server cannot be asked', async () => {
    await renderWith({ builtFrom: 'abc1234', check: vi.fn().mockRejectedValue(new Error('Failed to fetch')) })
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('does not ask at all in an unbuilt (dev) bundle', async () => {
    const check = vi.fn()
    await renderWith({ builtFrom: '', check })
    expect(check).not.toHaveBeenCalled()
  })

  it('asks again later, so a deploy while the tab is open is noticed', async () => {
    vi.useFakeTimers()
    const check = vi
      .fn()
      .mockResolvedValueOnce({ frontend_sha: 'abc1234' })
      .mockResolvedValue({ frontend_sha: 'def5678' })
    await renderWith({ builtFrom: 'abc1234', check })
    expect(screen.queryByRole('status')).toBeNull()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10 * 60 * 1000)
    })
    expect(check).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('status')).toBeDefined()
  })
})
