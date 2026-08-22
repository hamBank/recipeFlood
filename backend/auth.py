from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlmodel import Session, select

from .config import settings
from .database import get_session
from .models import User, UserRole, utcnow

TOKEN_LIFETIME = timedelta(days=30)
DEV_USER_EMAIL = "dev@localhost"

bearer_scheme = HTTPBearer(auto_error=False)


def verify_google_token(credential: str) -> dict:
    """Verify a Google ID token and return its claims. Raises ValueError."""
    return google_id_token.verify_oauth2_token(
        credential, google_requests.Request(), settings.google_client_id
    )


def allowed_emails() -> set[str]:
    return {
        email.strip().lower()
        for email in settings.allowed_emails.split(",")
        if email.strip()
    }


def create_access_token(user: User) -> str:
    payload = {"sub": str(user.id), "exp": utcnow() + TOKEN_LIFETIME}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _dev_user(session: Session) -> User:
    """AUTH_ENABLED=false: everyone is a persisted local admin (dev only)."""
    user = session.exec(select(User).where(User.email == DEV_USER_EMAIL)).first()
    if user is None:
        user = User(
            email=DEV_USER_EMAIL,
            name="Dev Admin",
            role=UserRole.admin,
            google_sub="dev",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
    return user


def _user_from_credentials(
    creds: HTTPAuthorizationCredentials | None, session: Session
) -> User | None:
    if creds is None:
        return None
    try:
        payload = jwt.decode(
            creds.credentials, settings.jwt_secret, algorithms=["HS256"]
        )
    except jwt.PyJWTError:
        return None
    user = session.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        return None
    return user


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> User:
    if not settings.auth_enabled:
        return _dev_user(session)
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user = _user_from_credentials(creds, session)
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid token, or unknown/inactive user"
        )
    return user


def get_optional_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> User | None:
    """Resolve the caller if they are signed in, else None — never raises.

    This is what makes "public read, costs behind login" work in a single
    handler: the recipe endpoints serve everyone, and consult the returned
    user only to decide whether to attach the cost block (see SPEC.md
    "Visibility"). A bad or expired token is treated as anonymous rather
    than as an error, so a stale tab keeps browsing instead of erroring.
    """
    if not settings.auth_enabled:
        return _dev_user(session)
    return _user_from_credentials(creds, session)
