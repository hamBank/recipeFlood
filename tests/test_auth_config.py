"""GET /auth/config — the unauthenticated client bootstrap."""

from backend.config import settings


class TestAuthConfig:
    def test_pantry_multi_merge_defaults_to_off(self, client):
        assert client.get("/auth/config").json()["pantry_multi_merge"] is False

    def test_pantry_multi_merge_reflects_the_setting(self, client, monkeypatch):
        monkeypatch.setattr(settings, "pantry_multi_merge", True)
        assert client.get("/auth/config").json()["pantry_multi_merge"] is True
