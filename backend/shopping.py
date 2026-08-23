"""The shopping list: aggregation, grouping and pricing.

Turning a week of cooking into a shopping list is mostly one question asked
over and over — *are these two lines the same thing?* — and the answer has
to be conservative, because a wrong merge is worse than no merge. Coming
home with 100g of onion when the lasagne needed 400g is a failure of the
list; coming home with two separate onion lines is a mild annoyance.

## What merges

Two lines merge when they are **the same pantry ingredient** and both have
a weight in grams. That is the only case where the arithmetic is real.

Everything else stays separate:

* **Unlinked lines never merge**, even when the text is identical. Without
  a pantry row there is no evidence that "1 bunch coriander" from one
  recipe and "coriander leaves" from another are the same purchase.
* **Same ingredient, no weight** ("1 bunch parsley", "salt to taste") stays
  its own line. Adding 1 bunch to 30g would mean inventing a bunch weight
  the pantry hasn't been told.

The result is a list that sometimes says "onion 400g" and "onion, 1 bunch
spring" on two lines. That is the honest rendering of what the recipes
asked for, and it matches how the rest of this codebase reports partial
knowledge (see `nutrition.coverage`, `RecipeCost.known_fraction`).

## Provenance

Every merged item keeps a `contributions` list — which recipe asked for how
much. Without it a shopping list is a set of numbers with no way to check
them, and the first time a total looks wrong the whole feature stops being
trusted.

## Shop order

Items are grouped by their pantry ingredient's `source` — the shop it's
usually bought from. `SHOP_ORDER` is a walking order rather than an
alphabetical one: fresh food first while there's room in the bags, cold
things last so they spend the least time out. Anything unlinked lands in
"other", at the end.
"""

from __future__ import annotations

from sqlmodel import Session, select

from .costing import cost_per_gram  # noqa: F401  (re-exported for callers)
from .models import (
    Ingredient,
    IngredientSource,
    MeasureUnit,
    Recipe,
    RecipeIngredient,
    ShoppingItem,
    ShoppingItemRead,
    ShoppingListRead,
    utcnow,
)
from .units import format_amount

#: Shops in the order they get walked, not alphabetical. Anything not
#: listed sorts after these, before "other".
SHOP_ORDER: list[str] = [
    IngredientSource.markets.value,
    IngredientSource.supermarket.value,
    IngredientSource.asian_grocery.value,
    IngredientSource.butcher.value,
    IngredientSource.fishmonger.value,
    IngredientSource.deli.value,
    IngredientSource.bakery.value,
    IngredientSource.nut_shop.value,
    IngredientSource.cake_supplies.value,
    IngredientSource.bottle_shop.value,
    IngredientSource.chemist.value,
    IngredientSource.hardware.value,
    IngredientSource.newsagent.value,
    IngredientSource.other.value,
]

#: Units that describe a state rather than an amount. A recipe line
#: carrying one of these has nothing to buy a quantity of, so it goes on
#: the list as a bare name rather than as "0.5 pinch".
UNQUANTIFIABLE = {MeasureUnit.to_taste, MeasureUnit.pinch}


def shop_of(ingredient: Ingredient | None) -> str:
    """Which shop an item belongs under. Unlinked items go to "other"."""
    if ingredient is None:
        return IngredientSource.other.value
    source = ingredient.source
    return source.value if isinstance(source, IngredientSource) else str(source)


def shop_sort_key(shop: str) -> tuple[int, str]:
    """Walking order, with unknown shops after the known ones but before
    "other" — a shop added to the enum and not yet to SHOP_ORDER should
    appear somewhere sensible rather than vanish."""
    if shop in SHOP_ORDER:
        return (SHOP_ORDER.index(shop), shop)
    return (len(SHOP_ORDER) - 1, shop)  # just ahead of "other"


def scale_factor(recipe: Recipe, wanted_servings: int | None) -> tuple[float, bool]:
    """How much to multiply a recipe's amounts by, and whether that number
    means anything.

    Returns (factor, scalable). `scalable` is False when servings were
    asked for but the recipe never recorded how many it makes — the factor
    is 1.0 in that case, and the caller is expected to say so rather than
    quietly serving the wrong amount of food.
    """
    if wanted_servings is None:
        return 1.0, True
    if not recipe.servings:
        return 1.0, False
    return wanted_servings / recipe.servings, True


