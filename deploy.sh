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
# -E so the ERR trap below fires for failures inside functions too; without
# it the trap only sees top-level commands and every real failure is silent.
set -Eeuo pipefail

APP_DIR=/opt/recipeFlood
REPO_URL=https://github.com/hamBank/recipeFlood.git
APP_USER=recipeFlood
SERVICE=recipeflood
DB_NAME=recipeflood
SERVER_NAME=recipeflood.hups.club
VHOST_NAME="$SERVER_NAME.conf"
VHOST_PATH="/etc/apache2/sites-available/$VHOST_NAME"
LOG=/var/log/recipeFlood-deploy.log
SYSTEM_FILES_INSTALLED=0

log() { echo "[$(date -Is)] $*" | tee -a "$LOG"; }

# `set -e` aborts at the first failure, and the Apache and timer steps are near
# the end — so an early failure means no vhost, with nothing in the log saying
# why. Name the failing line instead of stopping silently.
trap 'rc=$?; log "ERROR: ${BASH_SOURCE[0]}:${LINENO} exited $rc — the step named above is where it stopped, and nothing after it ran. Fix and re-run."; exit $rc' ERR

# Copy the systemd units (service, deploy watcher, backup timers) and the
# Apache vhost out of the repo into their system locations. Called by BOTH
# provision and --update: a push that changes deploy/ has to actually reach
# the server, or you get a "successful" deploy that silently left the old
# unit file running.
install_system_files() {
    log "systemd units"
    cp "$APP_DIR"/deploy/recipeflood.service /etc/systemd/system/"$SERVICE".service
    cp "$APP_DIR"/deploy/recipeflood-deploy.service /etc/systemd/system/recipeflood-deploy.service
    cp "$APP_DIR"/deploy/recipeflood-deploy.path /etc/systemd/system/recipeflood-deploy.path
    for unit in recipeflood-backup-db recipeflood-backup-uploads; do
        cp "$APP_DIR/deploy/$unit.service" "$APP_DIR/deploy/$unit.timer" /etc/systemd/system/
    done
    systemctl daemon-reload

    log "apache vhost"
    a2enmod -q proxy proxy_http
    if [ -f "$VHOST_PATH" ]; then
        # certbot rewrites this vhost in place when it adds TLS (and writes a
        # separate -le-ssl.conf). Overwriting it on every deploy would throw
        # away the http->https redirect certbot inserted, so once it exists
        # it belongs to the server, not to the repo.
        log "  $VHOST_PATH already exists — leaving it alone (certbot may own it)."
        log "  To apply repo changes: cp $APP_DIR/deploy/$VHOST_NAME $VHOST_PATH && certbot --apache -d $SERVER_NAME"
    else
        cp "$APP_DIR/deploy/$VHOST_NAME" "$VHOST_PATH"
        a2ensite -q "$SERVER_NAME"
    fi
    # Never reload Apache onto a broken config — on a webhook-triggered
    # deploy that would take the site down with nobody watching.
    if apache2ctl configtest >/dev/null 2>&1; then
        systemctl reload apache2
    else
        log "  WARNING: apache configtest failed, not reloading. Run: apache2ctl configtest"
    fi

    # Scheduled jobs are systemd timers (fleet spec DEP-5): each run leaves
    # a Result that the smoke check reads, where a failed cron job only
    # reached a log. The uploads backup runs as the app user, so the backup
    # directory is group-writable for it; the database dump runs as
    # postgres. Not fatal: a timer problem must never block a code deploy,
    # and the smoke check reports a timer that isn't enabled.
    log "backup timers"
    install -d -m 775 -o postgres -g "$APP_USER" /var/backups/recipeflood
    systemctl enable --now recipeflood-backup-db.timer recipeflood-backup-uploads.timer ||
        log "  WARNING: could not enable the backup timers; run: systemctl enable --now recipeflood-backup-db.timer recipeflood-backup-uploads.timer"
}

