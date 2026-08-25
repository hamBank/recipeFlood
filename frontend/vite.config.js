import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

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
  '/cook-lists',
  '/shopping',
  '/media',
]

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    // Installability (manifest + home-screen icon) and app-shell caching
    // only — precache the built JS/CSS/HTML so a reload works with no
    // network. Deliberately *not* used for API data: the shopping list's
    // offline support (src/offlineQueue.js) is a hand-rolled localStorage
    // outbox instead, so it stays visible and debuggable rather than
    // living inside a Workbox runtime-caching rule.
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg'],
      manifest: {
        name: 'Recipe Flood',
        short_name: 'Recipe Flood',
        description: 'A self-hosted family recipe manager',
        theme_color: '#c2410c',
        background_color: '#faf7f2',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: '/favicon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' },
        ],
      },
    }),
  ],
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
