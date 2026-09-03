import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api'
import CookListLatestPage from './CookListLatestPage'

vi.mock('../api', () => ({
  listCookLists: vi.fn(),
}))

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/cooking']}>
      <Routes>
        <Route path="/cooking" element={<CookListLatestPage />} />
        <Route path="/cooking/all" element={<p>All cooking lists</p>} />
        <Route path="/cooking/:id" element={<p>Cooking list detail</p>} />
      </Routes>
    </MemoryRouter>
  )

beforeEach(() => {
  vi.clearAllMocks()
})

describe('CookListLatestPage', () => {
  it('redirects to the most recent list', async () => {
    api.listCookLists.mockResolvedValue({ items: [{ id: 42 }], total: 1 })
    renderPage()
    await waitFor(() => expect(screen.getByText('Cooking list detail')).toBeDefined())
    expect(api.listCookLists).toHaveBeenCalledWith({ limit: 1, offset: 0 })
  })

  it('falls back to the full list when there are no cooking lists yet', async () => {
    api.listCookLists.mockResolvedValue({ items: [], total: 0 })
    renderPage()
    await waitFor(() => expect(screen.getByText('All cooking lists')).toBeDefined())
  })

  it('falls back to the full list on a load error', async () => {
    api.listCookLists.mockRejectedValue(new Error('offline'))
    renderPage()
    await waitFor(() => expect(screen.getByText('All cooking lists')).toBeDefined())
  })
})
