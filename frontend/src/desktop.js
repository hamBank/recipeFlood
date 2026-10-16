/**
 * Desktop-only behaviour that needs the Tauri shell. Loaded only through
 * dynamic `import()` behind `IS_DESKTOP`, so none of it (or of @tauri-apps)
 * reaches the web bundle.
 */
import { invoke } from '@tauri-apps/api/core'
import { openUrl } from '@tauri-apps/plugin-opener'
import { desktopExchange, setToken } from './api'
import { getServerUrl } from './platform'

/** Sign in through the user's own browser (SPEC.md "Desktop app sign-in").
 * The Rust side runs the loopback listener and hands back the code; trading
 * it for a token is an ordinary API call, so it stays here with the rest. */
export async function browserSignIn() {
  const { code, state } = await invoke('start_login', { serverUrl: getServerUrl() })
  const { token, user } = await desktopExchange({ code, state })
  setToken(token)
  return user
}

export const openExternal = (url) => openUrl(url)

/** Links to other sites open in the system browser; the webview itself
 * must never navigate away from the app. */
export function installExternalLinkHandler() {
  document.addEventListener('click', (event) => {
    const link = event.target instanceof Element ? event.target.closest('a[href]') : null
    if (!link) return
    let target
    try {
      target = new URL(link.href, window.location.href)
    } catch {
      return
    }
    if (!/^https?:$/.test(target.protocol) || target.origin === window.location.origin) return
    event.preventDefault()
    openExternal(target.href)
  })
}
