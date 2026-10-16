import hashlib
import hmac
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.datastructures import Headers
from starlette.types import Receive, Scope, Send

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

#: Never served as the app shell, even when a browser navigates straight to
#: them — the real health check / webhook / FastAPI's own interactive docs.
_API_ONLY_PATHS = {"/health", "/deploy", "/docs", "/redoc", "/openapi.json"}


class _CrossOriginOnlyCORS(CORSMiddleware):
    """CORSMiddleware that leaves a request with no `Origin` header alone.

    Starlette's own version appends `Vary: Origin` to every response, even
    one with nothing cross-origin about it. The web app's same-origin GETs
    carry no `Origin`, and they (the app shell's `Vary: Accept` above in
    particular) must come out byte-for-byte as they did before CORS
    existed here.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and "origin" not in Headers(scope=scope):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


def _static_file(path: str) -> Path | None:
    """The file `path` maps to under `STATIC_DIR`, if any exists."""
    candidate = STATIC_DIR / path.lstrip("/")
    return candidate if path and candidate.is_file() else None


def _index_response() -> FileResponse:
    """The app shell — never cached, and never reused across a differing
    `Accept` header. The shell and the API can share a URL (a recipe's
    page and `GET /recipes/{slug}` both live at /recipes/<slug>), and a
    browser's HTTP cache keys purely on URL+method unless told otherwise:
    without `Vary: Accept`, a cached copy of this HTML response can get
    served back to the frontend's own later `fetch()` call to that exact
    URL instead of hitting the JSON API — same symptom as not having this
    content negotiation at all, just one layer further down. `no-store`
    on top of that because the shell references hashed asset filenames
    that change on every deploy; it must never outlive a redeploy either.
    """
    response = FileResponse(STATIC_DIR / "index.html")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "Accept"
    return response


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

    if STATIC_DIR.is_dir():

        @app.middleware("http")
        async def prefer_app_shell_for_browser_navigation(request: Request, call_next):
            """A recipe's page and its API endpoint share one URL —
            `GET /recipes/{slug}` — because that's the right address for
            both: the frontend route the recipe naturally lives at, and
            the API's own way of fetching it. React Router only ever
            handles that path client-side, so the collision is invisible
            during normal browsing, but a hard reload, a typed address, or
            a shared link sends a real request to the server, and the API
            router (registered first, and correctly so — see below) would
            otherwise answer with raw JSON instead of the app shell.

            The fix is content negotiation, not a route rename (unlike
            the pages DEVELOPMENT.md's "Cooking lists" section describes
            avoiding this by naming around — a recipe's URL can't
            reasonably be anything other than /recipes/<slug>). A genuine
            browser navigation sends `Accept: text/html...`; `fetch()`
            calls (this app's own frontend) and non-browser clients
            (curl, the test suite) don't, so only real navigations are
            intercepted here — everything else still reaches the API
            exactly as before.
            """
            path = request.url.path
            if (
                request.method == "GET"
                and "text/html" in request.headers.get("accept", "")
                and path not in _API_ONLY_PATHS
                and not path.startswith("/media/")
                and _static_file(path) is None
            ):
                return _index_response()
            return await call_next(request)

    # Added after the middleware above on purpose: Starlette makes the last
    # one added the outermost, so CORS answers a preflight OPTIONS itself
    # and stamps its headers on every response, including the app shell,
    # before anything else sees the request. (The shell middleware only
    # acts on GET, so it would ignore OPTIONS anyway.) Only the desktop
    # app's origins are listed, never "*", and credentials stay off: auth
    # is a bearer header, not a cookie.
    desktop_origins = [
        origin.strip()
        for origin in settings.desktop_origins.split(",")
        if origin.strip()
    ]
    if desktop_origins:
        app.add_middleware(
            _CrossOriginOnlyCORS,
            allow_origins=desktop_origins,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
            # Cross-origin, a response hides every header but the basics;
            # the frontend's paging reads X-Total-Count (api.js).
            expose_headers=["X-Total-Count"],
            allow_credentials=False,
            max_age=600,
        )

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
    # everything and must be registered last. (The middleware above already
    # routes real browser navigations to the app shell before they'd ever
    # reach a router; this is the fallback for everything else unmatched —
    # a genuinely unknown path, or a static asset the middleware skipped
    # because the request wasn't a navigation.)
    if STATIC_DIR.is_dir():

        @app.get("/{spa_path:path}", include_in_schema=False)
        def spa(spa_path: str):
            static = _static_file(spa_path)
            return FileResponse(static) if static else _index_response()

    return app


app = create_app()
