#!/usr/bin/env python3
"""Check the app's configuration as the service will see it, before restarting it.

    scripts/check_config.py /opt/<app>/.env [module]      # module default: backend.config

Copy to scripts/ in the app. deploy.sh runs it after pulling the new code and BEFORE
`systemctl restart`; a non-zero exit means "abort the deploy, leave the running service
alone" instead of restarting into a crash loop.

It loads the env file the way systemd's EnvironmentFile does (KEY=VALUE, optional
quotes, no shell expansion, so an unquoted `SHEET_NAMES=Itinerary 2026` is fine) and
imports the module that builds the app's settings. For a pydantic-settings app with
`settings = Settings()` at module level, that import runs every validator, including
the CFG-2 one that rejects the default JWT_SECRET.
"""
import importlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Settings the service gets only from its env file: don't let the deploy's own
# environment leak in and hide a problem. Add the app's security-relevant keys here.
CHECKED = ("AUTH_ENABLED", "GOOGLE_CLIENT_ID", "JWT_SECRET", "DEPLOY_SECRET")


def load_env_file(path: str) -> dict:
    values = {}
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def main(argv) -> int:
    if len(argv) not in (2, 3):
        print("usage: check_config.py ENV_FILE [module]", file=sys.stderr)
        return 2
    for key in CHECKED:
        os.environ.pop(key, None)
    os.environ.update(load_env_file(argv[1]))
    try:
        importlib.import_module(argv[2] if len(argv) == 3 else "backend.config")
    except Exception as e:  # anything that would stop the service starting
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print("configuration OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
