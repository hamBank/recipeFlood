import hashlib
import hmac
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .config import settings
from .database import engine
from .routers import (
    auth_router,
    cook_lists,
    imports,
    ingredients,
    recipes,
    shopping,
    taxonomy,
    users,
)
from .version import backend_version, frontend_version

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="Recipe Flood")

    @app.get("/health")
    def health():
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        frontend = frontend_version()
        return {
            "status": "ok",
            "backend_version": backend_version(),
            "frontend_version": frontend["version"],
            "frontend_built_at": frontend["built_at"],
        }

    @app.post("/deploy")
    async def deploy(request: Request):
        """GitHub push webhook → touch .deploy-trigger; a systemd path unit
        watching that file runs deploy.sh --update (see DEPLOYMENT.md)."""
        if not settings.deploy_secret:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Deploy webhook not configured"
            )
        body = await request.body()
        signature = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(
            settings.deploy_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Bad signature")
        try:
            ref = json.loads(body).get("ref")
        except (json.JSONDecodeError, AttributeError):
            ref = None
        # GitHub sends pushes for every branch; only main redeploys.
        if ref is not None and ref != "refs/heads/main":
            return {"status": "ignored", "ref": ref}
        Path(settings.deploy_trigger_path).touch()
        return {"status": "triggered"}

    app.include_router(auth_router.router)
    app.include_router(users.router)
    app.include_router(taxonomy.router)
    app.include_router(recipes.router)
    app.include_router(ingredients.router)
    app.include_router(imports.router)
    app.include_router(cook_lists.router)
    app.include_router(shopping.router)

    # Recipe photos, self-hosted rather than hotlinked back to Blogger
    # (see SPEC.md "Images"). Mounted before the SPA catch-all.
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=upload_dir), name="media")

    # Routers must be included above this line — the SPA catch-all matches
    # everything and must be registered last.
    if STATIC_DIR.is_dir():

        @app.get("/{spa_path:path}", include_in_schema=False)
        def spa(spa_path: str):
            candidate = STATIC_DIR / spa_path
            if spa_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
