"""The content negotiation in backend/main.py that lets a recipe's page
and its API endpoint share one URL (GET /recipes/{slug}) without a hard
reload or a shared link returning raw JSON instead of the app.

STATIC_DIR (backend/static) only exists once the frontend has been built,
which the `backend` CI job never does — so without a dedicated fixture
here, this whole code path has zero coverage under a plain `pytest` run.
Each test below builds its own tiny fake "built frontend" instead.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend import main as main_module
from backend.config import settings
from backend.database import get_session

_SHELL_MARKER = "the app shell, not the api"


@pytest.fixture
def spa_client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    monkeypatch.setattr(settings, "public_read", True)

    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text(f"<!doctype html><body>{_SHELL_MARKER}</body>")
    (static_dir / "assets" / "app.js").write_text("console.log('hi')")
    monkeypatch.setattr(main_module, "STATIC_DIR", static_dir)

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    application = main_module.create_app()

    def override():
        with Session(engine) as session:
            yield session

    application.dependency_overrides[get_session] = override
    return TestClient(application)


class TestSpaContentNegotiation:
    def test_a_browser_navigation_to_a_recipe_gets_the_app_shell(self, spa_client):
        spa_client.post("/recipes", json={"title": "French Toast"})
        response = spa_client.get(
            "/recipes/french-toast",
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9"},
        )
        assert response.status_code == 200
        assert _SHELL_MARKER in response.text

    def test_the_app_shell_response_is_never_cached_or_confused_with_json(
        self, spa_client
    ):
        # Without Vary: Accept, a browser's HTTP cache would key purely on
        # the URL and could serve this same cached HTML back to the
        # frontend's own later fetch() to the identical path — the exact
        # bug this whole mechanism exists to avoid, one layer further down.
        response = spa_client.get("/recipes/anything", headers={"Accept": "text/html"})
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["vary"] == "Accept"

    def test_a_fetch_style_request_to_the_same_url_still_gets_real_json(
        self, spa_client
    ):
        created = spa_client.post("/recipes", json={"title": "French Toast"}).json()
        response = spa_client.get("/recipes/french-toast")
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["id"] == created["id"]

    def test_health_is_never_swallowed_by_the_app_shell(self, spa_client):
        response = spa_client.get("/health", headers={"Accept": "text/html"})
        assert response.headers["content-type"].startswith("application/json")

    def test_a_direct_navigation_to_a_real_asset_still_serves_the_asset(
        self, spa_client
    ):
        # Someone typing a built asset's own URL into the address bar
        # sends the same browser-navigation Accept header as any other
        # page — it must still get the real file, not the app shell.
        response = spa_client.get("/assets/app.js", headers={"Accept": "text/html"})
        assert "console.log" in response.text

    def test_an_unmatched_path_falls_back_to_the_app_shell(self, spa_client):
        response = spa_client.get("/some/nonsense/path")
        assert _SHELL_MARKER in response.text
