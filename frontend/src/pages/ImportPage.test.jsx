import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api'
import ImportPage from './ImportPage'

vi.mock('../api', () => ({
  getImportConfig: vi.fn(),
  importPaste: vi.fn(),
  importImage: vi.fn(),
}))

function NewRecipeStub() {
  const location = useLocation()
  return <div>Draft title: {location.state?.draft?.title}</div>
}

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/import']}>
      <Routes>
        <Route path="/import" element={<ImportPage />} />
        <Route path="/new" element={<NewRecipeStub />} />
      </Routes>
    </MemoryRouter>
  )

beforeEach(() => {
  vi.clearAllMocks()
  api.getImportConfig.mockResolvedValue({ ai_available: true })
})

describe('ImportPage', () => {
  it('shows the not-configured notice when AI import is unavailable', async () => {
    api.getImportConfig.mockResolvedValue({ ai_available: false })
    renderPage()
    await waitFor(() => expect(screen.getByText(/AI import is not configured/)).toBeDefined())
  })

  it('says nothing about configuration once AI import is available', async () => {
    renderPage()
    await waitFor(() => expect(api.getImportConfig).toHaveBeenCalled())
    expect(screen.queryByText(/AI import is not configured/)).toBeNull()
  })

  it('treats a config-fetch failure as unavailable rather than crashing', async () => {
    api.getImportConfig.mockRejectedValue(new Error('offline'))
    renderPage()
    await waitFor(() => expect(screen.getByText(/AI import is not configured/)).toBeDefined())
  })

  it('disables Import until there is text to paste', async () => {
    renderPage()
    await waitFor(() => expect(api.getImportConfig).toHaveBeenCalled())
    expect(screen.getByRole('button', { name: 'Import' }).disabled).toBe(true)

    fireEvent.change(screen.getByPlaceholderText(/Paste the whole thing/), {
      target: { value: 'Flour, sugar, eggs.' },
    })
    expect(screen.getByRole('button', { name: 'Import' }).disabled).toBe(false)
  })

  it('submits pasted text and navigates to the entry form with the draft', async () => {
    api.importPaste.mockResolvedValue({ title: 'Lemon Slice' })
    renderPage()
    await waitFor(() => expect(api.getImportConfig).toHaveBeenCalled())

    fireEvent.change(screen.getByPlaceholderText(/Nana's lemon slice/), {
      target: { value: 'Lemon Slice' },
    })
    fireEvent.change(screen.getByPlaceholderText(/Paste the whole thing/), {
      target: { value: 'Flour, sugar, eggs.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Import' }))

    await waitFor(() => expect(screen.getByText('Draft title: Lemon Slice')).toBeDefined())
    expect(api.importPaste).toHaveBeenCalledWith('Flour, sugar, eggs.', 'Lemon Slice')
  })

  it('switches to photo mode and requires a file instead of text', async () => {
    renderPage()
    await waitFor(() => expect(api.getImportConfig).toHaveBeenCalled())

    fireEvent.click(screen.getByRole('button', { name: 'From a photo' }))
    expect(screen.getByRole('button', { name: 'Import' }).disabled).toBe(true)
    expect(screen.getByText(/Photo of the recipe/)).toBeDefined()

    const file = new File(['fake'], 'recipe.jpg', { type: 'image/jpeg' })
    const input = document.querySelector('input[type="file"]')
    fireEvent.change(input, { target: { files: [file] } })
    expect(screen.getByRole('button', { name: 'Import' }).disabled).toBe(false)
  })

  it('shows an error and re-enables the form when the import fails', async () => {
    api.importPaste.mockRejectedValue(new Error('Could not read that'))
    renderPage()
    await waitFor(() => expect(api.getImportConfig).toHaveBeenCalled())

    fireEvent.change(screen.getByPlaceholderText(/Paste the whole thing/), {
      target: { value: 'Flour, sugar, eggs.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Import' }))

    await waitFor(() => expect(screen.getByText('Could not read that')).toBeDefined())
    expect(screen.getByRole('button', { name: 'Import' }).disabled).toBe(false)
  })
})
