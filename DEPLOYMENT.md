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
- **Backups:** systemd timers run a nightly `pg_dump` (02:45) and a nightly
  uploads tarball (03:15), both 7-day rotation, into `/var/backups/recipeflood`.
  A separate backup server pulls them off-box (see "Off-box backups").

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
6. Installs/refreshes the systemd service, path unit, backup timers and Apache vhost
7. Runs `alembic upgrade head`, seeds the navigation sections, builds the
   frontend, restarts the service, then runs the smoke check (see
   "Verifying a deploy")

`deploy.sh --update` runs the code-update part plus a refresh of the systemd
units, backup timers and Apache vhost — used by the webhook. Both modes must be
run as root; the script says so and exits rather than failing part-way.

### What `--update` does and does not touch

| | `deploy.sh` | `--update` |
|---|---|---|
| Packages, system user, Postgres role/db, `.env` | ✅ | — |
| Code, deps, migrations, sections, frontend build | ✅ | ✅ |
| systemd units and backup timers | ✅ | ✅ (re-copied and enabled every run) |
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
The Apache and timer steps are near the end, so **an early failure means no
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
sudo ./deploy.sh            # stops at "config check FAILED": .env is still the example
# fill in /opt/recipeFlood/.env  (see .env.example; JWT_SECRET is required)
sudo ./deploy.sh            # now runs to the end
sudo certbot --apache -d recipeflood.hups.club

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

## Desktop app origins (optional)

`DESKTOP_ORIGINS` in `.env` lists the origins the desktop app's webview
calls the API from, so the browser lets it. The default
(`tauri://localhost,http://tauri.localhost,https://tauri.localhost`)
covers the Linux and Windows builds. Set it empty to turn CORS off
entirely. It is never `*`, and the web app doesn't need it (same origin).
Keep the comment on its own line in `.env`; systemd doesn't strip an
inline `# ...` from a value.

## Desktop releases

The Windows and Linux desktop app (`desktop/`) is released separately from
the server: a `desktop-vX.Y.Z` tag builds the installers in GitHub Actions
(`.github/workflows/desktop.yml`) and attaches them to a **draft** release.
Nothing here touches the server, and no secrets are needed (the installers
are unsigned).

To release:

1. Bump `version` to `X.Y.Z` in `desktop/src-tauri/tauri.conf.json`,
   `desktop/package.json` and `desktop/src-tauri/Cargo.toml` (and let
   `Cargo.lock` follow), and merge that.
2. Push the tag: `git tag desktop-vX.Y.Z && git push origin desktop-vX.Y.Z`.
   The workflow first checks the tag against the three versions and fails
   if they disagree; you can run the same check locally with
   `node desktop/scripts/check-version.mjs desktop-vX.Y.Z`.
3. Wait for the **Desktop** workflow, then open the draft under
   **Releases**, check the installers are all there (`.exe`, `.msi`,
   `.deb`, `.AppImage`) and publish it.

Pull requests that touch `desktop/` or `frontend/` run the same build
without a release and keep the installers as workflow artifacts for 7 days.

### Installing

- **Windows:** run the `.exe` (NSIS, installs per-user, no admin prompt) or
  the `.msi`. Because the installer is unsigned, SmartScreen shows
  "Windows protected your PC": click **More info -> Run anyway**. That is
  expected. WebView2 is downloaded by the installer if the machine lacks it.
- **Linux:** `sudo apt install ./Recipe.Flood_X.Y.Z_amd64.deb`, or
  `chmod +x` the `.AppImage` and run it.

The app's server defaults to production; change it in **Settings**.

## Anthropic API key (optional)

`ANTHROPIC_API_KEY` in `.env` enables the paste and photo importers. Leave
it unset and those two endpoints return 503 with a clear message, the
Import page says so, and everything else works normally.

The same key drives `scripts/parse_blog.py`, but that is an offline job —
run it on a workstation and commit the resulting `data/recipes.json` rather
than running it on the server.

## Google Sheet sync (optional)

Two-way sync between the shopping list and a Google Sheet — see SPEC.md
"Google Sheet sync". Off unless both settings below are set.

1. <https://console.cloud.google.com/> → the same project as OAuth, or a
   new one → **IAM & Admin → Service Accounts → Create service account**
   (no roles needed — access is granted by sharing the sheet, not IAM).
