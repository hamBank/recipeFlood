"""What a pantry row should be called.

The household's naming rules, shared by the app and the tools:

* **Same ingredient, shorter name.** How much ("handfuls", "block", "x 5g
  packets"), notes ("note 1"), brackets, instructions and preparation words
  ("med", "chopped") are not part of the name.
* **Australian names and spelling** (`SYNONYMS` in `ingredient_names`).
* **`Name - Type`** for types of fruit, vegetables, cream and wine ("Pear -
  Green", "Cream - Thickened"), and **`Name - Canned`** for anything canned.

`proposed_name` applies all three. `recipes_service.get_or_create_ingredient`
uses it to name a new row minted from a recipe line, the shopping-list CSV
importer uses it for new rows, and `scripts/find_duplicate_ingredients.py`
uses it to propose renames and to name merged groups. A row a person types in
on the Pantry page keeps the name they typed.

`SAME_WORDS` is the duplicate finder's list of words that never change what
you buy; `_NOT_SURE` holds matching noise that can (see the finder).
"""

from __future__ import annotations

import re

from .ingredient_names import (
    AMOUNT_WORDS,
    CONTAINER_WORDS,
    MATCH_NOISE,
    PREP_WORDS,
    PRODUCT_FOLDS,
    SIZE_WORDS,
    UNIT_WORDS,
    australian,
    clean_name,
    fold_word,
    singular,
)


#: Matching noise that can still change the product, so a difference in one
#: of them is for a person to judge: "ground coriander" is not coriander, "extra
#: virgin olive oil" is not olive oil, "raw sugar" is not sugar.
_NOT_SURE = frozenset({
    "ground", "raw", "whole", "extra", "toasted", "cooked", "free", "range",
    "organic", "good", "quality", "flat",
    # bought that way as often as done at home: shredded coconut, slivered
    # almonds, tomato puree, crushed tomatoes, grated parmesan, minced garlic
    "shredded", "slivered", "slivers", "puree", "pureed", "crushed", "grated", "minced",
    "seeded",  # seeded mustard is wholegrain mustard
})
#: Words that never change what you buy.
SAME_WORDS: frozenset[str] = frozenset(
    fold_word(w)
    for w in (MATCH_NOISE | PREP_WORDS | SIZE_WORDS | UNIT_WORDS | AMOUNT_WORDS | {
        "divided", "ripe", "cracked", "few", "turns", "unsweetened", "best", "note", "approx", "roughly", "packed", "torn",
        # temperature and serving
        "cold", "warm", "chilled", "iced", "serving", "dusting", "frying", "garnish", "garnishing",
        "broken", "required", "needed", "such", "as", "well", "shaken", "other",
        "yield", "one", "two", "half", "quarter",
        # amounts and the way a recipe counts them
        "sprig", "bunch", "slice", "sheet", "handful", "tbsp", "tblsp", "tbls", "tbl",
        "tablespoon", "tsp", "teaspoon", "cup", "dessertspoon", "piece",
    }) - _NOT_SURE
)

