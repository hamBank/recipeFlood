"""GET /auth/config — the unauthenticated client bootstrap."""

from backend.config import settings


class TestAuthConfig:
    def test_pantry_multi_merge_defaults_to_off(self, client):
        assert client.get("/auth/config").json()["pantry_multi_merge"] is False

    def test_pantry_multi_merge_reflects_the_setting(self, client, monkeypatch):
        monkeypatch.setattr(settings, "pantry_multi_merge", True)
        assert client.get("/auth/config").json()["pantry_multi_merge"] is True

    def test_sheet_sync_enabled_defaults_to_off(self, client):
        assert client.get("/auth/config").json()["sheet_sync_enabled"] is False

    def test_sheet_sync_enabled_reflects_config(self, client, monkeypatch):
        monkeypatch.setattr(settings, "google_sheet_id", "sheet123")
        monkeypatch.setattr(settings, "google_service_account_file", "/tmp/sa.json")
        assert client.get("/auth/config").json()["sheet_sync_enabled"] is True

    def test_sheet_sync_enabled_needs_both_settings(self, client, monkeypatch):
        monkeypatch.setattr(settings, "google_sheet_id", "sheet123")
        monkeypatch.setattr(settings, "google_service_account_file", "")
        assert client.get("/auth/config").json()["sheet_sync_enabled"] is False
