#!/usr/bin/env bash
# Recipe Flood provisioning + deploy. Idempotent — safe to re-run.
#
#   sudo ./deploy.sh            # full provision (packages, user, db, units, vhost)
#   sudo ./deploy.sh --update   # code update only (used by the webhook path unit)
#
# The repo is public, so it is cloned over HTTPS and no deploy key is
# needed. (If it is ever made private, switch REPO_URL to the SSH form and
# add a read-only deploy key for the recipeFlood user first.)
#
# After first provision:
#   1. Fill in /opt/recipeFlood/.env  (see .env.example)
#   2. certbot --apache -d recipeflood.hups.club
#   3. Add the GitHub webhook: POST https://recipeflood.hups.club/deploy,
#      content type application/json, secret = DEPLOY_SECRET, push events.
#   4. Load the recipe collection:
#        sudo -u recipeFlood bash -c 'set -a && source .env && \
#          .venv/bin/python -m scripts.load_snapshot --heuristic'
#      (or run scripts/parse_blog.py first for the AI-parsed snapshot —
#       see DEVELOPMENT.md "Importing the blog")
set -euo pipefail

APP_DIR=/opt/recipeFlood
REPO_URL=https://github.com/hamBank/recipeFlood.git
APP_USER=recipeFlood
SERVICE=recipeflood
DB_NAME=recipeflood
LOG=/var/log/recipeFlood-deploy.log

log() { echo "[$(date -Is)] $*" | tee -a "$LOG"; }

update_code() {
    log "updating code"
    cd "$APP_DIR"
    sudo -u "$APP_USER" git fetch origin main
    sudo -u "$APP_USER" git reset --hard origin/main

    log "python deps + migrations"
    sudo -u "$APP_USER" .venv/bin/pip install -q -r requirements.txt
    sudo -u "$APP_USER" bash -c "set -a && source .env 2>/dev/null; .venv/bin/alembic upgrade head"

    log "seeding navigation sections"
    sudo -u "$APP_USER" bash -c "set -a && source .env 2>/dev/null; .venv/bin/python scripts/seed_sections.py"

    log "frontend build"
    (cd frontend && sudo -u "$APP_USER" npm ci --silent && sudo -u "$APP_USER" npm run build)

    log "restarting $SERVICE"
    systemctl restart "$SERVICE"
    log "update done"
}

provision() {
    log "=== full provision ==="

    log "packages"
    apt-get update -q
    apt-get install -qy python3-venv python3-pip git nodejs npm \
        postgresql apache2 curl

    log "system user + app dir"
    id -u "$APP_USER" &>/dev/null || useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
    mkdir -p "$APP_DIR" /var/backups/recipeflood
    chown "$APP_USER":"$APP_USER" "$APP_DIR"
    chown postgres:postgres /var/backups/recipeflood
    touch "$LOG" && chown "$APP_USER" "$LOG"

    log "clone/update repo"
    if [ ! -d "$APP_DIR/.git" ]; then
        sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
    fi
    sudo -u "$APP_USER" git -C "$APP_DIR" remote set-url origin "$REPO_URL"

    log "venv"
    [ -d "$APP_DIR/.venv" ] || sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"

    log "upload directory (recipe photos — not in git, back it up)"
    sudo -u "$APP_USER" mkdir -p "$APP_DIR/uploads/recipes"

    log "postgres role + database"
    sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='$APP_USER'" | grep -q 1 ||
        sudo -u postgres psql -c "CREATE ROLE \"$APP_USER\" LOGIN"
    sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 ||
        sudo -u postgres createdb -O "$APP_USER" "$DB_NAME"

    log "env file"
    if [ ! -f "$APP_DIR/.env" ]; then
        sudo -u "$APP_USER" cp "$APP_DIR/.env.example" "$APP_DIR/.env"
        chmod 600 "$APP_DIR/.env"
        log "NOTE: fill in $APP_DIR/.env before the app will fully work"
    fi

    log "deploy trigger + systemd units"
    sudo -u "$APP_USER" touch "$APP_DIR/.deploy-trigger"
    cp "$APP_DIR"/deploy/recipeflood.service /etc/systemd/system/"$SERVICE".service
    cp "$APP_DIR"/deploy/recipeflood-deploy.service /etc/systemd/system/recipeflood-deploy.service
    cp "$APP_DIR"/deploy/recipeflood-deploy.path /etc/systemd/system/recipeflood-deploy.path
    systemctl daemon-reload
    systemctl enable "$SERVICE" recipeflood-deploy.path

    log "apache vhost"
    a2enmod -q proxy proxy_http
    cp "$APP_DIR"/deploy/recipeflood.hups.club.conf /etc/apache2/sites-available/
    a2ensite -q recipeflood.hups.club
    systemctl reload apache2

    log "cron jobs"
    cp "$APP_DIR"/deploy/recipeflood.cron /etc/cron.d/recipeflood
    chmod 644 /etc/cron.d/recipeflood

    update_code
    systemctl start recipeflood-deploy.path
    log "=== provision done — see header of deploy.sh for the remaining manual steps ==="
}

if [ "${1:-}" = "--update" ]; then
    update_code
else
    provision
fi
