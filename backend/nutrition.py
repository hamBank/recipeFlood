"""Recipe nutrition, computed from the master ingredient list.

Nothing nutritional is stored on a recipe. Every panel is summed on read
from the linked `Ingredient` rows, so filling in one ingredient's numbers
immediately improves every recipe that uses it — which is the whole point
of having a master list.

The honest-reporting rule: an ingredient contributes only if it is linked
to a master ingredient, that ingredient has nutrition data, and the recipe
line has a weight in grams. Everything else is counted in `total_grams` but
not in `covered_grams`, and the resulting `coverage` fraction is what stops
a panel built from 3 of 14 ingredients from looking authoritative.
"""

from __future__ import annotations

from sqlmodel import Session

from .models import Ingredient, NutritionRead, RecipeIngredient

#: kJ and kcal are not independently measured — a food label computes one
#: from the other by this fixed factor. Kept here as the single home for
#: it: backend/afcd.py derives kcal from the government data's kJ figure;
#: backend/ingredient_enrichment.py derives kJ from Claude's kcal estimate.
#: Trusting a source to state both and have them agree is a needless way
#: to fail when one can simply be computed from the other.
KJ_PER_KCAL = 4.184


def kcal_from_kj(energy_kj: float | None) -> float | None:
    return round(energy_kj / KJ_PER_KCAL, 1) if energy_kj is not None else None


def kj_from_kcal(calories_kcal: float | None) -> float | None:
    return round(calories_kcal * KJ_PER_KCAL) if calories_kcal is not None else None


#: Per-100g fields summed across ingredients.
NUTRIENT_FIELDS = (
    "energy_kj",
    "calories_kcal",
    "protein_g",
    "fat_g",
    "saturated_fat_g",
    "carbs_g",
    "sugars_g",
    "fibre_g",
    "sodium_mg",
)


def has_nutrition(ingredient: Ingredient) -> bool:
    """True if any per-100g figure has been filled in."""
    return any(getattr(ingredient, field) is not None for field in NUTRIENT_FIELDS)


def compute_nutrition(
    session: Session,
    lines: list[RecipeIngredient],
    *,
    servings: int | None = None,
) -> tuple[NutritionRead, NutritionRead | None]:
    """Sum nutrition over a recipe's ingredient lines.

    Returns (whole recipe, per serving). The per-serving figure is None when
    the recipe doesn't record servings — dividing by a guess would be worse
    than showing nothing.
    """
    totals: dict[str, float] = {field: 0.0 for field in NUTRIENT_FIELDS}
    seen: dict[str, bool] = {field: False for field in NUTRIENT_FIELDS}
    total_grams = 0.0
    covered_grams = 0.0

    # One lookup per distinct ingredient rather than per line: a recipe that
    # lists butter three times shouldn't cost three queries.
    ingredient_ids = {line.ingredient_id for line in lines if line.ingredient_id}
    cache: dict[int, Ingredient] = {}
    for ingredient_id in ingredient_ids:
        ingredient = session.get(Ingredient, ingredient_id)
        if ingredient is not None:
            cache[ingredient_id] = ingredient

    for line in lines:
        if line.optional or not line.weight_grams:
            continue
        total_grams += line.weight_grams
        ingredient = cache.get(line.ingredient_id) if line.ingredient_id else None
        if ingredient is None or not has_nutrition(ingredient):
            continue
        covered_grams += line.weight_grams
        hundreds = line.weight_grams / 100.0
        for field in NUTRIENT_FIELDS:
            value = getattr(ingredient, field)
            if value is not None:
                totals[field] += value * hundreds
                seen[field] = True

    whole = NutritionRead(
        coverage=(covered_grams / total_grams) if total_grams else 0.0,
        covered_grams=round(covered_grams, 1),
        total_grams=round(total_grams, 1),
        **{
            field: round(totals[field], 2) if seen[field] else None
            for field in NUTRIENT_FIELDS
        },
    )

    if not servings or servings <= 0:
        return whole, None

    per_serving = NutritionRead(
        coverage=whole.coverage,
        covered_grams=round(covered_grams / servings, 1),
        total_grams=round(total_grams / servings, 1),
        per_serving=True,
        **{
            field: round(totals[field] / servings, 2) if seen[field] else None
            for field in NUTRIENT_FIELDS
        },
    )
    return whole, per_serving
