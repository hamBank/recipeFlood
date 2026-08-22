from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from ..database import get_session
from ..models import User, UserInvite, UserRead, UserUpdate
from ..permissions import require_admin_role

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserRead])
def list_users(
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin_role),
):
    return session.exec(select(User).order_by(User.name, User.email)).all()


@router.post("/invite", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def invite_user(
    body: UserInvite,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin_role),
):
    """Pre-create an account so a Google sign-in for that address is accepted
    without editing ALLOWED_EMAILS on the server."""
    email = body.email.strip().lower()
    if session.exec(select(User).where(User.email == email)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "That email already has an account")
    user = User(email=email, name=body.name, role=body.role)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    body: UserUpdate,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin_role),
):
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user")
    fields = body.model_dump(exclude_unset=True)
    # Guard against an admin locking everyone out of admin functions.
    if user.id == admin.id and ("role" in fields or fields.get("is_active") is False):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "You cannot demote or deactivate yourself"
        )
    for key, value in fields.items():
        setattr(user, key, value)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user
