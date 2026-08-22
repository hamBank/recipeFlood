from fastapi import Depends, HTTPException, status

from .auth import get_current_user, get_optional_user
from .config import settings
from .models import User, UserRole


def require_user_role(user: User = Depends(get_current_user)) -> User:
    return user


def require_admin_role(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator role required")
    return user


def allow_public_read(user: User | None = Depends(get_optional_user)) -> User | None:
    """Gate for read-only recipe endpoints.

    With PUBLIC_READ=true (the default) anonymous callers pass through as
    None. Setting it false converts the whole site to allowlist-only
    without touching any handler.
    """
    if user is None and not settings.public_read:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user
