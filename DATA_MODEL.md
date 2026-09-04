# Recipe Flood — Data Model

Tables are defined in [`backend/models.py`](backend/models.py); Alembic
autogenerate reads `SQLModel.metadata` from there.

```
Recipe >──< RecipeTagLink >── Tag        (tags flagged `is_section`
  │                                       are the navigation)
  ├──< RecipeIngredient >── Ingredient
  ├──< RecipeStep
  └──< PreparedEvent
User ──< Recipe.created_by, PreparedEvent.user_id
```

## `user`

Same shape as pocketMoney: `google_sub`, `email` (unique), `name`,
`avatar_url`, `role` (`admin` / `user`), `is_active`, `created_at`. The
first allowlisted account to sign in becomes the admin.

## `tag` / `recipetaglink` — the only taxonomy

| Column | Notes |
|---|---|
| `slug` (unique), `name` | |
| `is_section` | Indexed. True = this tag is site navigation |
| `sort_order` | Nav order; ignored for free-form tags |
| `description` | Shown on the section chip in the entry form |

`recipetaglink` is a composite PK of (`recipe_id`, `tag_id`). Tags are
created on demand when a recipe names one — and a recipe naming `dessert`
attaches to the **existing** Dessert section rather than forking a second
tag. That is what lets a recipe declare its section through the same flat
list as everything else, and what makes promotion free: flipping
`is_section` on a tag moves every recipe already carrying it into the nav,
with no recipe row touched.

Sections are seeded from `data/sections.json` by
`scripts/seed_sections.py`, which promotes an existing free tag rather than
duplicating it. See SPEC.md for why this is one table and not two.

`GET /recipes/{slug}` returns `tags` (every label) and `sections` (the
navigation subset of it, in nav order) — a subset, not a disjoint list.

## `recipe`

| Column | Type | Notes |
|---|---|---|
| `slug` | str, unique | URL identity; allocated from the title, suffixed on collision |
| `title` | str | |
| `description` | str? | |
| `image_path` | str? | Relative to `UPLOAD_DIR`, served at `/media/...` |
| `image_source_url` | str? | Original remote URL, kept for provenance |
| `image_generated` | bool | True when `image_path` is an AI illustration, not a real photo — see `scripts/generate_recipe_images.py` |
| `added_date` | datetime | Backdated to the post date on import |
| `prep_minutes`, `cook_minutes` | int? | Null unless the source stated it |
| `total_minutes_override` | int? | Null ⇒ total = prep + cook |
| `servings` | int? | Drives per-serve cost and nutrition |
| `servings_note` | str? | The author's wording: "serves 8–10" |
| `storage` | str? | |
| `nutrition_note` | str? | Free text beside the computed panel |
| `source_url`, `source_name` | str? | `source_url` is the import idempotency key |
| `units_system` | str | `au` (default) or `us` — see `backend/units.py` |
| `import_source` | enum | `manual` / `blog` / `ai_image` / `ai_paste` |
| `needs_review` | bool | Set by importers; cleared by saving an edit |
| `review_note` | str? | Parser + confidence + what it was unsure about |
| `is_published` | bool | Unpublished recipes are invisible to guests |
| `created_by` | FK? | |
| `created_at`, `updated_at` | datetime | |

**Derived, never stored:** `total_minutes`, `last_prepared_on`,
`prepared_count`, `sections`, `nutrition`, `nutrition_per_serving`, `cost`.

## `recipeingredient`

One row per line of the ingredient list. `raw_text` always keeps the
original wording so a bad parse can be redone from source.

| Column | Notes |
|---|---|
| `recipe_id`, `position` | Ordered within the recipe |
| `ingredient_id` | FK to the master list; null if unmatched |
| `raw_text` | The original line, verbatim |
| `name` | The parsed ingredient name |
| `quantity`, `quantity_max` | `quantity_max` only for ranges ("2–3 tbsp") |
| `unit` | enum — `g`…`lb`, `cup`/`tbsp`/`dsp`/`tsp`, `piece`/`clove`/`bunch`…, `pinch`, `to_taste` |
| `weight_grams` | float? — what a weight-priced ingredient's cost and (always) nutrition are computed from |
| `weight_source` | `explicit` / `converted` / `estimated` / `unknown` |
| `volume_ml` | float? — set whenever `unit` is a volume unit; what a volume-priced ingredient's cost is computed from |
| `note` | "finely chopped", "at room temperature" |
| `optional` | Excluded from cost and nutrition totals |
| `group` | Sub-heading: "For the sauce" |

`weight_source` is the honesty field. `explicit` means the recipe gave a
weight and it is never recomputed; `estimated` means a keyword-table
density was used and the UI marks it with an asterisk.

`volume_ml` has no equivalent source field: converting a stated volume
unit to millilitres is fixed unit arithmetic (`units.to_ml`), needing no
density or linked ingredient, so it is either exact or absent — never an
estimate. It is populated independently of `weight_grams` and of whether
the line matched a pantry row at all.

## `recipestep`

`recipe_id`, `position`, `text`. Replaced wholesale on save — steps have no
identity worth preserving across an edit.

## `ingredient` — the master pantry list

