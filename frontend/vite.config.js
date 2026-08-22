import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// API routes live at the top level (no /api prefix — see API.md), so the dev
// server proxies each backend prefix to uvicorn on :8000. /media serves the
// self-hosted recipe images.
const apiPrefixes = [
  '/health',
  '/auth',
  '/recipes',
  '/categories',
  '/tags',
  '/ingredients',
  '/imports',
  '/media',
]

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
  },
  server: {
    proxy: Object.fromEntries(apiPrefixes.map((p) => [p, 'http://localhost:8000'])),
  },
  test: {
    environment: 'jsdom',
    // Testing Library only registers its automatic between-test unmount when
    // a global afterEach exists. Without this, each render stacks on top of
    // the last and single-element queries start finding several.
    globals: true,
  },
})
