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

## Importing a shopping list

A four-column export — `Item, Weight, Location, Price` — becomes pantry
rows:

```bash
python -m scripts.import_pantry_csv data/shopping_list.csv --dry-run
python -m scripts.import_pantry_csv data/shopping_list.csv --report /tmp/report.csv
python -m scripts.import_pantry_csv data/shopping_list.csv
```

**The file is not committed.** A real shopping list names family members
and their medications, and this repository is public; `.gitignore` excludes
`data/shopping_list*.csv`. Keep yours there and re-run the import when it
changes.

The rules live in [`backend/pantry_import.py`](backend/pantry_import.py)
and are unit-tested in `tests/test_pantry_import.py`. What they do, on the
2,303-row export this was built against:

| Step | Effect |
|---|---|
| Trim, collapse whitespace, lowercase, drop a leading amount | `"1/4 red cabbage"` → `red cabbage`; `"00 flour"` is left alone |
| Correct spelling toward known words | 73 rewrites: `capcicum` → `capsicum`, `muchrooms` → `mushroom` |
| Group on the normalised name | 2,303 rows → 1,871 items |
| Match against the existing pantry | 316 already there, updated in place |
| Map the shop | 47 spellings → 14 sources |
| Flag non-food | 72 items marked `is_food=false` |

**Nothing is duplicated and nothing is overwritten.** Candidates are matched
with the same matcher the recipe importer uses — name, slug, alias, and a
normalised form — and an existing row only ever gains values it was missing.
Every spelling seen becomes an alias on the row it resolved to, which is
what makes a re-import a no-op and also lets a recipe written with
`capcicum` find the capsicum row. Re-running creates zero rows.

### Two things the rules deliberately refuse to do

**Guess at short words.** One edit apart is as likely to be a different food
as a typo, so nothing under six characters is corrected. Earlier versions
produced `peas`→`pear`, `sake`→`sage`, `foil`→`oil` and `milo`→`milk`.

**Treat repetition as spelling evidence.** A correction target must come
from the existing pantry or the density tables, never from the file's own
frequency — the list uses `vegimite` and `mozarella` more than once, and
counting that as evidence corrected the *right* spellings onto the wrong
ones.

Anything the rules get wrong is fixable in one place: `KNOWN_MISSPELLINGS`,
`NEVER_MERGE`, `NON_FOOD_WORDS` and `FOOD_EXCEPTIONS` in
`backend/pantry_import.py`. `--report` writes a per-item CSV of every
decision, which is the fastest way to spot one.

## Importing cooking history

A "date | title | … | source | notes" export — one row per dish cooked,
most rows sharing the date above them — becomes Recipe rows, a
`PreparedEvent` per cook date, and a `CookList` per date:

```bash
python -m scripts.import_recipe_history --input data/recipe_history.csv --limit 20 --dry-run
python -m scripts.import_recipe_history --input data/recipe_history.csv
```

**The file is not committed**, for the same reason the shopping-list
export isn't: it's years of one household's personal browsing and cooking
history, and this repository is public. `.gitignore` excludes
`data/recipe_history*.csv`, `data/recipe_html/` (the fetched-page cache)
and `data/recipes_to_look_up.csv` (the look-up output below).

See SPEC.md's "Importing cooking history" for what a row becomes and why,
and "Recipes from other sites, and copyright" for the rule the fetcher
follows (facts only, never formatting or images). In short:

| Row's source column | Becomes |
|---|---|
| A URL | Fetched (`backend/recipe_fetch.py`: schema.org JSON-LD, else AI-from-text) and deduped by `source_url` |
| A book/magazine citation with a page number | A title-only stub, deduped by `(source_name, source_page)` — nothing to fetch |
| A citation with no page, or nothing at all | Not imported — written to the look-up CSV for a human to chase down |

`ANTHROPIC_API_KEY` isn't required to run the import — pages with no
JSON-LD just fall through to the look-up CSV without it, same as any
other fetch failure, rather than the run erroring out.

