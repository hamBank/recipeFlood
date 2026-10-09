#!/usr/bin/env python3
"""One-off recompute of stored weights for sprig, bunch and can lines.

    python scripts/reconvert_unit_weights.py
    python scripts/reconvert_unit_weights.py --dry-run

`units.to_grams` used to weigh "6 sprigs lemon thyme" by the ingredient
name — six lemons, 600g — and "1 can tomatoes" as one tomato. It now lets
those units set the weight themselves (see the units module docstring),
but a recipe line keeps the weight computed when it was saved. This runs
every such line back through `to_grams`, skipping weights a recipe stated
outright, so stored recipes match what a fresh save would give.

Safe to re-run: a line already matching the current conversion is left
alone.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from backend.database import engine  # noqa: E402
from backend.models import (  # noqa: E402
    Ingredient,
    MeasureUnit,
    Recipe,
    RecipeIngredient,
    WeightSource,
)
from backend.units import to_grams  # noqa: E402

UNITS = (MeasureUnit.sprig, MeasureUnit.bunch, MeasureUnit.can)


def reconvert(session: Session) -> list[tuple[RecipeIngredient, float | None, float | None]]:
    """Recompute every non-explicit sprig/bunch/can line's weight. Returns
    (line, old grams, new grams) for each line that changed."""
    lines = session.exec(
        select(RecipeIngredient).where(
            RecipeIngredient.unit.in_(UNITS),
            RecipeIngredient.weight_source != WeightSource.explicit,
        )
    ).all()
    changed = []
    for line in lines:
        ingredient = session.get(Ingredient, line.ingredient_id) if line.ingredient_id else None
        recipe = session.get(Recipe, line.recipe_id)
        grams, source = to_grams(
            line.quantity,
            line.unit,
            line.name,
            density_g_per_ml=ingredient.density_g_per_ml if ingredient else None,
            grams_per_piece=ingredient.grams_per_piece if ingredient else None,
            system=recipe.units_system if recipe else "au",
        )
        if grams == line.weight_grams and source == line.weight_source:
            continue
        changed.append((line, line.weight_grams, grams))
        line.weight_grams = grams
        line.weight_source = source
        session.add(line)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with Session(engine) as session:
        changed = reconvert(session)
        for line, old, new in changed:
            print(f"  recipe {line.recipe_id}: {line.raw_text!r}  {old} g -> {new} g")
        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    prefix = "dry run: " if args.dry_run else ""
    print(f"{prefix}{len(changed)} recipe lines reconverted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
