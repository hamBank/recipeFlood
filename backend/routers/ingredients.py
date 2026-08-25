"""The master ingredient list.

Every endpoint here requires a signed-in user, without exception: this
table is where cost lives, and costs are not public (SPEC.md
"Visibility"). Public pages get ingredient *names* through the recipe
endpoints, never this router.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session, func, or_, select

from ..costing import cost_per_gram, cost_per_ml, package_cost_cents
from ..database import get_session
from ..models import (
    Ingredient,
    IngredientCreate,
    IngredientRead,
    IngredientUpdate,
    Recipe,
    RecipeIngredient,
    ShoppingItem,
    User,
    utcnow,
)
from ..nutrition import NUTRIENT_FIELDS, has_nutrition
from ..permissions import require_admin_role, require_user_role
from ..recipes_service import find_ingredient
from ..slugs import unique_slug
from ..units import to_grams

router = APIRouter(prefix="/ingredients", tags=["ingredients"])


def _read(session: Session, ingredient: Ingredient, recipe_count: int = 0) -> IngredientRead:
    return IngredientRead(
        **ingredient.model_dump(),
        cost_per_gram=cost_per_gram(ingredient),
        cost_per_ml=cost_per_ml(ingredient),
        package_cost_cents=package_cost_cents(ingredient),
        has_nutrition=has_nutrition(ingredient),
        recipe_count=recipe_count,
    )


def _usage_counts(session: Session) -> dict[int, int]:
    return dict(
        session.exec(
            select(
                RecipeIngredient.ingredient_id,
                func.count(func.distinct(RecipeIngredient.recipe_id)),
            )
            .where(RecipeIngredient.ingredient_id.is_not(None))
            .group_by(RecipeIngredient.ingredient_id)
        ).all()
    )


@router.get("", response_model=list[IngredientRead])
def list_ingredients(
    response: Response,
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
    q: str | None = None,
    source: str | None = None,
    is_food: bool | None = None,
    missing_cost: bool | None = None,
    missing_nutrition: bool | None = None,
    sort: str = Query("name", pattern="^(name|cost|usage|updated)$"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List the pantry.

    `missing_cost` / `missing_nutrition` are the work queues for filling
    this table in. `is_food=false` finds the things that come home from the
    shops but never go in a recipe — batteries, shampoo, cat litter — which
    the shopping-list import flags on the way in.
    """
    statement = select(Ingredient)
    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(Ingredient.name.ilike(pattern), Ingredient.slug.ilike(pattern))
        )
    if source:
        statement = statement.where(Ingredient.source == source)
    if is_food is not None:
        statement = statement.where(Ingredient.is_food == is_food)  # noqa: E712
    if missing_cost is True:
        statement = statement.where(Ingredient.cost_per_kg_cents.is_(None))
    elif missing_cost is False:
        statement = statement.where(Ingredient.cost_per_kg_cents.is_not(None))

    rows = list(session.exec(statement).all())
    if missing_nutrition is True:
        rows = [r for r in rows if not has_nutrition(r)]
    elif missing_nutrition is False:
        rows = [r for r in rows if has_nutrition(r)]

    counts = _usage_counts(session)
    if sort == "cost":
        rows.sort(key=lambda i: (i.cost_per_kg_cents is None, i.cost_per_kg_cents or 0))
    elif sort == "usage":
        rows.sort(key=lambda i: -counts.get(i.id, 0))
    elif sort == "updated":
        rows.sort(key=lambda i: i.updated_at, reverse=True)
    else:
        rows.sort(key=lambda i: i.name.lower())

    response.headers["X-Total-Count"] = str(len(rows))
    return [
        _read(session, i, counts.get(i.id, 0)) for i in rows[offset : offset + limit]
    ]


@router.get("/{key}", response_model=IngredientRead)
def get_ingredient(
    key: str,
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
):
    ingredient = _lookup(session, key)
    return _read(session, ingredient, _usage_counts(session).get(ingredient.id, 0))


def _lookup(session: Session, key: str) -> Ingredient:
    ingredient = None
    if key.isdigit():
        ingredient = session.get(Ingredient, int(key))
    if ingredient is None:
        ingredient = session.exec(
            select(Ingredient).where(Ingredient.slug == key)
        ).first()
    if ingredient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such ingredient")
    return ingredient


