"""Version reporting for `/health` (see API.md).

`backend_version()` is the git commit the running process was checked
out at — cached, since the systemd service restarts on every deploy
(see DEPLOYMENT.md), so it only needs computing once per process.

`frontend_version()` reads `static/version.json`, written by
`npm run build` (frontend/scripts/write-version.js) before Vite copies
`public/` into that directory. Read fresh on every call rather than
cached: if a deploy rebuilds the frontend without restarting the
backend (or vice versa), the two versions in `/health` diverge
immediately instead of only after the next restart.
"""

import json
import subprocess
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = Path(__file__).parent / "static" / "version.json"


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
        return {"version": None, "built_at": None}
    return {"version": data.get("version"), "built_at": data.get("built_at")}
