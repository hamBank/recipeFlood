"""Recipe endpoints.

Reads are public by default and writes never are — see SPEC.md
"Visibility". The split is carried by two dependencies rather than two sets
of routes: `allow_public_read` yields `User | None`, and passing that
optional user into `recipe_read` is what decides whether the response
carries costs.
"""

from datetime import date, timedelta
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlmodel import Session, func, or_, select

from ..config import settings
from ..database import get_session
from ..models import (
    Category,
    PreparedEvent,
    PreparedEventCreate,
    PreparedEventRead,
    Recipe,
    RecipeCreate,
    RecipeIngredient,
    RecipeRead,
    RecipeSummary,
    RecipeTagLink,
    RecipeUpdate,
    Tag,
    User,
    utcnow,
)
from ..permissions import allow_public_read, require_admin_role, require_user_role
from ..recipes_service import (
    allocate_slug,
    apply_ingredients,
    apply_steps,
    apply_tags,
    recipe_read,
    recipe_summary,
    resolve_category,
    total_minutes,
    touch,
)
from ..slugs import slugify

router = APIRouter(prefix="/recipes", tags=["recipes"])

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _get_recipe(session: Session, key: str | int) -> Recipe:
    """Look a recipe up by slug or numeric id — both forms are accepted so
    the UI can link by slug and PATCH by id without a second round trip."""
    recipe: Recipe | None = None
    if isinstance(key, int) or str(key).isdigit():
        recipe = session.get(Recipe, int(key))
    if recipe is None:
        recipe = session.exec(select(Recipe).where(Recipe.slug == str(key))).first()
    if recipe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such recipe")
    return recipe


@router.get("", response_model=list[RecipeSummary])
def list_recipes(
    response: Response,
    session: Session = Depends(get_session),
    user: User | None = Depends(allow_public_read),
    q: str | None = Query(None, description="Free text over title/description"),
    category: str | None = Query(None, description="Category slug"),
    tag: str | None = Query(None, description="Tag slug"),
    ingredient: str | None = Query(None, description="Master ingredient slug"),
    needs_review: bool | None = None,
    include_unpublished: bool = False,
    not_prepared_days: int | None = Query(
        None, description="Only recipes not cooked in this many days"
    ),
    sort: str = Query("added", pattern="^(added|title|last_prepared|total_time)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(48, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Browse and search. Sets `X-Total-Count` for pagination."""
    statement = select(Recipe)

    # Unpublished drafts are for signed-in editors only, whatever is asked.
    if not (include_unpublished and user is not None):
        statement = statement.where(Recipe.is_published == True)  # noqa: E712

    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(Recipe.title.ilike(pattern), Recipe.description.ilike(pattern))
        )
    if category:
        statement = statement.join(Category, Category.id == Recipe.category_id).where(
            Category.slug == category
        )
    if tag:
        statement = (
            statement.join(RecipeTagLink, RecipeTagLink.recipe_id == Recipe.id)
            .join(Tag, Tag.id == RecipeTagLink.tag_id)
            .where(Tag.slug == tag)
        )
    if ingredient:
        from ..models import Ingredient  # local: only needed on this branch

        statement = (
            statement.join(
                RecipeIngredient, RecipeIngredient.recipe_id == Recipe.id
            )
            .join(Ingredient, Ingredient.id == RecipeIngredient.ingredient_id)
            .where(Ingredient.slug == ingredient)
            .distinct()
        )
    if needs_review is not None:
        statement = statement.where(Recipe.needs_review == needs_review)

    if not_prepared_days is not None:
        cutoff = date.today() - timedelta(days=not_prepared_days)
        recent = select(PreparedEvent.recipe_id).where(PreparedEvent.prepared_on >= cutoff)
        statement = statement.where(Recipe.id.not_in(recent))

    rows = session.exec(statement).all()

    # last_prepared and total_time are derived, not columns, so those two
    # sorts happen in Python. The collection is a few hundred recipes; a
    # correct sort over a small set beats a denormalised column that can
    # drift out of step with the prepared-events log.
    if sort == "title":
        rows.sort(key=lambda r: r.title.lower())
    elif sort == "total_time":
        rows.sort(key=lambda r: (total_minutes(r) is None, total_minutes(r) or 0))
    elif sort == "last_prepared":
        last: dict[int, date] = {}
        for recipe_id, prepared_on in session.exec(
            select(PreparedEvent.recipe_id, func.max(PreparedEvent.prepared_on)).group_by(
                PreparedEvent.recipe_id
            )
        ).all():
            last[recipe_id] = prepared_on
        rows.sort(key=lambda r: (last.get(r.id) is None, last.get(r.id) or date.min))
    else:
        rows.sort(key=lambda r: r.added_date)
    if order == "desc":
        rows.reverse()

    response.headers["X-Total-Count"] = str(len(rows))
    return [recipe_summary(session, r) for r in rows[offset : offset + limit]]


@router.get("/{key}", response_model=RecipeRead)
def get_recipe(
    key: str,
    session: Session = Depends(get_session),
    user: User | None = Depends(allow_public_read),
):
    recipe = _get_recipe(session, key)
    if not recipe.is_published and user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such recipe")
    return recipe_read(session, recipe, user)


@router.post("", response_model=RecipeRead, status_code=status.HTTP_201_CREATED)
def create_recipe(
    body: RecipeCreate,
    session: Session = Depends(get_session),
    user: User = Depends(require_user_role),
):
    title = body.title.strip()
    if not title:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Title is required")

    recipe = Recipe(
        slug=allocate_slug(session, title),
        title=title,
        description=body.description,
        image_path=body.image_path,
        image_source_url=body.image_source_url,
        category_id=resolve_category(session, body.category_id, body.category_slug),
        added_date=body.added_date or utcnow(),
        prep_minutes=body.prep_minutes,
        cook_minutes=body.cook_minutes,
        total_minutes_override=body.total_minutes_override,
        servings=body.servings,
        servings_note=body.servings_note,
        storage=body.storage,
        nutrition_note=body.nutrition_note,
        source_url=body.source_url,
        source_name=body.source_name,
        units_system=body.units_system or settings.units_system,
        is_published=body.is_published,
        created_by=user.id,
    )
    session.add(recipe)
    session.flush()

    apply_tags(session, recipe, body.tags)
    # auto_create: an ingredient line that isn't linked to a master row can
    # never be priced or counted towards nutrition, so typing a recipe adds
    # its ingredients to the pantry the same way importing one does. Stubs
    # are cheap; the Pantry page can merge or delete them.
    apply_ingredients(session, recipe, body.ingredients, auto_create=True)
    apply_steps(session, recipe, body.steps)
    session.commit()
    session.refresh(recipe)
    return recipe_read(session, recipe, user)


@router.patch("/{key}", response_model=RecipeRead)
def update_recipe(
    key: str,
    body: RecipeUpdate,
    session: Session = Depends(get_session),
    user: User = Depends(require_user_role),
):
    recipe = _get_recipe(session, key)
    fields = body.model_dump(exclude_unset=True)

    # Children are replaced wholesale, and only when the key was sent —
    # omitting `ingredients` leaves them alone, sending [] clears them.
    tags = fields.pop("tags", None)
    ingredients = fields.pop("ingredients", None)
    steps = fields.pop("steps", None)
    category_slug = fields.pop("category_slug", None)
    if category_slug is not None or "category_id" in fields:
        recipe.category_id = resolve_category(
            session, fields.pop("category_id", None), category_slug
        )

    if "title" in fields and fields["title"]:
        new_title = fields["title"].strip()
        # Re-slug only when the title genuinely changed, so editing a
        # description never breaks an existing link.
        if slugify(new_title) != slugify(recipe.title):
            recipe.slug = allocate_slug(session, new_title)
        fields["title"] = new_title

    for name, value in fields.items():
        setattr(recipe, name, value)
    touch(recipe)
    session.add(recipe)
    session.flush()

    if tags is not None:
        apply_tags(session, recipe, tags)
    if ingredients is not None:
        apply_ingredients(session, recipe, body.ingredients, auto_create=True)
    if steps is not None:
        apply_steps(session, recipe, body.steps)

    session.commit()
    session.refresh(recipe)
    return recipe_read(session, recipe, user)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recipe(
    key: str,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin_role),
):
    recipe = _get_recipe(session, key)
    apply_ingredients(session, recipe, [])
    apply_steps(session, recipe, [])
    apply_tags(session, recipe, [])
    for event in session.exec(
        select(PreparedEvent).where(PreparedEvent.recipe_id == recipe.id)
    ).all():
        session.delete(event)
    session.delete(recipe)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------
