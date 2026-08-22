"""Recipe persistence and read-model assembly.

The routers stay thin; everything that has to happen consistently on both
the manual-entry path and the importer path lives here — slug allocation,
ingredient matching, weight conversion, tag upserts, and building the
`RecipeRead` projection with its nutrition and (for signed-in callers)
cost blocks.
"""

from __future__ import annotations

from datetime import date

from sqlmodel import Session, select

from .costing import compute_cost
from .models import (
    Ingredient,
    PreparedEvent,
    PreparedEventRead,
    Recipe,
    RecipeIngredient,
    RecipeIngredientIn,
    RecipeIngredientRead,
    RecipeRead,
    RecipeStep,
    RecipeStepIn,
    RecipeStepRead,
    RecipeSummary,
    RecipeTagLink,
    Tag,
    User,
    WeightSource,
    utcnow,
)
from .nutrition import compute_nutrition
from .slugs import slugify, unique_slug
from .units import format_amount, to_grams

#: Words stripped from an ingredient name before matching it against the
#: master list, so "finely chopped fresh flat-leaf parsley" finds "parsley".
_MATCH_NOISE = {
    "fresh", "dried", "frozen", "chopped", "finely", "roughly", "thinly",
    "sliced", "diced", "grated", "crushed", "minced", "ground", "whole",
    "large", "small", "medium", "extra", "good", "quality", "free",
    "range", "organic", "raw", "cooked", "peeled", "trimmed", "washed",
    "rinsed", "drained", "lightly", "beaten", "melted", "softened",
    "toasted", "flat", "leaf", "plus", "more", "to", "serve", "taste",
    "of", "the", "a", "an", "and", "or", "for", "at", "room", "temperature",
}


def normalise_ingredient_name(name: str) -> str:
    """Reduce an ingredient phrase to its matchable core.

    "1 cup fresh flat leaf parsley leaves, chopped" has already had its
    amount stripped by `units.parse_amount`; this drops the preparation
    words and trailing plural so it can find the master row for "parsley".
    """
    core = name.split(",")[0].lower()
    core = core.replace("-", " ")
    words = [w.strip("().") for w in core.split()]
    kept = [w for w in words if w and w not in _MATCH_NOISE]
    if not kept:
        kept = [w for w in words if w]
    # Singularise a trailing plural, but leave words that legitimately end
    # in "ss" ("cress") or "us" ("hummus") alone.
    if kept and len(kept[-1]) > 3 and kept[-1].endswith("s") and not kept[-1].endswith(("ss", "us", "is")):
        kept[-1] = kept[-1][:-1]
    return " ".join(kept)


def find_ingredient(session: Session, name: str) -> Ingredient | None:
    """Match a recipe line's name to a master ingredient, or None.

    Tries, in order: exact slug, the normalised slug, and an alias hit.
    """
    candidates = [slugify(name), slugify(normalise_ingredient_name(name))]
    for slug in candidates:
        if not slug:
            continue
        found = session.exec(select(Ingredient).where(Ingredient.slug == slug)).first()
        if found:
            return found
    normalised = normalise_ingredient_name(name)
    for ingredient in session.exec(select(Ingredient)).all():
        aliases = ingredient.aliases or []
        if normalised and normalised in [a.lower() for a in aliases]:
            return ingredient
    return None


def get_or_create_ingredient(session: Session, name: str) -> Ingredient:
    """Match, or add a bare stub to the master list.

    The importer uses this so that scraping the blog also *builds* the
    master ingredient list — 321 recipes' worth of pantry items, each ready
    for a price and nutrition figures to be filled in later, rather than an
    empty table someone has to populate by hand before anything works.
    """
    existing = find_ingredient(session, name)
    if existing:
        return existing
    display = normalise_ingredient_name(name) or name.strip().lower()
    slug = unique_slug(
        display,
        lambda s: session.exec(select(Ingredient).where(Ingredient.slug == s)).first()
        is not None,
    )
    ingredient = Ingredient(slug=slug, name=display, aliases=[])
    session.add(ingredient)
    session.flush()
    return ingredient


def get_or_create_tag(session: Session, name: str) -> Tag:
    """Find a tag by slug, or create it as a plain free-form tag.

    A recipe naming "dessert" attaches to the *existing* Dessert section
    rather than making a second tag — which is what lets a recipe declare
    its section through the same list as everything else.
    """
    slug = slugify(name)
    tag = session.exec(select(Tag).where(Tag.slug == slug)).first()
    if tag is None:
        tag = Tag(slug=slug, name=name.strip())
        session.add(tag)
        session.flush()
    return tag