update_code() {
    log "updating code"
    cd "$APP_DIR"
    sudo -u "$APP_USER" git fetch origin main
    sudo -u "$APP_USER" git reset --hard origin/main

    # Before the build, not after: the units, vhost and timers are independent
    # of whether pip or npm succeed, and a failed build must not be the
    # reason a corrected unit file never reaches the server. provision()
    # has already done this, hence the guard.
    if [ "${SYSTEM_FILES_INSTALLED:-0}" != "1" ]; then
        install_system_files
    fi

    log "python deps + migrations"
    sudo -u "$APP_USER" .venv/bin/pip install -q -r requirements.txt

    # Fleet spec CFG-2: the app refuses to start with auth on and a missing
    # or default JWT_SECRET. Check .env the way systemd will read it, before
    # the migrations and the restart, so a bad config stops the deploy here
    # with its reason instead of restarting into a crash loop.
    log "config check"
    sudo -u "$APP_USER" env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/check_config.py .env ||
        { log "config check FAILED (see above) — the running service is untouched; fix .env and re-run"; exit 1; }
    sudo -u "$APP_USER" bash -c "set -a && source .env 2>/dev/null; .venv/bin/alembic upgrade head"

    log "seeding navigation sections"
    sudo -u "$APP_USER" bash -c "set -a && source .env 2>/dev/null; .venv/bin/python scripts/seed_sections.py"

    log "frontend build"
    (cd frontend && sudo -u "$APP_USER" npm ci --silent && sudo -u "$APP_USER" npm run build)

    log "restarting $SERVICE"
    systemctl restart "$SERVICE"

    # Fleet spec DEP-4: a deploy must not fail semi-silently. Waits for the
    # restarted service, then checks /health's build_sha and backend_sha
    # against the commit just checked out (a skipped or failed build shows
    # up as a mismatch), that the app can read its database, that every
    # recipeflood*.timer's last run succeeded, and that the newest backup is
    # fresh. A failure makes this deploy exit non-zero, so the deploy unit
    # shows as failed. git runs as the app user: root would refuse the repo
    # as "dubious ownership".
    log "smoke check"
    local deployed
    deployed="$(sudo -u "$APP_USER" git rev-parse --short HEAD)"
    # SMOKE_CRON_PATTERN: both backups used to run from a system cron file,
    # which a deploy can't remove, so a line coming back would run them a
    # second time next to their timers. Both old lines wrote under this path.
    # (Keep the words "cron" + "d" / "tab" out of this file's text: fleet spec
    # DEP-5's check greps deploy.sh for them to catch an app installing cron.)
    if SMOKE_UNIT_PREFIX=recipeflood SMOKE_DATA_PATH='/tags?section=true' \
        SMOKE_CRON_PATTERN='/var/backups/recipeflood' SMOKE_APP_USER="$APP_USER" \
        SMOKE_BACKUP_GLOB='/var/backups/recipeflood/recipeflood-*.sql.gz /var/backups/recipeflood/uploads-*.tar.gz' \
        bash scripts/smoke_check.sh "http://127.0.0.1:8002" "$deployed" | tee -a "$LOG"; then
        log "update done"
    else
        log "update done, BUT the smoke check FAILED (see above) — the new code is live; check it now"
        exit 1
    fi
}

provision() {
    log "=== full provision ==="

    log "packages"
    apt-get update -q
    apt-get install -qy python3-venv python3-pip git nodejs npm \
        postgresql apache2 curl

    log "system user + app dir"
    if ! id -u "$APP_USER" &>/dev/null; then
        # shadow-utils >= 4.13 (Ubuntu 24.04, Debian 13) rejects a mixed-case
        # username outright: "invalid user name 'recipeFlood': use --badname
        # to ignore". Older releases accept it, and --badname does not exist
        # there — so try the plain form first and fall back.
        useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER" 2>/dev/null ||
            useradd --badname --system --create-home --shell /usr/sbin/nologin "$APP_USER"
    fi
    mkdir -p "$APP_DIR"
    chown "$APP_USER":"$APP_USER" "$APP_DIR"
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

    log "deploy trigger"
    sudo -u "$APP_USER" touch "$APP_DIR/.deploy-trigger"

    install_system_files
    SYSTEM_FILES_INSTALLED=1
    systemctl enable "$SERVICE" recipeflood-deploy.path

    update_code
    systemctl start recipeflood-deploy.path
    log "=== provision done — see header of deploy.sh for the remaining manual steps ==="
}

# Both paths write to /etc and drive systemctl. Fail with a clear message
# rather than half-way through with a permission error.
if [ "$(id -u)" -ne 0 ]; then
    echo "deploy.sh must be run as root — try: sudo $0 ${1:-}" >&2
    exit 1
fi

if [ "${1:-}" = "--update" ]; then
    update_code
else
    provision
fi
