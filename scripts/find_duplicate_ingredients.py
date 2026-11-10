#!/usr/bin/env python3
"""Sort the pantry's near-duplicates into what to merge, what to check and
what to leave alone.

    python -m scripts.find_duplicate_ingredients               # the report; changes nothing
    python -m scripts.find_duplicate_ingredients --min-usage 1 # skip rows no recipe uses
    python -m scripts.find_duplicate_ingredients --merge       # merge the CONFIDENT list
    python -m scripts.find_duplicate_ingredients --rename      # apply the RENAMES list
    python -m scripts.find_duplicate_ingredients --fix-names   # "tomatoe" -> "tomato"

Importing the blog, a shopping-list CSV and years of cooking history each
created one pantry row per phrase they saw, so one real ingredient can be
several rows ("onion", "med onion", "onions"). Each row has its own
incomplete price and nutrition.

## The rule

Two names are the same ingredient when the words that differ are
**post-purchase preparation**: size, chopping, slicing, ripeness, "freshly
grated". They are different ingredients when the difference describes a
**substantially different product**:

* a form or process: tinned, frozen, smoked, dried, powder, paste, juice
  (`PRODUCT_WORDS` in `backend/ingredient_names.py`);
* another ingredient: "cream cheese" is not a kind of cream;
* a type of fruit, vegetable, cream or wine: "green pear" is a pear, but
  not the same purchase as a pear. These are named `Name - Type`, e.g.
  "Pear - Green", and the RENAMES list proposes those names.

Anything else, such as "japanese eggplant", "caster sugar" or "00 flour",
is not a guess. It goes in REVIEW for a person to decide.

## The lists

* **CONFIDENT**: rows whose names differ only by preparation words, or
  by a word the keeper lists in its own `prep_terms`. `--merge` merges them.
* **REVIEW**: everything the rule cannot settle, with the reason. This
  includes every link made **only through an alias**. An alias is a
  person's or an importer's say-so, and one wrong alias can chain unrelated
  rows together ("onion" to "water" to "sugar"). Merge a review item by
  hand from the Pantry page, or fix the alias.
* **RENAMES**: `Name - Type` names for types of fruit, vegetable, cream
  and wine. `--rename` applies them. The old name is kept as an alias and
  the slug is unchanged, so links and URLs survive.
* **UNCHANGED**: related names that are kept apart, with the reason, and
  a count of everything with no near match.

A merge keeps the row used in the most recipes. It repoints recipe lines
and shopping items through `_merge_into`, the same function the
`/ingredients/{a}/merge/{b}` endpoint uses, and it cannot be undone.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, func, select  # noqa: E402

from backend.database import engine  # noqa: E402
from backend.ingredient_names import (  # noqa: E402
    CONTAINER_WORDS,
    MATCH_NOISE,
    PREP_WORDS,
    PRODUCT_FOLDS,
    SIZE_WORDS,
    UNIT_WORDS,
    clean_name,
    fold_word,
    repair,
    singular,
)
from backend.models import Ingredient, RecipeIngredient  # noqa: E402
from backend.routers.ingredients import _merge_into  # noqa: E402


# --------------------------------------------------------------------------
# Words

#: Matching noise that can still change the product, so a difference in one
#: of them is for a person to judge: "ground coriander" is not coriander, "extra
#: virgin olive oil" is not olive oil, "raw sugar" is not sugar.
_NOT_SURE = frozenset({
    "ground", "raw", "whole", "extra", "toasted", "cooked", "free", "range",
    "organic", "good", "quality", "flat",
    # bought that way as often as done at home: shredded coconut, slivered
    # almonds, tomato puree, crushed tomatoes, grated parmesan, minced garlic
    "shredded", "slivered", "slivers", "puree", "pureed", "crushed", "grated", "minced",
})
#: Words that never change what you buy.
SAME_WORDS: frozenset[str] = frozenset(
    fold_word(w)
    for w in (MATCH_NOISE | PREP_WORDS | SIZE_WORDS | UNIT_WORDS | {
        "divided", "firm", "ripe", "best", "note", "approx", "roughly", "packed", "torn",
        # temperature and serving
        "cold", "warm", "chilled", "iced", "serving", "dusting", "frying", "garnish", "garnishing",
        "steamed", "broken", "required", "needed", "such", "as", "well", "shaken", "other",
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
    "your", "on", "of", "with", "and", "or", "yet", "berries", "fruit",
))
#: Last words that name a part of the thing, not another thing: "coriander
#: leaves" may well be "coriander". For a person to say.
_PARTS = frozenset(fold_word(w) for w in (
    "leaf", "leaves", "stem", "stalk", "floret", "kernel", "segment", "seed", "pod",
))
#: "-ed" words that are a type of their own, not a way of cooking.
_ED_TYPES = frozenset({"thickened", "clotted", "seeded", "sparkling"})


@dataclass(frozen=True)
class Row:
    """A pantry row as the rule sees it."""

    ingredient: Ingredient
    #: Every word, folded, in key order ("Pear - Green" -> green, pear).
    words: tuple[str, ...]
    #: The words that are not `SAME_WORDS`: what the row *is*.
    core: tuple[str, ...]
    #: The row's own `prep_terms`, folded.
    prep: frozenset[str]

    @property
    def id(self) -> int:
        return self.ingredient.id

    @property
    def name(self) -> str:
        return self.ingredient.name


def words_of(text: str) -> tuple[str, ...]:
    """The folded words of a name, punctuation and bullets dropped."""
    cleaned = clean_name(text)
    words = cleaned.words or tuple(cleaned.display.lower().split())
    bare = (re.sub(r"^[\W_]+|[\W_]+$", "", w) for w in words)
    return tuple(fold_word(w) for w in bare if w)


def row_for(ingredient: Ingredient) -> Row:
    words = words_of(ingredient.name)
    prep: set[str] = set()
    for term in ingredient.prep_terms or []:
        prep.update(fold_word(w) for w in re.split(r"[\s/-]+", term.lower()) if w)
    return Row(ingredient, words, tuple(w for w in words if w not in SAME_WORDS), frozenset(prep))


# --------------------------------------------------------------------------
# The verdicts

CONFIDENT, REVIEW, APART = "confident", "review", "apart"


@dataclass(frozen=True)
class Verdict:
    kind: str
    keep: Row
    other: Row
    reason: str


def typed_base(core: tuple[str, ...]) -> tuple[str, ...] | None:
    """The `TYPED_BASES` word a name ends on, with the type in front of it, or
    None: ("green", "pear") -> ("pear",)."""
    if len(core) < 2 or core[-1] not in TYPED_BASES:
        return None
    if any(core[i:i + len(p)] == p for p in _NOT_A_TYPE for i in range(len(core))):
        return None
    return (core[-1],)


def judge(a: Row, b: Row, single_names: frozenset[str]) -> Verdict | None:
    """What the rule says about two rows, or None when they are unrelated
    (neither's core words contain the other's)."""
    ca, cb = set(a.core), set(b.core)
    if not ca or not cb:
        return None
    if ca == cb:
        return Verdict(CONFIDENT, a, b, "only preparation words differ")
    if ca < cb:
        small, big = a, b
    elif cb < ca:
        small, big = b, a
    else:
        return None
    extra = set(big.core) - set(small.core)
    if extra <= small.prep:
        return Verdict(CONFIDENT, small, big, f"{_list(extra)}: in {small.name!r}'s prep terms")
    product = extra & PRODUCT_FOLDS
    if product:
        return Verdict(APART, small, big, f"{_list(product)}: a different product")
    base = typed_base(big.core)
    if base and tuple(small.core) == base:
        compounds = extra & single_names
        if base[0] in _COMPOUND_SENSITIVE and compounds:
            return Verdict(APART, small, big, f"{_list(compounds)} {base[0]}: its own ingredient")
        if " - " in big.name:
            return Verdict(APART, small, big, f"a type of {base[0]}")
        if typed_name(big.ingredient, single_names):
            return Verdict(APART, small, big, f"a type of {base[0]}: see RENAMES")
    # The last word says what the thing is: "butter bean" is a bean, "cream
    # cheese" a cheese, "chicken thigh" a cut you buy as such.
    if big.core[-1] != small.core[-1] and big.core[-1] not in _PARTS:
        return Verdict(APART, small, big, f"a {big.core[-1]!r}, not a {small.core[-1]!r}")
    # Another ingredient in front: "milk chocolate easter egg" is not an egg.
    compounds = extra & single_names
    if compounds:
        return Verdict(APART, small, big, f"{_list(compounds)}: another ingredient")
    return Verdict(REVIEW, small, big, f"differs by {_list(extra)}")


def _list(words) -> str:
    return ", ".join(repr(w) for w in sorted(words))


@dataclass
class Report:
    confident: list[list[Row]]
    review: list[Verdict]
    apart: list[Verdict]
    alias_links: list[tuple[Row, str, Row]]
    no_core: list[Row]
    untouched: int


def classify(ingredients: list[Ingredient]) -> Report:
    rows = [row_for(i) for i in ingredients]
    single_names = frozenset(r.core[0] for r in rows if len(r.core) == 1)

    # Equal cores are an equivalence, so these groups never chain: each row has
    # exactly one core. That is the guarantee the alias-based grouping lacked.
    by_core: dict[frozenset[str], list[Row]] = defaultdict(list)
    for r in rows:
        if r.core:
            by_core[frozenset(r.core)].append(r)
    groups = {key: members for key, members in by_core.items() if len(members) > 1}
    grouped = {r.id for members in groups.values() for r in members}

    review: list[Verdict] = []
    apart: list[Verdict] = []
    # A bigger name that a smaller row's own prep terms explain joins that row's
    # group, but only when exactly one smaller row explains it.
    absorbed_by: dict[int, list[Row]] = defaultdict(list)
    seen_pairs: set[tuple[frozenset[str], frozenset[str]]] = set()
    representatives = [members[0] for members in by_core.values()]
    for a, b in combinations(representatives, 2):
        verdict = judge(a, b, single_names)
        if verdict is None or verdict.kind == CONFIDENT and set(a.core) == set(b.core):
            continue
        pair = (frozenset(verdict.keep.core), frozenset(verdict.other.core))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        if verdict.kind == CONFIDENT:
            absorbed_by[verdict.other.id].append(verdict.keep)
        elif verdict.kind == REVIEW:
            review.append(verdict)
        else:
            apart.append(verdict)

    for other_id, keepers in absorbed_by.items():
        other = next(r for r in representatives if r.id == other_id)
        best = max(len(k.core) for k in keepers)
        top = [k for k in keepers if len(k.core) == best]
        if len(top) > 1:
            review.append(Verdict(REVIEW, top[0], other, "prep terms of more than one row explain it"))
            continue
        keeper_key = frozenset(top[0].core)
        groups.setdefault(keeper_key, list(by_core[keeper_key]))
        groups[keeper_key].extend(by_core[frozenset(other.core)])
        groups.pop(frozenset(other.core), None)
        grouped.update(r.id for r in by_core[frozenset(other.core)])
        grouped.update(r.id for r in by_core[keeper_key])

    # Aliases: never confident, always shown with the alias that links them.
    by_core_id = {r.id: frozenset(r.core) for r in rows}
    alias_links: list[tuple[Row, str, Row]] = []
    for r in rows:
        for alias in r.ingredient.aliases or []:
            core = frozenset(w for w in words_of(alias) if w not in SAME_WORDS)
            for other in by_core.get(core, []):
                if other.id != r.id and by_core_id[other.id] != by_core_id[r.id]:
                    alias_links.append((r, alias, other))

    no_core = [r for r in rows if not r.core]
    mentioned = grouped | {v.keep.id for v in review + apart} | {v.other.id for v in review + apart}
    mentioned |= {r.id for r, _, o in alias_links} | {o.id for _, _, o in alias_links}
    mentioned |= {r.id for r in no_core}
    return Report(
        confident=[members for members in groups.values() if len(members) > 1],
        review=review,
        apart=apart,
        alias_links=alias_links,
        no_core=no_core,
        untouched=len([r for r in rows if r.id not in mentioned]),
    )


# --------------------------------------------------------------------------
# Renames: "green pear" -> "Pear - Green"

def typed_name(ingredient: Ingredient, single_names: frozenset[str]) -> str | None:
    """The `Name - Type` name for a type of fruit, vegetable, cream or wine, or
    None when the row is not one, or already is named that way."""
    if " - " in ingredient.name:
        return None
    row = row_for(ingredient)
    base = typed_base(row.core)
    if base is None:
        return None
    # Only a clean name: nothing but the type and the base, which is what makes
    # this safe to apply in bulk. "rind 2 lemon" or "handful kalamata olives"
    # stays as it is (and probably wants merging, not renaming).
    if row.words != row.core:
        return None
    qualifiers = row.core[: -len(base)]
    if not 1 <= len(qualifiers) <= 3:
        return None
    if set(qualifiers) & (PRODUCT_FOLDS | _NOT_SURE | _CONTAINERS | _NOT_TYPES):
        return None
    if any(len(q) > 4 and q.endswith(("ed", "ing")) and q not in _ED_TYPES for q in qualifiers):
        return None  # "stewed", "caramelised", "baking": how it is cooked or used, not a type
    if base[0] in _COMPOUND_SENSITIVE and set(qualifiers) & single_names:
        return None
    # Spell the words as the row does, not folded: "Beurre Bosc", "Roma".
    spelled = {fold_word(w): w for w in re.findall(r"[A-Za-z']+", ingredient.name.lower())}
    if not all(q in spelled for q in qualifiers) or not spelled.get(base[0]):
        return None
    if any(singular(spelled[q]) != spelled[q] for q in qualifiers):
        return None  # "plums peach", "berries cream": a list, not a type
    base_word = singular(spelled[base[0]])
    return f"{base_word.capitalize()} - {' '.join(spelled[q].capitalize() for q in qualifiers)}"


def rename_proposals(ingredients: list[Ingredient]) -> list[tuple[Ingredient, str]]:
    rows = [row_for(i) for i in ingredients]
    single_names = frozenset(r.core[0] for r in rows if len(r.core) == 1)
    out = []
    for ingredient in ingredients:
        new = typed_name(ingredient, single_names)
        if new and new != ingredient.name:
            out.append((ingredient, new))
    return out


def apply_renames(
    session: Session, renames: list[tuple[Ingredient, str]], taken: set[str]
) -> tuple[int, list[tuple[Ingredient, str]]]:
    """Rename, keeping the old name as an alias and the slug unchanged. A
    rename onto a name another row already has is skipped and returned.
    Returns (renamed, skipped)."""
    renamed, skipped = 0, []
    for ingredient, new_name in renames:
        if new_name.lower() in taken:
            skipped.append((ingredient, new_name))
            continue
        taken.discard(ingredient.name.lower())
        taken.add(new_name.lower())
        aliases = {a.lower() for a in (ingredient.aliases or [])}
        aliases.add(ingredient.name.lower())
        aliases.discard(new_name.lower())
        ingredient.aliases = sorted(aliases)
        ingredient.name = new_name
        session.add(ingredient)
        renamed += 1
    session.commit()
    return renamed, skipped


# --------------------------------------------------------------------------
# Merging

def usage_counts(session: Session) -> dict[int, int]:
    rows = session.exec(
        select(RecipeIngredient.ingredient_id, func.count())
        .where(RecipeIngredient.ingredient_id.is_not(None))
        .group_by(RecipeIngredient.ingredient_id)
    ).all()
    return dict(rows)


def keeper_first(group: list[Row], usage: dict[int, int]) -> list[Row]:
    """The row used in the most recipes first; then the plainest name."""
    return sorted(group, key=lambda r: (-usage.get(r.id, 0), len(r.core), len(r.words), r.id))


def _mangled(name: str) -> bool:
    return any(repair(w) != w for w in re.findall(r"[a-z]+", name.lower()))


def merge_groups(session: Session, groups: list[list[Row]], usage: dict[int, int]) -> int:
    """Merge each group into its keeper, one commit per group. If another
    member has a plainer name with the same core ("onion" next to a busier
    "med onion"), the keeper takes that name and keeps its own as an alias.
    Returns how many rows were absorbed."""
    merged = 0
    for group in groups:
        ordered = keeper_first(group, usage)
        keep = ordered[0]
        # The shortest name, and a correctly spelled one over "cherrie".
        plainest = min(ordered, key=lambda r: (len(r.words), _mangled(r.name), r.id))
        new_name = plainest.name if set(plainest.core) == set(keep.core) else keep.name
        for other in ordered[1:]:
            _merge_into(session, keep.ingredient, other.ingredient)
            merged += 1
        if new_name != keep.ingredient.name:
            aliases = {a.lower() for a in keep.ingredient.aliases or []}
            aliases.add(keep.ingredient.name.lower())
            aliases.discard(new_name.lower())
            keep.ingredient.aliases = sorted(aliases)
            keep.ingredient.name = new_name
            session.add(keep.ingredient)
        session.commit()
    return merged


# --------------------------------------------------------------------------
# Mangled plurals ("tomatoe", "cherrie")

def corpus_words(session: Session, ingredients: list[Ingredient]) -> set[str]:
    """Every word in the pantry's names and aliases and in the recipe lines:
    the household's own vocabulary, which is what decides whether a word that
    looks mangled really is."""
    texts = [n for i in ingredients for n in (i.name, *(i.aliases or []))]
    texts += list(session.exec(select(RecipeIngredient.name)).all())
    return {w.lower() for text in texts for w in re.findall(r"[A-Za-z]+", text or "")}


def name_repairs(
    ingredients: list[Ingredient], corpus: set[str]
) -> list[tuple[Ingredient, str]]:
    """Pantry rows whose name carries a plural the original rule mangled
    ("tomatoe", "cherrie", "peache"), with the name they should have.

    A word is only repaired when its repaired form turns up somewhere else in
    the corpus: "cherrie" -> "cherry" because "cherry" and "cherries" are in
    the recipes, but "Marie" is left alone because nothing says "Mary".
    """
    by_fold: dict[str, set[str]] = defaultdict(set)
    for word in corpus:
        by_fold[fold_word(word)].add(word)

    def fix(match: re.Match) -> str:
        word = match.group(0)
        lower = word.lower()
        repaired = repair(lower)
        if repaired == lower or not (by_fold.get(repaired, set()) - {lower}):
            return word
        return repaired.capitalize() if word[:1].isupper() else repaired

    repairs = []
    for ingredient in ingredients:
        new_name = re.sub(r"[A-Za-z]+", fix, ingredient.name)
        if new_name != ingredient.name:
            repairs.append((ingredient, new_name))
    return repairs


apply_name_repairs = apply_renames


# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--min-usage", type=int, default=0,
        help="leave out items where no row is used in at least this many recipes",
    )
    parser.add_argument("--merge", action="store_true", help="merge every CONFIDENT group")
    parser.add_argument("--rename", action="store_true", help='apply the RENAMES list ("Pear - Green")')
    parser.add_argument(
        "--fix-names", action="store_true",
        help='rename rows whose name carries a mangled plural ("tomatoe" -> "tomato")',
    )
    args = parser.parse_args()

    with Session(engine) as session:
        ingredients = list(session.exec(select(Ingredient)).all())
        usage = usage_counts(session)

        def label(row) -> str:
            ingredient = row.ingredient if isinstance(row, Row) else row
            count = usage.get(ingredient.id, 0)
            return f"{ingredient.name!r} (#{ingredient.id}, {count} recipe{'s' if count != 1 else ''})"

        def wanted(*rows) -> bool:
            return args.min_usage == 0 or any(usage.get(r.id, 0) >= args.min_usage for r in rows)

        report = classify(ingredients)
        print(f"{len(ingredients)} pantry ingredient(s) scanned.\n")

        confident = [g for g in report.confident if wanted(*g)]
        print(f"CONFIDENT: merge, only preparation differs ({len(confident)} group(s))\n")
        for group in confident:
            ordered = keeper_first(group, usage)
            print(f"  keep {label(ordered[0])}")
            for other in ordered[1:]:
                print(f"    ← {label(other)}")
        if not confident:
            print("  none")

        review = [v for v in report.review if wanted(v.keep, v.other)]
        links = [link for link in report.alias_links if wanted(link[0], link[2])]
        no_core = [r for r in report.no_core if wanted(r)]
        print(f"\nREVIEW: a person decides ({len(review) + len(links) + len(no_core)} item(s))\n")
        for v in sorted(review, key=lambda v: (v.keep.name.lower(), v.other.name.lower())):
            print(f"  {label(v.keep)}  vs  {label(v.other)}: {v.reason}")
        for row, alias, other in links:
            print(f"  {label(row)} has the alias {alias!r}, which is {label(other)}: merge them, or remove the alias")
        for row in no_core:
            print(f"  {label(row)}: the name is only preparation words; rename or delete it")
        if not (review or links or no_core):
            print("  none")

        renames = [(i, n) for i, n in rename_proposals(ingredients) if wanted(i)]
        print(f"\nRENAMES: Name - Type ({len(renames)} row(s))\n")
        for ingredient, new_name in renames:
            print(f"  {label(ingredient)}  →  {new_name!r}")
        if not renames:
            print("  none")

        apart = [v for v in report.apart if wanted(v.keep, v.other)]
        print(f"\nUNCHANGED: related but different ({len(apart)} pair(s)), "
              f"and {report.untouched} row(s) with no near match\n")
        for v in sorted(apart, key=lambda v: (v.keep.name.lower(), v.other.name.lower())):
            print(f"  {label(v.keep)}  ≠  {label(v.other)}: {v.reason}")

        # Labels are printed above, before merging: `_merge_into` deletes rows.
        if confident and args.merge:
            print(f"\nMerged {merge_groups(session, confident, usage)} row(s) into their group's keeper.")
        elif confident:
            print("\n  (nothing merged: pass --merge once the CONFIDENT list looks right)")

        if renames and args.rename:
            ingredients = list(session.exec(select(Ingredient)).all())
            current = {i.id for i in ingredients}
            todo = [(i, n) for i, n in renames if i.id in current]
            renamed, skipped = apply_renames(session, todo, {i.name.lower() for i in ingredients})
            print(f"Renamed {renamed} row(s); the old names are kept as aliases.")
            for ingredient, new_name in skipped:
                print(f"  skipped {ingredient.name!r}: a row named {new_name!r} already exists")
        elif renames:
            print("  (nothing renamed: pass --rename)")

        # Re-read: merges and renames changed rows.
        ingredients = list(session.exec(select(Ingredient)).all())
        repairs = name_repairs(ingredients, corpus_words(session, ingredients))
        print(f"\nMANGLED NAMES ({len(repairs)} row(s))\n")
        for ingredient, new_name in repairs:
            print(f"  {label(ingredient)}  →  {new_name!r}")
        if repairs and args.fix_names:
            renamed, skipped = apply_renames(session, repairs, {i.name.lower() for i in ingredients})
            print(f"\nRenamed {renamed} row(s); the old names are kept as aliases.")
            for ingredient, new_name in skipped:
                print(f"  skipped {ingredient.name!r}: a row named {new_name!r} already exists; merge them first")
        elif repairs:
            print("\n  (not renamed: pass --fix-names; the old name is kept as an alias)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
