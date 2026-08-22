# Recipe Flood — Deployment

> Production: `https://recipeflood.hups.club` on `camelidcastle.hups.club`
> (Debian/Ubuntu), alongside pocketMoney.

## Topology

- **App:** uvicorn serving `backend.main:app` on `127.0.0.1:8002` (pmoney
  has :8001), run by systemd unit `recipeflood`, as system user
  `recipeFlood`, from `/opt/recipeFlood`.
- **Web:** Apache vhost `recipeflood.hups.club.conf` — TLS termination +
  reverse proxy to :8002. The FastAPI app serves the API, the built SPA and
  `/media`, so Apache proxies everything.
- **DB:** Postgres, database `recipeflood`.
- **Uploads:** `/opt/recipeFlood/uploads` — recipe photos. **Not in git and
  not in the database**; the only app state that needs its own backup.
- **Cron:** nightly `pg_dump` (02:45) and a nightly uploads tarball (03:15),
  both 7-day rotation, into `/var/backups/recipeflood`.

## Repo access

The repo is **public**, so `deploy.sh` clones over HTTPS and no deploy key
is needed. If it is ever made private, switch `REPO_URL` in `deploy.sh` to
`git@github.com:hamBank/recipeFlood.git` and add a read-only deploy key for
the `recipeFlood` user first (see pocketMoney's DEPLOYMENT.md for that
dance).

## Provisioning — `deploy.sh`

Idempotent script that:

1. Installs OS packages (python, node, postgres client, apache modules)
2. Creates the `recipeFlood` system user and `/opt/recipeFlood`
3. Clones/updates the repo, creates the venv, installs requirements
4. Creates the uploads directory
5. Creates the Postgres role and `recipeflood` database
6. Installs/refreshes the systemd service, path unit, Apache vhost and cron
7. Runs `alembic upgrade head`, seeds the navigation sections, builds the
   frontend, restarts the service

`deploy.sh --update` runs the code-update part plus a refresh of the systemd
units, Apache vhost and cron file — used by the webhook. Both modes must be
run as root; the script says so and exits rather than failing part-way.

### What `--update` does and does not touch

| | `deploy.sh` | `--update` |
|---|---|---|
| Packages, system user, Postgres role/db, `.env` | ✅ | — |
| Code, deps, migrations, sections, frontend build | ✅ | ✅ |
| systemd units, cron file | ✅ | ✅ (re-copied every run) |
| Apache vhost | ✅ if absent | ✅ if absent |

The vhost is installed **only when it does not already exist**. Once it is
there it belongs to the server, because `certbot --apache` edits that file
in place to add the http→https redirect — re-copying the repo's plain :80
version over it on every deploy would silently undo TLS redirection. To
apply a repo change to the vhost:

```bash
sudo cp /opt/recipeFlood/deploy/recipeflood.hups.club.conf \
        /etc/apache2/sites-available/recipeflood.hups.club.conf
sudo certbot --apache -d recipeflood.hups.club   # re-add the TLS bits
sudo apache2ctl configtest && sudo systemctl reload apache2
```

Apache is only reloaded after `apache2ctl configtest` passes, so a bad
config can't take the site down during an unattended webhook deploy.

### When a deploy stops early

`deploy.sh` runs under `set -Eeuo pipefail` and aborts at the first failure.
The Apache and cron steps are near the end, so **an early failure means no
vhost**. The log names the step it was in and the line it died on:

```bash
tail -20 /var/log/recipeFlood-deploy.log
# ... ERROR: /opt/recipeFlood/deploy.sh:145 exited 1 — the step named above
#     is where it stopped, and nothing after it ran. Fix and re-run.
```

Re-running is safe — every step is idempotent.

The built `backend/static/` is produced on the server at deploy time — it
is **not** committed.

## First deploy — the whole sequence

