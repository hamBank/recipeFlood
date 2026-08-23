"""The shopping list.

One permanent list, shared by the household. Signed-in only — it carries
prices, and it is nobody else's business what we're having for dinner.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session, select

from ..database import get_session
from ..models import (
    Ingredient,
    ShoppingItem,
    ShoppingItemCreate,
    ShoppingItemRead,
    ShoppingItemUpdate,
    ShoppingListRead,
    User,
)
from ..permissions import require_user_role
from ..recipes_service import find_ingredient
from ..shopping import item_read, read_list, set_checked

router = APIRouter(prefix="/shopping", tags=["shopping"])


def _lookup(session: Session, item_id: int) -> ShoppingItem:
    item = session.get(ShoppingItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such shopping item")
    return item


def _read(session: Session, item: ShoppingItem) -> ShoppingItemRead:
    ingredient = (
        session.get(Ingredient, item.ingredient_id) if item.ingredient_id else None
    )
    return item_read(item, ingredient, with_cost=True)


@router.get("", response_model=ShoppingListRead)
def get_shopping_list(
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
):
    return read_list(session, with_cost=True)


@router.post("", response_model=ShoppingItemRead, status_code=status.HTTP_201_CREATED)
def add_item(
    body: ShoppingItemCreate,
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
):
    """Add a line by hand.

    A typed name is matched against the pantry so "milk" lands under the
    right shop and gets a price — the same matcher the recipe importers
    use. No match is fine; the item goes on the list as plain text.
    """
    name = body.name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name is required")

    ingredient_id = body.ingredient_id
    if ingredient_id is None:
        match = find_ingredient(session, name)
        ingredient_id = match.id if match else None
    elif session.get(Ingredient, ingredient_id) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"No ingredient with id {ingredient_id}"
        )

    item = ShoppingItem(
        **body.model_dump(exclude={"name", "ingredient_id"}),
        name=name,
        ingredient_id=ingredient_id,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return _read(session, item)


@router.patch("/{item_id}", response_model=ShoppingItemRead)
def update_item(
    item_id: int,
    body: ShoppingItemUpdate,
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
):
    """Edit a line, or tick it off.

    Editing an amount by hand clears `contributions`: the breakdown
    described how the old number was arrived at, and keeping it next to a
    number a human overrode would be a lie about where that number came
    from.
    """
    item = _lookup(session, item_id)
    fields = body.model_dump(exclude_unset=True)

    checked = fields.pop("is_checked", None)
    if checked is not None and checked != item.is_checked:
        set_checked(item, checked)

    if any(f in fields for f in ("weight_grams", "quantity", "unit")):
        item.contributions = []
    for name, value in fields.items():
        setattr(item, name, value)

    session.add(item)
    session.commit()
    session.refresh(item)
    return _read(session, item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(
    item_id: int,
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
):
    session.delete(_lookup(session, item_id))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/clear-checked", response_model=ShoppingListRead)
def clear_checked(
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
):
    """Delete everything ticked off — the end of a shop.

    Only checked items go. Clearing the whole list is not offered: the one
    irreversible action here should be the one you asked for.
    """
    for item in session.exec(
        select(ShoppingItem).where(ShoppingItem.is_checked == True)  # noqa: E712
    ).all():
        session.delete(item)
    session.commit()
    return read_list(session, with_cost=True)


@router.post("/uncheck-all", response_model=ShoppingListRead)
def uncheck_all(
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
):
    """Undo a shop's worth of ticking — the escape hatch for tapping
    "clear" too eagerly, offered because clearing is not reversible."""
    for item in session.exec(
        select(ShoppingItem).where(ShoppingItem.is_checked == True)  # noqa: E712
    ).all():
        set_checked(item, False)
        session.add(item)
    session.commit()
    return read_list(session, with_cost=True)
