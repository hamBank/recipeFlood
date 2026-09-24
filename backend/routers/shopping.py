"""The shopping list.

One permanent list, shared by the household. Signed-in only — it carries
prices, and it is nobody else's business what we're having for dinner.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlmodel import Session, select

from ..database import get_session
from ..models import (
    Ingredient,
    ShoppingItem,
    ShoppingItemCreate,
    ShoppingItemRead,
    ShoppingItemUpdate,
    ShoppingListRead,
    SheetSyncResult,
    User,
)
from ..permissions import require_user_role
from ..recipes_service import find_ingredient
from ..sheet_sync import delete_items_from_sheet, reconcile, sync_item
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
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
):
    """Add a line by hand.

    A typed name is matched against the pantry so "milk" lands under the
    right shop and gets a price — the same matcher the recipe importers
    use. No match is fine; the item goes on the list as plain text.

    Defaults to a quantity of 1 when no amount is given at all — typing
    just "eggs" means "buy some", and 1 is the least surprising amount to
    assume by hand. This is deliberately unlike a recipe line with no
    stated amount (see shopping.add_lines and SPEC.md "One permanent
    shopping list"): a recipe saying nothing about how much olive oil to
    buy is a real "unknown", not a "buy 1", and inventing a number there
    would misrepresent what the recipe actually asked for. Typing a bare
    name by hand carries no such intent to preserve.
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

    fields = body.model_dump(exclude={"name", "ingredient_id"})
    if fields["weight_grams"] is None and fields["volume_ml"] is None and fields["quantity"] is None:
        fields["quantity"] = 1

    item = ShoppingItem(**fields, name=name, ingredient_id=ingredient_id, sheet_dirty=True)
    session.add(item)
    session.commit()
    session.refresh(item)
    background_tasks.add_task(sync_item, item.id)
    return _read(session, item)


@router.patch("/{item_id}", response_model=ShoppingItemRead)
def update_item(
    item_id: int,
    body: ShoppingItemUpdate,
    background_tasks: BackgroundTasks,
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

    if any(f in fields for f in ("weight_grams", "volume_ml", "quantity", "unit")):
        item.contributions = []
    for name, value in fields.items():
        setattr(item, name, value)

    # Anything that changes what the sheet should show — name, amount,
    # ticked state — needs a push; shop_override/note don't, since the
    # sheet has no columns for them.
    if fields or checked is not None:
        item.sheet_dirty = True
    session.add(item)
    session.commit()
    session.refresh(item)
    background_tasks.add_task(sync_item, item.id)
    return _read(session, item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(
    item_id: int,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
):
    item = _lookup(session, item_id)
    session.delete(item)
    session.commit()
    background_tasks.add_task(delete_items_from_sheet, [item_id])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/clear-checked", response_model=ShoppingListRead)
def clear_checked(
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
):
    """Delete everything ticked off — the end of a shop.

    Only checked items go. Clearing the whole list is not offered: the one
    irreversible action here should be the one you asked for.
    """
    checked_ids = []
    for item in session.exec(
        select(ShoppingItem).where(ShoppingItem.is_checked == True)  # noqa: E712
    ).all():
        checked_ids.append(item.id)
        session.delete(item)
    session.commit()
    if checked_ids:
        background_tasks.add_task(delete_items_from_sheet, checked_ids)
    return read_list(session, with_cost=True)


@router.post("/uncheck-all", response_model=ShoppingListRead)
def uncheck_all(
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
):
    """Undo a shop's worth of ticking — the escape hatch for tapping
    "clear" too eagerly, offered because clearing is not reversible."""
    touched_ids = []
    for item in session.exec(
        select(ShoppingItem).where(ShoppingItem.is_checked == True)  # noqa: E712
    ).all():
        set_checked(item, False)
        if item.sheet_linked and not item.sheet_detached:
            item.sheet_dirty = True
            touched_ids.append(item.id)
        session.add(item)
    session.commit()
    for item_id in touched_ids:
        background_tasks.add_task(sync_item, item_id)
    return read_list(session, with_cost=True)


@router.post("/sheet-sync", response_model=SheetSyncResult)
def sheet_sync(
    session: Session = Depends(get_session),
    _user: User = Depends(require_user_role),
):
    """On-demand full reconcile with the Google Sheet — see
    backend/sheet_sync.py. No cron, no polling: this is the only way the
    sheet's own edits ever reach the app."""
    return reconcile(session)
