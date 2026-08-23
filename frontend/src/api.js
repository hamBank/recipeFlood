const TOKEN_KEY = 'rf_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

function authHeaders(extra = {}) {
  const headers = { ...extra }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  return headers
}

async function toError(response) {
  let detail
  try {
    detail = (await response.json()).detail
  } catch {
    // non-JSON error body
  }
  const error = new Error(detail || `${response.status} ${response.statusText}`)
  error.status = response.status
  return error
}

export async function apiFetch(path, { method = 'GET', body } = {}) {
  const headers = authHeaders(body !== undefined ? { 'Content-Type': 'application/json' } : {})
  const response = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) throw await toError(response)
  return response.status === 204 ? null : response.json()
}

/** Paged GET: resolves to { items, total } using the X-Total-Count header. */
export async function apiFetchPaged(path) {
  const response = await fetch(path, { headers: authHeaders() })
  if (!response.ok) throw await toError(response)
  return {
    items: await response.json(),
    total: Number(response.headers.get('X-Total-Count') || 0),
  }
}

async function apiUpload(path, formData) {
  const response = await fetch(path, {
    method: 'POST',
    headers: authHeaders(), // no Content-Type: the browser sets the boundary
    body: formData,
  })
  if (!response.ok) throw await toError(response)
  return response.json()
}

const query = (params) => {
  const search = new URLSearchParams()
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, value)
  })
  const string = search.toString()
  return string ? `?${string}` : ''
}

// Auth
export const getAuthConfig = () => apiFetch('/auth/config')
export const loginWithGoogle = (credential) =>
  apiFetch('/auth/google', { method: 'POST', body: { credential } })
export const getMe = () => apiFetch('/auth/me')

// Recipes
export const listRecipes = (params) => apiFetchPaged(`/recipes${query(params)}`)
export const getRecipe = (key) => apiFetch(`/recipes/${key}`)
export const createRecipe = (data) => apiFetch('/recipes', { method: 'POST', body: data })
export const updateRecipe = (key, data) =>
  apiFetch(`/recipes/${key}`, { method: 'PATCH', body: data })
export const deleteRecipe = (key) => apiFetch(`/recipes/${key}`, { method: 'DELETE' })
export const markPrepared = (key, data) =>
  apiFetch(`/recipes/${key}/prepared`, { method: 'POST', body: data })
export const deletePrepared = (key, id) =>
  apiFetch(`/recipes/${key}/prepared/${id}`, { method: 'DELETE' })
export const uploadRecipeImage = (key, file) => {
  const form = new FormData()
  form.append('file', file)
  return apiUpload(`/recipes/${key}/image`, form)
}

// Tags. Sections are tags flagged for the navigation, so they come from
// the same endpoint — there is no separate category concept.
export const listSections = () => apiFetch('/tags?section=true')
export const listTags = (minCount = 1) =>
  apiFetch(`/tags?section=false&min_count=${minCount}`)
export const createTag = (data) => apiFetch('/tags', { method: 'POST', body: data })
export const updateTag = (key, data) =>
  apiFetch(`/tags/${key}`, { method: 'PATCH', body: data })
export const deleteTag = (key) => apiFetch(`/tags/${key}`, { method: 'DELETE' })

// Master ingredients (signed-in only — this is where cost lives)
export const listIngredients = (params) => apiFetchPaged(`/ingredients${query(params)}`)
export const getIngredient = (key) => apiFetch(`/ingredients/${key}`)
export const createIngredient = (data) =>
  apiFetch('/ingredients', { method: 'POST', body: data })
export const updateIngredient = (key, data) =>
  apiFetch(`/ingredients/${key}`, { method: 'PATCH', body: data })
export const mergeIngredients = (keepKey, mergeKey) =>
  apiFetch(`/ingredients/${keepKey}/merge/${mergeKey}`, { method: 'POST' })
export const deleteIngredient = (key) =>
  apiFetch(`/ingredients/${key}`, { method: 'DELETE' })

// AI import
export const getImportConfig = () => apiFetch('/imports/config')
export const importPaste = (text, titleHint) =>
  apiFetch('/imports/paste', { method: 'POST', body: { text, title_hint: titleHint } })
export const importImage = (file, titleHint) => {
  const form = new FormData()
  form.append('file', file)
  if (titleHint) form.append('title_hint', titleHint)
  return apiUpload('/imports/image', form)
}

// Cooking lists
export const listCookLists = (params) => apiFetchPaged(`/cook-lists${query(params)}`)
export const getCookList = (id) => apiFetch(`/cook-lists/${id}`)
export const createCookList = (data) =>
  apiFetch('/cook-lists', { method: 'POST', body: data })
export const updateCookList = (id, data) =>
  apiFetch(`/cook-lists/${id}`, { method: 'PATCH', body: data })
export const deleteCookList = (id) => apiFetch(`/cook-lists/${id}`, { method: 'DELETE' })
export const addRecipeToCookList = (id, data) =>
  apiFetch(`/cook-lists/${id}/recipes`, { method: 'POST', body: data })
export const removeRecipeFromCookList = (id, recipeId) =>
  apiFetch(`/cook-lists/${id}/recipes/${recipeId}`, { method: 'DELETE' })
export const addCookListToShopping = (id) =>
  apiFetch(`/cook-lists/${id}/add-to-shopping`, { method: 'POST' })

// The shopping list
export const getShoppingList = () => apiFetch('/shopping')
export const addShoppingItem = (data) =>
  apiFetch('/shopping', { method: 'POST', body: data })
export const updateShoppingItem = (id, data) =>
  apiFetch(`/shopping/${id}`, { method: 'PATCH', body: data })
export const deleteShoppingItem = (id) =>
  apiFetch(`/shopping/${id}`, { method: 'DELETE' })
export const clearCheckedShopping = () =>
  apiFetch('/shopping/clear-checked', { method: 'POST' })
export const uncheckAllShopping = () =>
  apiFetch('/shopping/uncheck-all', { method: 'POST' })
