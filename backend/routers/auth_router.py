from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from .. import desktop_handoff
from ..auth import (
    allowed_emails,
    create_access_token,
    get_current_user,
    verify_google_token,
)
from ..config import settings
from ..database import get_session
from ..models import User, UserRead, UserRole, UserSelfUpdate
from ..sheet_sync import sheet_sync_enabled

router = APIRouter(prefix="/auth", tags=["auth"])


class GoogleLoginRequest(BaseModel):
    credential: str  # Google ID token from Google Identity Services


class LoginResponse(BaseModel):
    token: str
    user: UserRead


class DesktopHandoffRequest(BaseModel):
    # Unprivileged ports only, so the handoff can't be aimed at a system
    # service; `state` is the desktop app's own random nonce.
    port: int = Field(ge=1024, le=65535)
    state: str = Field(pattern=r"^[A-Za-z0-9_-]{32,128}$")


class DesktopExchangeRequest(BaseModel):
    code: str
    state: str


@router.get("/config")
def auth_config():
    """Unauthenticated client bootstrap."""
    return {
        "auth_enabled": settings.auth_enabled,
        "google_client_id": settings.google_client_id,
        "public_read": settings.public_read,
        "currency_symbol": settings.currency_symbol,
        "units_system": settings.units_system,
        "pantry_multi_merge": settings.pantry_multi_merge,
        "sheet_sync_enabled": sheet_sync_enabled(),
    }


@router.post("/google", response_model=LoginResponse)
def google_login(body: GoogleLoginRequest, session: Session = Depends(get_session)):
    if not settings.auth_enabled:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Auth is disabled; use /auth/me directly"
        )
    try:
        claims = verify_google_token(body.credential)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Google token")

    email = claims["email"].lower()
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        if email not in allowed_emails():
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "This Google account is not on the allowlist",
            )
        # Bootstrap: the very first account to sign in becomes the admin;
        # everyone after that starts as a regular user (see SPEC.md).
        has_admin = (
            session.exec(select(User).where(User.role == UserRole.admin)).first()
            is not None
        )
        user = User(email=email, role=UserRole.user if has_admin else UserRole.admin)
    elif not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is deactivated")

    user.google_sub = claims["sub"]
    user.name = user.name or claims.get("name", "")
    user.avatar_url = claims.get("picture")
    session.add(user)
    session.commit()
    session.refresh(user)
    return LoginResponse(token=create_access_token(user), user=user)


@router.post("/desktop-handoff")
def desktop_handoff_start(
    body: DesktopHandoffRequest, user: User = Depends(get_current_user)
):
    """Step 1 of the desktop app's sign-in: a signed-in user, having
    clicked Continue on the website, gets a single-use code addressed to
    the app's loopback listener. The URL is built here, not taken from the
    client, so the host is always 127.0.0.1 — no open redirect, and the
    code can only reach a process on the user's own machine."""
    code = desktop_handoff.issue(user.id, body.state)
    return {
        "redirect_url": f"http://127.0.0.1:{body.port}/callback"
        f"?code={code}&state={body.state}"
    }


@router.post("/desktop-exchange", response_model=LoginResponse)
def desktop_exchange(
    body: DesktopExchangeRequest, session: Session = Depends(get_session)
):
    """Step 2: the desktop app trades its code (plus the state it
    generated) for the same token `POST /auth/google` returns. Public by
    necessity — the code is the credential."""
    user_id = desktop_handoff.redeem(body.code, body.state)
    if user_id is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired sign-in code"
        )
    user = session.get(User, user_id)
    # Deactivated in the (up to two-minute) gap since the code was issued.
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is deactivated")
    return LoginResponse(token=create_access_token(user), user=user)


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=UserRead)
def update_me(
    body: UserSelfUpdate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Self-service edits — UI preferences only, unlike PATCH /users/{id}
    which is admin-only and covers role/name/is_active."""
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(user, key, value)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user
