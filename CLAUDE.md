# Recipe Flood — Claude Instructions

## Project
A household recipe collection: recipes (imported from an old blog, typed in, pasted or
photographed and structured by Claude), a pantry of ingredients with prices and unit
conversions, cooking lists, and one permanent shopping list that two-way syncs with a Google
Sheet. FastAPI + SQLModel + Alembic, React + Vite + Tailwind; one uvicorn process serves the
API and the built SPA from `backend/static/`. There is also a Tauri desktop app (`desktop/`)
built from the same frontend. `SPEC.md` is the product spec; `ARCHITECTURE.md`,
`DATA_MODEL.md`, `API.md`, `DEPLOYMENT.md` and `DEVELOPMENT.md` are the reference docs.

## Running the app
```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
AUTH_ENABLED=false .venv/bin/uvicorn backend.main:app --reload     # http://localhost:8000
cd frontend && npm ci && npm run dev                                # http://localhost:5173
```
`AUTH_ENABLED=false` makes everyone the local dev admin (`dev@localhost`). In a remote session the
SessionStart hook in `.claude/` creates the venv, installs both sets of dependencies, runs the
migrations and exports `AUTH_ENABLED=false`.

## Tests (run both before every push)
```bash
.venv/bin/python -m pytest -q                         # backend, in-memory SQLite
TEST_DATABASE_URL=postgresql+psycopg2://…/db .venv/bin/python -m pytest -q   # the same suite on Postgres
cd frontend && npm run lint && npx vitest run         # eslint + vitest
```
CI also runs the suite on Postgres (`backend-postgres`), `alembic check`, a snapshot load (`scripts.load_snapshot --heuristic`), a
Postgres migration round trip, the desktop build (`desktop.yml`) and the fleet-spec check.

## Database & schema migrations
Alembic owns the schema; the models are the source of truth. Tests build the schema with
`create_all()`, so `alembic check` in CI is the drift guard.
```bash
alembic revision --autogenerate -m "add recipe.oven_temp_c"
alembic upgrade head && alembic check
```
Prod is Postgres, dev and the fast tests are SQLite. Any migration that touches a column type
or an enum-like column must be run by hand on Postgres: `upgrade head`, `downgrade base`,
`upgrade head`, `alembic check` (see "Incident rules"). Enum-like columns use
`native_enum=False`. Every `datetime` column is an instant (aware UTC, `timestamptz`).

## Frontend build
`backend/static/` is build output: gitignored, never committed. `deploy.sh --update` builds it
on every deploy after checking out the commit. The build writes `version.json`
(`frontend/scripts/write-version.js`, which fails rather than write `unknown`), and `/health`
reports `backend_sha`, `build_sha` and `frontend_sha`. After a deploy `build_sha == backend_sha`
== the deployed commit; `scripts/smoke_check.sh`, the deploy's last step, asserts it and makes
the deploy exit non-zero if anything is off.

## Git workflow
Branch from fresh `origin/main` → run both test suites → PR (non-draft) → auto-merge once CI
is green → the push to `main` deploys through the `/deploy` webhook (`DEPLOYMENT.md`) → check
`/health`'s `backend_sha` is the merge commit. After
each merge, reset your branch onto `origin/main` before the next change.

## Fleet spec — conformance is checked in CI
This app follows `hamBank/fleetSpec`. `.fleet-spec.yml` lists the deviations (rule, reason,
`until` date). CI's `fleet-spec` job fails on a new MUST violation, an expired deviation, or a
stale one (the rule passes now, so delete the entry in the PR that fixed it).

## Incident rules
Each rule names what broke, when, and why it wasn't caught.

- **Round-trip every migration on real Postgres, all the way to `base`.** 2026-08-23: the
  baseline `downgrade()` dropped the tables but not the Postgres enum types they created, so
  a full teardown left five orphaned types and the next `CREATE TYPE` collided. Migrations
  had only been checked one step at a time, which never reached the baseline. CI's
  `migrations-postgres` job now runs the full round trip.
