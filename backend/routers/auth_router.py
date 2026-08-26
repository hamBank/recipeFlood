from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from ..auth import (
    allowed_emails,
    create_access_token,
    get_current_user,
    verify_google_token,
)
from ..config import settings
from ..database import get_session
from ..models import User, UserRead, UserRole

router = APIRouter(prefix="/auth", tags=["auth"])


class GoogleLoginRequest(BaseModel):
    credential: str  # Google ID token from Google Identity Services


class LoginResponse(BaseModel):
    token: str
    user: UserRead


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


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)):
    return user
