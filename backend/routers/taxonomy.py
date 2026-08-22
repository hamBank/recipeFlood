"""Tags — the site's only taxonomy.

Most tags are free-form labels for search. A curated few carry
`is_section` and form the navigation; see the `Tag` docstring in
models.py for why that's one table rather than two.

Reads are public. Creating a tag, promoting one to a section, reordering
the nav and deleting are all admin.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session, func, select

from ..database import get_session
from ..models import (
    RecipeTagLink,
    Tag,
    TagCreate,
    TagRead,
    TagUpdate,
    User,
)
from ..permissions import allow_public_read, require_admin_role
from ..slugs import unique_slug

router = APIRouter(prefix="/tags", tags=["tags"])


def _counts(session: Session) -> dict[int, int]:
    return dict(
        session.exec(
            select(RecipeTagLink.tag_id, func.count(RecipeTagLink.recipe_id)).group_by(
                RecipeTagLink.tag_id
            )
        ).all()
    )


def _read(tag: Tag, count: int = 0) -> TagRead:
    return TagRead(
        id=tag.id,
        slug=tag.slug,
        name=tag.name,
        is_section=tag.is_section,
        sort_order=tag.sort_order,
        description=tag.description,
        recipe_count=count,
    )


def _lookup(session: Session, key: str) -> Tag:
    tag = None
    if key.isdigit():
        tag = session.get(Tag, int(key))
    if tag is None:
        tag = session.exec(select(Tag).where(Tag.slug == key)).first()
    if tag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such tag")
    return tag


@router.get("", response_model=list[TagRead])
def list_tags(
    session: Session = Depends(get_session),
    _user: User | None = Depends(allow_public_read),
    section: bool | None = None,
    min_count: int = 0,
):
    """Tags with usage counts.

    `?section=true` is the navigation: curated tags in nav order, returned
    whether or not anything uses them yet, so an empty section still shows
    up for an editor. Free-form tags come back most-used first, and
    `min_count=2` is the usual way to drop the long tail of one-offs —
    over half of the imported labels are used exactly once.
    """
    counts = _counts(session)
    rows = session.exec(select(Tag)).all()

    if section is True:
        rows = [t for t in rows if t.is_section]
        rows.sort(key=lambda t: (t.sort_order, t.name.lower()))
        return [_read(t, counts.get(t.id, 0)) for t in rows]

    if section is False:
        rows = [t for t in rows if not t.is_section]

    result = [
        _read(t, counts.get(t.id, 0))
        for t in rows
        # Sections are never hidden by min_count — they are the nav.
        if t.is_section or counts.get(t.id, 0) >= min_count
    ]
    result.sort(key=lambda t: (not t.is_section, -t.recipe_count, t.name.lower()))
    return result


@router.get("/{key}", response_model=TagRead)
def get_tag(
    key: str,
    session: Session = Depends(get_session),
    _user: User | None = Depends(allow_public_read),
):
    tag = _lookup(session, key)
    return _read(tag, _counts(session).get(tag.id, 0))


@router.post("", response_model=TagRead, status_code=status.HTTP_201_CREATED)
def create_tag(
    body: TagCreate,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin_role),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name is required")
    slug = unique_slug(
        body.slug or name,
        lambda s: session.exec(select(Tag).where(Tag.slug == s)).first() is not None,
    )
    tag = Tag(
        slug=slug,
        name=name,
        is_section=body.is_section,
        sort_order=body.sort_order,
        description=body.description,
    )
    session.add(tag)
    session.commit()
    session.refresh(tag)
    return _read(tag)


@router.patch("/{key}", response_model=TagRead)
def update_tag(
    key: str,
    body: TagUpdate,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin_role),
):
    """Rename a tag, or promote/demote it between section and free-form.

    Promotion is the intended way to grow the nav: a free tag that turns
    out to be load-bearing becomes a section without any recipe changing,
    because every recipe already links to that same tag row.
    """
    tag = _lookup(session, key)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(tag, field, value)
    session.add(tag)
    session.commit()
    session.refresh(tag)
    return _read(tag, _counts(session).get(tag.id, 0))


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(
    key: str,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin_role),
):
    tag = _lookup(session, key)
    for link in session.exec(
        select(RecipeTagLink).where(RecipeTagLink.tag_id == tag.id)
    ).all():
        session.delete(link)
    session.delete(tag)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
