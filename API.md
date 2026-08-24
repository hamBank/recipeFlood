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

## Tags

One taxonomy. A tag flagged `is_section` is site navigation; everything
else is a free-form label. There is no `/categories`.

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/tags` | public | All tags with `recipe_count`, sections first |
| GET | `/tags?section=true` | public | **The navigation**, in `sort_order`. Empty sections included, so an editor can still file into one |
| GET | `/tags?section=false&min_count=2` | public | Free-form tags, most-used first. `min_count` drops the long tail — over half the imported labels are used exactly once |
| GET | `/tags/{slug\|id}` | public | |
| POST | `/tags` | admin | `{name, slug?, is_section?, sort_order?, description?}` |
| PATCH | `/tags/{key}` | admin | Rename, or **promote/demote** with `is_section`. Promotion moves every recipe already carrying the tag into the nav — no recipe is modified |
| DELETE | `/tags/{key}` | admin | Also removes its links |

`min_count` never hides a section — the nav must survive filtering.

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
| `tag` | Tag slug. Sections are tags, so this filters both |
| `ingredient` | Master ingredient slug — "what can I make with tahini?" |
| `needs_review` | bool |
| `include_unpublished` | bool; ignored for guests |
| `include_empty` | bool; include recipes with no ingredients, no method and no notes — hidden by default |
| `not_prepared_days` | Only recipes not cooked in this many days |
| `same_season` | bool; only recipes cooked before in roughly this ~3-month window of the year, going back 4 years — "what did we make around now, in past years?" |
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

`tags` on write is one flat list of every label, sections included — a
recipe does not say which of its tags are sections, because that is a
property of the tag. On read you get back `tags` (all of them) plus
`sections` (the navigation subset, in nav order).

Saving an edit clears `needs_review`. Renaming reallocates the slug; any
other edit leaves it alone so links keep working.

`POST /recipes/{key}/image` takes multipart `file`; JPEG/PNG/WebP/GIF up to
8MB. The extension comes from the declared content type, never the
filename.

## Ingredients (the pantry)

**Every route here requires a signed-in user** — this is where cost lives.

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/ingredients` | user | `q`, `source`, `is_food`, `missing_cost`, `missing_nutrition`, `sort` (`name`/`cost`/`usage`/`updated`), `limit`, `offset`; sets `X-Total-Count` |
| GET | `/ingredients/{slug\|id}` | user | |
| POST | `/ingredients` | user | 409 if the name already matches an existing row |
| PATCH | `/ingredients/{key}` | user | Changing density or grams-per-piece **re-derives the weight of every recipe line using it**, except `explicit` ones |
| POST | `/ingredients/{keep}/merge/{other}` | admin | Repoints recipe lines, inherits missing data, keeps the old name as an alias, deletes `other` |
| DELETE | `/ingredients/{key}` | admin | Unlinks recipe lines rather than damaging them |

Reads include derived `cost_per_gram`, `cost_per_ml`, `package_cost_cents`,
`has_nutrition` and `recipe_count`, plus provenance: `nutrition_source` /
`nutrition_updated_at` and `cost_source` / `cost_updated_at` — a label
("AFCD (<matched food>)", "AI estimate (Claude)", "manual", a packet) and
a timestamp for each, filled in by `scripts/enrich_pantry.py` or by a
human editing the row. `PATCH` stamps `cost_updated_at` (and defaults
`cost_source` to `"manual"`) whenever either `cost_per_kg_cents` or
`cost_per_litre_cents` actually changes.

`measure_kind` (`weight` default, or `volume`) decides which pair of
fields — `package_size_grams`/`cost_per_kg_cents` or
`package_size_ml`/`cost_per_litre_cents` — is the one actually used for
costing and shopping-list pricing; the other pair is accepted and stored
but ignored. Most liquids (milk, stock, oil, wine) want `volume`, since
that is how they are sold and shelf-priced.

`is_food=false` lists the non-recipe items a shopping-list import flagged —
batteries, shampoo, cat litter. `source` accepts any of the fourteen
`IngredientSource` values; anything else is a 422.

## Cooking lists

Signed-in only, every endpoint.

| Method | Path | Notes |
|---|---|---|
| GET | `/cook-lists` | newest date first; `since`, `until`, `exclude_imported` (skips cooking-history import batches — see SPEC.md), `include_completed` (bool; completed lists are hidden by default — see SPEC.md), `limit`, `offset`; `X-Total-Count` |
| POST | `/cook-lists` | `{cook_date?, description?, notes?, recipes?}` — date defaults to today |
| GET | `/cook-lists/{id}` | |
| PATCH | `/cook-lists/{id}` | `{cook_date?, description?, notes?, completed?, recipes?}`; omit `recipes` to leave membership alone, pass a list to replace it |
| DELETE | `/cook-lists/{id}` | shopping items it created stay, with `cook_list_id` cleared |
| POST | `/cook-lists/{id}/recipes` | `{recipe_id, servings?, note?}`; an existing recipe is updated, not duplicated |
| DELETE | `/cook-lists/{id}/recipes/{recipe_id}` | |
| POST | `/cook-lists/{id}/add-to-shopping` | folds the list's ingredients into the shopping list |

Each recipe row in a read carries `scalable` and `scale_factor` alongside
`servings` and `base_servings`. `scalable: false` means the recipe has no
serving size to scale from, so `scale_factor` is 1.0 and the amounts are
the ones as written — say so rather than implying the scaling happened.

`add-to-shopping` returns `{added, merged, skipped, items}`. It is
deliberately additive and re-runnable: calling it twice adds the
ingredients twice. `skipped` lists any line with no usable name.

## The shopping list

One permanent list. Signed-in only — it carries prices.

| Method | Path | Notes |
|---|---|---|
| GET | `/shopping` | the whole list, grouped and ordered |
| POST | `/shopping` | `{name, ingredient_id?, weight_grams?, volume_ml?, quantity?, unit?, note?}` — an unmatched name is matched against the pantry |
| PATCH | `/shopping/{id}` | edit an amount, or `{is_checked}` to tick off |
| DELETE | `/shopping/{id}` | |
| POST | `/shopping/clear-checked` | deletes only the ticked items |
| POST | `/shopping/uncheck-all` | unticks everything — the undo for clearing |

Each item carries `amount_text` (server-rendered — "450 g", "1.2 l", "1
bunch") and, for a linked ingredient, `cost_cents` priced from whichever
of `weight_grams`/`volume_ml` the ingredient's `measure_kind` says to use.
`GET` returns `{items, shops, total_count, checked_count, total_cents,
priced_fraction}`. `shops` is in walking order and each item carries its
own `shop`, so a client renders the grouping without deciding the order.
`priced_fraction` is the share of *unticked* items that had a price —
the same honesty rule as `RecipeCost.known_fraction`: a total built from
half the list is a floor, not an answer.

Each item also carries `amount_text` (rendered server-side, so "450 g" and
"1.2 kg" are decided in one place) and `contributions`, the per-recipe
breakdown of a merged line. Editing an amount via `PATCH` clears
`contributions`.

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
