"""AI-assisted recipe import: paste some text, or photograph a page.

These endpoints never write a recipe. They return a *draft* in the shape
`POST /recipes` accepts, which the entry form loads for the user to check
and submit. A model reading a photo of a handwritten card will sometimes
get an amount wrong, and the cheapest place to catch that is before it
becomes a row.
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from ..ai_import import (
    AIImportUnavailable,
    draft_from_image,
    draft_from_text,
    is_configured,
)
from ..config import settings
from ..models import User
from ..permissions import require_user_role

router = APIRouter(prefix="/imports", tags=["imports"])

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TEXT_CHARS = 30_000


class PasteRequest(BaseModel):
    text: str
    title_hint: str | None = None


@router.get("/config")
def import_config(_user: User = Depends(require_user_role)):
    """Lets the UI hide the AI import tabs when no key is configured,
    rather than offering a button that 503s."""
    return {"ai_available": is_configured(), "model": settings.anthropic_model}


def _unavailable(error: AIImportUnavailable) -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error))


@router.post("/paste")
def import_paste(body: PasteRequest, _user: User = Depends(require_user_role)):
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No text supplied")
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Paste is {len(text)} characters; the limit is {MAX_TEXT_CHARS}",
        )
    try:
        return draft_from_text(text, title_hint=body.title_hint)
    except AIImportUnavailable as error:
        raise _unavailable(error)
    except ValueError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Could not parse: {error}")


@router.post("/image")
async def import_image(
    file: UploadFile = File(...),
    title_hint: str | None = Form(None),
    _user: User = Depends(require_user_role),
):
    media_type = (file.content_type or "").lower()
    if media_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported image type {media_type!r} — use JPEG, PNG, WebP or GIF",
        )
    payload = await file.read()
    if len(payload) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Image must be 8MB or smaller"
        )
    try:
        return draft_from_image(payload, media_type, title_hint=title_hint)
    except AIImportUnavailable as error:
        raise _unavailable(error)
    except ValueError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Could not parse: {error}")
