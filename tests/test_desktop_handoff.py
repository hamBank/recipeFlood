"""The desktop app's sign-in handoff (see SPEC.md "Desktop app sign-in")."""

import re
import secrets
from urllib.parse import parse_qs, urlparse

import pytest

from backend import auth as auth_module
from backend import desktop_handoff
from backend.config import settings
from backend.models import User, UserRole

STATE = secrets.token_urlsafe(32)


@pytest.fixture(autouse=True)
def _clean_store():
    desktop_handoff._reset()
    yield
    desktop_handoff._reset()


@pytest.fixture
def auth_on(app, monkeypatch):
    # Reverted at teardown in reverse order, after the `app` fixture's own
    # patch is still in place — unlike monkeypatch.undo(), which would
    # also revert the fixture's patches.
    monkeypatch.setattr(settings, "auth_enabled", True)
    # The dev default secret is shorter than PyJWT's recommended 32 bytes
    # for HS256, and every token these tests mint would warn about it.
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-" + "x" * 32)


@pytest.fixture
def member(session):
    user = User(email="cook@example.com", name="Cook", role=UserRole.user, google_sub="g1")
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _bearer(user):
    return {"Authorization": f"Bearer {auth_module.create_access_token(user)}"}


def _handoff(client, user, port=53123, state=STATE):
    return client.post(
        "/auth/desktop-handoff",
        json={"port": port, "state": state},
        headers=_bearer(user),
    )


def _code_from(response):
    url = urlparse(response.json()["redirect_url"])
    return parse_qs(url.query)["code"][0]


class TestHandoff:
    def test_requires_auth(self, client, auth_on):
        response = client.post("/auth/desktop-handoff", json={"port": 53123, "state": STATE})
        assert response.status_code == 401

    @pytest.mark.parametrize("port", [80, 1023, 65536, 70000])
    def test_rejects_a_bad_port(self, client, auth_on, member, port):
        assert _handoff(client, member, port=port).status_code == 422

    @pytest.mark.parametrize("state", ["short", "x" * 129, "a" * 31 + "!", "a" * 31 + " ", "a" * 31 + "&"])
    def test_rejects_a_bad_state(self, client, auth_on, member, state):
        assert _handoff(client, member, state=state).status_code == 422

    def test_redirects_to_loopback_with_the_code_and_state(self, client, auth_on, member):
        response = _handoff(client, member)
        assert response.status_code == 200
        url = urlparse(response.json()["redirect_url"])
        assert url.scheme == "http"
        assert url.hostname == "127.0.0.1"
        assert url.netloc == "127.0.0.1:53123"
        assert url.path == "/callback"
        query = parse_qs(url.query)
        assert query["state"] == [STATE]
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", query["code"][0])

    def test_the_url_carries_no_token(self, client, auth_on, member):
        token = auth_module.create_access_token(member)
        assert token not in _handoff(client, member).json()["redirect_url"]


class TestExchange:
    def _exchange(self, client, code, state=STATE):
        return client.post("/auth/desktop-exchange", json={"code": code, "state": state})

    def test_returns_a_token_that_works(self, client, auth_on, member):
        code = _code_from(_handoff(client, member))
        response = self._exchange(client, code)
        assert response.status_code == 200
        body = response.json()
        assert body["user"]["email"] == "cook@example.com"
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
        assert me.status_code == 200
        assert me.json()["email"] == "cook@example.com"

    def test_needs_no_auth_header(self, client, auth_on, member):
        code = _code_from(_handoff(client, member))
        assert self._exchange(client, code).status_code == 200

    def test_a_code_is_single_use(self, client, auth_on, member):
        code = _code_from(_handoff(client, member))
        assert self._exchange(client, code).status_code == 200
        assert self._exchange(client, code).status_code == 401

    def test_an_unknown_code_is_rejected(self, client, auth_on):
        assert self._exchange(client, "nope").status_code == 401

    def test_a_wrong_state_is_rejected_and_burns_the_code(self, client, auth_on, member):
        code = _code_from(_handoff(client, member))
        assert self._exchange(client, code, state=secrets.token_urlsafe(32)).status_code == 401
        assert self._exchange(client, code).status_code == 401

    def test_an_expired_code_is_rejected(self, client, auth_on, member, monkeypatch):
        code = _code_from(_handoff(client, member))
        with monkeypatch.context() as patch:
            now = desktop_handoff.time.monotonic()
            patch.setattr(
                desktop_handoff.time,
                "monotonic",
                lambda: now + desktop_handoff.CODE_LIFETIME_SECONDS + 1,
            )
            assert self._exchange(client, code).status_code == 401

    def test_a_code_just_inside_its_lifetime_still_works(self, client, auth_on, member, monkeypatch):
        code = _code_from(_handoff(client, member))
        with monkeypatch.context() as patch:
            now = desktop_handoff.time.monotonic()
            patch.setattr(
                desktop_handoff.time,
                "monotonic",
                lambda: now + desktop_handoff.CODE_LIFETIME_SECONDS - 1,
            )
            assert self._exchange(client, code).status_code == 200

    def test_a_user_deactivated_after_the_handoff_is_refused(
        self, client, auth_on, member, session
    ):
        code = _code_from(_handoff(client, member))
        member.is_active = False
        session.add(member)
        session.commit()
        assert self._exchange(client, code).status_code == 403


class TestStore:
    def test_issuing_purges_expired_codes(self, monkeypatch):
        old = desktop_handoff.issue(1, STATE)
        with monkeypatch.context() as patch:
            now = desktop_handoff.time.monotonic()
            patch.setattr(
                desktop_handoff.time,
                "monotonic",
                lambda: now + desktop_handoff.CODE_LIFETIME_SECONDS + 1,
            )
            desktop_handoff.issue(2, STATE)
        assert old not in desktop_handoff._codes
