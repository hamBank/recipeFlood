"""Recipe costing from the master ingredient list.

Costs are never public (see SPEC.md "Visibility") — the routers attach the
result of this module only for signed-in callers.

Prices live as integer cents per kilogram on `Ingredient` — or, for an
ingredient with `measure_kind == volume` (most liquids: milk, stock, oil,
wine), integer cents per litre. A weight-priced line costs
`weight_grams / 1000 * cost_per_kg_cents`; a volume-priced line costs
`volume_ml / 1000 * cost_per_litre_cents`. Same arithmetic either way, just
a different amount and price feeding it, and the only rounding happens
once at the end.

Which basis applies is decided by `measure_kind`, not by which fields
happen to be set: a volume ingredient with a leftover `cost_per_kg_cents`
from before it was reclassified is not read as a weight price.
"""

from __future__ import annotations

from sqlmodel import Session

from .models import Ingredient, MeasureKind, RecipeCost, RecipeIngredient


def cost_per_gram(ingredient: Ingredient) -> float | None:
    """Dollars per gram — display only; never used for arithmetic."""
    if ingredient.cost_per_kg_cents is None:
        return None
    return round(ingredient.cost_per_kg_cents / 100_000, 5)


def cost_per_ml(ingredient: Ingredient) -> float | None:
    """Dollars per millilitre — display only; never used for arithmetic."""
    if ingredient.cost_per_litre_cents is None:
        return None
    return round(ingredient.cost_per_litre_cents / 100_000, 5)


def package_cost_cents(ingredient: Ingredient) -> int | None:
    """What one usual package costs, for the shopping-list view.

    Reads whichever basis matches `measure_kind`; the other pair of fields
    (if set) is ignored, for the same reason `line_cost_cents` ignores it
    below.
    """
    if ingredient.measure_kind == MeasureKind.volume:
        if ingredient.cost_per_litre_cents is None or not ingredient.package_size_ml:
            return None
        return round(ingredient.cost_per_litre_cents * ingredient.package_size_ml / 1000)
    if ingredient.cost_per_kg_cents is None or not ingredient.package_size_grams:
        return None
    return round(ingredient.cost_per_kg_cents * ingredient.package_size_grams / 1000)


def amount_cost_cents(
    ingredient: Ingredient | None,
    *,
    weight_grams: float | None = None,
    volume_ml: float | None = None,
) -> int | None:
    """Cost of an amount of an ingredient, on whichever basis it prices by.

    Shared by `line_cost_cents` below and `shopping.item_cost_cents`, which
    face the same choice for a `RecipeIngredient` and a `ShoppingItem`
    respectively — keeping the measure_kind branch in one place means the
    two can't quietly drift apart on how a volume ingredient gets priced.
    """
    if ingredient is None:
        return None
    if ingredient.measure_kind == MeasureKind.volume:
        if ingredient.cost_per_litre_cents is None or not volume_ml:
            return None
        return round(volume_ml / 1000 * ingredient.cost_per_litre_cents)
    if ingredient.cost_per_kg_cents is None or not weight_grams:
        return None
    return round(weight_grams / 1000 * ingredient.cost_per_kg_cents)


def line_cost_cents(
    line: RecipeIngredient, ingredient: Ingredient | None
) -> int | None:
    """Cost of one ingredient line, or None if it can't be priced."""
    return amount_cost_cents(
        ingredient, weight_grams=line.weight_grams, volume_ml=line.volume_ml
    )


def compute_cost(
    session: Session,
    lines: list[RecipeIngredient],
    *,
    servings: int | None = None,
) -> tuple[RecipeCost, dict[int, int]]:
    """Total a recipe's cost.

    Returns (summary, {recipe_ingredient_id: cents}) so the caller can show
    a per-line breakdown without re-deriving it. `known_fraction` reports
    how much of the ingredient list actually had a price — a $3.40 total
    built from 4 of 12 ingredients is a floor, not an answer, and the UI
    labels it as such.
    """
    ingredient_ids = {line.ingredient_id for line in lines if line.ingredient_id}
    cache: dict[int, Ingredient] = {}
    for ingredient_id in ingredient_ids:
        ingredient = session.get(Ingredient, ingredient_id)
        if ingredient is not None:
            cache[ingredient_id] = ingredient

    per_line: dict[int, int] = {}
    total = 0
    priced = 0
    countable = 0
    for line in lines:
        if line.optional:
            continue
        countable += 1
        ingredient = cache.get(line.ingredient_id) if line.ingredient_id else None
        cents = line_cost_cents(line, ingredient)
        if cents is None:
            continue
        priced += 1
        total += cents
        if line.id is not None:
            per_line[line.id] = cents

    summary = RecipeCost(
        total_cents=total,
        per_serving_cents=round(total / servings) if servings and servings > 0 else None,
        known_fraction=(priced / countable) if countable else 0.0,
        priced_count=priced,
        ingredient_count=countable,
    )
    return summary, per_line
