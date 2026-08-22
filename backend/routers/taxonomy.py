"""Categories (a recipe's single "Type") and tags (many, free-form)."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session, func, select

from ..database import get_session
from ..models import (
    Category,
    CategoryCreate,
    CategoryRead,
    Recipe,
    RecipeTagLink,
    Tag,
    TagRead,
    User,
)
from ..permissions import allow_public_read, require_admin_role
from ..slugs import unique_slug

router = APIRouter(tags=["taxonomy"])


@router.get("/categories", response_model=list[CategoryRead])
def list_categories(
    session: Session = Depends(get_session),
    _user: User | None = Depends(allow_public_read),
):
    counts = dict(
        session.exec(
            select(Recipe.category_id, func.count(Recipe.id))
            .where(Recipe.is_published == True)  # noqa: E712
            .group_by(Recipe.category_id)
        ).all()
    )
    categories = session.exec(
        select(Category).order_by(Category.sort_order, Category.name)
    ).all()
    return [
        CategoryRead(
            id=c.id,
            slug=c.slug,
            name=c.name,
            description=c.description,
            sort_order=c.sort_order,
            recipe_count=counts.get(c.id, 0),
        )
        for c in categories
    ]


@router.post(
    "/categories", response_model=CategoryRead, status_code=status.HTTP_201_CREATED
)
def create_category(
    body: CategoryCreate,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin_role),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name is required")
    slug = unique_slug(
        body.slug or name,
        lambda s: session.exec(select(Category).where(Category.slug == s)).first()
        is not None,
    )
    category = Category(
        slug=slug,
        name=name,
        description=body.description,
        sort_order=body.sort_order,
    )
    session.add(category)
    session.commit()
    session.refresh(category)
    return CategoryRead(
        id=category.id,
        slug=category.slug,
        name=category.name,
        description=category.description,
        sort_order=category.sort_order,
        recipe_count=0,
    )


@router.get("/tags", response_model=list[TagRead])
def list_tags(
    session: Session = Depends(get_session),
    _user: User | None = Depends(allow_public_read),
    min_count: int = 1,
):
    """Tags with their usage counts, most-used first — the shape a tag
    cloud or filter bar wants. Unused tags are dropped by default."""
    counts = dict(
        session.exec(
            select(RecipeTagLink.tag_id, func.count(RecipeTagLink.recipe_id)).group_by(
                RecipeTagLink.tag_id
            )
        ).all()
    )
    tags = session.exec(select(Tag)).all()
    result = [
        TagRead(id=t.id, slug=t.slug, name=t.name, recipe_count=counts.get(t.id, 0))
        for t in tags
        if counts.get(t.id, 0) >= min_count
    ]
    result.sort(key=lambda t: (-t.recipe_count, t.name.lower()))
    return result


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(
    tag_id: int,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin_role),
):
    tag = session.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such tag")
    for link in session.exec(
        select(RecipeTagLink).where(RecipeTagLink.tag_id == tag_id)
    ).all():
        session.delete(link)
    session.delete(tag)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
