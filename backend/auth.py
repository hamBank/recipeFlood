from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlmodel import Session, select

from .config import settings
from .database import get_session
from .models import User, UserRole, utcnow

TOKEN_LIFETIME = timedelta(days=30)
#: A token older than this gets swapped for a fresh one on the next request
#: it makes (see `_note_refresh`), so anyone who uses the app at least once a
#: fortnight or so stays signed in indefinitely, while a token left unused
#: for the full lifetime still expires.
REFRESH_AFTER = TOKEN_LIFETIME / 2
#: Response header carrying the fresh token (api.js stores it).
REFRESH_HEADER = "X-Refreshed-Token"
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
    now = utcnow()
    payload = {"sub": str(user.id), "iat": now, "exp": now + TOKEN_LIFETIME}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _note_refresh(request: Request, payload: dict, user: User) -> None:
    """Past halfway through its life, mint a replacement for this token.

    The new token rides back on the response as a header, never in a body
    or URL (see `RefreshTokenMiddleware`). Issued from the token's age
    rather than on every request, so most requests carry no header at all.
    A token from before `iat` was added is aged from its expiry instead.
    """
    expires = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    issued = (
        datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
        if "iat" in payload
        else expires - TOKEN_LIFETIME
    )
    if datetime.now(timezone.utc) - issued >= REFRESH_AFTER:
        request.state.refreshed_token = create_access_token(user)


class RefreshTokenMiddleware:
    """ASGI glue for `_note_refresh`: put a fresh token, if one was minted
    for this request, on its response. An error response gets none, so a
    request that failed for any reason never extends a session."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_token(message):
            if message["type"] == "http.response.start" and message["status"] < 400:
                token = scope.get("state", {}).get("refreshed_token")
                if token:
                    message["headers"] = list(message.get("headers", [])) + [
                        (REFRESH_HEADER.lower().encode(), token.encode())
                    ]
            await send(message)

        await self.app(scope, receive, send_with_token)


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
    creds: HTTPAuthorizationCredentials | None, session: Session, request: Request
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
    _note_refresh(request, payload, user)
    return user


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> User:
    if not settings.auth_enabled:
        return _dev_user(session)
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user = _user_from_credentials(creds, session, request)
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid token, or unknown/inactive user"
        )
    return user


def get_optional_user(
    request: Request,
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
    return _user_from_credentials(creds, session, request)
