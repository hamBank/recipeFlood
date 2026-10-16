# Plan 2 — Backend: CORS and desktop sign-in handoff

## Goal

Let a desktop app, running on its own origin, call the API and sign a user
in, while every existing web behaviour stays unchanged:

1. **CORS** for the desktop app's origins only.
2. **A sign-in handoff.** The desktop app opens the user's normal browser
   at the website, where they sign in with Google as usual. The site then
   hands a single-use code to the desktop app over a loopback URL, and the
   app exchanges that code for a normal JWT.

This plan covers the backend endpoints plus the website page that drives
the handoff. The desktop side (opening the browser, the loopback listener)
is plan 3.

## Why this is needed (facts from the code)

- **No CORS middleware.** `backend/main.py` has none, because the SPA is
  served from the same origin. The desktop webview's origin is
  `tauri://localhost` (Linux), `http://tauri.localhost` (Windows), or
  `https://tauri.localhost` (Windows with the https scheme), so every API
  call from it is cross-origin.
- **`X-Total-Count` must be readable.** `frontend/src/api.js:48` reads it
  for paging, and a cross-origin response hides it unless it's listed in
  `Access-Control-Expose-Headers`. If it's missing, paging silently
  breaks: the total reads 0.
- **Google sign-in only works from registered origins.**
  `frontend/src/pages/LoginPage.jsx` uses Google Identity Services, which
  only works on origins registered for `GOOGLE_CLIENT_ID`. A desktop
  webview origin can't be registered, so the desktop app needs another
  route.
- **The backend issues 30-day JWTs.**
  `backend/auth.py:create_access_token` has `TOKEN_LIFETIME = 30 days`.
  The handoff just has to deliver one of those to the desktop app.

## Changes

### 1. Config (`backend/config.py`, `.env.example`)

`desktop_origins: str = "tauri://localhost,http://tauri.localhost,https://tauri.localhost"`.
It's a comma-separated list, and an empty value disables CORS entirely.
Add it to the existing inline-comment-stripping validator. Document it in
`.env.example`, with the comment on its own line, since systemd keeps
inline comments as part of the value (see DEPLOYMENT.md).

### 2. CORS (`backend/main.py`)

Use `fastapi.middleware.cors.CORSMiddleware` with:

- `allow_origins`: the parsed list. **Never `*`.**
- `allow_methods`: `["GET", "POST", "PATCH", "PUT", "DELETE"]`.
- `allow_headers`: `["Authorization", "Content-Type"]`.
- `expose_headers`: `["X-Total-Count"]`.
- `allow_credentials=False` (auth is a bearer header, not cookies).
- `max_age=600`.

Add it with `app.add_middleware` **after** the existing `@app.middleware`
definitions, so it wraps them and preflight `OPTIONS` requests are
answered before the app-shell middleware or routers see them. Check that
`prefer_app_shell_for_browser_navigation` only acts on `GET`, so it
ignores `OPTIONS`. Write the reason for the ordering in a comment.

### 3. Handoff store (`backend/desktop_handoff.py`, new)

An in-memory store of single-use codes, guarded by a `threading.Lock`.
That's the same single-uvicorn-process assumption `backend/sheet_sync.py`
already makes and documents; say so in the docstring.

- `issue(user_id: int, state: str) -> str`: makes a
  `secrets.token_urlsafe(32)` code, stores `(user_id, state, expires_at)`
  with a 120 s lifetime, purges expired entries, and returns the code.
- `redeem(code: str, state: str) -> int | None`: **pops** the code
  whatever happens, so a wrong state still burns it and the code can't be
  brute-forced. Returns the user id only if it hasn't expired and the
  state matches (`hmac.compare_digest`). Otherwise returns `None`.
- `_reset()`: a test hook.

### 4. Endpoints (`backend/routers/auth_router.py`)

- **`POST /auth/desktop-handoff`** (requires `get_current_user`).
  - Body: `{port: int, state: str}`. Validate `port` is in 1024–65535
    and `state` matches `^[A-Za-z0-9_-]{32,128}$`. Otherwise return 422.
  - Response: `{"redirect_url": "http://127.0.0.1:{port}/callback?code={code}&state={state}"}`.
  - The backend builds the URL itself, so the host is always
    `127.0.0.1`. There's no open redirect, and the code can only ever go
    to a process on the user's own machine.
- **`POST /auth/desktop-exchange`** (no auth).
  - Body: `{code: str, state: str}`.
  - Returns `401` if `redeem` gives `None`, and `403` if the user is now
    inactive.
  - Otherwise returns the same `LoginResponse` shape as `POST /auth/google`:
    `{token, user}`.

The JWT is never put in a URL. Only the short-lived, single-use code is,
and only to loopback.

### 5. Website handoff page (frontend, web build)

