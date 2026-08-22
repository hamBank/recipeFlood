# Recipe Flood — Local Development

## Prerequisites

- Python 3.11+
- Node 20+
- (Optional) Postgres — local dev defaults to SQLite

## First-time setup

```bash
git clone https://github.com/hamBank/recipeFlood.git
cd recipeFlood

# Backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head                     # creates local SQLite DB
python scripts/seed_sections.py          # the 20 navigation sections

# The whole blog collection — 321 recipes, no API key needed
python -m scripts.load_snapshot --heuristic

# Frontend
cd frontend && npm install
```

## Running

```bash
# Backend (repo root) → http://localhost:8000
AUTH_ENABLED=false python -m uvicorn backend.main:app --reload

# Frontend dev server with HMR → http://localhost:5173
cd frontend && npm run dev

# Or: production-style single origin — build then serve from the backend
cd frontend && npm run build             # outputs to backend/static/
```

`AUTH_ENABLED=false` bypasses Google OAuth and signs you in as a local dev
admin — never set in production.

## Environment variables

| Var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./recipeflood.db` | Postgres URL in production |
| `AUTH_ENABLED` | `true` | `false` = local dev bypass |
| `PUBLIC_READ` | `true` | `false` = whole site behind the allowlist |
| `GOOGLE_CLIENT_ID` | — | OAuth client |
| `JWT_SECRET` | — | app token signing |
| `ALLOWED_EMAILS` | — | comma-separated bootstrap allowlist (first admin) |
| `DEPLOY_SECRET` | — | HMAC key for the `/deploy` webhook |
| `CURRENCY_SYMBOL` | `$` | display only |
| `UNITS_SYSTEM` | `au` | `au` = 250ml cup / 20ml tbsp; `us` = 240ml / 15ml |
| `UPLOAD_DIR` | `backend/uploads` | where recipe photos are written |
| `ANTHROPIC_API_KEY` | — | AI import; unset = those features report "not configured" |
| `ANTHROPIC_MODEL` | `claude-sonnet-5` | model for AI import |

## Importing the blog

Four steps. Steps 1–3 write files under `data/`, which are **committed** —
so in normal use you only ever run step 4.

```bash
# 1. Snapshot the Blogger feed -> data/blog_raw.json  (321 posts)
python scripts/fetch_blog.py

# 2. Download post images -> data/images/  (see SPEC.md "Images" first)
python scripts/fetch_images.py

# 3. Structure the posts.
#    The real run — needs ANTHROPIC_API_KEY, ~321 API calls, costs money:
python scripts/parse_blog.py                 # -> data/recipes.json
python scripts/parse_blog.py --limit 5       # try it on five posts first
python scripts/parse_blog.py --resume        # continue after an interruption
#    No key? The deterministic rule parser:
python scripts/parse_blog.py --offline       # -> data/recipes.heuristic.json

# 4. Load a snapshot into the database (idempotent, keyed on source_url)
python -m scripts.load_snapshot              # data/recipes.json
python -m scripts.load_snapshot --heuristic  # the rule-parsed one
python -m scripts.load_snapshot --dry-run
```

Step 3 flushes to disk after every post, so an interrupted paid run loses
nothing and `--resume` picks up where it stopped.

Loading also builds the master ingredient list: every distinct ingredient
phrase becomes a stub row ready to be priced. Expect a lot of near
duplicates on the first pass — the Pantry page's merge action is for
exactly that.

### Which parser?

The AI parser is the intended one: it writes descriptions, splits run-on
method paragraphs sensibly, picks sections, and reads servings and times
out of prose. The rule parser (`backend/blog_parser.py`) exists so the
pipeline is testable without a key and so the collection can always be
rebuilt from the repo. On the 321 posts it manages ≥3 ingredients on 291
of them and a section on 283, and it flags every recipe for review.

## Tests

```bash
pytest                       # backend — tests/ — runs against in-memory SQLite
cd frontend && npm run lint  # eslint — flags hook/JSX bug patterns statically
cd frontend && npm test      # vitest
```

The highest-value backend tests are the unit conversions
(`tests/test_units.py` — the 20ml tablespoon), the visibility rules
(`tests/test_recipes_api.py::TestVisibility` — costs must never reach a
guest) and the re-derivation behaviour
(`tests/test_ingredients_api.py::TestUpdateRederivesWeights`).

## Migrations

```bash
alembic revision --autogenerate -m "add recipe.oven_temp_c"
alembic upgrade head
```

Keep migrations SQLite-compatible so local dev and CI stay on SQLite.

## Git workflow

1. Branch from `main`.
2. Make changes; run `pytest`, `npm run lint`, and `npm test`.
3. Commit source only — `backend/static/` and `backend/uploads/` are
   gitignored.
4. Push, open a PR, merge to `main`. A push to `main` triggers production
   redeploy via the `/deploy` webhook (see [DEPLOYMENT.md](DEPLOYMENT.md)).