2. **Keys → Add key → Create new key → JSON**, downloads a key file. Copy
   it to the server as `/opt/recipeFlood/google-sa.json`, then
   `chown recipeFlood:recipeFlood /opt/recipeFlood/google-sa.json` and
   `chmod 600` it — it's a bearer credential, not a config file.
3. **APIs & Services → Library** → enable the **Google Sheets API** for
   the project.
4. Open the household's spreadsheet, **Share** it with the service
   account's email (from the JSON key's `client_email`, looks like
   `...@...iam.gserviceaccount.com`) as **Editor**.
5. In `/opt/recipeFlood/.env`, set:
   ```
   GOOGLE_SHEET_ID=<the id from the sheet's URL>
   GOOGLE_SERVICE_ACCOUNT_FILE=/opt/recipeFlood/google-sa.json
   ```
   `GOOGLE_SHEET_TAB` defaults to `Shopping`; set it only if the tab is
   named differently. Keep comments on their own lines in `.env` —
   systemd doesn't strip an inline `# ...` from a value.
6. `systemctl restart recipeflood`. `GET /auth/config` should now report
   `sheet_sync_enabled: true`, and a "Sync now" button appears on the
   shopping list page.

## Configuration

Environment lives in `/opt/recipeFlood/.env` (loaded by the systemd unit;
not in the repo). See `.env.example` for the full list.

With `AUTH_ENABLED=true` (the default), the app **refuses to start** if
`JWT_SECRET` is missing, empty or the public default from the source (fleet
spec CFG-2): anyone could otherwise sign their own login tokens. Every
deploy checks this first (`scripts/check_config.py`, reading `.env` the way
systemd does) and stops, leaving the running service alone, if it fails.

`DATABASE_URL`'s `+driver` must name a driver installed in the venv; the
same preflight loads it (without connecting) and stops the deploy if it
can't. The app uses **psycopg3** (fleet spec STK-6):
`postgresql+psycopg://recipeFlood@/recipeflood?host=/var/run/postgresql`.

**Switching an existing server from psycopg2** (one time; psycopg2 stays
installed in the venv, so this is reversible):

```bash
sudoedit /opt/recipeFlood/.env      # DATABASE_URL: +psycopg2  ->  +psycopg  (nothing else changes)
sudo -u recipeFlood /opt/recipeFlood/.venv/bin/python /opt/recipeFlood/scripts/check_config.py /opt/recipeFlood/.env
                                    # must print "configuration OK"
sudo systemctl restart recipeflood
curl -s localhost:8002/health       # status ok
```

To roll back, put `+psycopg2` back and restart.

## Logs & operations

```bash
journalctl -u recipeflood -f                     # app logs
tail -f /var/log/recipeFlood-deploy.log          # deploy runs
systemctl restart recipeflood                    # manual restart
sudo -u postgres pg_dump recipeflood > backup.sql
```

## Verifying a deploy

Every `deploy.sh --update` ends with `scripts/smoke_check.sh` (fleet spec
DEP-4), and the deploy exits non-zero, so `recipeflood-deploy.service`
shows as failed, if it fails. It waits up to 60 s for the restarted
service, then checks:

- `/health` answers `status: ok`;
- `backend_sha` **and** `build_sha` equal the commit just checked out. A
  `build_sha` mismatch means the frontend build failed or was skipped and
  the old bundle is still being served;
- `GET /tags?section=true` returns data (the app can read its database);
- every `recipeflood*.timer`'s last run succeeded;
- the newest database dump **and** the newest uploads tarball are each
  under 36 hours old (a warning, not a failure).

The result is in `/var/log/recipeFlood-deploy.log`. To check by hand:

```bash
curl -s https://recipeflood.hups.club/health
# {"status":"ok","backend_sha":"…","frontend_sha":"…","build_sha":"…","built_at":"…","started_at":"…"}
sudo -u recipeFlood git -C /opt/recipeFlood rev-parse --short HEAD   # should equal backend_sha and build_sha
```

`frontend_sha` is the last commit that changed the frontend, so it lags
behind after a backend-only deploy; that is expected. Open browser tabs
compare it with the one baked into their bundle and offer a reload when
it changes.