```bash
sudo ./deploy.sh
# fill in /opt/recipeFlood/.env  (see .env.example)
sudo certbot --apache -d recipeflood.hups.club
sudo systemctl restart recipeflood

# load the recipe collection
sudo -u recipeFlood bash -c 'cd /opt/recipeFlood && set -a && source .env && \
  .venv/bin/python -m scripts.load_snapshot --heuristic'
```

Then add the GitHub webhook: **Settings → Webhooks → Add webhook**, payload
URL `https://recipeflood.hups.club/deploy`, content type
`application/json`, secret = `DEPLOY_SECRET`, just the push event.

### Loading the AI-parsed collection instead

If you have generated `data/recipes.json` locally (see DEVELOPMENT.md) and
committed it, `load_snapshot.py` without `--heuristic` uses it. Loading is
idempotent and keyed on the source URL, so running it over the top of a
heuristic load upgrades every recipe in place — slugs, and therefore links,
survive.

## Auto-redeploy webhook

A push to `main` → GitHub webhook `POST /deploy` (HMAC-signed with
`DEPLOY_SECRET`) → app touches `.deploy-trigger` → systemd **path unit**
watches that file and runs `deploy.sh --update`.

The path-unit indirection means the deploy runs with root privileges
without the web app itself needing any.

## Google OAuth setup (one-time, manual)

1. <https://console.cloud.google.com/> → create a project ("Recipe Flood").
2. **APIs & Services → OAuth consent screen**: **External**, fill in the
   app name and your email. Add the accounts that should be able to edit as
   **Test users** — an app in "Testing" status only allows listed test
   users, which is exactly the allowlist behaviour we want; there is no
   need to publish it.
3. **Credentials → Create credentials → OAuth client ID**:
   - Application type: **Web application**
   - Authorized JavaScript origins: `https://recipeflood.hups.club`
     (add `http://localhost:5173` and `http://localhost:8000` for local
     testing with real Google sign-in)
   - No redirect URIs — the app uses Google Identity Services' ID-token
     flow, not a redirect flow.
4. Copy the **Client ID** into `GOOGLE_CLIENT_ID` in
   `/opt/recipeFlood/.env`.
5. Put the editors' Gmail addresses in `ALLOWED_EMAILS` (comma-separated).
   The **first** of them to sign in becomes the admin; invite/promote the
   rest from the app afterwards.

No client secret is required anywhere: the backend only *verifies* Google's
ID tokens against the client ID.

Note that this only gates **editing**. Reading is public
(`PUBLIC_READ=true`); set it to `false` to require sign-in for everything.

## Anthropic API key (optional)

`ANTHROPIC_API_KEY` in `.env` enables the paste and photo importers. Leave
it unset and those two endpoints return 503 with a clear message, the
Import page says so, and everything else works normally.

The same key drives `scripts/parse_blog.py`, but that is an offline job —
run it on a workstation and commit the resulting `data/recipes.json` rather
than running it on the server.

## Configuration

Environment lives in `/opt/recipeFlood/.env` (loaded by the systemd unit;
not in the repo). See `.env.example` for the full list.

## Logs & operations

```bash
journalctl -u recipeflood -f                     # app logs
tail -f /var/log/recipeFlood-deploy.log          # deploy runs
systemctl restart recipeflood                    # manual restart
sudo -u postgres pg_dump recipeflood > backup.sql
```

## Verifying a deploy

```bash
curl -s https://recipeflood.hups.club/health
# {"status":"ok","backend_version":"…","frontend_version":"…","frontend_built_at":"…"}
```

`backend_version` and `frontend_version` are both git short SHAs and should
match after a full `deploy.sh --update`. If they diverge, the frontend
build step failed or was skipped — check the deploy log and rerun
`sudo ./deploy.sh --update`.

## Backups

Two things need backing up, and the cron file provisions both:

- **Postgres** (`recipeflood`) — the recipes, the pantry, the prepared log.
- **`/opt/recipeFlood/uploads`** — recipe photos. These exist nowhere else;
  losing them loses them.

`data/` in the repo (the blog snapshots) is the third leg: it means the
imported collection can always be rebuilt even if both of the above are
lost.