# Prepared log
# --------------------------------------------------------------------------


@router.post(
    "/{key}/prepared",
    response_model=PreparedEventRead,
    status_code=status.HTTP_201_CREATED,
)
def mark_prepared(
    key: str,
    body: PreparedEventCreate,
    session: Session = Depends(get_session),
    user: User = Depends(require_user_role),
):
    """Record that this recipe was cooked. The recipe's Last Prepared Date
    is the newest of these events (see DATA_MODEL.md)."""
    recipe = _get_recipe(session, key)
    event = PreparedEvent(
        recipe_id=recipe.id,
        prepared_on=body.prepared_on or date.today(),
        user_id=user.id,
        rating=body.rating,
        note=body.note,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return PreparedEventRead(
        id=event.id,
        recipe_id=event.recipe_id,
        prepared_on=event.prepared_on,
        user_id=event.user_id,
        user_name=user.name or user.email,
        rating=event.rating,
        note=event.note,
    )


@router.delete("/{key}/prepared/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prepared(
    key: str,
    event_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(require_user_role),
):
    recipe = _get_recipe(session, key)
    event = session.get(PreparedEvent, event_id)
    if event is None or event.recipe_id != recipe.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such prepared entry")
    session.delete(event)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------


@router.post("/{key}/image", response_model=RecipeRead)
async def upload_image(
    key: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    user: User = Depends(require_user_role),
):
    """Store a recipe photo under UPLOAD_DIR and point the recipe at it.

    Extensions come from the declared content type, never from the client's
    filename — an uploaded "x.html" must not end up served as HTML from our
    own origin.
    """
    extension = ALLOWED_IMAGE_TYPES.get((file.content_type or "").lower())
    if extension is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported image type {file.content_type!r} — use JPEG, PNG, WebP or GIF",
        )
    payload = await file.read()
    if len(payload) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Image must be 8MB or smaller"
        )

    recipe = _get_recipe(session, key)
    relative = Path("recipes") / f"{recipe.slug}{extension}"
    destination = Path(settings.upload_dir) / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)

    recipe.image_path = str(relative)
    touch(recipe)
    session.add(recipe)
    session.commit()
    session.refresh(recipe)
    return recipe_read(session, recipe, user)
