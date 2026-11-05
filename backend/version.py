"""Build and release identity for `/health` (fleet spec BLD-2/OBS-1, see API.md).

`backend_version()` is the git commit the running process was checked
out at — cached, since the systemd service restarts on every deploy
(see DEPLOYMENT.md), so it only needs computing once per process.

`frontend_version()` reads `static/version.json`, written by
`npm run build` (frontend/scripts/write-version.js) before Vite copies
`public/` into that directory: `build_sha` (the commit that was built),
`frontend_sha` (the last commit that changed the frontend) and
`built_at`. Read fresh on every call rather than cached: the service can
restart before the build finishes, and a rebuild without a restart (or
the reverse) should show in `/health` immediately.
"""

import json
import subprocess
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = Path(__file__).parent / "static" / "version.json"

#: When this process started, for `/health`'s `started_at`.
STARTED_AT = datetime.now(timezone.utc).isoformat()


@lru_cache
def backend_version() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def frontend_version() -> dict:
    try:
        data = json.loads(VERSION_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {key: data.get(key) for key in ("build_sha", "frontend_sha", "built_at")}
