#!/bin/bash
set -euo pipefail

# Only runs in Claude Code on the web — a local checkout is assumed to
# already have its own venv/node_modules set up the way the developer
# wants them.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# --- Backend ----------------------------------------------------------------
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt

# Local dev bypass (see DEVELOPMENT.md "Running") — no Google OAuth secret
# is available in this environment, so sign-in has to be bypassed for the
# app to be usable at all. AI import and image generation are unaffected:
# with no ANTHROPIC_API_KEY / OPENAI_API_KEY set, they just report
# "not configured" rather than failing.
{
  echo "export AUTH_ENABLED=false"
  echo "export PATH=\"$CLAUDE_PROJECT_DIR/.venv/bin:\$PATH\""
} >> "$CLAUDE_ENV_FILE"

# Creates/updates the local SQLite dev DB (DATABASE_URL's default).
alembic upgrade head

# The 20 navigation sections — idempotent, matched by slug (same script
# deploy.sh runs on every real deploy), so the nav isn't empty on a fresh
# database.
python scripts/seed_sections.py

# --- Frontend -----------------------------------------------------------
cd frontend
npm install
