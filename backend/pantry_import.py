"""Rationalising a shopping-list export into pantry rows.

The input is a four-column dump — Item, Weight, Location, Price — of the
kind a shopping app produces after years of use. It is messy in specific,
repeatable ways, and each of those is handled here rather than in the
script, so the rules are testable:

* **The same thing appears many times.** 2,300 rows collapse to about 1,900
  distinct items on whitespace, case and plurals alone.
* **Spelling drifts.** "capcicum"/"capsicum", "muchroom"/"mushroom",
  "bococini"/"boconcini" — 145 pairs one edit apart. Correcting these
  automatically is only safe in one direction: toward a spelling we have
  independent evidence for (see `correct_spelling`).
* **The shop column is free text.** 47 spellings of about 15 shops:
  `Costco`/`costco`/`Costo`, `Bottlo`/`bottlo`/`booze`/`Grog`/`Alcholo`.
* **Some rows are shifted.** Twenty have the shop repeated in the Price
  column.
* **Not everything is food.** Batteries, shampoo, cat litter and fencing
  mesh live in the same list as the flour.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from .models import IngredientSource

#: Free-text shop -> the source it means. Keys are lowercased and stripped.
SHOP_SOURCES: dict[str, IngredientSource] = {
    "sm": IngredientSource.supermarket,
    "sm-aldi": IngredientSource.supermarket,
    "aldi": IngredientSource.supermarket,
    "costco": IngredientSource.supermarket,
    "costo": IngredientSource.supermarket,
    "bigw": IngredientSource.supermarket,
    "markets": IngredientSource.markets,
    "market": IngredientSource.markets,
    "butcher": IngredientSource.butcher,
    "nuts": IngredientSource.nut_shop,
    "nut": IngredientSource.nut_shop,
    "deli": IngredientSource.deli,
    "asian": IngredientSource.asian_grocery,
    "indian": IngredientSource.asian_grocery,
    "fish": IngredientSource.fishmonger,
    "bakery": IngredientSource.bakery,
    "bottlo": IngredientSource.bottle_shop,
    "bottle": IngredientSource.bottle_shop,
    "booze": IngredientSource.bottle_shop,
    "alcohol": IngredientSource.bottle_shop,
    "alcholo": IngredientSource.bottle_shop,
    "wine": IngredientSource.bottle_shop,
    "grog": IngredientSource.bottle_shop,
    "cake": IngredientSource.cake_supplies,
    "cake shop": IngredientSource.cake_supplies,
    "chemist": IngredientSource.chemist,
    "pharm": IngredientSource.chemist,
    "pharmacy": IngredientSource.chemist,
    "bunnings": IngredientSource.hardware,
    "bunn": IngredientSource.hardware,
    "hardware": IngredientSource.hardware,
    "x-metalworks": IngredientSource.hardware,
    "newsagent": IngredientSource.newsagent,
    "healthfood": IngredientSource.other,
    "servo": IngredientSource.other,
    "our house": IngredientSource.other,
    "supplier": IngredientSource.other,
    "kingston": IngredientSource.other,
    "done": IngredientSource.other,
}

#: Sources whose contents are never a recipe ingredient.
NON_FOOD_SOURCES = {
    IngredientSource.chemist,
    IngredientSource.hardware,
    IngredientSource.newsagent,
}

#: Whole words that mark a non-food item wherever it was bought. Matched on
#: word boundaries: a substring test drags in "cabbage" for "bag" and
#: "baguette" for "bag", which is how the first attempt at this went wrong.
NON_FOOD_WORDS = {
    "batteries", "battery", "tissues", "tissue", "toilet", "napkins",
    "napkin", "foil", "detergent", "soap", "shampoo", "conditioner",
    "toothpaste", "toothbrush", "deoderant", "deodorant", "cleaner",
    "bleach", "disinfectant", "candles", "lighter", "matches", "dishwasher",
    "sponges", "laundry", "wipes", "nappies", "nappy", "litter", "bin",
    "bins", "broom", "mop", "lightbulb", "lightbulbs", "stamps",
    "firewood", "mesh", "bolts", "hooks", "compost", "vaporiser", "nurofen",
    "panadol", "script", "sunscreen", "razors", "razor", "floss",
    "serviettes", "poo", "canestan", "canesten", "czine",
}

#: Multi-word non-food terms, checked as substrings. "bulb" and "globe"
#: cannot be single keywords — they would condemn fennel bulbs, garlic
#: bulbs and globe artichokes, which is exactly what happened on the first
#: pass over this data.
NON_FOOD_PHRASES = ("light bulb", "light globe", "bin liner", "cling film")

#: Items the word list would wrongly condemn. "candle nuts" are a real
#: Southeast Asian ingredient; a "choc sponge" is cake, not washing up.
FOOD_EXCEPTIONS = {
    "candle nuts", "candlenuts", "choc sponge", "sponge cake", "bottle brush",
    "fennel bulb", "fennel bulbs", "garlic bulb", "garlic bulbs",
    "globe artichoke", "globe artichokes",
}

#: The values a bulk edit left behind: 251 of 323 weights are exactly 0.3
#: and 232 of 341 prices exactly 3. Treating those as measurements would put
#: invented numbers into the cost panel, so they are ignored.
PLACEHOLDER_WEIGHT_KG = 0.3
PLACEHOLDER_PRICE = 3.0

_NUMERIC = re.compile(r"^\d+(?:\.\d+)?$")
# Leading amounts worth stripping: a fraction, a number with a unit, or a
# bare "1". Deliberately NOT a bare number in general — "00 flour" is a
# flour grade and "3 bean mix" is the name of the product.
_LEADING_AMOUNT = re.compile(r"^(?:\d+\s*/\s*\d+|\d+(?:\.\d+)?\s*(?:g|kg|ml|l)\b|1)\s+", re.I)


def clean_item(raw: str) -> str:
    """Trim, collapse whitespace, drop a leading amount, lowercase."""
    text = re.sub(r"\s+", " ", (raw or "").strip())
    text = _LEADING_AMOUNT.sub("", text).strip()
    return text.lower()


def parse_number(raw: str | None) -> float | None:
    """A number, or None for blanks and for the shop names that ended up in
    the Price column on twenty shifted rows."""
    text = (raw or "").strip()
    return float(text) if _NUMERIC.match(text) else None


def map_source(raw: str | None) -> IngredientSource:
    """Free-text shop -> IngredientSource, defaulting to `other`."""
    return SHOP_SOURCES.get((raw or "").strip().lower(), IngredientSource.other)


def is_food(name: str, source: IngredientSource) -> bool:
    lowered = name.lower()
    if lowered in FOOD_EXCEPTIONS:
        return True
    if source in NON_FOOD_SOURCES:
        return False
    if any(phrase in lowered for phrase in NON_FOOD_PHRASES):
        return False
    return not (set(re.findall(r"[a-z]+", lowered)) & NON_FOOD_WORDS)


def _edit_distance_one(a: str, b: str) -> bool:
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    return any(shorter == longer[:i] + longer[i + 1 :] for i in range(len(longer)))


def _singular(text: str) -> str:
    words = text.split()
    if words and len(words[-1]) > 3 and words[-1].endswith("s") and not words[-1].endswith(
        ("ss", "us", "is")
    ):
        words[-1] = words[-1][:-1]
    return " ".join(words)


#: Below this length, one edit is as likely to be a different food as a
#: typo: peas/pear, sake/sage, foil/oil, milo/milk, mints/mint. All of those
#: were produced by an earlier version of this function.
MIN_CORRECTION_LENGTH = 6

#: Pairs that pass every rule and are still wrong, because both sides are
#: real and distinct. Extend this rather than loosening the rules.
NEVER_MERGE: set[frozenset[str]] = {
    frozenset({"craisins", "raisins"}),      # dried cranberries, not raisins
    frozenset({"dried noodles", "fried noodles"}),
    frozenset({"masala", "marsala"}),        # spice blend, not the wine
    frozenset({"eshallot", "shallot"}),      # eschalot is its own thing here
    frozenset({"smoked cheddar", "smokey cheddar"}),
}

#: Spellings this list gets wrong often enough that frequency alone would
#: entrench them. Applied before anything else, in this direction only.
KNOWN_MISSPELLINGS = {
    "vegimite": "vegemite",
    "mozarella": "mozzarella",
    "bococini": "bocconcini",
    "boccini": "bocconcini",
    "boccocini": "bocconcini",
    "boconcini": "bocconcini",
    "zuchini": "zucchini",
    "zuchinni": "zucchini",
    "zuchinis": "zucchini",
    "oinon": "onion",
    "red oinon": "red onion",
    "muchroom": "mushroom",
    "muchrooms": "mushroom",
    "capcicum": "capsicum",
    "capcisum": "capsicum",
    "vegi oil": "vegetable oil",
    "vege oil": "vegetable oil",
    "vegi stock": "vegetable stock",
    "vegie stock": "vegetable stock",
    "haloumi": "halloumi",
    "marscapone": "mascarpone",
    "mascapone": "mascarpone",
}


def correct_spelling(
    names: list[str], vocabulary: set[str], *, extra: dict[str, str] | None = None
) -> dict[str, str]:
    """Map misspellings onto a spelling we have real evidence for.

    Returns {wrong: right}, containing only names to rewrite.

    The rules, each of which exists because its absence produced a wrong
    merge on this data:

    1. `KNOWN_MISSPELLINGS` first, in one direction only. Without this,
       "vegimite" appearing twice made it look canonical and *attracted*
       the correct "vegemite" to it. Frequency within a shopping list is
       evidence of habit, not of spelling.
    2. A correction target must be in `vocabulary`, which the caller builds
       only from things that are independently known — the existing pantry
       and the density tables — never from this file's own repetitions.
    3. A name already in `vocabulary` is never rewritten.
    4. Nothing shorter than `MIN_CORRECTION_LENGTH` is touched.
    5. Pairs differing only by a plural are skipped: the grouping key
       already singularises, so "avocados" and "avocado" merge downstream
       without a guess here.
    6. Exactly one candidate must match. Two candidates means we cannot
       tell, so nothing happens.
    7. `NEVER_MERGE` overrides all of the above.
    """
    overrides = {**KNOWN_MISSPELLINGS, **(extra or {})}
    corrections: dict[str, str] = {}
    unique = sorted(set(names))

    for name in unique:
        if name in overrides:
            corrections[name] = overrides[name]

    # An override's target is settled: never correct it away again, and
    # never let an override's key be a target. Without this the two rules
    # disagree and produce a cycle — the blog pantry contains "haloumi" and
    # "mozarella", so the distance rule mapped the corrected spellings
    # straight back onto the misspellings they had just replaced.
    override_targets = set(overrides.values())

    by_length: dict[int, list[str]] = defaultdict(list)
    for name in unique:
        by_length[len(name)].append(name)

    for name in unique:
        if name in corrections or name in vocabulary or name in override_targets:
            continue
        if len(name) < MIN_CORRECTION_LENGTH:
            continue
        candidates = [
            candidate
            for length in (len(name) - 1, len(name), len(name) + 1)
            for candidate in by_length.get(length, [])
            if candidate in vocabulary
            and candidate not in overrides
            and _edit_distance_one(name, candidate)
            and _singular(name) != _singular(candidate)
            and frozenset({name, candidate}) not in NEVER_MERGE
        ]
        if len(candidates) == 1:
            corrections[name] = candidates[0]
    return corrections


def resolve_source(sources: list[IngredientSource]) -> IngredientSource:
    """The shop an item is most often bought from.

    The same item appears under several shops ("aioli" at both the
    supermarket and Costco). Most-frequent wins; `other` only wins if
    nothing else was ever recorded, since it is the fallback rather than a
    real answer.
    """
    counts = Counter(sources)
    real = {s: n for s, n in counts.items() if s is not IngredientSource.other}
    pool = real or counts
    best = max(pool.values())
    # Deterministic tie-break, so a re-run produces the same pantry.
    return sorted((s for s, n in pool.items() if n == best), key=lambda s: s.value)[0]


def pack_metrics(weight_kg: float | None, price: float | None) -> tuple[float | None, int | None]:
    """(package_size_grams, cost_per_kg_cents) from one row's Weight/Price.

    Both are dropped when they hold the bulk-edit placeholder. A price
    without a weight cannot become a per-kilogram cost, so it is discarded
    rather than guessed at — in this export that case never arises, but the
    rule should not depend on that.
    """
    weight = weight_kg if weight_kg and weight_kg != PLACEHOLDER_WEIGHT_KG else None
    cost = price if price and price != PLACEHOLDER_PRICE else None
    grams = round(weight * 1000, 3) if weight else None
    if cost is None or weight is None:
        return grams, None
    return grams, round(cost / weight * 100)
