# Plan 3 — Tauri shell

## Goal

A runnable Recipe Flood desktop app for Windows and Linux. It covers:

- a new `desktop/` Tauri 2 project that loads the `build:desktop` bundle
  from plan 1;
- sign-in through the user's browser, using the handoff from plan 2;
- a desktop-only Settings screen to pick the server;
- external links opening in the system browser;
- remembered window size and position.

Packaging, CI and releases are plan 4. This plan stops at "it builds and
runs".

## Before you start

Plans 1 and 2 are merged. Read `frontend/src/platform.js`, the
`desktop-login` page, `POST /auth/desktop-exchange`, and SPEC.md "Desktop
app sign-in".

The Linux build needs system packages. In this cloud container,
`apt-get update` first:

```bash
apt-get update && apt-get install -y libwebkit2gtk-4.1-dev build-essential \
  libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev
```

Rust is already installed (`cargo`, `rustc`). crates.io and npm are
reachable. GitHub release downloads are **not**, so don't rely on any tool
that fetches from `github.com/.../releases`.

## Layout

```
desktop/
  package.json          # devDependency @tauri-apps/cli ^2; scripts: tauri, dev, build
  package-lock.json
  dist/                 # gitignored; written by `npm --prefix ../frontend run build:desktop`
  src-tauri/
    Cargo.toml  Cargo.lock  build.rs  tauri.conf.json
    capabilities/default.json
    icons/              # generated with `npx tauri icon ../frontend/public/favicon.svg`
    src/main.rs  src/lib.rs  src/login.rs
```

Add `desktop/node_modules/` (already covered by `node_modules/`) and
`desktop/src-tauri/target/` to `.gitignore`. Commit `Cargo.lock` (it's an
application, not a library).

## Changes

### 1. `tauri.conf.json`

- `productName` "Recipe Flood", `identifier` `club.hups.recipeflood`,
  `version` `0.1.0`. Keep this, `desktop/package.json` and `Cargo.toml` in
  step; plan 4 checks that they match.
- **Build settings:**
  - `frontendDist: "../dist"`.
  - `devUrl: "http://localhost:5173"`.
  - `beforeDevCommand: "npm --prefix ../frontend run dev -- --mode desktop"`.
  - `beforeBuildCommand: "npm --prefix ../frontend run build:desktop"`.
  - Confirm which directory Tauri runs these commands from, and fix the
    paths if needed.
- **One window:**
  - title "Recipe Flood", 1200×800, min 800×600.
  - `dragDropEnabled: true` for now. Plan 6 flips it.
- **CSP** that allows the configurable server:
  - `default-src 'self'`
  - `connect-src 'self' https: http://localhost:* http://127.0.0.1:*`
  - `img-src 'self' https: data: blob: http://localhost:* http://127.0.0.1:*`
  - `style-src 'self' 'unsafe-inline'`
  - Tauri adds its own `ipc:` entries, so check the built app actually
    loads and calls APIs with it on.
- **Bundle targets:** `["deb", "appimage", "nsis", "msi"]`. Plan 4 builds
  them; this plan only needs `--no-bundle` or `deb` to work.

### 2. Rust (`src/lib.rs`, `src/login.rs`)

**Plugins:** `tauri-plugin-opener` and `tauri-plugin-window-state`.
Capabilities grant only what's used: core defaults, `opener:allow-open-url`
for `https://*` and `http://*`, and the window-state defaults.

**`login.rs`: the loopback listener.** Use `tiny_http`, or plain
`std::net::TcpListener` if that's simpler. Keep the logic in pure,
testable functions:

- `validate_server_url(&str) -> Result<String, String>` uses the same
  rule as `platform.js setServerUrl`: `https://`, or `http://localhost` /
  `http://127.0.0.1` with an optional port. It strips a trailing `/`.
- `new_state() -> String` returns 32 random bytes, base64url without
  padding (43 chars). That satisfies the backend's
  `^[A-Za-z0-9_-]{32,128}$`.
- `login_url(server, port, state) -> String` builds
  `{server}/desktop-login?port={port}&state={state}`, URL-encoded.
- `parse_callback(path_and_query, expected_state) -> CallbackOutcome`
  returns one of:
  - `Code(String)` when the path is `/callback`, `code` is present and
    `state` matches (constant-time compare);
  - `WrongState`;
  - `NotCallback` for any other path, such as `/favicon.ico`.
- `wait_for_callback(listener, expected_state, deadline) -> Result<String, String>`
  handles each kind of request:
  - **Valid callback:** respond `303 See Other` with `Location: /done`,
    so the code doesn't linger in the address bar. Then serve `/done` as
    a small HTML page, "Signed in to Recipe Flood. You can close this
    tab.", and return the code. Give up waiting for `/done` after about
    5 s.
  - **Wrong state:** respond 400 with a short message and keep waiting.
  - **Anything else:** 404.
  - **Deadline passed:** return `Err("Timed out waiting for sign-in")`.
- `#[tauri::command] async fn start_login(app, server_url) -> Result<Callback { code, state }, String>`:
  1. Validate the server URL.
  2. Bind `127.0.0.1:0` and read the port back.
  3. Make the state.
  4. Open `login_url` in the default browser through the opener plugin.
  5. Run `wait_for_callback` on a blocking task with a 5-minute deadline.
  6. Return `{code, state}`. The frontend does the exchange, because that's
     an ordinary API call and stays in one place (`api.js`).

### 3. Frontend, desktop-only code

Load all of this through dynamic `import()` behind `IS_DESKTOP`, so
none of it reaches the web bundle. Verify that with a grep of
`backend/static` after `npm run build`.

