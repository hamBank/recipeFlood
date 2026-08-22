# Recipe Flood — Architecture & Reference

> Snapshot for re-loading context in future sessions. Last updated: 2026-08-22.
>
> Companion docs: [SPEC.md](SPEC.md) (product spec), [DATA_MODEL.md](DATA_MODEL.md)
> (tables & schemas), [API.md](API.md) (endpoints), [DEVELOPMENT.md](DEVELOPMENT.md)
> (local dev workflow + the blog import), [DEPLOYMENT.md](DEPLOYMENT.md) (server & deploy).

## Overview

A recipe hub. A FastAPI + SQL backend serves a REST API **and** the compiled
React SPA from the same origin — the same shape as its sibling apps
[pocketMoney](https://github.com/hamBank/pocketMoney) and travelCompantion.

Recipes are **publicly readable**; signing in (Google, allowlisted) is
needed to add or edit anything, to record that you cooked something, and to
see **cost** figures. Costs are the one thing that is never public.

Three things distinguish it from a plain CRUD app:

1. **A master ingredient list.** Price, density and per-100g nutrition live
   once per pantry item. Every recipe that uses that ingredient picks them
   up, so filling in "plain flour" improves 78 baking recipes at once.
2. **Automatic weight conversion.** Recipes are written in cups and spoons;
   costs and nutrition need grams. `backend/units.py` converts, and records
   *how* it converted, so an estimate is never mistaken for a measurement.
   Measures are **Australian** — 250ml cup, **20ml tablespoon**.
3. **A reproducible import pipeline.** 321 posts scraped from a Blogger
   site, structured by Claude, committed as a JSON snapshot, loaded
   idempotently. The collection can be rebuilt from this repo alone.
4. **One taxonomy, two roles.** Tags are the only labelling concept; a
   curated few carry `is_section` and form the navigation. Promoting a
   free tag to a section moves every recipe already carrying it, with no
   recipe row touched. See SPEC.md for why not categories, and why not
   tags alone.

- **Repo:** `https://github.com/hamBank/recipeFlood` (default branch `main`)
- **Production:** `https://recipeflood.hups.club` on `camelidcastle.hups.club`
- **Source blog:** <https://foobie-rcp.blogspot.com/> ("Recipe 'n stuff")

## Stack

- **Backend:** FastAPI + SQLModel (SQLAlchemy) + Postgres (`recipeflood`) in
  production, SQLite for local dev/testing. Schema migrations via Alembic.
- **Frontend:** React 19 + Vite + Tailwind 4 + React Router, built into
  `backend/static/`.
- **Auth:** Google OAuth for editors (JWT bearer tokens issued by the
  backend), restricted to an admin-managed allowlist. Reads are anonymous
  by default. Auth can be disabled for local dev (`AUTH_ENABLED=false`).
- **AI:** Anthropic API (`backend/ai_import.py`) for the blog import and
  the paste/photo import endpoints. Optional — everything else works
  without a key.
- **Money:** integer **cents per kilogram** on ingredients (see below).
- **Server:** systemd unit `recipeflood` runs uvicorn on `127.0.0.1:8002`,
  behind an Apache vhost. Debian/Ubuntu.

## Repo layout

```
backend/
  main.py            # app factory, /health, /deploy webhook, /media mount,
                     # static SPA catch-all
  config.py          # environment settings
  database.py        # engine setup (Postgres/SQLite), session dependency
  models.py          # SQLModel tables + API schemas (see DATA_MODEL.md)
  auth.py            # JWT issue/verify, Google token verification,
                     # get_current_user AND get_optional_user
  permissions.py     # require_admin_role / require_user_role / allow_public_read
  units.py           # amount parsing + volume/count -> grams (AU measures)
  nutrition.py       # per-recipe nutrition summed from the pantry
  costing.py         # per-recipe cost summed from the pantry
  slugs.py           # URL slug allocation
  recipes_service.py # persistence + read-model assembly shared by every writer
  blog_parser.py     # deterministic fallback parser for the Blogger posts
  shopping_list.py   # rationalising a shopping-list export into pantry rows
  afcd.py             # local matching against the Australian Food Composition
                      # Database — real nutrition data, no AI involved
  ingredient_enrichment.py # Claude prompt + response normalisation for the
                      # nutrition/cost fallback and reclassification pass
  ai_import.py       # Claude prompt + response normalisation (3 callers)
  routers/
    auth_router.py   # /auth/google, /auth/me, /auth/config
    users.py         # /users admin management
    taxonomy.py      # /tags (sections are tags flagged for the nav)
    recipes.py       # /recipes CRUD, prepared log, image upload
    ingredients.py   # /ingredients master list (signed-in only)
    imports.py       # /imports/paste, /imports/image
  static/            # compiled frontend output — served at /
  uploads/           # recipe photos — served at /media, NOT in git
alembic/             # migration scripts
data/
  blog_raw.json          # committed: the 321-post feed snapshot
  recipes.heuristic.json # committed: rule-parsed structured snapshot
  recipes.json           # the AI-parsed snapshot (produced by parse_blog.py)
  sections.json          # the 20 navigation section tags
  pantry.json            # densities + rough prices for 60 common items
  images/                # downloaded post images (gitignored — see SPEC.md)
  afcd/                  # AFCD Release 3 files (gitignored — see SPEC.md)
  shopping_list*.csv     # a shopping-list export (gitignored — see SPEC.md)
scripts/
  fetch_blog.py      # 1. Blogger feed  -> data/blog_raw.json
  fetch_images.py    # 2. post images   -> data/images/
  parse_blog.py      # 3. Claude (or --offline rules) -> data/recipes*.json
  load_snapshot.py   # 4. snapshot      -> database (idempotent)
  seed_sections.py   # navigation sections from data/sections.json
  seed_pantry.py     # densities/prices from data/pantry.json
  import_pantry_csv.py # a shopping-list export -> the master ingredient list
  fetch_afcd.py       # downloads the AFCD dataset (gitignored, not committed)
  enrich_pantry.py    # AFCD first, then Claude -> nutrition + cost + is_food
  seed_dev_data.py   # a small local fixture set
frontend/
  src/
    App.jsx          # routes, session context
    api.js           # fetch wrapper + all endpoint helpers
    format.js        # display formatting (times, grams, money, fractions)
    themes.js        # light / dark / herb / berry
    pages/           # RecipeList, RecipeDetail, RecipeForm, Import, Pantry, Login
    components/      # Layout, RecipeCard, NutritionPanel, CostPanel,
                     # PreparedLog, IngredientEditor, ThemePicker
tests/               # pytest (backend); frontend/src/**/*.test.{js,jsx} (vitest)
deploy.sh            # idempotent server provisioning + --update mode
```

## Data model

Hierarchy (details in [DATA_MODEL.md](DATA_MODEL.md)):

```
Recipe >──< RecipeTagLink >── Tag          (one taxonomy; tags flagged
  │                                         `is_section` are the navigation)
  ├──< RecipeIngredient >── Ingredient     (the master pantry list:
  │                                         price, density, nutrition)
  ├──< RecipeStep                          (ordered method)
  └──< PreparedEvent                       (each time it was cooked;
                                            the newest is the
                                            Last Prepared Date)
```

## Two numeric conventions

**Cost is integer cents per kilogram** (`Ingredient.cost_per_kg_cents`).
Most pantry items cost a fraction of a cent per gram, so a
dollars-per-gram float would round almost everything to zero. Cents/kg
gives four significant figures on a per-gram price and prices a 2g pinch of
saffron and a 1kg bag of flour with the same arithmetic. `cost_per_gram` is
derived for display only.

**Weight is always grams**, a float, because a converted ⅓ cup rarely lands
on an integer. Every `RecipeIngredient` also carries a `weight_source`:
`explicit` (the recipe said so) / `converted` (density from the linked
pantry item) / `estimated` (keyword-table density) / `unknown`. The UI marks
estimates with an asterisk; nothing pretends to a precision it doesn't have.

## Honest reporting

Nutrition and cost are both summed on read from whatever the pantry
happens to know, which early on is not much. Rather than present a
confident-looking undercount, both report their own completeness —
`nutrition.coverage` (share of the recipe's weight that had data) and
`cost.known_fraction` (share of ingredients that had a price) — and the UI
says "at least $3.40, 4 of 12 ingredients priced" instead of "$3.40".

## Key API endpoints

See [API.md](API.md) for the full list. Highlights:

- `GET /recipes`, `GET /recipes/{slug}` — public; cost omitted for guests
- `GET /tags?section=true` — the navigation; `PATCH /tags/{key}` promotes
- `POST/PATCH/DELETE /recipes/{key}` — signed in
- `POST /recipes/{key}/prepared` — record a cook
- `GET/PATCH /ingredients/{key}` — the pantry; **401 for guests**
- `POST /ingredients/{keep}/merge/{other}` — fold duplicates together
- `POST /imports/paste`, `POST /imports/image` — AI draft, never saved
- `GET /health`, `POST /deploy` (HMAC-signed redeploy webhook)

## Build & deploy workflow

```bash
# Frontend build (required after any frontend/src change) — outputs to backend/static/
cd frontend && npm run build

# Run backend locally (from repo root)
AUTH_ENABLED=false python -m uvicorn backend.main:app --reload   # → http://localhost:8000
```

**Git workflow:** make changes → run `pytest`, `npm run lint`, `npm test` →
commit → branch, push, PR, merge to `main`. The compiled `backend/static/`
bundle is **not** committed; it is built server-side during deploy.

**Production deploy:** `deploy.sh` (idempotent). A push to `main` triggers
redeploy via the `/deploy` webhook (HMAC-signed, `DEPLOY_SECRET`) which
touches `.deploy-trigger`; a systemd path unit runs `deploy.sh --update`
(git pull → npm build → alembic upgrade → seed sections → restart).

## Conventions / gotchas

- **Australian measures.** 1 cup = 250ml, 1 tbsp = **20ml** (not 15ml),
  1 tsp = 5ml. Every scraped recipe assumes this. `Recipe.units_system`
  records it per recipe so a future US import doesn't corrupt the rest.
- Editing a recipe clears its `needs_review` flag — saving *is* the review.
- Both importers and manual entry auto-create master ingredient stubs. An
  unlinked ingredient line can never be priced, so a stub beats a dangling
  string; the Pantry page merges duplicates.
- `Ingredient.aliases` is how spellings stay bound to one row. The
  shopping-list importer writes every variant it saw there, which makes a
  re-import a no-op; `find_ingredient` normalises both sides, so an alias
  matches whether or not the query needed singularising.
- `Ingredient.source` is a plain VARCHAR, not a database ENUM — the value
  list has already grown once and will again.
- Nutrition and cost are held to different accuracy bars: `enrich_pantry.py`
  tries a real government lookup (AFCD) before ever asking Claude for
  nutrition, but always asks Claude for cost, since AFCD has no price data
  and a rough estimate is the actual requirement there. `nutrition_source`
  / `cost_source` say which is which on every row.
- Re-slugging happens only when a title genuinely changes, so editing a
  description never breaks a link.
- An `explicit` weight is never recomputed, even when the pantry's density
  changes — a stated weight outranks anything derived.
- API routes live at the top level (no `/api` prefix); `vite.config.js`
  proxies each prefix in dev. The SPA catch-all must stay registered last.
- Tests: `tests/` (pytest), `frontend/src/**/*.test.{js,jsx}` (vitest).
