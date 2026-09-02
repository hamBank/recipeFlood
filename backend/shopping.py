"""The shopping list: aggregation, grouping and pricing.

Turning a week of cooking into a shopping list is mostly one question asked
over and over — *are these two lines the same thing?* — and the answer has
to be conservative, because a wrong merge is worse than no merge. Coming
home with 100g of onion when the lasagne needed 400g is a failure of the
list; coming home with two separate onion lines is a mild annoyance.

## What merges

Two lines merge when they are **the same pantry ingredient** and state the
same *kind* of amount — both a weight, both a volume, or both a count in
the same unit. Those are the only cases where the arithmetic is real.

Weight and volume merge on different terms. Weight needs a density (explicit
or estimated) to turn "2 cups" into grams, so two weight amounts are only
comparable once that conversion has already happened. Volume needs nothing
of the kind: "2 cups" and "500ml" both convert to millilitres by fixed
unit arithmetic alone (see `units.to_ml`), so they merge exactly regardless
of whether anyone has ever told the pantry this ingredient's density. That is
what makes a liquid with no known density still mergeable and priceable —
see `Ingredient.measure_kind` in models.py.

An ingredient with a known density gets both a weight and a volume for the
same line; which one the shopping list aggregates on follows the
ingredient's `measure_kind` (weight ingredients merge on weight even when a
density happens to be set, volume ingredients merge on volume even when a
weight happens to be derivable) — that is also what its cost is computed
from, so the two stay in step.

One exception: a *guessed* weight never outranks an exact volume. Weight
conversion has a keyword-table fallback for common ingredient names (see
units.DENSITIES) that fires even with no linked pantry density — "milk",
"stock" and "honey" are all in that table — and it produces
`WeightSource.estimated`, the same tier the recipe-detail page already
marks with an asterisk as "not to be trusted." A weight-measure_kind
ingredient only merges on weight when the conversion was stated outright
or came from a real linked density (`explicit`/`converted`); an estimated
weight defers to the exact millilitre figure when one is available.

Everything else stays separate:

* **Unlinked lines never merge**, even when the text is identical. Without
  a pantry row there is no evidence that "1 bunch coriander" from one
  recipe and "coriander leaves" from another are the same purchase.
* **Same ingredient, no weight and no volume** ("1 bunch parsley", "salt to
  taste") stays its own line. Adding 1 bunch to 30g would mean inventing a
  bunch weight the pantry hasn't been told.

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

from .costing import amount_cost_cents, cost_per_gram  # noqa: F401  (cost_per_gram re-exported)
from .models import (
    Ingredient,
    IngredientSource,
    MeasureKind,
    MeasureUnit,
    Recipe,
    RecipeIngredient,
    ShoppingItem,
    ShoppingItemRead,
    ShoppingListRead,
    WeightSource,
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


def shop_of(ingredient: Ingredient | None, override: IngredientSource | None = None) -> str:
    """Which shop an item belongs under.

    `override` — a per-item `shop_override` — wins outright when set; it's
    the one-off "not from the usual place this time" case, and re-deriving
    it from the ingredient would defeat the point. Otherwise this follows
    the linked ingredient's own `source`, or "other" when unlinked.
    """
    if override is not None:
        return override.value if isinstance(override, IngredientSource) else str(override)
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


def _render_grams(grams: float) -> str:
    if grams >= 1000:
        return f"{grams / 1000:g} kg"
    return f"{round(grams):g} g"


def _render_ml(ml: float) -> str:
    if ml >= 1000:
        return f"{ml / 1000:g} l"
    return f"{round(ml):g} ml"


def amount_text(item: ShoppingItem) -> str:
    """Render an item's amount for display.

    Weight or volume wins when present — whichever merging produced, since
    an item only ever has one of the two populated (see `add_lines`). Whole
    units below the next size up, the bigger unit above — "1.2 kg"/"1.2 l"
    read better than "1200 g"/"1200 ml" on a phone in a supermarket.
    """
    if item.weight_grams:
        return _render_grams(item.weight_grams)
    if item.volume_ml:
        return _render_ml(item.volume_ml)
    if item.quantity is not None:
        return format_amount(item.quantity, None, item.unit)
    if item.unit in UNQUANTIFIABLE:
        return item.unit.value.replace("_", " ")
    return ""


def item_cost_cents(item: ShoppingItem, ingredient: Ingredient | None) -> int | None:
    """What this line costs, or None when it can't be known.

    Delegates to costing.amount_cost_cents, which picks weight or volume
    to price by from the ingredient's `measure_kind` — the same choice
    `line_cost_cents` makes for a recipe line, kept in one place so the two
    can't drift apart on how a volume ingredient gets priced.
    """
    return amount_cost_cents(
        ingredient, weight_grams=item.weight_grams, volume_ml=item.volume_ml
    )


def item_read(
    item: ShoppingItem,
    ingredient: Ingredient | None,
    *,
    with_cost: bool,
) -> ShoppingItemRead:
    return ShoppingItemRead(
        **item.model_dump(),
        shop=shop_of(ingredient, item.shop_override),
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

    Four kinds of line, four rules — and all of them require the same
    pantry ingredient, because without one there is no evidence two lines
    are the same purchase.

    * ``weight``   — both sides have grams. Add them.
    * ``volume``   — both sides have millilitres. Add them — this is exact
      regardless of which volume unit either line was originally written
      in ("2 cups" and "500ml" both merge here).
    * ``quantity`` — neither has grams or millilitres, and the units match
      ("1 bunch" plus "2 bunch"). Same arithmetic, different unit.
    * ``bare``     — neither side states any amount at all. Nothing to add;
      the two lines are simply the same shopping trip.

    A line never merges into a row of a different kind: folding an unknown
    amount into a known one, or a volume into a weight, would present a
    number that is quietly missing some of the food (or double-counting
    it, if both got summed independently).

    Checked items are excluded throughout. Adding to something already in
    the trolley would silently reopen it and the shopper would walk past.
    """
    if line_ingredient_id is None or item.ingredient_id != line_ingredient_id:
        return False
    if item.is_checked:
        return False
    if kind == "weight":
        return item.weight_grams is not None
    if kind == "volume":
        return item.weight_grams is None and item.volume_ml is not None
    if kind == "quantity":
        return (
            item.weight_grams is None
            and item.volume_ml is None
            and item.quantity is not None
            and item.unit == unit
        )
    return item.weight_grams is None and item.volume_ml is None and item.quantity is None


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
    ingredient_ids = {line.ingredient_id for line, _, _ in lines if line.ingredient_id}
    ingredients: dict[int, Ingredient] = {}
    if ingredient_ids:
        for row in session.exec(
            select(Ingredient).where(Ingredient.id.in_(ingredient_ids))
        ).all():
            ingredients[row.id] = row

    touched: dict[int, ShoppingItem] = {}
    new_items: list[ShoppingItem] = []
    added = merged = 0
    skipped: list[str] = []

    for line, recipe, factor in lines:
        name = (line.name or "").strip()
        if not name:
            skipped.append(f"{recipe.title}: {line.raw_text}")
            continue

        ingredient = ingredients.get(line.ingredient_id) if line.ingredient_id else None
        grams = line.weight_grams * factor if line.weight_grams else None
        millilitres = line.volume_ml * factor if line.volume_ml else None
        quantity = line.quantity * factor if line.quantity is not None else None
        # A weight this codebase actually stands behind — stated outright,
        # or converted via a real linked density — as opposed to a keyword
        # guess from units.DENSITIES (WeightSource.estimated). That guess
        # exists as a last resort for solids with nowhere else to go; it
        # should never outrank an exact millilitre figure, which is what
        # "weight is available so prefer weight" would otherwise do for
        # any liquid whose name happens to match a density keyword (most
        # of them: "milk", "stock", "honey", ...).
        confident_weight = grams is not None and line.weight_source in (
            WeightSource.explicit,
            WeightSource.converted,
        )

        # An ingredient priced by volume aggregates on volume even when a
        # density also happens to make a weight derivable, and vice versa —
        # this has to match what its cost is computed from (costing.py), or
        # the merged total and the price it's multiplied by would silently
        # stop corresponding to the same amount.
        prefer_volume = ingredient is not None and ingredient.measure_kind == MeasureKind.volume
        if prefer_volume:
            kind = "volume" if millilitres is not None else "weight" if grams is not None else None
        elif confident_weight:
            kind = "weight"
        else:
            kind = "volume" if millilitres is not None else "weight" if grams is not None else None
        if kind is None:
            kind = "quantity" if quantity is not None else "bare"

        contribution = {
            "recipe": recipe.title,
            "recipe_slug": recipe.slug,
            "amount": (
                _render_grams(grams)
                if kind == "weight"
                else _render_ml(millilitres)
                if kind == "volume"
                else format_amount(quantity, None, line.unit)
                if kind == "quantity"
                else ""
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
            elif kind == "volume":
                target.volume_ml = (target.volume_ml or 0) + millilitres
            elif kind == "quantity":
                target.quantity = (target.quantity or 0) + quantity
            target.contributions = [*(target.contributions or []), contribution]
            if cook_list_id is not None and target.cook_list_id is None:
                target.cook_list_id = cook_list_id
            session.add(target)
            touched[id(target)] = target
            merged += 1
            continue

        # A weighted or volumed line's quantity is already expressed by that
        # amount; keeping both would show "400 g" and "4 piece" for the same
        # onions. The unit survives only for quantity/bare, so an
        # amount-less "salt, to taste" can still say so.
        item = ShoppingItem(
            ingredient_id=line.ingredient_id,
            name=name,
            weight_grams=grams if kind == "weight" else None,
            volume_ml=millilitres if kind == "volume" else None,
            quantity=quantity if kind == "quantity" else None,
            unit=line.unit if kind in ("quantity", "bare") else None,
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
