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
`1.5 kg`) **and** a weight in grams. The weight is what cost and nutrition
are computed from, and it is derived automatically:

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

**Measures are Australian**: 1 cup = 250ml, 1 tablespoon = **20ml**, 1
teaspoon = 5ml. The 20ml tablespoon is the one that matters — treating it
as 15ml would overstate every spoonful of butter, oil and syrup in the
collection by a third.

## The master ingredient list ("Pantry")

One row per pantry item, referenced by every recipe that uses it.

| Field | Notes |
|---|---|
| Name | Plus aliases used when matching recipe lines ("fetta"/"feta"). |
| Usual package size | Grams. |
| Cost | Stored as integer **cents per kilogram**; displayed per kg and per package. This is what gives a useful per-gram resolution. |
| Source | Markets · Supermarket · Butcher · Nut shop · Deli · Asian grocery · Fishmonger · Bakery · Bottle shop · Cake supplies · Chemist · Hardware · Newsagent · Other |
| Is food | False for the things that come home from the shops but never go in a recipe — batteries, shampoo, cat litter. They stay in the pantry so it remains a complete shopping lookup, but they are kept out of the "needs a price" work queues. |
| Density (g/ml) | Turns "1 cup" into grams. |
| Grams per piece | Turns "2 onions" into grams. |
| Nutrition per 100g | Energy (kJ), calories, protein, fat, saturated fat, carbs, sugars, fibre, sodium, plus where the figures came from (`nutrition_source`) and when. |
| Cost | Stored as cents per kg. `cost_source` records where the price came from — "manual", an AI estimate, or blank. |

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

## Prepared log

Recording a cook appends a dated entry, optionally with a 1–5 rating and a
note. The recipe's Last Prepared Date is the newest entry. Kept as a log
rather than a single field so "we haven't made this in a year" and "our
most-cooked" both work, and so a note like "halved the sugar" survives.

## Import

Three ways in, all landing in the same entry form for review:

1. **Manual entry** — the form.
2. **Paste** — paste any recipe text; Claude structures it.
3. **Photo** — photograph a cookbook page or handwritten card.

Neither AI path writes to the database. Both return a *draft* that
pre-fills the form, because a model misreading "¼ tsp" as "¼ cup" should
cost a correction, not a ruined recipe. Drafts carry a confidence score and
a list of things the model was unsure about, both shown above the form.

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
