import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { registerSW } from 'virtual:pwa-register'
import App from './App.jsx'
import { initTheme } from './themes'
import './index.css'

initTheme()

// App-shell only (see vite.config.js) — a no-op where the browser has no
// serviceWorker (older browsers, and jsdom under test).
registerSW({ immediate: true })

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