@router.post("", response_model=IngredientRead, status_code=status.HTTP_201_CREATED)
def create_ingredient(
    body: IngredientCreate,
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name is required")
    if find_ingredient(session, name):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{name!r} already matches an existing ingredient"
        )
    slug = unique_slug(
        name,
        lambda s: session.exec(select(Ingredient).where(Ingredient.slug == s)).first()
        is not None,
    )
    ingredient = Ingredient(
        slug=slug, **body.model_dump() | {"name": name, "aliases": [a.lower() for a in body.aliases]}
    )
    session.add(ingredient)
    session.commit()
    session.refresh(ingredient)
    return _read(session, ingredient)


@router.patch("/{key}", response_model=IngredientRead)
def update_ingredient(
    key: str,
    body: IngredientUpdate,
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
):
    """Update a pantry item, then re-derive every weight that depended on it.

    Adding a density to "plain flour" has to make the 78 baking recipes that
    say "2 cups plain flour" show 300g each — otherwise the master list is
    a place data goes to sit rather than a lookup the recipes actually use.
    Adding an alias works the same way: recipes and shopping items already
    sitting there unlinked (saved before this alias existed to match them)
    get matched against it too, not just ones saved from now on.
    """
    ingredient = _lookup(session, key)
    fields = body.model_dump(exclude_unset=True)
    if "aliases" in fields and fields["aliases"] is not None:
        fields["aliases"] = [a.strip().lower() for a in fields["aliases"] if a.strip()]
    if any(field in fields for field in NUTRIENT_FIELDS):
        ingredient.nutrition_updated_at = utcnow()
    # A human editing the price in the Pantry page is itself a source: it
    # means "I looked and this is what it costs," which should read
    # differently from an unset field or an AI estimate. Only stamp when
    # the price actually changes — editing the package size alone shouldn't
    # make an old price look freshly verified. Both cost bases share one
    # provenance pair, so either one changing counts.
    price_changed = (
        "cost_per_kg_cents" in fields and fields["cost_per_kg_cents"] != ingredient.cost_per_kg_cents
    ) or (
        "cost_per_litre_cents" in fields
        and fields["cost_per_litre_cents"] != ingredient.cost_per_litre_cents
    )
    if price_changed:
        ingredient.cost_updated_at = utcnow()
        if "cost_source" not in fields:
            ingredient.cost_source = "manual"

    conversion_changed = any(
        field in fields and fields[field] != getattr(ingredient, field)
        for field in ("density_g_per_ml", "grams_per_piece")
    )
    matching_changed = any(
        field in fields and fields[field] != getattr(ingredient, field)
        for field in ("name", "aliases")
    )
    for name, value in fields.items():
        setattr(ingredient, name, value)
    ingredient.updated_at = utcnow()
    session.add(ingredient)
    session.flush()

    if conversion_changed:
        _reconvert_lines(session, ingredient)
    if matching_changed:
        _relink_unmatched(session, ingredient)

    session.commit()
    session.refresh(ingredient)
    return _read(session, ingredient, _usage_counts(session).get(ingredient.id, 0))


def _reconvert_line(session: Session, line: RecipeIngredient, ingredient: Ingredient) -> None:
    """Recompute one recipe line's weight from `ingredient`'s density/piece
    weight. Skipped by both callers below when the recipe stated the
    weight outright — a real measured weight always outranks anything we
    can derive."""
    from ..models import WeightSource

    if line.weight_source == WeightSource.explicit:
        return
    recipe = session.get(Recipe, line.recipe_id)
    grams, source = to_grams(
        line.quantity,
        line.unit,
        line.name,
        density_g_per_ml=ingredient.density_g_per_ml,
        grams_per_piece=ingredient.grams_per_piece,
        system=recipe.units_system if recipe else "au",
    )
    line.weight_grams = grams
    line.weight_source = source
    session.add(line)


def _reconvert_lines(session: Session, ingredient: Ingredient) -> None:
    """Recompute weights for every recipe line already linked to this
    ingredient — its density or piece weight just changed."""
    lines = session.exec(
        select(RecipeIngredient).where(RecipeIngredient.ingredient_id == ingredient.id)
    ).all()
    for line in lines:
        _reconvert_line(session, line, ingredient)


