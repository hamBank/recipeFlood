"""CORS for the desktop app's webview origins (see SPEC.md "Desktop app
sign-in"). The web app is same-origin and must be unaffected."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from backend import main as main_module
from backend.config import settings
from backend.database import get_session

TAURI = "tauri://localhost"
TAURI_WINDOWS = "http://tauri.localhost"


def _preflight(client, origin, path="/recipes"):
    return client.options(
        path,
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )


@pytest.fixture
def client_with_origins(engine, monkeypatch):
    """A client for an app built with the given DESKTOP_ORIGINS value
    (the middleware is wired at app creation, so it can't be flipped on
    the shared `app` fixture afterwards)."""

    def build(origins):
        monkeypatch.setattr(settings, "auth_enabled", False)
        monkeypatch.setattr(settings, "desktop_origins", origins)
        application = main_module.create_app()

        def override():
            with Session(engine) as session:
                yield session

        application.dependency_overrides[get_session] = override
        return TestClient(application)

    return build


class TestCors:
    @pytest.mark.parametrize("origin", [TAURI, TAURI_WINDOWS, "https://tauri.localhost"])
    def test_preflight_from_a_desktop_origin_is_allowed(self, client, origin):
        response = _preflight(client, origin)
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["access-control-max-age"] == "600"
        assert "access-control-allow-credentials" not in response.headers

    def test_preflight_allows_the_auth_and_content_type_headers(self, client):
        response = client.options(
            "/recipes",
            headers={
                "Origin": TAURI,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert response.status_code == 200

    def test_preflight_from_another_origin_gets_no_allow_origin(self, client):
        response = _preflight(client, "https://evil.example")
        assert "access-control-allow-origin" not in response.headers

    def test_wildcard_is_never_used(self, client):
        response = _preflight(client, TAURI)
        assert response.headers["access-control-allow-origin"] != "*"

    def test_simple_get_exposes_the_total_count_header(self, client):
        response = client.get("/recipes", headers={"Origin": TAURI})
        assert response.headers["access-control-allow-origin"] == TAURI
        assert "X-Total-Count" in response.headers["access-control-expose-headers"]

    def test_empty_setting_turns_cors_off(self, client_with_origins):
        client = client_with_origins("")
        response = _preflight(client, TAURI)
        assert "access-control-allow-origin" not in response.headers
        response = client.get("/recipes", headers={"Origin": TAURI})
        assert "access-control-allow-origin" not in response.headers

    def test_a_request_without_an_origin_is_unchanged(self, client):
        response = client.get("/recipes")
        assert response.status_code == 200
        assert not [h for h in response.headers if h.startswith("access-control")]
        assert "vary" not in response.headers


class TestCorsWithTheAppShell:
    def test_a_browser_navigation_still_gets_the_app_shell(self, tmp_path, engine, monkeypatch):
        static_dir = tmp_path / "static"
        static_dir.mkdir()
        (static_dir / "index.html").write_text("<!doctype html><body>the shell</body>")
        monkeypatch.setattr(main_module, "STATIC_DIR", static_dir)
        monkeypatch.setattr(settings, "auth_enabled", False)
        application = main_module.create_app()

        def override():
            with Session(engine) as session:
                yield session

        application.dependency_overrides[get_session] = override
        client = TestClient(application)

        response = client.get("/recipes/anything", headers={"Accept": "text/html"})
        assert "the shell" in response.text
        # ...and a preflight reaches CORS rather than the shell or the SPA
        # catch-all.
        preflight = _preflight(client, TAURI, "/recipes/anything")
        assert preflight.status_code == 200
        assert "the shell" not in preflight.text