The script is re-runnable: a URL or book citation already matched to a
recipe is never re-fetched or re-applied (a re-run must not clobber a
human's edits to something already through `needs_review`), only extended
with `PreparedEvent`/`CookList` rows for dates it wasn't already linked
to. `--limit N` processes only the first N rows — useful for a quick
check before committing to a run over the whole file, which fetches one
new page every couple of seconds and can take a while.

`backend/recipe_history.py` (the parsing) and `backend/recipe_fetch.py`
(the fetching) are unit tested with no network in `tests/
test_recipe_history.py` and `tests/test_recipe_fetch.py`; the importer's
own dedupe/idempotency logic is tested against the shared SQLite fixture
with `fetch_recipe_draft` mocked out, in `tests/
test_import_recipe_history.py`.

## Generating placeholder images

Recipes with no photo of any kind — never uploaded, never self-hosted
from the blog, never generated before — get a lettered placeholder tile
on the grid. `scripts/generate_recipe_images.py` can replace that with an
actual illustration instead, generated from the recipe's own title and
description:

```bash
python -m scripts.generate_recipe_images --dry-run            # preview, no key needed
python -m scripts.generate_recipe_images --budget 5.00         # stop before spending more than this
python -m scripts.generate_recipe_images --limit 20 --quality low
```

Needs `OPENAI_API_KEY` (see `.env.example`) — a separate provider and key
from the rest of the app's AI features, since Claude has no
image-generation endpoint of its own. `--dry-run` works without a key: it
lists what would be generated and the estimated total cost, and spends
nothing.

Candidates are recipes with `image_path IS NULL`, **most-cooked first**
(`select_recipes_needing_images` in the script, unit tested against the
shared SQLite fixture — no network) — excluding "empty" recipes (no
ingredients, no method, no notes; `exclude_empty` in
`backend/recipes_service.py`, shared with the same default-hiding filter
on `GET /recipes`), since there's nothing there to generate a photo of.
`--limit` caps how many images to
generate; `--budget` caps estimated spend instead, working out how many
images that actually affords and stopping there; pass either, both, or
neither. `--quality` (`low`/`medium`/`high`) trades cost for detail — see
`backend/image_generation.py`'s `COST_PER_IMAGE_USD` for the per-image
estimates this is based on, and verify them against
platform.openai.com/pricing before a large run since they can drift.
`gpt-image-1` (the default model, `OPENAI_IMAGE_MODEL`) is scheduled for
deprecation on 2026-10-23 — swap in its replacement via that setting when
the time comes, no code change needed.

Every generated image is saved self-hosted, same as an uploaded photo,
and the recipe is flagged `image_generated=True` so the UI shows an
"AI photo" badge over it rather than let an illustration pass as a real
photo of the dish — see SPEC.md "AI-generated placeholder photos" for why
that flag exists and why the copyright caution around the blog's
hotlinked images (SPEC.md "Images") doesn't apply here.

`backend/image_generation.py`'s prompt-building is unit tested with no
network in `tests/test_image_generation.py`, matching the pattern
`recipe_fetch.py` set: the function that actually calls the API isn't
covered by tests, only exercised by hand against a real key.

## Filling in nutrition and cost

The pantry starts with names only. Two passes fill in the rest — a local
one and a network one — and they can be run separately, which is what you
want on a pantry of a few thousand items:

```bash
python scripts/fetch_afcd.py                       # once — ~3MB, local only

python -m scripts.enrich_pantry --phase local      # AFCD only: seconds, free, no key
python -m scripts.enrich_pantry --phase network    # Claude: the slow, costed half
python -m scripts.enrich_pantry                    # both, in that order (default)
```

`--phase local` needs no API key and no network, finishes in seconds, and
tells you how many items are left for the network pass. Run it first, look
at what it did, then spend money.

The network pass sends batches concurrently (`--concurrency`, default 4)
and can be bounded with `--limit` and `--resume-from` while you sanity-check
a sample. `--only nutrition` / `--only price` narrows what is asked for.

A batch whose response is cut short by the model's output limit no longer
loses the whole batch: the complete items are kept and the remainder is
automatically retried in smaller batches, as is a batch that fails
outright. `--concurrency 1` restores fully serial behaviour if you're
debugging.

**Nutrition, in order of preference:**

1. **AFCD** — the Australian Food Composition Database (FSANZ, Release 3),
   matched locally against the pantry name with no network call
   (`backend/afcd.py`). When it finds a confident match, the numbers are
   the actual government-published figures for that food, and
   `nutrition_source` records exactly which AFCD entry answered — e.g.
   `AFCD (Chicken, breast, lean flesh, raw)` — so a wrong match is
   something you can see and fix on the Pantry page, not a black box.
   Matches ~15-20% of a typical scraped pantry; the rest are compound
   names, brand names, or genuinely not in AFCD's ~1,600 entries.
2. **Claude**, for everything AFCD didn't confidently match. Labelled
   `nutrition_source = "AI estimate (Claude)"` — a well-informed guess
   from trained knowledge of standard food composition, not a lookup.
   Genuinely solid for common whole foods (rice, chicken, olive oil);
   weaker for obscure or branded ones.

**Cost** always comes from Claude — AFCD carries no price data — and is
held to a much lower bar on purpose: a mid-season, mid-tier Australian
retail estimate, labelled `cost_source = "AI estimate (mid-season,
indicative) YYYY-MM"`. It exists so a recipe's cost panel isn't empty, not
to reconcile a receipt.

**Reclassification.** The same Claude pass asks whether each name is
actually human food at all, catching what `backend/pantry_import.py`'s
keyword filter missed on the way in (a shopping list's "cat mince" has no
food keyword in it to catch). A confident no sets `is_food = False` and
writes nothing else to that row.

**Neither pass overwrites anything already on a row** — this only fills
blanks, so it's safe to re-run after fixing something by hand, and a
second run does nothing (`AFCD matches: 0`).

Useful flags: `--only nutrition` / `--only price` restricts what's asked
for and written; `--limit N` / `--resume-from N` bound and continue a run;
`--skip-afcd` goes straight to Claude. `data/afcd/` is gitignored — FSANZ's
download page states plain copyright with no licence grant, so the
dataset isn't redistributed in this repo; the fetch script is the way to
get it.

## Cooking lists and the shopping list

Both live behind sign-in, at `/cooking` and `/groceries` in the frontend.

Those paths deliberately don't match their API prefixes (`/cook-lists` and
`/shopping`). The routers are mounted ahead of the SPA catch-all in
`main.py`, so a frontend route sharing a name with an API prefix would make
a direct visit or a refresh return JSON instead of the app. Vite's dev
proxy is looser still — it matches on string *prefix*, so even
`/shopping-list` would be swallowed by the `/shopping` entry. If you add a
page, check its path against `apiPrefixes` in `frontend/vite.config.js`.

