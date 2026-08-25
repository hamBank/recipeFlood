#!/usr/bin/env python3
"""Find pantry ingredients that are probably the same thing typed
differently, and suggest which to merge.

    python -m scripts.find_duplicate_ingredients
    python -m scripts.find_duplicate_ingredients --min-usage 1

Importing the blog, a shopping-list CSV and years of cooking history each
create one pantry row per distinct phrase they saw (see SPEC.md "The
master ingredient list"), so the same real ingredient routinely ends up
as several rows — "egg" / "eggs" / "large eggs", "onion" / "red onion" /
"brown onions" — each with its own separate, incomplete price and
nutrition. `find_ingredient` (backend/recipes_service.py) already stops
*exact* re-matches at creation time, but only checks a new name's slug
and normalised form against each existing row's *slug* and explicit
*aliases* — never against another row's own name — so two rows created
independently, in different import runs, with phrasing that normalises
to the same thing but was never spelled identically, slip through as two
rows instead of one.

This script never merges anything itself — a wrong auto-merge would
silently point some recipes' cost and nutrition at the wrong ingredient,
and that is not a call a heuristic gets to make. It only prints
candidates, in two tiers:

  **Exact matches** — rows whose name (or alias) reduces to the exact
  same normalised core via the app's own `normalise_ingredient_name`
  (the noise-word/plural stripping that already backs recipe-line
  matching, e.g. "Eggs" and "Large Eggs" both reduce to "egg"). About as
  close to certain as this gets.

  **Qualified variants** — one ingredient's normalised words are a
  *subset* of the other's, e.g. "onion" ⊂ "red onion", "capsicum" ⊂ "red
  capsicum". Still needs a human's judgement — a household might
  genuinely want "butter" priced separately from "peanut butter" — but
  this catches the shape SPEC.md's own example describes ("onion" / "red
  onion" / "onions") without the false positives a plain spelling-
  similarity score turns out to produce at this word length: character
  similarity alone scores "salt" against "malt" *higher* than it scores
  "hand soap" against "handwash", an actual duplicate — short ingredient
  names are just too short for that to discriminate reliably, so this
  script doesn't use it.

Merge a suggested pair from the Pantry page's own "Merge" button, or:

    curl -X POST /ingredients/<keep-slug>/merge/<absorb-slug>

`--min-usage` drops pairs where neither side is used in any recipe yet —
mostly shopping-list-only stubs, where a wrong merge costs nothing to
undo but a long list of them is just noise while you're working through
the ones that actually matter.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, func, select  # noqa: E402

from backend.database import engine  # noqa: E402
from backend.models import Ingredient, RecipeIngredient  # noqa: E402
from backend.recipes_service import normalise_ingredient_name  # noqa: E402


def usage_counts(session: Session) -> dict[int, int]:
    rows = session.exec(
        select(RecipeIngredient.ingredient_id, func.count())
        .where(RecipeIngredient.ingredient_id.is_not(None))
        .group_by(RecipeIngredient.ingredient_id)
    ).all()
    return dict(rows)


def normalised_keys(ingredient: Ingredient) -> set[str]:
    """Every normalised form this ingredient could be found under — its
    own name, plus each alias."""
    keys = {normalise_ingredient_name(ingredient.name)}
    keys.update(normalise_ingredient_name(a) for a in ingredient.aliases or [])
    keys.discard("")
    return keys


def find_exact_groups(ingredients: list[Ingredient]) -> list[list[Ingredient]]:
    """Ingredients that share a normalised key — about as close to a
    certain duplicate as text alone can show."""
    by_key: dict[str, list[Ingredient]] = defaultdict(list)
    for ingredient in ingredients:
        for key in normalised_keys(ingredient):
            by_key[key].append(ingredient)

    groups: list[list[Ingredient]] = []
    seen_ids: set[int] = set()
    for members in by_key.values():
        ids = {m.id for m in members}
        if len(ids) < 2 or ids <= seen_ids:
            continue
        groups.append(members)
        seen_ids |= ids
    return groups


def find_qualified_variants(
    ingredients: list[Ingredient], exclude_ids: set[int]
) -> list[tuple[Ingredient, Ingredient]]:
    """Pairs where one's normalised words are a subset of the other's —
    "onion" vs "red onion", not "salt" vs "malt". O(n^2), fine at pantry
    scale (a few hundred rows — same reasoning as
    recipes_service.same_season_recipe_ids)."""
    candidates = [i for i in ingredients if i.id not in exclude_ids]
    tokens = {i.id: set(normalise_ingredient_name(i.name).split()) for i in candidates}
    pairs: list[tuple[Ingredient, Ingredient]] = []
    for a, b in combinations(candidates, 2):
        ta, tb = tokens[a.id], tokens[b.id]
        if ta and tb and ta != tb and (ta <= tb or tb <= ta):
            pairs.append((a, b))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--min-usage",
        type=int,
        default=0,
        help="skip a pair when neither side is used in any recipe at least this many times",
    )
    args = parser.parse_args()

    with Session(engine) as session:
        ingredients = list(session.exec(select(Ingredient)).all())
        usage = usage_counts(session)

        def label(ingredient: Ingredient) -> str:
            count = usage.get(ingredient.id, 0)
            return f"{ingredient.name!r} (#{ingredient.id}, used in {count} recipe{'s' if count != 1 else ''})"

        def worth_reporting(members: list[Ingredient]) -> bool:
            return args.min_usage == 0 or any(usage.get(m.id, 0) >= args.min_usage for m in members)

        print(f"{len(ingredients)} pantry ingredient(s) scanned.\n")

        all_exact_groups = find_exact_groups(ingredients)
        exact_groups = [g for g in all_exact_groups if worth_reporting(g)]
        exact_ids = {m.id for group in all_exact_groups for m in group}

        if not exact_groups:
            print("No exact-normalised-match duplicates found.")
        else:
            print(f"EXACT MATCHES — {len(exact_groups)} group(s):\n")
            for group in exact_groups:
                group = sorted(group, key=lambda m: usage.get(m.id, 0), reverse=True)
                print(f"  keep {label(group[0])}")
                for other in group[1:]:
                    print(f"    ← merge {label(other)}")
                print()

        variants = [
            (a, b)
            for a, b in find_qualified_variants(ingredients, exact_ids)
            if worth_reporting([a, b])
        ]
        print(f"\nQUALIFIED VARIANTS — {len(variants)} pair(s):\n")
        for a, b in variants:
            shorter, longer = (a, b) if len(a.name) <= len(b.name) else (b, a)
            print(f"  {label(shorter)}  ⊂  {label(longer)}")

        if not exact_groups and not variants:
            print("\nNothing found — the pantry looks clean.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