- **Run the whole suite on Postgres, not only the migrations.** 2026-11-05: deleting a recipe
  that was on a cooking list failed in production with a foreign-key violation, because SQLite
  (the fast tests) doesn't enforce foreign keys by default. Found by the first run of CI's
  `backend-postgres` job. Deleting a row means deleting or re-pointing everything that
  references it.
- **Enum-like columns are `native_enum=False`.** Widening a native enum needs
  `ALTER TYPE ... ADD VALUE` on Postgres but a table rebuild on SQLite, so the two dialects'
  migrations diverged. A plain string column plus a Python enum makes adding a value a
  one-line change with no migration.
- **Know what a plain `timestamp` column holds before converting it.** 2026-11-05: psycopg2
  sends an aware datetime as `timestamptz`, and Postgres stores it in a `timestamp` column as
  wall-clock time in the *session's* TimeZone, not UTC. The `timestamptz` migration
  (`e8c3f1a7b2d5`) therefore relies on Postgres's own cast and has no `USING ... AT TIME
  ZONE 'UTC'`, which would have shifted every value on a non-UTC server. This was found by
  testing with the server zone set to Australia/Melbourne; on a UTC test server the two are
  indistinguishable.
- **Test offline behaviour in a real browser against a production build.** 2026-08-25: the
  app's bootstrap treated any `getMe()` failure, including no network, as an expired token,
  signing users out when they lost signal, and a cold offline load never reached the router.
  Found only with Playwright `setOffline(true)` against a built, single-origin app (dev mode
  registers no service worker). A network failure has no `.status`; only a real `401` signs out.
- **The app shell is `Vary: Accept` and `Cache-Control: no-store`.** 2026-08-24: a recipe's page
  and `GET /recipes/{slug}` share a URL, and the browser served a cached HTML shell back to the
  app's own `fetch()`. Real navigations (`Accept: text/html`) get the shell; nothing else does.
- **`deploy.sh` stops loudly.** 2026-08-23: under `set -e` an early failure stopped the deploy
  before the vhost was written, and nothing in the log said why. `set -Eeuo pipefail` plus an
  ERR trap now logs the failing line to `/var/log/recipeFlood-deploy.log` (`-E` so it fires
  inside functions).
- **Never reload Apache onto a broken config, and never overwrite a vhost certbot owns.** A
  webhook deploy reloading a bad config takes the site down with nobody watching, and copying
  the repo's vhost over certbot's would drop the http→https redirect. `deploy.sh` runs
  `apache2ctl configtest` first and leaves an existing vhost alone.
- **The app never deletes a Google Sheet row.** 2026-10-24: removing an item (and "Clear ticked"
  at the end of a shop) deleted the whole sheet row, taking the household's location formula in
  G and any spare data with it. Removal now empties only A, B and I, and only rows whose column
  I matches the item's id, re-read fresh. Never write column G.
- **Send a row's text, status and strikethrough to the sheet in one call.** 2026-10-24: a tick
  was two API calls; when the second hit Google's per-minute quota, the status said "ticked"
  but the strike never appeared. Writes are one `batchUpdate`, retried on 429/5xx.
- **Ask Claude for structured output, not "reply with JSON".** 2026-10-22: AI import failed with
  `Expecting ',' delimiter` on a long recipe. Import now uses `output_config.format` with a JSON
  schema (keep it inside the API's limits on optional and union-typed fields; a test enforces
  the union count).
- **Scheduled jobs are systemd timers, and a backup never replaces the last good one with a
  failure.** Until 2026-11-05 the backups were cron lines: `pg_dump | gzip` exits 0 even when
  `pg_dump` fails, writing an empty `.gz` over a good one, and a failed cron job was invisible.
  The timers' services use `pipefail` and a temporary file, and the smoke check fails a deploy
  when a timer's last `Result` isn't `success`. In unit files, `%%` and `$$` mean `%` and `$`.
- **Weigh count units by the unit, never by matching the ingredient's name.** 2026-10-09:
  "6 sprigs lemon thyme" came out at 600 g because the count fell back to the piece weight of
  "lemon", found inside the name. A sprig is a fixed 4 g; a bunch or can uses the pantry item's
  own piece weight or stays unknown.