The interesting logic is in `backend/shopping.py`: what merges, what
deliberately doesn't, and the shop walking order. `tests/test_shopping.py`
is organised around the cases that must *not* merge, since those are the
ones that send you home with the wrong amount of food.

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

Keep migrations SQLite-compatible — local dev runs SQLite. Production
runs Postgres, and the two have genuinely diverged before: a native enum
column needs `ALTER TYPE ... ADD VALUE` on Postgres versus a table
rebuild on SQLite (see `IngredientSource`/`ImportSource`'s `native_enum
=False` fields for the pattern that avoids it), and a Postgres `ALTER
COLUMN ... TYPE` on a column with a `DEFAULT` needs the default dropped
and re-added around it (SQLite has no such restriction). If a migration
touches an enum-like column or changes a column's type, verify it by
hand against a real Postgres instance, not just SQLite — `alembic
upgrade head`, `alembic downgrade base`, `alembic upgrade head` again,
`alembic check` clean throughout.

CI's `migrations-postgres` job (`.github/workflows/ci.yml`) runs exactly
that round trip against a real `postgres:16` service container on every
PR — added after a downgrade-to-base/upgrade-to-head round trip (run by
hand, not by CI, since CI didn't check this yet) turned up a real bug:
the baseline migration's `downgrade()` dropped every table but never the
Postgres enum types those tables' columns had created, so a full
teardown left five orphaned types behind and the next `CREATE TYPE`
collided with them. Every enum-widening migration since had only ever
been verified one step at a time (`downgrade -1` / `upgrade head`),
which never happened to reach all the way back down to the migration
that first created those types.

## Git workflow

1. Branch from `main`.
2. Make changes; run `pytest`, `npm run lint`, and `npm test`.
3. Commit source only — `backend/static/` and `backend/uploads/` are
   gitignored.
4. Push, open a PR, merge to `main`. A push to `main` triggers production
   redeploy via the `/deploy` webhook (see [DEPLOYMENT.md](DEPLOYMENT.md)).

### CI as the merge gate

Every PR runs all four `.github/workflows/ci.yml` jobs — `backend`,
`frontend`, `snapshot`, `migrations-postgres` — plus a GitHub Copilot
review requested on open (advisory only; it doesn't block anything).
Green CI is meant to be sufficient to merge, no human/AI approval
required — but that only actually holds once two repo-level settings
(Settings tab, not something a PR can carry) are turned on:

- **Settings → General → Pull Requests → "Allow auto-merge"** — without
  this, `enable_pr_auto_merge` on a PR fails outright.
- **Settings → Branches → protect `main` → "Require status checks to
  pass before merging"**, with all four jobs above selected — without
  this, auto-merge waits for *no* checks in particular and can fire
  before CI even finishes. Leave "Require approvals" off to match "green
  CI is enough."

Once both are set, a PR whose CI is green can carry `enable_pr_auto_merge`
and merge itself the moment the last required job finishes.