def _relink_unmatched(session: Session, ingredient: Ingredient) -> None:
    """Match this ingredient's new name/aliases against recipe lines and
    shopping items that are still unlinked.

    Matching (`find_ingredient`) only ever runs once, when a line is first
    saved — so a household adding an alias *after* the fact (the normal
    order: cook a bunch of recipes, then notice "fetta"/"feta" should be
    one pantry row) would otherwise only benefit whatever gets saved from
    now on. Everything already sitting there unlinked stays unlinked, and
    on the shopping list that means lines that plainly are the same thing
    never merge. Re-running the exact same trusted matcher against just
    the unlinked rows is what makes adding an alias actually retroactive.

    A newly-linked recipe line also gets its weight recomputed the same
    way `_reconvert_lines` does — it was saved with no ingredient to
    derive a weight from, so it's sitting on `weight_source=unknown` (or
    a guessed one) even though a real conversion is possible now.
    """
    for line in session.exec(
        select(RecipeIngredient).where(RecipeIngredient.ingredient_id.is_(None))
    ).all():
        match = find_ingredient(session, line.name)
        if match and match.id == ingredient.id:
            line.ingredient_id = ingredient.id
            _reconvert_line(session, line, ingredient)

    for item in session.exec(
        select(ShoppingItem).where(ShoppingItem.ingredient_id.is_(None))
    ).all():
        match = find_ingredient(session, item.name)
        if match and match.id == ingredient.id:
            item.ingredient_id = ingredient.id
            session.add(item)


@router.post("/{key}/merge/{other_key}", response_model=IngredientRead)
def merge_ingredient(
    key: str,
    other_key: str,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin_role),
):
    """Fold `other_key` into `key`: repoint its recipe lines and shopping
    items, inherit its name as an alias, delete it.

    The blog import creates one master row per distinct ingredient phrase,
    so "red onion", "red onions" and "small red onion" arrive as three.
    Merging is how that settles down into a list worth pricing.
    """
    target = _lookup(session, key)
    other = _lookup(session, other_key)
    if target.id == other.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot merge an ingredient into itself")

    for line in session.exec(
        select(RecipeIngredient).where(RecipeIngredient.ingredient_id == other.id)
    ).all():
        line.ingredient_id = target.id
        session.add(line)

    # Shopping items reference the pantry too, and `other` is about to be
    # deleted — miss this and a shopping item that had matched the
    # absorbed row is left pointing at a row that no longer exists: a
    # dangling foreign key. SQLite doesn't enforce it by default, so this
    # silently drops the item's shop and price instead of erroring, which
    # is exactly what "the shopping list stops matching after I merge an
    # alias in" looks like from the outside.
    for item in session.exec(
        select(ShoppingItem).where(ShoppingItem.ingredient_id == other.id)
    ).all():
        item.ingredient_id = target.id
        session.add(item)

    aliases = {a.lower() for a in (target.aliases or [])}
    aliases.add(other.name.lower())
    aliases.update(a.lower() for a in (other.aliases or []))
    aliases.discard(target.name.lower())
    target.aliases = sorted(aliases)

    # Inherit anything the absorbed row knew and the survivor doesn't.
    for field in (
        "package_size_grams", "cost_per_kg_cents",
        "package_size_ml", "cost_per_litre_cents",
        "density_g_per_ml", "grams_per_piece", *NUTRIENT_FIELDS,
    ):
        if getattr(target, field) is None and getattr(other, field) is not None:
            setattr(target, field, getattr(other, field))

    target.updated_at = utcnow()
    session.add(target)
    session.delete(other)
    session.flush()
    _reconvert_lines(session, target)
    session.commit()
    session.refresh(target)
    return _read(session, target, _usage_counts(session).get(target.id, 0))


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ingredient(
    key: str,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin_role),
):
    """Delete a pantry item. Recipe lines that referenced it keep their text
    and lose only the link — deleting a lookup row must never damage a
    recipe."""
    ingredient = _lookup(session, key)
    for line in session.exec(
        select(RecipeIngredient).where(RecipeIngredient.ingredient_id == ingredient.id)
    ).all():
        line.ingredient_id = None
        session.add(line)
    session.delete(ingredient)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
