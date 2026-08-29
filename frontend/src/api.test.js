import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  apiFetch,
  apiFetchPaged,
  getToken,
  loginWithGoogle,
  setToken,
  uploadRecipeImage,
} from './api'

const jsonResponse = (body, { ok = true, status = 200, headers = {} } = {}) => ({
  ok,
  status,
  statusText: 'status text',
  json: () => Promise.resolve(body),
  headers: { get: (key) => headers[key] ?? null },
})

beforeEach(() => {
  localStorage.clear()
  global.fetch = vi.fn()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('token storage', () => {
  it('stores and returns the token', () => {
    setToken('abc123')
    expect(getToken()).toBe('abc123')
    expect(localStorage.getItem('rf_token')).toBe('abc123')
  })

  it('clears the token when set to a falsy value', () => {
    setToken('abc123')
    setToken(null)
    expect(getToken()).toBeNull()
  })
})

describe('apiFetch', () => {
  it('sends a bare GET with no body and no auth header when signed out', async () => {
    global.fetch.mockResolvedValue(jsonResponse({ ok: true }))
    await apiFetch('/health')

    const [path, options] = global.fetch.mock.calls[0]
    expect(path).toBe('/health')
    expect(options.method).toBe('GET')
    expect(options.body).toBeUndefined()
    expect(options.headers.Authorization).toBeUndefined()
  })

  it('adds a bearer token when one is stored', async () => {
    setToken('my-token')
    global.fetch.mockResolvedValue(jsonResponse({}))
    await apiFetch('/auth/me')

    expect(global.fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer my-token')
  })

  it('JSON-encodes a body and sets Content-Type', async () => {
    global.fetch.mockResolvedValue(jsonResponse({ id: 1 }))
    await apiFetch('/recipes', { method: 'POST', body: { title: 'Soup' } })

    const [, options] = global.fetch.mock.calls[0]
    expect(options.method).toBe('POST')
    expect(options.headers['Content-Type']).toBe('application/json')
    expect(options.body).toBe(JSON.stringify({ title: 'Soup' }))
  })

  it('returns null for a 204 response instead of parsing a body', async () => {
    global.fetch.mockResolvedValue(jsonResponse(null, { status: 204 }))
    await expect(apiFetch('/shopping/1', { method: 'DELETE' })).resolves.toBeNull()
  })

  it('rejects with the detail message from a JSON error body', async () => {
    global.fetch.mockResolvedValue(jsonResponse({ detail: 'Title is required' }, { ok: false, status: 422 }))
    await expect(apiFetch('/recipes', { method: 'POST', body: {} })).rejects.toMatchObject({
      message: 'Title is required',
      status: 422,
    })
  })

  it('falls back to status text when the error body is not JSON', async () => {
    const response = jsonResponse(undefined, { ok: false, status: 500 })
    response.json = () => Promise.reject(new Error('not json'))
    global.fetch.mockResolvedValue(response)

    await expect(apiFetch('/recipes')).rejects.toMatchObject({
      message: '500 status text',
      status: 500,
    })
  })
})

describe('apiFetchPaged', () => {
  it('pairs the parsed items with the X-Total-Count header', async () => {
    global.fetch.mockResolvedValue(jsonResponse([{ id: 1 }, { id: 2 }], { headers: { 'X-Total-Count': '37' } }))
    await expect(apiFetchPaged('/recipes')).resolves.toEqual({ items: [{ id: 1 }, { id: 2 }], total: 37 })
  })

  it('defaults the total to 0 when the header is missing', async () => {
    global.fetch.mockResolvedValue(jsonResponse([]))
    await expect(apiFetchPaged('/recipes')).resolves.toEqual({ items: [], total: 0 })
  })
})

describe('typed endpoints', () => {
  it('loginWithGoogle posts the credential', async () => {
    global.fetch.mockResolvedValue(jsonResponse({ token: 't', user: {} }))
    await loginWithGoogle('a-credential')

    const [path, options] = global.fetch.mock.calls[0]
    expect(path).toBe('/auth/google')
    expect(JSON.parse(options.body)).toEqual({ credential: 'a-credential' })
  })

  it('uploadRecipeImage posts a FormData body with no Content-Type override', async () => {
    global.fetch.mockResolvedValue(jsonResponse({ image_path: '/media/x.jpg' }))
    const file = new File(['fake'], 'photo.jpg', { type: 'image/jpeg' })
    await uploadRecipeImage('flax-bread', file)

    const [path, options] = global.fetch.mock.calls[0]
    expect(path).toBe('/recipes/flax-bread/image')
    expect(options.body).toBeInstanceOf(FormData)
    expect(options.headers['Content-Type']).toBeUndefined()
  })
})
