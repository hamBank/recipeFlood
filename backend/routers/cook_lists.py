"""Cooking lists — what we're making, and when.

Signed-in only, all of it. A cooking list is household planning rather than
published content, and the public recipe pages have no reason to know about
it (SPEC.md "Visibility").
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session, select

from ..cook_lists import cook_list_read, shopping_lines
from ..database import get_session
from ..models import (
    AddToShoppingResult,
    CookList,
    CookListCreate,
    CookListRead,
    CookListRecipe,
    CookListRecipeIn,
    CookListUpdate,
    Recipe,
    User,
    utcnow,
)
from ..permissions import require_user_role
from ..shopping import add_lines, read_items

router = APIRouter(prefix="/cook-lists", tags=["cook-lists"])


def _lookup(session: Session, cook_list_id: int) -> CookList:
    cook_list = session.get(CookList, cook_list_id)
    if cook_list is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such cooking list")
    return cook_list


def _replace_recipes(
    session: Session, cook_list: CookList, recipes: list[CookListRecipeIn]
) -> None:
    """Set a list's membership to exactly `recipes`, in the order given."""
    for existing in session.exec(
        select(CookListRecipe).where(CookListRecipe.cook_list_id == cook_list.id)
    ).all():
        session.delete(existing)
    session.flush()

    seen: set[int] = set()
    position = 0
    for entry in recipes:
        if entry.recipe_id in seen:
            # The same recipe twice in one list is a double-click, not a
            # plan to cook it twice — and it would double the shopping.
            continue
        if session.get(Recipe, entry.recipe_id) is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"No recipe with id {entry.recipe_id}",
            )
        seen.add(entry.recipe_id)
        session.add(
            CookListRecipe(
                cook_list_id=cook_list.id,
                recipe_id=entry.recipe_id,
                position=position,
                servings=entry.servings,
                note=entry.note,
            )
        )
        position += 1


@router.get("", response_model=list[CookListRead])
def list_cook_lists(
    response: Response,
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
    since: date | None = None,
    until: date | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Cooking lists, newest date first — the useful end of a long history."""
    statement = select(CookList)
    if since:
        statement = statement.where(CookList.cook_date >= since)
    if until:
        statement = statement.where(CookList.cook_date <= until)
    statement = statement.order_by(CookList.cook_date.desc(), CookList.id.desc())

    rows = list(session.exec(statement).all())
    response.headers["X-Total-Count"] = str(len(rows))
    return [cook_list_read(session, row) for row in rows[offset : offset + limit]]


@router.get("/{cook_list_id}", response_model=CookListRead)
def get_cook_list(
    cook_list_id: int,
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
):
    return cook_list_read(session, _lookup(session, cook_list_id))


@router.post("", response_model=CookListRead, status_code=status.HTTP_201_CREATED)
def create_cook_list(
    body: CookListCreate,
    session: Session = Depends(get_session),
    user: User = Depends(require_user_role),
):
    cook_list = CookList(
        cook_date=body.cook_date or date.today(),
        description=(body.description or "").strip() or None,
        notes=body.notes,
        created_by=user.id,
    )
    session.add(cook_list)
    session.flush()
    _replace_recipes(session, cook_list, body.recipes)
    session.commit()
    session.refresh(cook_list)
    return cook_list_read(session, cook_list)


@router.patch("/{cook_list_id}", response_model=CookListRead)
def update_cook_list(
    cook_list_id: int,
    body: CookListUpdate,
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
):
    cook_list = _lookup(session, cook_list_id)
    fields = body.model_dump(exclude_unset=True)
    recipes = fields.pop("recipes", None)
    for name, value in fields.items():
        setattr(cook_list, name, value)
    if recipes is not None:
        _replace_recipes(
            session, cook_list, [CookListRecipeIn(**r) for r in recipes]
        )
    cook_list.updated_at = utcnow()
    session.add(cook_list)
    session.commit()
    session.refresh(cook_list)
    return cook_list_read(session, cook_list)


@router.post(
    "/{cook_list_id}/recipes",
    response_model=CookListRead,
    status_code=status.HTTP_201_CREATED,
)
def add_recipe(
    cook_list_id: int,
    body: CookListRecipeIn,
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
):
    """Add one recipe to the list. Adding one already on it updates its
    serving count rather than creating a second row."""
    cook_list = _lookup(session, cook_list_id)
    if session.get(Recipe, body.recipe_id) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"No recipe with id {body.recipe_id}"
        )

    existing = session.exec(
        select(CookListRecipe)
        .where(CookListRecipe.cook_list_id == cook_list.id)
        .where(CookListRecipe.recipe_id == body.recipe_id)
    ).first()
    if existing is not None:
        existing.servings = body.servings
        existing.note = body.note
        session.add(existing)
    else:
        last = session.exec(
            select(CookListRecipe)
            .where(CookListRecipe.cook_list_id == cook_list.id)
            .order_by(CookListRecipe.position.desc())
        ).first()
        session.add(
            CookListRecipe(
                cook_list_id=cook_list.id,
                recipe_id=body.recipe_id,
                position=(last.position + 1) if last else 0,
                servings=body.servings,
                note=body.note,
            )
        )
    cook_list.updated_at = utcnow()
    session.add(cook_list)
    session.commit()
    session.refresh(cook_list)
    return cook_list_read(session, cook_list)


@router.delete("/{cook_list_id}/recipes/{recipe_id}", response_model=CookListRead)
def remove_recipe(
    cook_list_id: int,
    recipe_id: int,
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
):
    cook_list = _lookup(session, cook_list_id)
    entry = session.exec(
        select(CookListRecipe)
        .where(CookListRecipe.cook_list_id == cook_list.id)
        .where(CookListRecipe.recipe_id == recipe_id)
    ).first()
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That recipe is not on this list")
    session.delete(entry)
    cook_list.updated_at = utcnow()
    session.add(cook_list)
    session.commit()
    session.refresh(cook_list)
    return cook_list_read(session, cook_list)


@router.post("/{cook_list_id}/add-to-shopping", response_model=AddToShoppingResult)
def add_to_shopping(
    cook_list_id: int,
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
):
    """Fold every recipe on this list into the shopping list.

    Deliberately re-runnable and additive: calling it twice adds the
    ingredients twice, because "we're cooking this again" is a real thing
    to want and guessing otherwise would silently drop a shop. The response
    reports what merged and what was skipped so a double-click is visible
    rather than mysterious.
    """
    cook_list = _lookup(session, cook_list_id)
    lines = shopping_lines(session, cook_list.id)
    items, added, merged, skipped = add_lines(
        session, lines, cook_list_id=cook_list.id
    )
    session.commit()
    for item in items:
        session.refresh(item)

    return AddToShoppingResult(
        added=added,
        merged=merged,
        skipped=skipped,
        items=read_items(session, items, with_cost=True),
    )


@router.delete("/{cook_list_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cook_list(
    cook_list_id: int,
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
):
    """Delete a list. Shopping items it created stay — they may already be
    half-bought, and losing the list is not a reason to lose the shop."""
    cook_list = _lookup(session, cook_list_id)
    for entry in session.exec(
        select(CookListRecipe).where(CookListRecipe.cook_list_id == cook_list.id)
    ).all():
        session.delete(entry)

    from ..models import ShoppingItem

    for item in session.exec(
        select(ShoppingItem).where(ShoppingItem.cook_list_id == cook_list.id)
    ).all():
        item.cook_list_id = None
        session.add(item)

    session.delete(cook_list)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