def apply_tags(session: Session, recipe: Recipe, names: list[str]) -> None:
    """Replace a recipe's tags wholesale."""
    for link in session.exec(
        select(RecipeTagLink).where(RecipeTagLink.recipe_id == recipe.id)
    ).all():
        session.delete(link)
    seen: set[int] = set()
    for name in names:
        if not name or not name.strip():
            continue
        tag = get_or_create_tag(session, name)
        if tag.id in seen:
            continue
        seen.add(tag.id)
        session.add(RecipeTagLink(recipe_id=recipe.id, tag_id=tag.id))


def recipe_tags(session: Session, recipe_id: int) -> tuple[list[str], list[str]]:
    """Return (all tag names, section tag names) for a recipe.

    Sections come back in nav order; everything else alphabetically. The
    section list is a subset of the first, not a disjoint one — callers
    that want only the free-form chips subtract it.
    """
    rows = session.exec(
        select(Tag)
        .join(RecipeTagLink, RecipeTagLink.tag_id == Tag.id)
        .where(RecipeTagLink.recipe_id == recipe_id)
        .order_by(Tag.name)
    ).all()
    sections = sorted(
        (tag for tag in rows if tag.is_section), key=lambda t: (t.sort_order, t.name)
    )
    return [tag.name for tag in rows], [tag.name for tag in sections]


def build_ingredient_row(
    session: Session,
    recipe_id: int,
    position: int,
    data: RecipeIngredientIn,
    *,
    units_system: str = "au",
    auto_create: bool = False,
) -> RecipeIngredient:
    """Turn an inbound ingredient into a stored row, filling the weight.

    An explicitly supplied `weight_grams` always wins — a human correcting
    a bad conversion must not have it silently recomputed on the next save.
    """
    ingredient: Ingredient | None = None
    if data.ingredient_id is not None:
        ingredient = session.get(Ingredient, data.ingredient_id)
    elif auto_create:
        ingredient = get_or_create_ingredient(session, data.name)
    else:
        ingredient = find_ingredient(session, data.name)

    if data.weight_grams is not None:
        grams: float | None = data.weight_grams
        source = WeightSource.explicit
    else:
        grams, source = to_grams(
            data.quantity,
            data.unit,
            data.name,
            density_g_per_ml=ingredient.density_g_per_ml if ingredient else None,
            grams_per_piece=ingredient.grams_per_piece if ingredient else None,
            system=units_system,
        )

    raw_text = data.raw_text
    if not raw_text:
        amount = format_amount(data.quantity, data.quantity_max, data.unit)
        raw_text = " ".join(part for part in (amount, data.name) if part).strip()

    return RecipeIngredient(
        recipe_id=recipe_id,
        position=position,
        ingredient_id=ingredient.id if ingredient else None,
        raw_text=raw_text,
        name=data.name.strip(),
        quantity=data.quantity,
        quantity_max=data.quantity_max,
        unit=data.unit,
        weight_grams=grams,
        weight_source=source,
        note=data.note,
        optional=data.optional,
        group=data.group,
    )


def apply_ingredients(
    session: Session,
    recipe: Recipe,
    items: list[RecipeIngredientIn],
    *,
    auto_create: bool = False,
) -> None:
    """Replace a recipe's ingredient lines wholesale."""
    for row in session.exec(
        select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id)
    ).all():
        session.delete(row)
    session.flush()
    for position, item in enumerate(items):
        session.add(
            build_ingredient_row(
                session,
                recipe.id,
                position,
                item,
                units_system=recipe.units_system,
                auto_create=auto_create,
            )
        )


def apply_steps(session: Session, recipe: Recipe, steps: list[RecipeStepIn]) -> None:
    """Replace a recipe's method wholesale."""
    for row in session.exec(
        select(RecipeStep).where(RecipeStep.recipe_id == recipe.id)
    ).all():
        session.delete(row)
    session.flush()
    for position, step in enumerate(steps):
        text = (step.text or "").strip()
        if text:
            session.add(RecipeStep(recipe_id=recipe.id, position=position, text=text))


def allocate_slug(session: Session, title: str) -> str:
    return unique_slug(
        title,
        lambda s: session.exec(select(Recipe).where(Recipe.slug == s)).first()
        is not None,
    )


def total_minutes(recipe: Recipe) -> int | None:
    """Total Time: the explicit override, else prep + cook, else None."""
    if recipe.total_minutes_override is not None:
        return recipe.total_minutes_override
    parts = [m for m in (recipe.prep_minutes, recipe.cook_minutes) if m is not None]
    return sum(parts) if parts else None