## Backups

Two things need backing up, and two systemd timers do both (fleet spec
DEP-5), into `/var/backups/recipeflood` with a 7-day rotation by weekday:

| unit | when | runs as | writes |
|---|---|---|---|
| `recipeflood-backup-db` | 02:45 | `postgres` | `recipeflood-<1-7>.sql.gz` |
| `recipeflood-backup-uploads` | 03:15 | `recipeFlood` | `uploads-<1-7>.tar.gz` |

- **Postgres** (`recipeflood`) — the recipes, the pantry, the prepared log.
- **`/opt/recipeFlood/uploads`** — recipe photos. These exist nowhere else;
  losing them loses them.

Each job writes to a temporary file and only replaces the day's backup when
it succeeded, and runs with `pipefail`, so a failed `pg_dump` fails the unit
instead of leaving an empty `.gz`. Every deploy's smoke check fails if
either job's last run failed, and warns if the newest database dump or the
newest uploads tarball is over 36 hours old. (The cron job this replaced never
wrote a single uploads tarball: it ran as `recipeFlood` into a directory only
`postgres` could write, and nothing reported it.)

```bash
systemctl list-timers 'recipeflood-*'                   # next and last runs
systemctl show -p Result recipeflood-backup-db.service  # success / exit-code
sudo systemctl start recipeflood-backup-db.service      # run one now
journalctl -u recipeflood-backup-uploads -n 20
```

`data/` in the repo (the blog snapshots) is the third leg: it means the
imported collection can always be rebuilt even if both of the above are
lost.

## Off-box backups

`/var/backups/recipeflood` is on the same disk as the app, so it doesn't survive losing the
server (fleet spec DEP-6). A separate, locked-down **backup server** *pulls* a copy over
rsync/ssh, the same design as travelCompantion's.

```
 app server (camelidcastle)                    backup server
 ──────────────────────────                    ─────────────
 02:45 recipeflood-backup-db                   every 6 h  recipeflood-pull-backup.timer
 03:15 recipeflood-backup-uploads                         └ recipeflood-pull-backup.sh
   └ /var/backups/recipeflood/*-<1-7>.gz
 user rfbackup (read-only key)  ◄──────────── rsync over ssh (key + pinned host key)
 forced: rrsync -ro /var/backups/recipeflood          └ verify · file dated copies · freshness · prune
```

**Pull, not push**: the app server holds no credentials for the backup server, so a compromised
app can't reach or delete the copies. The app-side key can only run a read-only rsync inside
`/var/backups/recipeflood` (`rrsync -ro`): no shell, no writes, no other paths. That puts `.env`
out of its reach by path, and `add_backup_reader.sh` also checks the user can't read it.

**What it keeps.** The app's backups are named by weekday and overwritten a week later, so the
pull files every new one under a dated name (`dumps/recipeflood-YYYYMMDD-HHMMSS.sql.gz`,
`uploads/uploads-YYYYMMDD-HHMMSS.tar.gz`) and keeps 90 days of them, never fewer than 7 of each.
An uploads tarball identical to the previous one (no photo changed) is hard-linked to it, so
the photos cost space only when they change.

**Not copied, on purpose: `.env`.** A restored database works without it, but the server
doesn't: it holds `JWT_SECRET`, the Google OAuth client, the Anthropic key and the Sheet
credentials. Keep a copy of `.env` (and the Sheet service-account key file, if it lives outside
it) in your password manager.

### Setup

**1. Backup server** (as root, from a checkout of this repo):

```bash
sudo deploy/backup-server/install.sh
```

Creates user `rfpull`, an ed25519 key, `/etc/recipeflood-pull-backup.conf`, the service and the
timer (enabled). It prints the next steps with your public key filled in.

**2. App server** (as root): authorise that key. `--from` restricts it to the backup server's IP.

```bash
echo '<the public key install.sh printed>' | sudo scripts/add_backup_reader.sh --from <backup-server-ip> -
```

This creates the login-less `rfbackup` user, installs the key as
`restrict,from="…",command="rrsync -ro /var/backups/recipeflood"`, then checks that `rfbackup`
**can** read every backup file and **cannot** read `/opt/recipeFlood/.env`. Needs the `rsync`
package (it provides `rrsync`), and sshd must allow the user (`AllowUsers`, if you use it).