#: Bases whose types get a `Name - Type` name: fruit and vegetables, cream and
#: wine. Add to this to cover more.
TYPED_BASES: frozenset[str] = frozenset(fold_word(w) for w in (
    # fruit
    "apple", "pear", "orange", "lemon", "lime", "grapefruit", "mandarin", "grape",
    "plum", "peach", "nectarine", "apricot", "cherry", "strawberry", "raspberry",
    "blueberry", "blackberry", "banana", "mango", "melon", "watermelon", "rockmelon",
    "avocado", "fig", "kiwi", "kiwifruit", "pineapple", "pomegranate", "olive",
    "rhubarb", "papaya",
    # vegetables
    "capsicum", "chilli", "onion", "potato", "tomato", "eggplant", "pumpkin",
    "cabbage", "lettuce", "mushroom", "zucchini", "squash", "carrot", "beetroot",
    "cucumber", "kale", "spinach", "garlic", "radish", "celery", "leek", "shallot",
    "fennel", "broccoli", "cauliflower", "asparagus", "turnip", "parsnip",
    # and the two the household names the same way
    "cream", "wine",
))
#: For these, a qualifier that is another ingredient makes a different product
#: ("coconut cream", "rice wine"). For fruit and veg it is usually the type
#: ("cherry tomato", "dutch cream potato").
_COMPOUND_SENSITIVE = frozenset({"cream", "wine"})
#: The types of cream and wine that get `Name - Type`. A list rather than a
#: rule, because "coconut cream" and "rice wine" look just like "sour cream"
#: and "red wine", and naming a new row has no pantry to check against.
KNOWN_TYPES: dict[str, frozenset[str]] = {
    "cream": frozenset({
        "thickened", "pure", "double", "single", "heavy", "light", "sour", "clotted",
        "pouring", "whipping", "cooking", "rich", "thick",
    }),
    "wine": frozenset({
        "red", "white", "dry", "sweet", "rose", "rosé", "sparkling", "dessert",
        "fortified", "cooking",
    }),
}
#: Names that look like "<type> <base>" and are not.
_NOT_A_TYPE: frozenset[tuple[str, ...]] = frozenset(
    tuple(fold_word(w) for w in phrase.split())
    for phrase in ("sweet potato", "spring onion", "green onion", "ice cream", "cream of")
)
_CONTAINERS = frozenset(fold_word(w) for w in CONTAINER_WORDS)
#: Words in front of a base that are a part or an amount, not a type.
_NOT_TYPES = frozenset(fold_word(w) for w in (
    "rind", "zest", "head", "bunch", "clove", "handful", "bulb", "stalk", "stick",
    "sprig", "punnet", "piece", "wedge", "leaf", "salad", "stir", "fry", "semi",
    "your", "on", "of", "with", "and", "or", "yet", "berries", "fruit", "firm", "soft",
))
#: Last words that name a part of the thing, not another thing: "coriander
#: leaves" may well be "coriander". For a person to say.
_PARTS = frozenset(fold_word(w) for w in (
    "leaf", "leaves", "stem", "stalk", "floret", "kernel", "segment", "seed", "pod",
))
#: "-ed" words that are a type of their own, not a way of cooking.
_ED_TYPES = frozenset({"thickened", "clotted", "seeded", "sparkling"})



def typed_base(core: tuple[str, ...]) -> tuple[str, ...] | None:
    """The `TYPED_BASES` word a name ends on, with the type in front of it, or
    None: ("green", "pear") -> ("pear",)."""
    if len(core) < 2 or core[-1] not in TYPED_BASES:
        return None
    if any(core[i:i + len(p)] == p for p in _NOT_A_TYPE for i in range(len(core))):
        return None
    return (core[-1],)



#: Words a tidied name keeps even though they never change the product: the
#: joins in "cream of tartar" and "salt and pepper", and "fresh" ("fresh pasta").
_TIDY_KEEP = frozenset({"of", "and", "or", "the", "with", "fresh", "a", "an", "for", "to", "at"})