| Column | Notes |
|---|---|
| `slug` (unique), `name` | |
| `aliases` | JSON list, lowercased; matched against recipe lines |
| `measure_kind` | `weight` (default) or `volume` — which unit family this ingredient is bought and priced in. Plain VARCHAR, same reasoning as `source` below |
| `package_size_grams` | float? |
| `cost_per_kg_cents` | **int?** — see below |
| `package_size_ml` | float? — the volume-priced sibling of `package_size_grams` |
| `cost_per_litre_cents` | **int?** — the volume-priced sibling of `cost_per_kg_cents` |
| `cost_source`, `cost_updated_at` | Where a price came from and when — "manual" once a human edits it, or an enrichment script's own label. Mirrors `nutrition_source`; shared between both cost bases |
| `source` | Where it is bought. Fourteen values — see `IngredientSource`. Stored as a plain VARCHAR with no database CHECK: the first seven were a guess and a real shopping list added seven more, so the next addition should not need a migration that behaves differently on SQLite and Postgres |
| `is_food` | Indexed. False for batteries, shampoo, cat litter — in the pantry as a shopping lookup, out of the ingredient work queues |
| `density_g_per_ml` | float? — converts volumes to grams |
| `grams_per_piece` | float? — converts counts to grams |
| `energy_kj`, `calories_kcal`, `protein_g`, `fat_g`, `saturated_fat_g`, `carbs_g`, `sugars_g`, `fibre_g`, `sodium_mg` | float?, all **per 100g** |
| `nutrition_source`, `nutrition_updated_at` | Provenance: `"AFCD (<matched food>)"`, `"AI estimate (Claude)"`, a packet, or a human's own note |
| `notes`, `created_at`, `updated_at` | |

### Why cents per kilogram (and per litre)

The spec asked for "cost per gram with enough resolution to be useful".
Stored per gram in dollars, plain flour at $2.50/kg is `0.0025` — three
leading zeros, and any two-decimal money type rounds it to nothing.
Cents-per-kilogram keeps it an integer (`250`), gives four significant
figures on the per-gram price, and prices a 2g pinch of saffron and a 1kg
bag of flour with the same arithmetic. `cost_per_gram` is derived on read,
for display only. `cost_per_litre_cents` is the same idea for liquids —
most of them are sold and shelf-priced by volume in Australia, and
`measure_kind` says which of the two pairs of fields (`*_grams`/`*_kg` or
`*_ml`/`*_litre`) is the one actually being priced from; the other pair
is ignored even if it happens to hold a stale value from before the
ingredient was reclassified. `density_g_per_ml` is still worth setting on
a volume ingredient regardless — nutrition is always per 100g, so it is
what lets a volume amount contribute to the nutrition panel.

`aliases` is load-bearing beyond search: the shopping-list importer records
every spelling it saw on the row it resolved to, so a re-import is a no-op
and a recipe line reading "capcicum" finds the capsicum row. `find_ingredient`
normalises both sides when comparing, so the alias "pinenuts" also matches a
line reading "pinenut".

Every nutrition column is nullable and independently so: a recipe's panel
reports which fields it actually has rather than filling gaps with zeros.

## `preparedevent`

`recipe_id`, `prepared_on` (date), `user_id?`, `rating?` (1–5), `note?`,
`created_at`, `cook_list_id?`.

A log rather than a `last_prepared_date` column on the recipe. The newest
entry *is* the Last Prepared Date, and keeping the history is what makes
"not cooked in a year" (`GET /recipes?not_prepared_days=365`) and
per-cook notes possible.

`cook_list_id` is set only on an entry a cooking list auto-created when
the recipe joined it (see "Adding a recipe logs a prepared event" in
SPEC.md) — null for anything logged by hand from the recipe page. It's
cleared, not cascaded, if that list is later deleted: the plan can go,
but the entry it logged stays as history.

## `cooklist` / `cooklistrecipe`

`cooklist`: `cook_date` (indexed), `description?`, `notes?`, `created_by?`,
`created_at`, `updated_at`.

`cooklistrecipe`: `cook_list_id`, `recipe_id`, `position`, `servings?`,
`note?`.

`cook_date` is not unique — a week of dinners and Saturday's cake are two
plans that can start on the same Monday.

`servings` is the scaling request, not a stored factor. The multiplier is
derived at read time from `recipe.servings`, so fixing a recipe's serving
size later corrects every list that used it; when the recipe has no
serving size, the read model reports `scalable: false` rather than
inventing one.

## `shoppingitem`

`ingredient_id?`, `name`, `weight_grams?`, `volume_ml?`, `quantity?`, `unit?`,
`note?`, `is_checked` (indexed), `checked_at?`, `source` (`manual` | `cook_list`),
`cook_list_id?`, `contributions` (JSON), `added_at`.

There is no `shoppinglist` table: there is exactly one list and it is
permanent, so these rows *are* the list.

`ingredient_id` is nullable for the same reason `recipeingredient`'s is —
an unmatched line still belongs on the list as plain text. It is also what
gates merging: two lines combine only when they share a pantry row.

An item normally has exactly one of `weight_grams` / `volume_ml` / `quantity`
populated — whichever kind of amount the merge that produced it worked in.
`volume_ml` merges are exact regardless of which volume unit either
contributing line used ("2 cups" and "500ml" both land here), which is what
lets a liquid with no known density still be merged and priced correctly —
see `backend/shopping.py`'s module docstring for the full precedence
between weight, volume, and count merging.

`contributions` is a JSON list of `{recipe, recipe_slug, amount}`, recording
what each merge folded in. It is cleared when a human edits the amount, so
a breakdown never sits next to a number it no longer explains.

`unit` is a plain VARCHAR here, not the native `measureunit` enum that
`recipeingredient` uses. That Postgres type already exists from the
baseline migration and a second `CREATE TYPE` for it fails — the same
dual-dialect trap `ingredient.source` documents.

## Migrations

```bash
alembic revision --autogenerate -m "add recipe.oven_temp_c"
alembic upgrade head
```

Keep migrations SQLite-compatible (no Postgres-only types) so local dev and
CI stay on SQLite.
