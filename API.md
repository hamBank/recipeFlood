# Recipe Flood — API

All routes are top-level (no `/api` prefix) so the SPA and the API share an
origin. `vite.config.js` proxies each prefix to uvicorn in development.

Auth is a bearer JWT: `Authorization: Bearer <token>` from `POST /auth/google`.

**Three access levels**, enforced by dependencies in
`backend/permissions.py`:

- `allow_public_read` — anonymous allowed (yields `User | None`)
- `require_user_role` — any signed-in user
- `require_admin_role` — admins only

## System

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/health` | public | `{status, backend_version, frontend_version, frontend_built_at}` |
| POST | `/deploy` | HMAC | GitHub push webhook; `X-Hub-Signature-256`, only `refs/heads/main` acts |

## Auth

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/auth/config` | public | `{auth_enabled, google_client_id, public_read, currency_symbol, units_system}` |
| POST | `/auth/google` | public | Body `{credential}` → `{token, user}` |
| GET | `/auth/me` | user | The signed-in user |

## Users

| Method | Path | Access |
|---|---|---|
| GET | `/users` | admin |
| POST | `/users/invite` | admin |
| PATCH | `/users/{id}` | admin |

An admin cannot demote or deactivate themselves.

## Taxonomy

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/categories` | public | With `recipe_count` per category |
| POST | `/categories` | admin | |
| GET | `/tags?min_count=1` | public | Sorted by usage, descending |
| DELETE | `/tags/{id}` | admin | Also removes its links |

## Recipes

| Method | Path | Access |
|---|---|---|
| GET | `/recipes` | public |
| GET | `/recipes/{slug\|id}` | public |
| POST | `/recipes` | user |
| PATCH | `/recipes/{slug\|id}` | user |
| DELETE | `/recipes/{slug\|id}` | admin |
| POST | `/recipes/{key}/prepared` | user |
| DELETE | `/recipes/{key}/prepared/{id}` | user |
| POST | `/recipes/{key}/image` | user |

### `GET /recipes` query parameters

| Param | Notes |
|---|---|
| `q` | Free text over title and description |
| `category` | Category slug |
| `tag` | Tag slug |
| `ingredient` | Master ingredient slug — "what can I make with tahini?" |
| `needs_review` | bool |
| `include_unpublished` | bool; ignored for guests |
| `not_prepared_days` | Only recipes not cooked in this many days |
| `sort` | `added` (default) / `title` / `last_prepared` / `total_time` |
| `order` | `asc` / `desc` |
| `limit` (≤200), `offset` | Pagination |

Responds with `RecipeSummary[]` and an **`X-Total-Count`** header.

### Visibility rules

- A guest gets `cost: null` and `cost_cents: null` on every ingredient.
  A signed-in caller gets both. Nutrition is returned to everyone.
- Unpublished recipes are excluded from listings and 404 on fetch for
  guests.
- With `PUBLIC_READ=false`, every read returns 401 without a token.

### Write semantics

`PATCH` applies only the keys present in the body. `tags`, `ingredients`
and `steps` are **replaced wholesale** when sent and left untouched when
omitted — sending `[]` clears them.

Saving an edit clears `needs_review`. Renaming reallocates the slug; any
other edit leaves it alone so links keep working.

`POST /recipes/{key}/image` takes multipart `file`; JPEG/PNG/WebP/GIF up to
8MB. The extension comes from the declared content type, never the
filename.

## Ingredients (the pantry)

**Every route here requires a signed-in user** — this is where cost lives.

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/ingredients` | user | `q`, `source`, `missing_cost`, `missing_nutrition`, `sort` (`name`/`cost`/`usage`/`updated`), `limit`, `offset`; sets `X-Total-Count` |
| GET | `/ingredients/{slug\|id}` | user | |
| POST | `/ingredients` | user | 409 if the name already matches an existing row |
| PATCH | `/ingredients/{key}` | user | Changing density or grams-per-piece **re-derives the weight of every recipe line using it**, except `explicit` ones |
| POST | `/ingredients/{keep}/merge/{other}` | admin | Repoints recipe lines, inherits missing data, keeps the old name as an alias, deletes `other` |
| DELETE | `/ingredients/{key}` | admin | Unlinks recipe lines rather than damaging them |

Reads include derived `cost_per_gram`, `package_cost_cents`,
`has_nutrition` and `recipe_count`.

## AI import

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/imports/config` | user | `{ai_available, model}` |
| POST | `/imports/paste` | user | `{text, title_hint?}` |
| POST | `/imports/image` | user | multipart `file`, `title_hint?` |

Both return a **draft**, not a saved recipe: the same shape `POST /recipes`
accepts, plus `confidence` (0–1) and `uncertain` (a list of strings). 503
when `ANTHROPIC_API_KEY` is unset; 502 if the response can't be parsed.

## Media

`GET /media/{path}` serves recipe photos from `UPLOAD_DIR`. Public.
