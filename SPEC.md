# Recipe Flood — Product Spec

## What it is

A recipe hub, seeded from twelve years of an Australian food blog
(<https://foobie-rcp.blogspot.com/>, "Recipe 'n stuff", 321 posts), and
extended with manual entry and AI-assisted import.

## Visibility

| Who | Can |
|---|---|
| Anyone | Browse, search and read every published recipe, including nutrition |
| Signed in (allowlisted Google account) | All of the above, plus add/edit recipes, record cooks, use AI import, and **see ingredient costs** |
| Admin | All of the above, plus delete recipes, promote/demote and delete tags, merge/delete pantry items, manage users |

Cost is the only thing hidden from the public. Nutrition is not sensitive
and is shown to everyone. Setting `PUBLIC_READ=false` puts the whole site
behind the allowlist without any code change.

## A recipe

| Field | Notes |
|---|---|
| Title | Required. Also the URL slug. |
| Description | One or two sentences. Written by the AI importer when the source has none. |
| Image | Self-hosted under `/media`. Optional — see **Images** below. |
| Added date | Backdated to the original post date for imported recipes. |
| Last prepared date | Derived — the newest entry in the prepared log. |
| Prep time | Minutes. Null unless the source states it. |
| Cooking time | Minutes. Null unless the source states it. |
| Total time | Derived as prep + cooking, unless overridden (proving, chilling, marinating). |
| Servings | A number, plus a free-text note ("serves 8–10", "makes 24"). Drives per-serve cost and nutrition. |
| Storage | Free text. |
| Nutritional information | **Computed** from the master ingredient list, per recipe and per serving, with a coverage figure. Plus a free-text note. |
| Link to source | URL + a source name. |
| Ingredients | Ordered; name, amount, unit, weight in grams, optional note/group. |
| Process | Ordered list of steps. |
| Tags | Many, free-form. A curated few are **sections** — see below. |

### Tags, and the sections among them

There is one taxonomy: tags. A recipe carries a flat list of them.

A small curated set is flagged as **sections**, and those are the site's
navigation. Everything else is a free-form label for search and for the
"more like this" chips. Whether a tag is a section is a property of the
*tag*, not of the recipe — so a recipe just lists tags, and some of them
happen to be navigation.

That split exists because neither extreme works on this collection:

- **Tags alone can't navigate.** The blog's 266 labels are 53% singletons;
  only 11 are used ten or more times, and those eleven are
  `baking, dessert, salad, chocolate, cake, warm salad, caramel, banana,
  slice, fritter, tart` — a mix of techniques, ingredients and dish types.
  A nav built from the top 20 reaches 68% of recipes and strands about a
  hundred behind search.
- **A single-valued Category needs a second concept** to express one idea,
  and forces a chocolate tart to choose between Dessert and Pastry.

Sections give navigation without either cost, and a recipe may sit in
none, one, or several. Promotion is the growth path: a free tag that turns
out to be load-bearing becomes a section with one PATCH, and every recipe
already carrying it joins immediately — because they all link to the same
tag row.

The trade-off accepted: section counts no longer partition the collection,
so a recipe in two sections is counted twice. For a home recipe site
that's more honest than forcing a choice.

The 20 seeded sections (`data/sections.json`, editable):

Breakfast · Bread · Cake · Biscuits & Slices · Pastry & Tarts · Dessert ·
Salad · Soup · Main — Vegetarian · Main — Meat · Main — Seafood ·
Pasta & Noodles · Curry · Side · Snack · Dips & Spreads ·
Sauces & Dressings · Preserves & Chutney · Drinks · Basics & Components

"Basics & Components" is for the things used *inside* other recipes —
pastry cream, honeycomb, caramelised onions — which the blog has a
surprising number of.

Of the 321 imported recipes, 283 land in a section from the rule parser
alone; the rest stay reachable by search and tags until someone files them.

### Ingredients and weight

Each ingredient line records the amount as written (`2 cups`, `4`,
`1.5 kg`) **and** a weight in grams. The weight is what nutrition — and a
weight-priced ingredient's cost — is computed from, and it is derived
automatically:

1. The amount is already a mass → used as-is (`explicit`)
2. Volume × the linked pantry item's density → `converted`
3. Count × the linked pantry item's grams-per-piece → `converted`
4. Volume × a density from the built-in keyword table → `estimated`
5. Count × a weight from the built-in table → `estimated`
6. Nothing matched → no weight (`unknown`)

Estimates are marked with an asterisk in the UI and explained on hover.
Adding a density to a pantry item re-derives every recipe line that uses
it — except lines whose weight the recipe stated outright, which are never
overwritten.

**A volume-unit line also gets a millilitre amount**, converted the same
way regardless of whether it also converts to a weight — "2 cups" is
500ml by fixed unit arithmetic alone, no density or pantry match
required. This is what lets a liquid ingredient with no known density
still be shopped for and priced correctly: see "Volume-priced
ingredients" below.

**Measures are Australian**: 1 cup = 250ml, 1 tablespoon = **20ml**, 1
teaspoon = 5ml. The 20ml tablespoon is the one that matters — treating it
as 15ml would overstate every spoonful of butter, oil and syrup in the
collection by a third.

## The master ingredient list ("Pantry")

One row per pantry item, referenced by every recipe that uses it.

| Field | Notes |
|---|---|
| Name | Plus aliases used when matching recipe lines ("fetta"/"feta"). |
| Measured by | Weight (default) or volume — see "Volume-priced ingredients" below. Decides which of the next two rows is the one actually used. |
| Usual package size & cost, by weight | Grams, and integer **cents per kilogram** — displayed per kg and per package. This is what gives a useful per-gram resolution. |
| Usual package size & cost, by volume | Millilitres, and integer **cents per litre** — the same idea, for the ingredients this repo now lets be priced by volume instead. |
| `cost_source` | Where the price came from and when — "manual", an AI estimate, or blank. Shared between both cost bases. |
| Source | Markets · Supermarket · Butcher · Nut shop · Deli · Asian grocery · Fishmonger · Bakery · Bottle shop · Cake supplies · Chemist · Hardware · Newsagent · Other |
| Is food | False for the things that come home from the shops but never go in a recipe — batteries, shampoo, cat litter. They stay in the pantry so it remains a complete shopping lookup, but they are kept out of the "needs a price" work queues. |
| Density (g/ml) | Turns "1 cup" into grams. Worth setting even for a volume-priced ingredient — nutrition is always per 100g. |
| Grams per piece | Turns "2 onions" into grams. |
| Nutrition per 100g | Energy (kJ), calories, protein, fat, saturated fat, carbs, sugars, fibre, sodium, plus where the figures came from (`nutrition_source`) and when. |

The last seven sources came from importing a real shopping list: the first
seven were a guess, and the export showed the shopping actually happens at
a fishmonger, a bakery and a bottle shop too.

Importing the blog creates a stub row for every distinct ingredient phrase,
so the pantry arrives pre-populated and ready to be priced rather than
empty. A shopping-list export can be imported on top of it
(`scripts/import_pantry_csv.py`), which adds the items the recipes never
mention and fills in where each one is bought. Near-duplicates ("onion" / "red onion" / "onions") are folded
together with the merge action, which repoints recipe lines, inherits any
data the absorbed row had, and keeps the old name as an alias.

The Pantry page's "missing a price" and "missing nutrition" filters are the
work queues for filling this in — and `scripts/enrich_pantry.py` can fill
most of it automatically.

### Volume-priced ingredients

Most groceries are weighed, but most liquids — milk, stock, oil, wine —
are sold and shelf-priced by volume, and Australian unit pricing puts
$/L on the ticket, not $/kg. Forcing them through a density guess just to
get a cost was both unnecessary and a source of error the density might
not deserve, so a pantry item can be flagged "measured by volume" and
priced in cents per litre instead.

This changes costing and the shopping list, not nutrition: nutrition
figures are always per 100g, so a volume ingredient still wants a density
set if it's meant to contribute to a recipe's nutrition panel. Cost and
the shopping list, on the other hand, need no density at all for a
volume-priced ingredient — "2 cups" and "500ml" of the same liquid both
convert to an exact millilitre figure by fixed unit arithmetic, merge on
that when they turn up in different recipes, and price from
`cost_per_litre_cents` directly.

A freshly-added ingredient defaults to "measured by weight" and gets no
special treatment until someone flags it — except that a liquid with no
known density already merges and displays correctly on the shopping list
regardless, because the exact millilitre amount is there either way; only
its *cost* needs the flag to come from the right pair of fields.

### Filling the pantry automatically

Nutrition and cost are held to different accuracy bars, deliberately.

**Nutrition should be right.** The primary source is the Australian Food
Composition Database (AFCD, FSANZ Release 3) — real government-published
per-100g figures, matched locally to a pantry name with no AI involved.
When AFCD doesn't have a confident match (compound names, brands, the
~80% of a scraped pantry it simply doesn't cover), Claude fills the gap
from its knowledge of standard food composition — genuinely solid for
common whole foods, weaker for the obscure. Every value carries
`nutrition_source` recording exactly which one answered, so an estimate is
never mistaken for a verified figure, and a bad AFCD match (matching is
name-based, not a real lookup key — see `backend/afcd.py`) is something a
human can see and correct.

**Cost only needs to be in the right neighbourhood.** It exists to keep a
recipe's cost panel from being empty, not to reconcile a receipt — a
mid-season, mid-tier Australian retail estimate is enough, and
`cost_source` says so plainly.

Neither pass ever overwrites a value already on the row.

## Cooking lists and the shopping list

A **cooking list** is a date, an optional name, and some recipes — a week's
dinners, a dinner party, Christmas. The date is the identity of the list;
the name is for the ones that earn one ("Anna's birthday"). Two lists can
share a date, because a week of dinners and Saturday's cake are separate
plans that happen to start on the same Monday.

Sending a cooking list to the shopping list folds every recipe's
ingredients into one set of lines. It is additive and re-runnable —
"we're cooking this again" is a real thing to want, and guessing otherwise
would silently drop a shop.

### Quick-add from anywhere a recipe appears

Browsing the grid or a recipe's own page is the moment "we should make
that" actually happens, so both carry a one-click add to whichever
cooking list is most recent — the same "newest first" the Cooking page
itself already sorts by (soonest/latest `cook_date`, ties broken by
whichever was made most recently). Clicking again removes it; there is no
separate confirmation, because adding twice is harmless (the recipe
endpoint that backs this is idempotent) and removing is one click away if
it was a mistake. Signed-in only, same as the rest of cooking-list
planning, and silently absent rather than a broken button when nobody has
started a list yet.

### One permanent shopping list

Not a list per week or per shop: one list, added to and ticked off
forever. A list you clear and rebuild every week loses the "we always need
milk" line. Items are **checked off rather than deleted**, so a
half-finished shop survives closing the phone, and "clear ticked" is the
one destructive action — offered explicitly, with "untick all" as the
escape hatch.

### Grouped by shop, in walking order

Each line inherits its pantry ingredient's `source` — markets, butcher,
Asian grocery — so the list doubles as a route. The order is a walking
order, not alphabetical: fresh food first while there's room in the bags,
cold things last. Anything not linked to a pantry row lands in "other", at
the end.

### What merges, and what deliberately doesn't

A wrong merge is worse than no merge: coming home with 100g of onion when
the lasagne needed 400g is a failure of the list, while two onion lines are
a mild annoyance. So lines combine only on real arithmetic — same pantry
ingredient, and either both in grams, both in millilitres, or both in the
same count unit. An unmatched line never merges with another, and a
weightless "1 bunch" is never folded into a weighed 250g, because that
would mean inventing a bunch weight nobody supplied.

Volume merging is exact regardless of which volume unit either line used
— "2 cups" and "500ml" of the same liquid both merge to a millilitre
figure, no density required. That is what lets a liquid with no known
density still merge and price correctly; see "Volume-priced ingredients"
above.

Every merged line keeps a breakdown of which recipe asked for how much, so
"why is 400g of onion on my list" is answerable without re-running
anything. Editing an amount by hand clears that breakdown rather than
leaving it next to a number it no longer explains.

An ingredient with **no stated amount at all still reaches the list**.
"Olive oil" with no quantity still means buy olive oil, and leaving it off
because the amount is unknown is the one failure a shopping list must not
have.

### Scaling to a number of serves (phase 2)

A recipe on a cooking list can ask for a different number of serves. The
factor is derived live from the recipe's own serving size rather than
frozen when the list was made, so correcting a recipe later fixes every
list that used it. Most scraped recipes have no serving size at all —
those report that they can't be scaled instead of quietly using the base
amounts as though they had been.

## Prepared log

Recording a cook appends a dated entry, optionally with a 1–5 rating and a
note. The recipe's Last Prepared Date is the newest entry. Kept as a log
rather than a single field so "we haven't made this in a year" and "our
most-cooked" both work, and so a note like "halved the sugar" survives.

## Import

Four ways in:

1. **Manual entry** — the form.
2. **Paste** — paste any recipe text; Claude structures it.
3. **Photo** — photograph a cookbook page or handwritten card.
4. **Cooking-history import** — an offline, one-off batch run over a whole
   spreadsheet of past cooking at once. See "Importing cooking history"
   below.

The first three land in the same entry form for review, and neither AI
path (paste or photo) writes to the database directly — both return a
*draft* that pre-fills the form, because a model misreading "¼ tsp" as
"¼ cup" should cost a correction, not a ruined recipe. Drafts carry a
confidence score and a list of things the model was unsure about, both
shown above the form.

The history import is the odd one out: there is no form to review 800
recipes through one at a time, so it writes straight to the database and
leans on `needs_review` instead (see below).

## Recipes from other sites, and copyright

Under Australian law a recipe's **substance is not copyrightable** — a list
of ingredients and the steps to combine them are facts and a method, not a
literary work. What *is* protected is the particular expression: the
author's prose, their headnote, their photographs, and the layout.

So importing a recipe from elsewhere is fine, provided the import takes the
facts and leaves the expression:

- **Don't preserve formatting.** Ingredients and steps are re-parsed into
  this app's own structure. Nothing is copied across as a block of the
  original's markup or prose.
- **Don't preserve images.** No photograph is ever fetched, stored or
  re-displayed from a third-party site (which is also the conclusion the
  blog import reached for its own hotlinked photos — see *Images* below).
- **Always keep the link.** `source_url` and `source_name` are recorded on
  every imported recipe and shown on the page, so the original is one click
  away and gets the visit. Attribution is the point, not a disclaimer.

One consequence for this repository: the committed blog snapshot
(`data/recipes.heuristic.json`) is *our own* blog, and that is why it can
be committed. Recipes imported from other sites live in the database only
— they must not be written into a snapshot that this public repo ships.

## The blog import

A four-step, re-runnable pipeline (see [DEVELOPMENT.md](DEVELOPMENT.md)):

```
fetch_blog.py  ->  data/blog_raw.json       (committed)
fetch_images.py -> data/images/             (committed)
parse_blog.py  ->  data/recipes.json        (committed; costs API calls once)
load_snapshot.py -> the database            (idempotent, keyed on source_url)
```

Because the structured snapshot is committed, the collection can be rebuilt
from this repo by anyone, without an API key and without re-spending on
inference. `parse_blog.py --offline` uses a deterministic rule parser
(`backend/blog_parser.py`) instead — lower quality, but it keeps the
pipeline testable and gives a working collection with no key at all.

Everything imported is flagged `needs_review` with the parser and its
confidence recorded. Editing and saving clears the flag: saving *is* the
review. The recipe grid has a "needs review" filter for signed-in users.

### Images

**Known issue, needs a decision.** The blog has 44 posts with an image, but
none of them are hosted by the blog — every one is a hotlink to a
commercial recipe site (goodfood.com.au, taste.com.au, ABC, BBC Good Food,
Yahoo). Twelve years on, **40 of the 44 are dead or refuse the request**;
only 4 still resolve, and those 4 are someone else's press photography.

Self-hosting works and is implemented (`fetch_images.py` +
`load_snapshot.py --with-images`), but since the site is publicly readable,
republishing four commercial photos is a copyright question rather than a
technical one. So `--with-images` is **off by default**: imported recipes
keep `image_source_url` for provenance and show a generated placeholder
tile. Turn it on if you want them; better still, photograph the dishes and
upload your own, which the recipe form already supports.

## Importing cooking history

A household's own spreadsheet — one row per dish cooked, going back years
— is a different shape of import from the blog: it names hundreds of
distinct third-party sites rather than one source, and most rows are a
repeat of a dish cooked before rather than a new recipe. `scripts/
import_recipe_history.py` handles it in one offline batch:

```
backend/recipe_history.py  parses the spreadsheet: forward-filled dates,
                            a source column that's a URL or a book/
                            magazine citation ("Plenty More", p133), light
                            name cleanup. No network, no database.
backend/recipe_fetch.py    fetches and structures a linked recipe:
                            schema.org JSON-LD first (free, exact), else
                            AI-from-text over the page's stripped text.
scripts/import_recipe_history.py
                            ties the two together: dedupe, write, backfill.
```

What a row becomes depends on what its source column held:

- **A URL** — fetched and deduped by `source_url`, same as the blog
  import. Written as a full Recipe, `import_source=web`,
  `needs_review=True`. Per "Recipes from other sites, and copyright"
  above: no formatting or images are preserved, only the facts, and
  `source_url` keeps the link back.
- **A book or magazine citation with a page number** — nothing to fetch
  over HTTP, so it's written as a title-only stub, deduped by
  `(source_name, source_page)`, with `source_page` recording the page
  within `source_name`. Real provenance, waiting on a human to open the
  book.
- **Everything else** — no link, or a citation too vague to be one
  recipe (no page number) — isn't written to the database at all. It
  lands in a look-up CSV instead, alongside genuine fetch failures (a
  dead link, a page with nothing schema.org or AI could make sense of),
  for a human to search out and add by hand later.

Every row that *did* resolve to a Recipe also gets a `PreparedEvent` for
its cook date — a dish cooked a dozen times across the spreadsheet gets a
dozen events even though it was only imported once — and each date's
resolved recipes are grouped into one `CookList` for that date, so the
spreadsheet becomes real cooking-list history, not just a recipe box.

The script is safe to run again over an updated export: a recipe already
matched by `source_url` or its book citation is never re-applied, only
extended with any new dates it wasn't already linked to. It has been
through `needs_review` once, and a re-run must not silently overwrite
whatever a human has since edited.

Neither the export, the fetched-page HTML cache (`data/recipe_html/`),
nor the look-up CSV is committed — see `.gitignore`. The export is a
household's years of personal browsing history; the cache and look-up
CSV are just that history reshaped.