**3. Backup server**: check `SRC_HOST=rfbackup@<app-host>` in `/etc/recipeflood-pull-backup.conf`
and pin the app server's host key. The script uses `StrictHostKeyChecking=yes`, so an unknown or
changed key fails the run instead of prompting. Compare the fingerprint from
`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the app server with what you scan here:

```bash
sudo -u rfpull ssh-keyscan -t ed25519 <app-host> | sudo -u rfpull tee -a /var/lib/recipeflood-backup/.ssh/known_hosts
sudo -u rfpull ssh-keygen -lf /var/lib/recipeflood-backup/.ssh/known_hosts
```

**4. First run, through systemd** (not only by hand: the unit is sandboxed, and a path that works
by hand can be read-only under it):

```bash
sudo systemctl start recipeflood-pull-backup.service
journalctl -u recipeflood-pull-backup.service -n 20   # expect "✓ ok: N dump(s), newest Xh old; M uploads tarball(s)…"
systemctl list-timers recipeflood-pull-backup.timer
```

To keep the copies on another disk, set `DEST` in the config **and** add a drop-in
(`systemctl edit recipeflood-pull-backup.service`) with `RequiresMountsFor=` and
`ReadWritePaths=` for that path. Without them the sandbox makes it read-only; travelCompantion
hit exactly this on its first run.

### What a failed run means

The unit exits non-zero (and shows in `systemctl --failed`) when:

| Message | Cause |
|---|---|
| `rsync of the backups failed (exit …)` | ssh/key/host-key/permission problem; the line above it says which |
| `not a complete backup: …` | A file failed `gzip -t`, has no `dump complete` marker, or isn't a readable tar. It's moved to `quarantine/` and fetched again next run |
| `… differs from the copy already filed …` | A file changed without its timestamp changing. Look before trusting either copy |
| `newest database dump is Nh old` / `newest uploads tarball is Nh old` | **The app server's own backup stopped.** Check `systemctl status recipeflood-backup-db` (or `-uploads`) there |
| `… has never run` | The app server has no backup of that kind at all |

For an alert, point `OnFailure=` in the service at a unit that mails or pushes you (there is a
commented line for it). Without one, check `systemctl --failed` now and then, or look at
`/var/lib/recipeflood-backup/data/last-success`, which holds the time of the last good pull.

### Restore drill (do this once, then yearly)

A backup you haven't restored is only a hope. On any machine with Postgres client tools:

```bash
B=/var/lib/recipeflood-backup/data
gunzip -c "$B"/dumps/recipeflood-<newest>.sql.gz | head -20          # readable?
createuser recipeflood          # the dump's OWNER TO lines need it; skip if it exists
createdb rf_restore_test
gunzip -c "$B"/dumps/recipeflood-<newest>.sql.gz | psql -q -v ON_ERROR_STOP=1 rf_restore_test
psql rf_restore_test -c 'select count(*) from recipe'
psql rf_restore_test -c 'select version_num from alembic_version'   # the schema revision
dropdb rf_restore_test
tar -tzf "$B"/uploads/uploads-<newest>.tar.gz | head                 # the photos are there
```

Without the `recipeflood` role, `ON_ERROR_STOP` stops at the first `OWNER TO` line and
restores nothing. That was checked against a real dump of this schema.

Also confirm you can find `.env` in your password manager.

### Rotating the key / removing access

Re-run `add_backup_reader.sh` with the new public key (it replaces the old `rf-offsite-backup`
line), or delete that line from `/var/lib/rfbackup/.ssh/authorized_keys` to cut access at once.

### Tests

`tests/test_pull_backup.py` runs the real script and rsync against a local stand-in for the
backup directory: the pull, the dated history (including a weekday file overwritten at the
source), verification and recovery after a quarantined file, the freshness checks for both
kinds, retention, the hard-linked unchanged tarball, and the key builder's refusal of injected
options. Two tests route the pull through the real `rrsync -ro` forced command, which allows
reads under the root and refuses a path outside it, a push and a shell. Not covered: ssh
itself and running under systemd. The first run in step 4 is that check.
