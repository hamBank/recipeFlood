# Plan 1 — Frontend portability

## Goal

Make the existing React frontend buildable in a second **desktop** mode
that talks to a remote server, without changing anything about the web
build. After this plan, `npm run build` produces exactly the web app it
does today, and a new `npm run build:desktop` produces a bundle in
`desktop/dist/` that a Tauri shell (plan 3) can load from its own origin.

No Tauri, Rust or backend changes in this plan.

## Why this is needed (facts from the code)

The web app is served by the backend from the same origin, so everything
uses root-relative URLs. Inside a desktop webview the page's origin is the
app itself (`tauri://localhost` on Linux, `http://tauri.localhost` on
Windows), so each of these would point at nothing:

- `frontend/src/api.js` — `apiFetch` (line ~33), `apiFetchPaged` (~44) and
  `apiUpload` (~53) call `fetch(path)` with paths like `/recipes`.
- Images: `frontend/src/components/RecipeCard.jsx:43` and
  `frontend/src/pages/RecipeDetailPage.jsx:203` build
  ``src={`/media/${recipe.image_path}`}``.
- Full-page navigations that bypass the router (they'd reload the
  bundle, and under a hash router they'd go to the wrong place):
  - `frontend/src/pages/ImportPage.jsx:59` — `<a href="/new">`
  - `frontend/src/pages/CookListsPage.jsx:53` —
    ``window.location.assign(`/cooking/${created.id}`)``
- `frontend/src/main.jsx` uses `BrowserRouter` (needs server-side
  fallback to index.html, which a desktop bundle doesn't have) and
  registers the PWA service worker (`registerSW`), which is pointless in
  an installed app.
- `frontend/vite.config.js` always builds to `../backend/static` with the
  PWA plugin on.

## Changes

### 1. `frontend/src/platform.js` (new)

The single place that knows which target the bundle was built for and
where the server is.

- `IS_DESKTOP` — `import.meta.env.VITE_TARGET === 'desktop'`.
- `DEFAULT_SERVER_URL` — `import.meta.env.VITE_DEFAULT_SERVER_URL` (set
  only for desktop builds).
- `getServerUrl()` — web: always `''` (same origin, so every URL stays
  exactly as it is today). Desktop: the URL saved under localStorage key
  `rf_server_url`, else `DEFAULT_SERVER_URL`; trailing slash stripped.
  Wrap localStorage access in try/catch like `offlineQueue.js` does.
- `setServerUrl(url)` — desktop only; normalises (trim, strip trailing
  `/`), validates (`https://…`, or `http://localhost[:port]` /
  `http://127.0.0.1[:port]` for development; anything else throws), and
  saves it. Plan 3 adds the settings screen that calls this; it lives
  here so the rule is in one place.
- `apiUrl(path)` — `getServerUrl() + path`. Path must start with `/`.
- `mediaUrl(imagePath)` — `apiUrl(`/media/${imagePath}`)`.

### 2. `frontend/src/api.js`

Route the three `fetch` calls through `apiUrl(path)`. Nothing else in
the file changes; the exported functions keep their signatures.

### 3. Images

`RecipeCard.jsx` and `RecipeDetailPage.jsx` use `mediaUrl(recipe.image_path)`.
Grep for any other `/media/` string in `frontend/src` (excluding tests)
and convert it too.

### 4. Router-only navigation

- `ImportPage.jsx`: `<a href="/new">` → React Router `<Link to="/new">`,
  same classes.
- `CookListsPage.jsx`: `window.location.assign(...)` → `useNavigate()`.
  Check why it did a full reload (read the surrounding code and its
  test); if the reload was deliberate (e.g. to refresh state), keep that
  effect by other means and explain it in a comment. Update its test if
  it asserted `window.location.assign`.
- Grep `frontend/src` for any other `href="/`, `location.href`,
  `location.assign` or `location.replace` and handle them the same way.
  External links (`https://…`, `target="_blank"`) are left alone here —
  plan 3 handles opening them in the system browser.

### 5. `frontend/src/main.jsx`

- `const Router = IS_DESKTOP ? HashRouter : BrowserRouter`.
- Only register the service worker when `!IS_DESKTOP`. Prefer keeping the
  static `virtual:pwa-register` import working with the plugin's
  `disable` option (step 6). If the virtual module isn't provided while
  disabled, switch to `if (!IS_DESKTOP) import('virtual:pwa-register').then(...)`
  — either way, verify the web build still includes a service worker and
  the desktop build doesn't.

### 6. `frontend/vite.config.js`

Convert to the function form `defineConfig(({ mode }) => ...)` with
`const desktop = mode === 'desktop'`:

- `build.outDir`: `desktop ? '../desktop/dist' : '../backend/static'`
  (`emptyOutDir: true` either way).
- `base`: `'./'` for desktop (assets load relative to the app's own
  origin), unchanged (default `/`) for web.
- `VitePWA({ ..., disable: desktop })`.
- Everything else (proxy, test config) unchanged.

### 7. Build scripts and env

- `frontend/.env.desktop` (committed, no secrets):
  `VITE_TARGET=desktop` and
  `VITE_DEFAULT_SERVER_URL=https://recipeflood.hups.club`.
- `frontend/package.json`: add
  `"build:desktop": "node scripts/write-version.js && vite build --mode desktop"`.
- Add `desktop/dist/` to the root `.gitignore`. Don't create anything
  else under `desktop/`. That's plan 3.

## Tests

- `frontend/src/platform.test.js` (new). Use `vi.stubEnv` to cover both
  targets:
  - web: `getServerUrl()` is `''`, `apiUrl('/recipes')` is `'/recipes'`.
  - desktop: the default applies when nothing is saved, and a saved URL wins.
  - A trailing slash is stripped.
  - `setServerUrl` accepts `https://x` and `http://localhost:8000`, and rejects
    `http://example.com`, `ftp://…` and an empty string.
  - `mediaUrl` composes correctly in both modes.
  - A localStorage that throws doesn't crash `getServerUrl`.
- `frontend/src/api.test.js`: add one test per fetch helper, asserting that
  in desktop mode the URL passed to `fetch` carries the server prefix.
  Existing assertions on relative paths must keep passing untouched,
  because they run in web mode.
- `RecipeCard` and `RecipeDetailPage` tests: if they assert the image
  `src`, keep that passing. Add a desktop-mode case for one of them.

## Verify

```bash
cd frontend
npm run lint
npx vitest run
npm run build && ls ../backend/static/sw.js ../backend/static/index.html
npm run build:desktop && ls ../desktop/dist/index.html && ! ls ../desktop/dist/sw.js 2>/dev/null
grep -c 'recipeflood.hups.club' ../desktop/dist/assets/*.js   # >= 1
! grep -l 'recipeflood.hups.club' ../backend/static/assets/*.js  # web bundle has no hardcoded server
grep -o 'src="[^"]*"' ../desktop/dist/index.html                # relative ./assets/... paths
cd .. && git status --short   # no backend/static or desktop/dist files staged/tracked
```

Then run the full baseline from the README. The backend is untouched, but
its suite still runs.

## Acceptance

- [ ] The web build is byte-for-byte equivalent in behaviour: same output
      dir, service worker present, relative API paths, BrowserRouter.
- [ ] The desktop build is in `desktop/dist/`, with no service worker,
      HashRouter, `./` asset base, and API, image and upload URLs prefixed
      with the server URL.
- [ ] No full-page navigations to app routes remain in `frontend/src`.
- [ ] All existing tests pass, and the new tests cover both modes.
- [ ] DEVELOPMENT.md has a short "Desktop build (frontend side)" note:
      `npm run build:desktop`, `.env.desktop`, and what `platform.js` is
      for.

## Out of scope

Tauri, Rust and `desktop/` beyond `dist/`; the sign-in flow; CORS; the
server-URL settings UI; opening external links.