def prepared_summary(session: Session, recipe_id: int) -> tuple[date | None, int]:
    events = session.exec(
        select(PreparedEvent)
        .where(PreparedEvent.recipe_id == recipe_id)
        .order_by(PreparedEvent.prepared_on.desc())
    ).all()
    return (events[0].prepared_on if events else None), len(events)


def recipe_summary(session: Session, recipe: Recipe) -> RecipeSummary:
    last_prepared, prepared_count = prepared_summary(session, recipe.id)
    tags, sections = recipe_tags(session, recipe.id)
    return RecipeSummary(
        id=recipe.id,
        slug=recipe.slug,
        title=recipe.title,
        description=recipe.description,
        image_path=recipe.image_path,
        added_date=recipe.added_date,
        total_minutes=total_minutes(recipe),
        servings=recipe.servings,
        tags=tags,
        sections=sections,
        last_prepared_on=last_prepared,
        prepared_count=prepared_count,
        needs_review=recipe.needs_review,
        is_published=recipe.is_published,
    )


def recipe_read(
    session: Session, recipe: Recipe, user: User | None = None
) -> RecipeRead:
    """Full recipe projection. Cost is attached only for signed-in callers."""
    lines = session.exec(
        select(RecipeIngredient)
        .where(RecipeIngredient.recipe_id == recipe.id)
        .order_by(RecipeIngredient.position)
    ).all()
    steps = session.exec(
        select(RecipeStep)
        .where(RecipeStep.recipe_id == recipe.id)
        .order_by(RecipeStep.position)
    ).all()
    events = session.exec(
        select(PreparedEvent)
        .where(PreparedEvent.recipe_id == recipe.id)
        .order_by(PreparedEvent.prepared_on.desc())
    ).all()

    cost = None
    per_line_cost: dict[int, int] = {}
    if user is not None:
        cost, per_line_cost = compute_cost(session, list(lines), servings=recipe.servings)

    whole, per_serving = compute_nutrition(
        session, list(lines), servings=recipe.servings
    )

    tags, sections = recipe_tags(session, recipe.id)

    user_names: dict[int, str] = {}
    for event in events:
        if event.user_id and event.user_id not in user_names:
            found = session.get(User, event.user_id)
            user_names[event.user_id] = (found.name or found.email) if found else "—"

    return RecipeRead(
        id=recipe.id,
        slug=recipe.slug,
        title=recipe.title,
        description=recipe.description,
        image_path=recipe.image_path,
        image_source_url=recipe.image_source_url,
        added_date=recipe.added_date,
        prep_minutes=recipe.prep_minutes,
        cook_minutes=recipe.cook_minutes,
        total_minutes=total_minutes(recipe),
        total_minutes_override=recipe.total_minutes_override,
        servings=recipe.servings,
        servings_note=recipe.servings_note,
        storage=recipe.storage,
        nutrition_note=recipe.nutrition_note,
        source_url=recipe.source_url,
        source_name=recipe.source_name,
        units_system=recipe.units_system,
        import_source=recipe.import_source,
        needs_review=recipe.needs_review,
        review_note=recipe.review_note,
        is_published=recipe.is_published,
        created_at=recipe.created_at,
        updated_at=recipe.updated_at,
        tags=tags,
        sections=sections,
        ingredients=[
            RecipeIngredientRead(
                id=line.id,
                position=line.position,
                ingredient_id=line.ingredient_id,
                raw_text=line.raw_text,
                name=line.name,
                quantity=line.quantity,
                quantity_max=line.quantity_max,
                unit=line.unit,
                weight_grams=line.weight_grams,
                weight_source=line.weight_source,
                note=line.note,
                optional=line.optional,
                group=line.group,
                cost_cents=per_line_cost.get(line.id),
            )
            for line in lines
        ],
        steps=[
            RecipeStepRead(id=step.id, position=step.position, text=step.text)
            for step in steps
        ],
        last_prepared_on=events[0].prepared_on if events else None,
        prepared_count=len(events),
        prepared_events=[
            PreparedEventRead(
                id=event.id,
                recipe_id=event.recipe_id,
                prepared_on=event.prepared_on,
                user_id=event.user_id,
                user_name=user_names.get(event.user_id) if event.user_id else None,
                rating=event.rating,
                note=event.note,
            )
            for event in events
        ],
        nutrition=whole,
        nutrition_per_serving=per_serving,
        cost=cost,
    )


def touch(recipe: Recipe) -> None:
    recipe.updated_at = utcnow()
