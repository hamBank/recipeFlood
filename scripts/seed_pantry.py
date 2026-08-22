#!/usr/bin/env python3
"""Fill in densities, per-piece weights and rough prices for common items.

    python scripts/seed_pantry.py           # merge into existing rows
    python scripts/seed_pantry.py --overwrite

Loading the blog creates hundreds of bare ingredient stubs. This adds the
conversion data for the ones that appear most often, which is what turns
"2 cups plain flour" into 300g — and therefore into a cost and a nutrition
contribution — across the whole collection at once.

Merges by default: an existing row keeps every value it already has, and
only its blanks are filled. That way running this after someone has priced
their own pantry doesn't overwrite their figures. `--overwrite` reverses
that for a deliberate reset.

Prices are rough Australian supermarket figures meant to be corrected on
the Pantry page. Nutrition is deliberately absent — enter it from the
packets you actually buy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from backend.database import engine  # noqa: E402
from backend.models import Ingredient, IngredientSource, utcnow  # noqa: E402
from backend.recipes_service import find_ingredient  # noqa: E402
from backend.routers.ingredients import _reconvert_lines  # noqa: E402
from backend.slugs import unique_slug  # noqa: E402

PANTRY_PATH = Path(__file__).resolve().parent.parent / "data" / "pantry.json"

FIELDS = (
    "density_g_per_ml",
    "grams_per_piece",
    "package_size_grams",
    "cost_per_kg_cents",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace existing values instead of only filling blanks",
    )
    args = parser.parse_args()

    definitions = json.loads(PANTRY_PATH.read_text())["ingredients"]
    created = updated = 0

    with Session(engine) as session:
        for definition in definitions:
            name = definition["name"]
            ingredient = find_ingredient(session, name)
            if ingredient is None:
                slug = unique_slug(
                    name,
                    lambda s: session.exec(
                        select(Ingredient).where(Ingredient.slug == s)
                    ).first()
                    is not None,
                )
                ingredient = Ingredient(slug=slug, name=name, aliases=[])
                session.add(ingredient)
                session.flush()
                created += 1
            else:
                updated += 1

            for field in FIELDS:
                value = definition.get(field)
                if value is None:
                    continue
                if args.overwrite or getattr(ingredient, field) is None:
                    setattr(ingredient, field, value)

            if definition.get("source"):
                ingredient.source = IngredientSource(definition["source"])

            # Aliases accumulate: the importer may have already learned some.
            aliases = {a.lower() for a in (ingredient.aliases or [])}
            aliases.update(a.lower() for a in definition.get("aliases", []))
            aliases.discard(ingredient.name.lower())
            ingredient.aliases = sorted(aliases)
            ingredient.updated_at = utcnow()
            session.add(ingredient)
            session.flush()

            # Recipes already loaded should pick the new density up now.
            _reconvert_lines(session, ingredient)

        session.commit()

    print(f"pantry: {created} ingredients created, {updated} updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
