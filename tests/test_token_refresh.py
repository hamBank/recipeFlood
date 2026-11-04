"""Sliding sign-in sessions: a token past halfway through its life is
swapped for a fresh one on the response (see backend/auth.py)."""

from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from backend import auth as auth_module
from backend import main as main_module
from backend.config import settings
from backend.database import get_session
from backend.models import User, UserRole, utcnow

SECRET = "test-secret-" + "x" * 32


@pytest.fixture
def auth_client(app, monkeypatch):
    """A client against the real auth dependencies (no overrides)."""
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "jwt_secret", SECRET)
    return TestClient(app)


@pytest.fixture
def member(session):
    user = User(email="cook@example.com", name="Cook", role=UserRole.user, google_sub="g1")
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _token(user, age, *, with_iat=True):
    issued = utcnow() - age
    payload = {"sub": str(user.id), "exp": issued + auth_module.TOKEN_LIFETIME}
    if with_iat:
        payload["iat"] = issued
    return jwt.encode(payload, SECRET, algorithm="HS256")


def _get_me(client, token, **headers):
    return client.get("/auth/me", headers={"Authorization": f"Bearer {token}", **headers})


def test_a_young_token_is_left_alone(auth_client, member):
    response = _get_me(auth_client, _token(member, timedelta(days=2)))
    assert response.status_code == 200
    assert auth_module.REFRESH_HEADER not in response.headers


def test_a_token_past_halfway_gets_a_fresh_one(auth_client, member):
    response = _get_me(auth_client, _token(member, timedelta(days=20)))
    assert response.status_code == 200
    fresh = response.headers[auth_module.REFRESH_HEADER]
    claims = jwt.decode(fresh, SECRET, algorithms=["HS256"])
    assert claims["sub"] == str(member.id)
    assert claims["exp"] - claims["iat"] == auth_module.TOKEN_LIFETIME.total_seconds()
    # And the fresh one works, without needing another refresh yet.
    again = _get_me(auth_client, fresh)
    assert again.status_code == 200
    assert auth_module.REFRESH_HEADER not in again.headers


def test_a_token_from_before_iat_is_aged_from_its_expiry(auth_client, member):
    old = _get_me(auth_client, _token(member, timedelta(days=20), with_iat=False))
    assert auth_module.REFRESH_HEADER in old.headers
    young = _get_me(auth_client, _token(member, timedelta(days=2), with_iat=False))
    assert auth_module.REFRESH_HEADER not in young.headers


def test_public_reads_refresh_a_signed_in_visitor_too(auth_client, member):
    response = auth_client.get(
        "/recipes", headers={"Authorization": f"Bearer {_token(member, timedelta(days=20))}"}
    )
    assert response.status_code == 200
    assert auth_module.REFRESH_HEADER in response.headers


def test_an_expired_token_is_refused_and_not_refreshed(auth_client, member):
    response = _get_me(auth_client, _token(member, timedelta(days=31)))
    assert response.status_code == 401
    assert auth_module.REFRESH_HEADER not in response.headers


def test_an_inactive_user_gets_no_fresh_token(auth_client, member, session):
    member.is_active = False
    session.add(member)
    session.commit()
    response = _get_me(auth_client, _token(member, timedelta(days=20)))
    assert response.status_code == 401
    assert auth_module.REFRESH_HEADER not in response.headers


def test_a_failed_request_never_carries_a_fresh_token(auth_client, member):
    response = auth_client.get(
        "/recipes/no-such-recipe",
        headers={"Authorization": f"Bearer {_token(member, timedelta(days=20))}"},
    )
    assert response.status_code == 404
    assert auth_module.REFRESH_HEADER not in response.headers


def test_the_desktop_app_can_read_the_header_cross_origin(engine, monkeypatch, member):
    # CORS is wired at app creation, so this needs its own app.
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "jwt_secret", SECRET)
    monkeypatch.setattr(settings, "desktop_origins", "tauri://localhost")
    application = main_module.create_app()

    def override():
        with Session(engine) as session:
            yield session

    application.dependency_overrides[get_session] = override
    response = _get_me(
        TestClient(application), _token(member, timedelta(days=20)), Origin="tauri://localhost"
    )
    assert auth_module.REFRESH_HEADER in response.headers
    exposed = response.headers["access-control-expose-headers"].lower()
    assert auth_module.REFRESH_HEADER.lower() in exposed