def amount_text(item: ShoppingItem) -> str:
    """Render an item's amount for display.

    Weight wins when present: it is what merging produced and what the cost
    is computed from. Whole grams below a kilo, kilos above — "1.2 kg" reads
    better than "1200 g" on a phone in a supermarket.
    """
    if item.weight_grams:
        grams = item.weight_grams
        if grams >= 1000:
            return f"{grams / 1000:g} kg"
        return f"{round(grams):g} g"
    if item.quantity is not None:
        return format_amount(item.quantity, None, item.unit)
    if item.unit in UNQUANTIFIABLE:
        return item.unit.value.replace("_", " ")
    return ""


def item_cost_cents(item: ShoppingItem, ingredient: Ingredient | None) -> int | None:
    """What this line costs, or None when it can't be known.

    Only weights can be priced: prices are per kilogram, and "1 bunch" has
    no weight until someone tells the pantry what a bunch weighs.
    """
    if ingredient is None or ingredient.cost_per_kg_cents is None:
        return None
    if not item.weight_grams:
        return None
    return round(item.weight_grams / 1000 * ingredient.cost_per_kg_cents)


def item_read(
    item: ShoppingItem,
    ingredient: Ingredient | None,
    *,
    with_cost: bool,
) -> ShoppingItemRead:
    return ShoppingItemRead(
        **item.model_dump(),
        shop=shop_of(ingredient),
        amount_text=amount_text(item),
        cost_cents=item_cost_cents(item, ingredient) if with_cost else None,
    )


def _ingredient_map(session: Session, items: list[ShoppingItem]) -> dict[int, Ingredient]:
    ids = {i.ingredient_id for i in items if i.ingredient_id}
    if not ids:
        return {}
    rows = session.exec(select(Ingredient).where(Ingredient.id.in_(ids))).all()
    return {row.id: row for row in rows}


def read_items(
    session: Session, items: list[ShoppingItem], *, with_cost: bool
) -> list[ShoppingItemRead]:
    """Project a handful of items, resolving their pantry rows in one query."""
    ingredients = _ingredient_map(session, items)
    return [
        item_read(item, ingredients.get(item.ingredient_id), with_cost=with_cost)
        for item in items
    ]


def read_list(session: Session, *, with_cost: bool) -> ShoppingListRead:
    """The whole shopping list, grouped and ordered for display.

    Unchecked items first — the list is a thing you work through, and what
    you have already bought should not push what you haven't off the top of
    the screen.
    """
    items = list(session.exec(select(ShoppingItem)).all())
    reads = read_items(session, items, with_cost=with_cost)
    reads.sort(key=lambda r: (r.is_checked, shop_sort_key(r.shop), r.name.lower()))

    shops: list[str] = []
    for read in reads:
        if read.shop not in shops:
            shops.append(read.shop)
    shops.sort(key=shop_sort_key)

    unchecked = [r for r in reads if not r.is_checked]
    priced = [r for r in unchecked if r.cost_cents is not None]
    total_cents = sum(r.cost_cents for r in priced) if with_cost else None

    return ShoppingListRead(
        items=reads,
        shops=shops,
        total_count=len(reads),
        checked_count=sum(1 for r in reads if r.is_checked),
        total_cents=total_cents,
        priced_fraction=round(len(priced) / len(unchecked), 3) if unchecked else 0.0,
    )


# --------------------------------------------------------------------------
# Adding a cooking list's recipes to the shopping list
# --------------------------------------------------------------------------