def tidy_name(name: str) -> str:
    """The name without what the rule says is not the ingredient: how much
    ("handfuls", "block", "x 5g packets", counts, measures), notes ("note 1"),
    brackets, instructions and preparation words, in Australian.

        "x 5g packets roasted seaweed snack" -> "roasted seaweed snack"
        "block halloumi" -> "halloumi";  "med onion" -> "onion"
        "bell pepper" -> "capsicum";  "steamed buns" -> "chinese steamed buns"
    """
    cleaned = clean_name(name)
    text = cleaned.display if " - " in cleaned.display else cleaned.display_no_counts
    # "well-shaken", "flat-leaf", "all-purpose": words, the way the matcher reads them.
    text = re.sub(r"(?<=\w)-(?=\w)", " ", text or name)
    text = australian(text)
    # "x 7 g tin anchovies": the tin went with the packaging, but it is canned.
    if "canned" in cleaned.words and "canned" not in text.lower().split():
        text = f"canned {text}"
    # Likewise a jar ("x 500g jars pitted sweet cherries") is a jarred product.
    elif {"jar", "jars"} & {n.lower() for n in cleaned.notes} and "jarred" not in text.lower().split():
        text = f"jarred {text}"
    head, dash, kind = text.partition(" - ")
    kept = []
    for word in head.split():
        bare = re.sub(r"^[^\w%]+|[^\w%]+$", "", word)
        if not bare or re.fullmatch(r"(?!0\d)[\d./]+", bare):
            continue  # punctuation, or an amount left over ("4 qt/4 l")
        lower = bare.lower()
        if kept and fold_word(kept[-1].lower()) == fold_word(lower):
            continue  # "orange zest 1 orange" -> "orange", not "orange orange"
        if lower in _TIDY_KEEP or fold_word(lower) not in SAME_WORDS:
            kept.append(bare)
    while kept and kept[0].lower() in _TIDY_KEEP - {"fresh"}:
        kept.pop(0)
    if not any(re.search(r"[A-Za-z]", w) for w in kept):
        return name  # "1 cup": nothing left that names anything
    return " ".join(kept) + (f" - {kind}" if dash else "")


def typed_name(name: str, single_names: frozenset[str]) -> str | None:
    """The `Name - Type` name for a type of fruit, vegetable, cream or wine
    ("green pear" -> "Pear - Green"), or for anything canned ("canned
    tomatoes" -> "Tomato - Canned"). None when it is neither, or is already
    named that way."""
    if " - " in name:
        return None
    words = re.findall(r"[A-Za-z']+", name.lower())
    folded = [fold_word(w) for w in words]
    # Only a clean name, which is what makes this safe to apply in bulk:
    # nothing but the type and the base. `tidy_name` gets most names there.
    if not folded or any(w in SAME_WORDS for w in folded):
        return None

    if "canned" in folded and len(folded) > 1:
        rest = [w for w, f in zip(words, folded) if f != "canned"]
        if set(fold_word(w) for w in rest) & _CONTAINERS:
            return None
        rest[-1] = singular(rest[-1])
        return f"{' '.join(rest).capitalize()} - Canned"

    base = typed_base(tuple(folded))
    if base is None:
        return None
    qualifiers = words[: -len(base)]
    folded_q = folded[: -len(base)]
    if not 1 <= len(qualifiers) <= 3 or base[0] in folded_q:
        return None  # "orange orange", "bibb lettuce green lettuce"
    if set(folded_q) & (PRODUCT_FOLDS | _NOT_SURE | _CONTAINERS | _NOT_TYPES):
        return None
    if any(len(q) > 4 and q.endswith(("ed", "ing")) and q not in _ED_TYPES for q in folded_q):
        return None  # "stewed", "caramelised", "baking": how it is cooked or used, not a type
    if base[0] in KNOWN_TYPES and not set(folded_q) <= KNOWN_TYPES[base[0]]:
        return None
    if base[0] in _COMPOUND_SENSITIVE and set(folded_q) & single_names:
        return None
    if any(singular(q) != q for q in qualifiers):
        return None  # "plums peach", "berries cream": a list, not a type
    base_word = singular(words[-1])
    return f"{base_word.capitalize()} - {' '.join(q.capitalize() for q in qualifiers)}"


def proposed_name(name: str, single_names: frozenset[str]) -> str:
    """What the row should be called: tidied, then `Name - Type` where that
    applies. The same name when there is nothing to change."""
    tidy = tidy_name(name)
    return typed_name(tidy, single_names) or tidy




def new_row_name(text: str) -> str:
    """The name for a pantry row minted from a recipe line or an import:
    `proposed_name`, in the pantry's usual lower case and singular unless it is
    a `Name - Type`. Falls back to the text itself."""
    name = proposed_name(text.strip(), frozenset())
    if " - " not in name:
        words = name.lower().split()
        if words:
            words[-1] = singular(words[-1])
        name = " ".join(words)
    return name or text.strip().lower()