- **Dependencies:** add `@tauri-apps/api` ^2 and
  `@tauri-apps/plugin-opener` ^2 to `frontend/package.json`.
- **`frontend/src/desktop.js` (new):**
  - `browserSignIn()`: `invoke('start_login', { serverUrl: getServerUrl() })`,
    then `desktopExchange({ code, state })`, then `setToken(token)`.
    Returns the user.
  - `openExternal(url)`: the opener's `openUrl`.
  - `installExternalLinkHandler()`: one document-level click listener.
    For an `<a>` whose resolved `href` is `http(s)` on another origin,
    call `preventDefault()` and `openExternal(href)`. This covers the
    recipe source link (`RecipeDetailPage.jsx:~405`, `target="_blank"`)
    and any others.
- **`LoginPage.jsx`:** when `IS_DESKTOP`, render a **"Sign in with your
  browser"** button instead of the Google Identity Services script and
  button.
  - Below it, explain that "Your browser will open Recipe Flood; sign in
    there and come back."
  - While waiting, show busy text: "Waiting for you to finish signing in
    in your browser…".
  - On error, show the message. On success, call `onSignedIn(user)`.
  - The web path is untouched.
- **`frontend/src/pages/SettingsPage.jsx` (new):** desktop-only route
  `settings`, with a link in the layout nav only when `IS_DESKTOP`. It has
  a **Server** field, prefilled from `getServerUrl()`, and a Save button.
  - Save is refused while the offline shopping queue (`offlineQueue.js`)
    has pending changes: "You have N unsynced shopping changes. Go back
    online and let them sync first." Replaying them against a different
    server would be wrong.
  - Otherwise Save calls `setServerUrl`, clears the token, the
    `rf_auth_config` cache (App.jsx) and the shopping cache, then reloads.
  - Show validation errors from `setServerUrl` inline.
- **`main.jsx`:** when `IS_DESKTOP`, `import('./desktop').then(m => m.installExternalLinkHandler())`.

### 4. Window state

`tauri-plugin-window-state` restores size and position. No code beyond
registering the plugin.

## Tests

- **Rust, `cargo test` in `desktop/src-tauri`:**
  - `validate_server_url`: accept and reject cases matching the JS ones.
  - `new_state` length and alphabet, and two calls differ.
  - `login_url` encoding.
  - `parse_callback`: right state, wrong state, missing code, other path.
  - `wait_for_callback` end to end on a real `127.0.0.1:0` listener,
    driven from the test thread with `std::net::TcpStream`:
    - a correct callback gets a 303 to `/done`, `/done` gets 200 HTML, and
      the function returns the code;
    - a wrong state gets 400 and the function keeps waiting;
    - a short deadline gives `Err` on timeout.
- **Vitest** (mock `./desktop` with `vi.mock`; stub `VITE_TARGET`):
  - LoginPage in desktop mode shows the browser button, not GIS; clicking
    it calls `browserSignIn` and then `onSignedIn`; an error is shown.
  - SettingsPage: Save validates; it's blocked with a non-empty queue; on
    success it clears the token, config and shopping cache.
  - The settings nav link and route are absent in web mode.
  - External link handler: a cross-origin link calls `openExternal` and
    prevents default; a same-origin or relative link is untouched.

## Verify

```bash
# web build unaffected, no tauri code in it
(cd frontend && npm run lint && npx vitest run && npm run build)
! grep -rl "__TAURI\|plugin-opener\|start_login" backend/static/assets/
# desktop
(cd desktop/src-tauri && cargo test)
(cd desktop && npm ci && npx tauri build --bundles deb)
ls desktop/src-tauri/target/release/bundle/deb/*.deb
# smoke: the app starts and stays up under a virtual display (exit 124 = killed by timeout, i.e. still running)
xvfb-run -a timeout 20 desktop/src-tauri/target/release/recipe-flood; test $? -eq 124
```

Name the binary as Cargo produces it. Then run the full baseline from the
README.

Also do a manual end-to-end against a local backend, so the CSP, CORS and
URL prefixing are exercised for real:

- Run the backend: `AUTH_ENABLED=false uvicorn backend.main:app --port 8000`.
- Point the app at it, either through a desktop build with
  `VITE_DEFAULT_SERVER_URL=http://localhost:8000` or through the Settings
  screen.
- Run under `xvfb-run` and check that the recipe list request reaches the
  backend (watch uvicorn's log) and returns 200 with the
  `Origin: tauri://localhost` header.

The browser sign-in can't be completed headless here. Report that it
wasn't exercised; the Rust tests cover the loopback half and plan 2's
tests cover the server half.

## Acceptance

- [ ] `desktop/` builds a working Linux binary and `.deb` here. The Windows
      build is plan 4's CI.
- [ ] The app loads the recipe list from the configured server, with
      images, paging (the total isn't 0) and the shopping list working.
- [ ] Browser sign-in implemented as specified, with state checked and a
      5-minute timeout. The code never appears in the app's own logs.
- [ ] Settings changes the server safely: blocked with unsynced changes,
      and clears the token and caches.
- [ ] External links open in the system browser.
- [ ] The web bundle contains no Tauri code, and every web test passes
      unchanged.
- [ ] Docs:
  - DEVELOPMENT.md "Desktop app": prerequisites per OS (Rust; on Linux the
    apt packages above; on Windows the MSVC build tools; WebView2 already
    ships with Windows 10/11), `npm run dev`, building, and running the
    Rust tests.
  - ARCHITECTURE.md: the repo layout entry for `desktop/`.

## Out of scope

Installers beyond a local `.deb`, CI, releases, auto-update (plans 4–5),
drag-and-drop (plan 6), tray, hotkeys, notifications, autostart, and
keychain token storage. The token stays in the webview's localStorage,
like the website.