def _mergeable(item: ShoppingItem, line_ingredient_id: int | None, kind: str, unit) -> bool:
    """Whether an existing list row can absorb an incoming line.

    Three kinds of line, three rules — and all of them require the same
    pantry ingredient, because without one there is no evidence two lines
    are the same purchase.

    * ``weight``   — both sides have grams. Add them.
    * ``quantity`` — neither has grams and the units match ("1 bunch" plus
      "2 bunch"). Same arithmetic, different unit.
    * ``bare``     — neither side states any amount at all. Nothing to add;
      the two lines are simply the same shopping trip.

    A weighted line never merges into an amount-less one or vice versa:
    folding an unknown amount into a known one would present a number that
    is quietly missing some of the food.

    Checked items are excluded throughout. Adding to something already in
    the trolley would silently reopen it and the shopper would walk past.
    """
    if line_ingredient_id is None or item.ingredient_id != line_ingredient_id:
        return False
    if item.is_checked:
        return False
    if kind == "weight":
        return item.weight_grams is not None
    if kind == "quantity":
        return (
            item.weight_grams is None
            and item.quantity is not None
            and item.unit == unit
        )
    return item.weight_grams is None and item.quantity is None


def add_lines(
    session: Session,
    lines: list[tuple[RecipeIngredient, Recipe, float]],
    *,
    cook_list_id: int | None = None,
) -> tuple[list[ShoppingItem], int, int, list[str]]:
    """Fold recipe lines into the shopping list.

    `lines` is (line, recipe, factor) — the factor scales the amount for a
    cooking list entry that asked for a different number of serves.

    Every line with a name reaches the list, including the ones that never
    stated an amount. A recipe that just says "olive oil" still means buy
    olive oil, and leaving it off because the quantity is unknown is the
    one failure a shopping list must not have. Such items appear with no
    amount rather than with a guessed one.

    Returns (touched items, added, merged, skipped descriptions). Existing
    rows are mutated in place; new ones are added to the session. The
    caller commits.
    """
    existing = list(session.exec(select(ShoppingItem)).all())
    touched: dict[int, ShoppingItem] = {}
    new_items: list[ShoppingItem] = []
    added = merged = 0
    skipped: list[str] = []

    for line, recipe, factor in lines:
        name = (line.name or "").strip()
        if not name:
            skipped.append(f"{recipe.title}: {line.raw_text}")
            continue

        grams = line.weight_grams * factor if line.weight_grams else None
        quantity = line.quantity * factor if line.quantity is not None else None
        if grams is not None:
            kind = "weight"
        elif quantity is not None:
            kind = "quantity"
        else:
            kind = "bare"

        contribution = {
            "recipe": recipe.title,
            "recipe_slug": recipe.slug,
            "amount": (
                f"{round(grams)} g"
                if grams is not None
                else format_amount(quantity, None, line.unit)
            ),
        }

        # Prefer a row already added in this pass over one from the query,
        # so three recipes wanting onion produce one line, not two.
        target = next(
            (
                candidate
                for candidate in [*new_items, *existing]
                if _mergeable(candidate, line.ingredient_id, kind, line.unit)
            ),
            None,
        )

        if target is not None:
            if kind == "weight":
                target.weight_grams = (target.weight_grams or 0) + grams
            elif kind == "quantity":
                target.quantity = (target.quantity or 0) + quantity
            target.contributions = [*(target.contributions or []), contribution]
            if cook_list_id is not None and target.cook_list_id is None:
                target.cook_list_id = cook_list_id
            session.add(target)
            touched[id(target)] = target
            merged += 1
            continue

        item = ShoppingItem(
            ingredient_id=line.ingredient_id,
            name=name,
            weight_grams=grams,
            # A weighted line's quantity is already expressed by the
            # weight; keeping both would show "400 g" and "4 piece" for the
            # same onions. The unit survives either way, so an amount-less
            # "salt, to taste" can still say so.
            quantity=None if grams is not None else quantity,
            unit=None if grams is not None else line.unit,
            note=line.note,
            source=_source_for(cook_list_id),
            cook_list_id=cook_list_id,
            contributions=[contribution],
        )
        session.add(item)
        new_items.append(item)
        touched[id(item)] = item
        added += 1

    return list(touched.values()), added, merged, skipped


def _source_for(cook_list_id: int | None):
    from .models import ShoppingItemSource

    return (
        ShoppingItemSource.cook_list
        if cook_list_id is not None
        else ShoppingItemSource.manual
    )


def set_checked(item: ShoppingItem, checked: bool) -> None:
    item.is_checked = checked
    item.checked_at = utcnow() if checked else None
