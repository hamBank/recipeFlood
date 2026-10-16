import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, HashRouter } from 'react-router-dom'
import { registerSW } from 'virtual:pwa-register'
import App from './App.jsx'
import { IS_DESKTOP } from './platform'
import { initTheme } from './themes'
import './index.css'

initTheme()

// Links to other sites (a recipe's source) open in the system browser, not in
// the app window, and a file dropped outside a photo drop zone must not
// replace the app with the image. Dynamic, so none of the Tauri code is in the
// web bundle.
if (IS_DESKTOP) {
  import('./desktop').then((m) => {
    m.installExternalLinkHandler()
    m.installDropGuard()
  })
}

// The desktop bundle loads from the app's own origin with no server-side
// fallback to index.html, so routes live in the URL hash there.
const Router = IS_DESKTOP ? HashRouter : BrowserRouter

// App-shell only (see vite.config.js) — a no-op where the browser has no
// serviceWorker (older browsers, and jsdom under test), and the PWA plugin is
// disabled for the desktop build, where an installed app needs no caching.
registerSW({ immediate: true })

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Router>
      <App />
    </Router>
  </StrictMode>,
)
