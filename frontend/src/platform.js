/**
 * Which target this bundle was built for, and where the server is.
 *
 * The web build is served by the backend from the same origin, so every URL
 * stays root-relative (`/recipes`, `/media/...`). The desktop build loads
 * from the app's own origin, so API and image URLs need the server prefixed
 * on. Everything that builds such a URL goes through here, which keeps the
 * web build's behaviour identical to before this file existed.
 */

export const IS_DESKTOP = import.meta.env.VITE_TARGET === 'desktop'
export const DEFAULT_SERVER_URL = import.meta.env.VITE_DEFAULT_SERVER_URL

const SERVER_URL_KEY = 'rf_server_url'

const stripTrailingSlashes = (url) => url.replace(/\/+$/, '')

export function getServerUrl() {
  if (!IS_DESKTOP) return ''
  let saved = null
  try {
    saved = localStorage.getItem(SERVER_URL_KEY)
  } catch {
    // storage blocked or unavailable: fall back to the default
  }
  return stripTrailingSlashes(saved || DEFAULT_SERVER_URL || '')
}

// https anywhere, or plain http only for a local development server —
// credentials and the bearer token must not cross the network in the clear.
const SERVER_URL_PATTERN = /^(https:\/\/[^/\s]+|http:\/\/(localhost|127\.0\.0\.1)(:\d+)?)$/

export function setServerUrl(url) {
  if (!IS_DESKTOP) return
  const normalised = stripTrailingSlashes((url || '').trim())
  if (!SERVER_URL_PATTERN.test(normalised)) {
    throw new Error('Server address must start with https:// (or http://localhost for development)')
  }
  localStorage.setItem(SERVER_URL_KEY, normalised)
}

/** `path` must start with `/`. */
export const apiUrl = (path) => getServerUrl() + path

export const mediaUrl = (imagePath) => apiUrl(`/media/${imagePath}`)
