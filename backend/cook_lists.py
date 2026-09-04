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
    PreparedEvent,
    Recipe,
    RecipeIngredient,
)
from .shopping import scale_factor

#: The `description` scripts/import_recipe_history.py stamps on every
#: CookList it creates or extends. Shared here (rather than living only in
#: the script) so the API can filter these out too — see
#: `list_cook_lists`'s `exclude_imported`: a cooking-history import can
#: create hundreds of these, backdated close to "now" by definition (that
#: was the household's last real cooked-something), and a plain
#: newest-first sort would otherwise happily hand quick-add one of them
#: instead of the list someone is actually planning.
IMPORTED_COOK_LIST_DESCRIPTION = "Cooking history import"


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

    # entries_of keeps its own (position, id) order, since that's also
    # what shopping_lines uses and insertion order doesn't matter there.
    # Here, for display, completed recipes sink below the still-to-cook
    # ones — same idea as the shopping list ticking checked items down —
    # while a stable sort keeps everything else in its planned order.
    entries = sorted(entries, key=lambda e: e.completed)

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
                completed=entry.completed,
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
        completed=cook_list.completed,
        created_at=cook_list.created_at,
        updated_at=cook_list.updated_at,
        recipe_count=len(rows),
        recipes=rows,
    )


def sync_prepared_event(
    session: Session, cook_list: CookList, recipe_id: int, user_id: int | None
) -> None:
    """A recipe joining (or staying on) a list is "we're cooking this on
    the list's date" — so it gets a `PreparedEvent` dated to `cook_date`,
    linked back to the list so later edits keep it in step. Idempotent:
    calling it again for the same (recipe, list) just refreshes the date
    rather than logging a second cook.
    """
    event = session.exec(
        select(PreparedEvent).where(
            PreparedEvent.recipe_id == recipe_id,
            PreparedEvent.cook_list_id == cook_list.id,
        )
    ).first()
    if event is None:
        session.add(
            PreparedEvent(
                recipe_id=recipe_id,
                prepared_on=cook_list.cook_date,
                user_id=user_id,
                cook_list_id=cook_list.id,
            )
        )
    elif event.prepared_on != cook_list.cook_date:
        event.prepared_on = cook_list.cook_date
        session.add(event)


def unlink_prepared_event(session: Session, cook_list_id: int, recipe_id: int) -> None:
    """Undo `sync_prepared_event` when a recipe leaves a list — the entry
    it auto-logged no longer reflects a real plan."""
    event = session.exec(
        select(PreparedEvent).where(
            PreparedEvent.recipe_id == recipe_id,
            PreparedEvent.cook_list_id == cook_list_id,
        )
    ).first()
    if event is not None:
        session.delete(event)


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
