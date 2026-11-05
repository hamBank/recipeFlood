import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from './api'
import App, { USER_CACHE_KEY } from './App'

let expire = null
vi.mock('./api', () => ({
  getAuthConfig: vi.fn(),
  getMe: vi.fn(),
  getToken: vi.fn(),
  setToken: vi.fn(),
  getHealth: vi.fn().mockResolvedValue({}),
  setSessionExpiredHandler: vi.fn((handler) => {
    expire = handler
  }),
}))
vi.mock('./pages/RecipeListPage', () => ({ default: () => <div>Recipe list</div> }))
vi.mock('./pages/PantryPage', () => ({ default: () => <div>Pantry page</div> }))
vi.mock('./pages/LoginPage', () => ({
  default: ({ notice, onSignedIn }) => (
    <div>
      <p>Sign-in</p>
      {notice && <p>{notice}</p>}
      <button onClick={() => onSignedIn({ id: 1, email: 'cook@example.com' })}>Finish sign-in</button>
    </div>
  ),
}))

async function renderAt(path, { publicRead = true } = {}) {
  api.getAuthConfig.mockResolvedValue({ auth_enabled: true, public_read: publicRead })
  await act(async () => {
    render(
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>,
    )
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  expire = null
  api.getToken.mockReturnValue('token')
  api.getMe.mockResolvedValue({ id: 1, email: 'cook@example.com' })
})

describe('a session that expires mid-use', () => {
  it('goes to the sign-in page with a notice, then back to the page it was on', async () => {
    await renderAt('/pantry')
    await waitFor(() => expect(screen.getByText('Pantry page')).toBeDefined())

    act(() => expire())
    expect(screen.getByText('Sign-in')).toBeDefined()
    expect(screen.getByText('Your session has expired. Please sign in again.')).toBeDefined()
    expect(localStorage.getItem(USER_CACHE_KEY)).toBe('null')

    fireEvent.click(screen.getByText('Finish sign-in'))
    await waitFor(() => expect(screen.getByText('Pantry page')).toBeDefined())
  })

  it('shows the notice on a private site too', async () => {
    await renderAt('/', { publicRead: false })
    await waitFor(() => expect(screen.getByText('Recipe list')).toBeDefined())
    act(() => expire())
    expect(screen.getByText('Your session has expired. Please sign in again.')).toBeDefined()
  })

  it('does nothing for a visitor who was never signed in', async () => {
    api.getToken.mockReturnValue(null)
    await renderAt('/')
    await waitFor(() => expect(screen.getByText('Recipe list')).toBeDefined())
    act(() => expire())
    expect(screen.getByText('Recipe list')).toBeDefined()
    expect(screen.queryByText('Sign-in')).toBeNull()
  })
})