- `frontend/src/api.js`: add `desktopHandoff({ port, state })` and
  `desktopExchange({ code, state })`. Plan 3 calls `desktopExchange` from
  the app.
- `frontend/src/pages/DesktopLoginPage.jsx` (new), route `desktop-login`
  in `App.jsx`.
  - Read `port` and `state` from the query string. If either is missing or
    malformed (same rules as the backend), show a plain error.
  - **Not signed in:** render `<LoginPage config={config} onSignedIn={setUser} embedded />`
    from the session context. After sign-in the page re-renders signed in.
    Check how this interacts with the private-site gate at `App.jsx:123`:
    the URL must survive sign-in in both public and private modes.
  - **Signed in:** show "Sign in to the Recipe Flood desktop app as
    **{email}**?" with **Continue** and **Cancel**. This explicit click is
    what stops a crafted link from silently minting a code.
    - **Continue** → `desktopHandoff` → `window.location.assign(redirect_url)`.
      This is the one deliberate full-page navigation, to the desktop app's
      loopback listener; comment it as such.
    - **Cancel** → navigate to `/`.
  - On success the loopback page (plan 3) says "you can close this tab".
    This page just shows "Handing off to the desktop app…" while the
    redirect happens.

## Tests

- `tests/test_cors.py` (new):
  - A preflight from `tauri://localhost` and from `http://tauri.localhost`
    gets `access-control-allow-origin` echoed back.
  - A preflight from `https://evil.example` gets no allow-origin header.
  - A simple GET from an allowed origin includes
    `access-control-expose-headers` containing `X-Total-Count`.
  - With `desktop_origins=""` no CORS headers appear.
  - A same-origin request with no `Origin` header is unchanged.
  - A browser navigation, `GET` with `Accept: text/html`, still gets the
    app shell when static files exist. Mirror whatever existing test
    covers that middleware.
- `tests/test_desktop_handoff.py` (new):
  - The handoff requires auth: `401` when signed out with auth enabled.
    Use the conftest patterns; find how existing tests turn auth on.
  - Bad port (80, 70000) and bad state (too short, illegal characters)
    return `422`.
  - The redirect URL's host is exactly `127.0.0.1` and carries the code
    and state.
  - Exchange with the right code and state returns a token that works on
    `GET /auth/me`.
  - A code is single-use: the second exchange gets `401`.
  - A wrong state gets `401` *and* burns the code: retrying with the right
    state also gets `401`.
  - An expired code gets `401`. Monkeypatch the clock or the TTL rather
    than sleeping.
  - A deactivated user gets `403`.
- `frontend/src/pages/DesktopLoginPage.test.jsx` (new):
  - Malformed params show an error.
  - Signed out renders the login.
  - Signed in shows the email plus Continue and Cancel.
  - Continue calls `desktopHandoff` and then `window.location.assign`
    with the returned URL (mock both).
  - Cancel navigates home.

## Verify

The baseline from the README, plus:

```bash
source .venv/bin/activate && rm -f recipeflood.db*
python -m pytest -q tests/test_cors.py tests/test_desktop_handoff.py
# manual end-to-end against a local server
AUTH_ENABLED=false uvicorn backend.main:app --port 8000 &
sleep 2
curl -si -X OPTIONS http://localhost:8000/recipes \
  -H 'Origin: tauri://localhost' -H 'Access-Control-Request-Method: GET' | grep -i access-control
STATE=$(python -c "import secrets;print(secrets.token_urlsafe(32))")
curl -s -X POST localhost:8000/auth/desktop-handoff -H 'Content-Type: application/json' \
  -d "{\"port\": 53123, \"state\": \"$STATE\"}"
# take the code from redirect_url, then:
#   curl -s -X POST localhost:8000/auth/desktop-exchange -H 'Content-Type: application/json' \
#     -d "{\"code\": \"<code>\", \"state\": \"$STATE\"}"     -> {token, user}
kill %1; rm -f recipeflood.db*
```

## Acceptance

- [ ] CORS covers the configured desktop origins only, and `X-Total-Count`
      is exposed.
- [ ] The JWT never appears in any URL. The code is single-use, expires
      in 120 s, is bound to `state`, and is burned on a mismatch.
- [ ] The handoff always redirects to `127.0.0.1`, and only after an
      explicit Continue click by a signed-in user.
- [ ] Web sign-in, browsing and every existing test are unchanged.
- [ ] Docs:
  - API.md: both endpoints.
  - SPEC.md: a short "Desktop app sign-in" section with the flow and why
    each guard exists.
  - DEPLOYMENT.md and `.env.example`: `DESKTOP_ORIGINS`.

## Out of scope

Anything under `desktop/`; the server-URL settings screen; changing
`POST /auth/google` or the web login page beyond reuse.
