"""Cooking lists: read projection and the bridge to the shopping list.

A cooking list is a date plus some recipes. The only non-obvious part is
scaling: an entry can ask for a different number of serves than the recipe
was written for, and the factor is derived live from `Recipe.servings`
rather than stored, so correcting a recipe's serving size later fixes every
list that used it.

Many recipes — most of the scraped ones — have no serving size at all. Those
entries report `scalable: false` and a factor of 1.0. The list still works;
it just says it cannot scale that one, which is better than multiplying by
a number nobody supplied.
"""

from __future__ import annotations

from sqlmodel import Session, select

from .models import (
    CookList,
    CookListRead,
    CookListRecipe,
    CookListRecipeRead,
    Recipe,
    RecipeIngredient,
)
from .shopping import scale_factor


def _recipe_map(session: Session, entries: list[CookListRecipe]) -> dict[int, Recipe]:
    ids = {e.recipe_id for e in entries}
    if not ids:
        return {}
    rows = session.exec(select(Recipe).where(Recipe.id.in_(ids))).all()
    return {row.id: row for row in rows}


def entries_of(session: Session, cook_list_id: int) -> list[CookListRecipe]:
    return list(
        session.exec(
            select(CookListRecipe)
            .where(CookListRecipe.cook_list_id == cook_list_id)
            .order_by(CookListRecipe.position, CookListRecipe.id)
        ).all()
    )


def cook_list_read(session: Session, cook_list: CookList) -> CookListRead:
    entries = entries_of(session, cook_list.id)
    recipes = _recipe_map(session, entries)

    rows: list[CookListRecipeRead] = []
    for entry in entries:
        recipe = recipes.get(entry.recipe_id)
        if recipe is None:
            # The recipe was deleted out from under the list. Skip rather
            # than 500 — a stale membership row must not break the page.
            continue
        factor, scalable = scale_factor(recipe, entry.servings)
        rows.append(
            CookListRecipeRead(
                id=entry.id,
                recipe_id=entry.recipe_id,
                position=entry.position,
                servings=entry.servings,
                note=entry.note,
                slug=recipe.slug,
                title=recipe.title,
                image_path=recipe.image_path,
                base_servings=recipe.servings,
                scalable=scalable,
                scale_factor=round(factor, 4),
            )
        )

    return CookListRead(
        id=cook_list.id,
        cook_date=cook_list.cook_date,
        description=cook_list.description,
        notes=cook_list.notes,
        created_at=cook_list.created_at,
        updated_at=cook_list.updated_at,
        recipe_count=len(rows),
        recipes=rows,
    )


def shopping_lines(
    session: Session, cook_list_id: int
) -> list[tuple[RecipeIngredient, Recipe, float]]:
    """Every ingredient line the list implies, each with its scale factor.

    Feeds `shopping.add_lines`. Returned in list order so the shopping list
    reflects the order the cooking was planned in.
    """
    entries = entries_of(session, cook_list_id)
    recipes = _recipe_map(session, entries)

    lines: list[tuple[RecipeIngredient, Recipe, float]] = []
    for entry in entries:
        recipe = recipes.get(entry.recipe_id)
        if recipe is None:
            continue
        factor, _ = scale_factor(recipe, entry.servings)
        for line in session.exec(
            select(RecipeIngredient)
            .where(RecipeIngredient.recipe_id == recipe.id)
            .order_by(RecipeIngredient.position, RecipeIngredient.id)
        ).all():
            lines.append((line, recipe, factor))
    return lines
