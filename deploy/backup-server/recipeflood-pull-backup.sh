#!/usr/bin/env bash
# recipeflood-pull-backup.sh — runs on the BACKUP server. Pulls Recipe Flood's nightly
# backups from the app server over rsync/ssh, checks they are sound and fresh, keeps a
# dated history of them, and prunes that history (fleet spec DEP-6: an off-box copy).
#
# Pull, not push: the app server holds no credentials for the backup server, so
# compromising the app cannot reach the backups. The app server lets each of our two keys
# do one thing (see scripts/add_backup_reader.sh):
#   SSH_KEY         read-only rsync of /var/backups/recipeflood  (the database dumps)
#   PHOTOS_SSH_KEY  read-only rsync of /opt/recipeFlood/uploads  (the recipe photos)
# One directory per key, so neither can reach the app's .env.
#
# Database: recipeflood-<1-7>.sql.gz, the nightly pg_dump (02:45). The app names them by
# weekday, so each is overwritten a week later; this script files every new one under a
# dated name (from its mtime, UTC), data/dumps/recipeflood-YYYYMMDD-HHMMSS.sql.gz, and
# keeps KEEP_DAYS of them.
# Photos: a dated snapshot of the uploads directory, data/photos/YYYYMMDD-HHMMSS/, made
# with rsync --link-dest against the previous one: an unchanged photo is a hard link, so
# 90 days of history costs about one copy plus the photos that changed. A pull that finds
# nothing changed keeps no new snapshot. (The app's own uploads-<1-7>.tar.gz are its local
# copy and are not pulled: a full ~1 GB tarball per changed night is what this replaces.)
# NOT pulled, and unreachable to both keys: the app's .env (secrets). Keep a copy of it
# in your password manager (DEPLOYMENT.md, "Off-box backups").
#
# Fails (non-zero, so the systemd unit's Result shows it) if: a pull fails, a dump is not
# sound, the newest dump is older than MAX_AGE_HOURS (the app server's backup job has
# stopped), or a new photo snapshot holds under half the files of the one before (photos
# were mass-deleted, or the wrong directory is mounted; the snapshot is kept to look at).
# That last one keeps failing every run, and pruning nothing, until data/PHOTOS-DROPPED
# is removed by hand.
#
# Config: /etc/recipeflood-pull-backup.conf (shell KEY=VALUE; override path with RF_PULL_CONF).
set -Eeuo pipefail
umask 077

CONF="${RF_PULL_CONF:-/etc/recipeflood-pull-backup.conf}"
if [[ -r "$CONF" ]]; then set -a; source "$CONF"; set +a; fi

SRC_HOST="${SRC_HOST:-}"                          # user@host of the app server; empty = local path (tests)
SRC_ROOT="${SRC_ROOT:-/var/backups/recipeflood}"  # used only when SRC_HOST is empty
SRC_PHOTOS_ROOT="${SRC_PHOTOS_ROOT:-/opt/recipeFlood/uploads}"   # likewise
PULL_PHOTOS="${PULL_PHOTOS:-1}"                   # 0 = database only
DEST="${DEST:-${STATE_DIRECTORY:-/var/lib/recipeflood-backup}/data}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
PHOTOS_SSH_KEY="${PHOTOS_SSH_KEY:-$HOME/.ssh/id_ed25519_photos}"
KNOWN_HOSTS="${KNOWN_HOSTS:-$HOME/.ssh/known_hosts}"
KEEP_DAYS="${KEEP_DAYS:-90}"                      # our history (the app keeps 7 days)
MIN_KEEP="${MIN_KEEP:-7}"                         # never prune below this many dumps or snapshots
MAX_AGE_HOURS="${MAX_AGE_HOURS:-30}"              # the newest dump must be younger than this
RSYNC_TIMEOUT="${RSYNC_TIMEOUT:-120}"

log()  { echo "$(date '+%F %T') $*"; }
die()  { log "✗ $*" >&2; exit 1; }
trap 'log "✗ failed at line $LINENO: $BASH_COMMAND" >&2' ERR

command -v rsync >/dev/null || die "rsync is not installed"
[[ "$KEEP_DAYS" =~ ^[0-9]+$ && "$MIN_KEEP" =~ ^[0-9]+$ && "$MAX_AGE_HOURS" =~ ^[0-9]+$ ]] \
  || die "KEEP_DAYS, MIN_KEEP and MAX_AGE_HOURS must be whole numbers"

mkdir -p "$DEST/incoming" "$DEST/dumps" "$DEST/photos" "$DEST/quarantine"
chmod 700 "$DEST"
exec 9>"$DEST/.lock"
flock -n 9 || die "another pull is already running"

if [[ -n "$SRC_HOST" ]]; then
  [[ -r "$SSH_KEY" ]]     || die "ssh key $SSH_KEY is missing or unreadable"
  [[ -r "$KNOWN_HOSTS" ]] || die "$KNOWN_HOSTS is missing: connect once by hand to accept the app server's host key"
  if (( PULL_PHOTOS )); then
    [[ -r "$PHOTOS_SSH_KEY" ]] || die "ssh key $PHOTOS_SSH_KEY (photos) is missing or unreadable"
  fi
  ssh_with() { echo "ssh -i $1 -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KNOWN_HOSTS -o ConnectTimeout=20"; }
  # Tests only: stand-ins for ssh that run the app server's forced command
  # (rrsync -ro <dir>) locally, so the pull meets the real confinement.
  RSH="${RF_PULL_TEST_RSH:-$(ssh_with "$SSH_KEY")}"
  PHOTOS_RSH="${RF_PULL_TEST_RSH_PHOTOS:-$(ssh_with "$PHOTOS_SSH_KEY")}"
  SRC="${SRC_HOST}:./"                            # each key's rrsync resolves this to its root
  PHOTOS_SRC="${SRC_HOST}:./"
else
  RSH="ssh"; PHOTOS_RSH="ssh"
  SRC="${SRC_ROOT}/"
  PHOTOS_SRC="${SRC_PHOTOS_ROOT}/"
fi

# ── pull the database dumps ──────────────────────────────────────────────────
# incoming/ mirrors the app's seven rotating dumps. --chmod: our copies are private
# whatever the source modes were. No --delete, ever: our history is ours. The *.tmp
# files the app writes before its atomic mv are never matched.
PRIVATE=--chmod=Fu=rw,Fg=,Fo=,Du=rwx,Dg=,Do=
log "pulling the database dumps from ${SRC_HOST:-$SRC_ROOT}"
rc=0
rsync -a --partial --timeout="$RSYNC_TIMEOUT" -e "$RSH" "$PRIVATE" \
      --include='recipeflood-*.sql.gz' --exclude='*' \
      "$SRC" "$DEST/incoming/" || rc=$?
# 24 = a source file vanished mid-transfer: harmless.
if (( rc != 0 && rc != 24 )); then die "rsync of the backups failed (exit $rc)"; fi

# ── verify, then file each new backup under a dated name ─────────────────────
sound() {                                         # sound <file>: is this a complete backup?
  local f="$1" tail
  gzip -t "$f" 2>/dev/null || return 1
  case "$f" in
    *.sql.gz) tail="$(gzip -dc "$f" | tail -c 400)" || return 1
              [[ "$tail" == *"PostgreSQL database dump complete"* ]];;
    *)        return 1;;
  esac
}

bad=0; added=0
shopt -s nullglob
for f in "$DEST"/incoming/recipeflood-*.sql.gz; do
  base="$(basename "$f")"
  dir="$DEST/dumps"; prefix=recipeflood; ext=sql.gz
  target="$dir/$prefix-$(date -u -r "$f" +%Y%m%d-%H%M%S).$ext"
  if [[ -e "$target" ]]; then
    cmp -s "$target" "$f" && continue             # filed (and verified) on an earlier run
    # Same timestamp, different content: never skip a file we have not verified.
    log "✗ $base differs from the copy already filed as $(basename "$target")"; bad=$((bad+1)); continue
  fi
  if ! sound "$f"; then
    # Moving it out of incoming/ makes the next run fetch it again.
    log "✗ not a complete backup: $base"; mv -f "$f" "$DEST/quarantine/$base"; bad=$((bad+1)); continue
  fi
  # A hard link to incoming/ costs no space; rsync replaces an incoming file by
  # writing a new one and renaming it, so this copy is never changed under us.
  ln "$f" "$target" 2>/dev/null || cp -p "$f" "$target"
  added=$((added+1))
done
(( bad == 0 )) || die "$bad pulled file(s) failed verification (moved to $DEST/quarantine)"

# ── freshness: has the app server's backup job kept running? ──────────────────
age_of_newest() {                                 # age_of_newest <glob>: hours, or "" if none
  local t
  t="$(find "$DEST/incoming" -maxdepth 1 -name "$1" -printf '%T@\n' | sort -nr | head -1)"
  [[ -n "$t" ]] && echo $(( ( $(date +%s) - ${t%%.*} ) / 3600 ))
  return 0
}
db_age="$(age_of_newest 'recipeflood-*.sql.gz')"
[[ -n "$db_age" ]] || die "no recipeflood-*.sql.gz on the app server: its database backup has never run"
(( db_age < MAX_AGE_HOURS )) || die "newest database dump is ${db_age}h old (limit ${MAX_AGE_HOURS}h): the app server's backup job may have stopped (recipeflood-backup-db)"

# ── photos: a dated snapshot, hard-linked to the previous one ─────────────────
# Built in .partial/ and renamed into place only when complete, so a cut-off pull never
# looks like a snapshot. Retried from scratch next run.
snapshots() { find "$DEST/photos" -mindepth 1 -maxdepth 1 -type d -name '20[0-9]*' | sort; }
DROPPED="$DEST/PHOTOS-DROPPED"
photo_note=""
if (( PULL_PHOTOS )); then
  latest="$(snapshots | tail -1)"
  partial="$DEST/photos/.partial"
  rm -rf -- "$partial"
  log "pulling the photos from ${SRC_HOST:-$SRC_PHOTOS_ROOT}"
  rc=0
  rsync -a --timeout="$RSYNC_TIMEOUT" -e "$PHOTOS_RSH" "$PRIVATE" \
        ${latest:+--link-dest="$latest"} "$PHOTOS_SRC" "$partial/" || rc=$?
  if (( rc != 0 && rc != 24 )); then die "rsync of the photos failed (exit $rc)"; fi
  count() { find "$1" -type f | wc -l; }
  n_new="$(count "$partial")"
  # Same files, sizes and times as the newest snapshot (and none gone): keep no new one.
  if [[ -n "$latest" ]] && [[ -z "$(rsync -a --dry-run --delete -i "$partial/" "$latest/")" ]]; then
    rm -rf -- "$partial"
    photo_note="photos unchanged ($n_new files)"
  else
    snap="$DEST/photos/$(date -u +%Y%m%d-%H%M%S)"
    while [[ -e "$snap" ]]; do sleep 1; snap="$DEST/photos/$(date -u +%Y%m%d-%H%M%S)"; done   # never mv into one
    mv -T -- "$partial" "$snap"
    photo_note="new photo snapshot $(basename "$snap") ($n_new files)"
    if [[ -n "$latest" ]]; then
      n_old="$(count "$latest")"
      if (( n_new * 2 < n_old )); then
        echo "photo count fell from $n_old to $n_new in snapshot $(basename "$snap") ($(date -u +%FT%TZ))" > "$DROPPED"
      fi
    fi
  fi
fi
# Sticky until someone has looked: every run fails, and nothing is pruned, while the
# marker exists. A single failed run is easy to miss, and the next pull would compare
# against the smaller snapshot and pass.
if [[ -e "$DROPPED" ]]; then
  die "$(cat "$DROPPED"): were photos deleted, or is the wrong directory mounted? Older snapshots are kept and nothing is pruned. Once checked: rm $DROPPED"
fi

# ── retention (only reached when everything above passed) ─────────────────────
# By the date in the name, not the mtime: hard-linked photos keep their first mtime.
cutoff="$(date -u -d "-$KEEP_DAYS days" +%Y%m%d)"
prune() {                                         # prune <label> <path>... (each named <prefix>YYYYMMDD-…)
  local label="$1" f stamp total=0 old=(); shift
  for f in "$@"; do
    total=$((total+1))
    stamp="$(basename "$f")"; stamp="${stamp#recipeflood-}"; stamp="${stamp%%-*}"
    [[ "$stamp" < "$cutoff" ]] && old+=("$f")
  done
  (( ${#old[@]} )) || return 0
  if (( total - ${#old[@]} >= MIN_KEEP )); then
    rm -rf -- "${old[@]}"; log "pruned ${#old[@]} $label older than ${KEEP_DAYS} days"
  else
    log "kept ${#old[@]} old $label: pruning would leave fewer than $MIN_KEEP"
  fi
}
prune "dump(s)" "$DEST"/dumps/recipeflood-*.sql.gz
mapfile -t snaps < <(snapshots)
prune "photo snapshot(s)" "${snaps[@]}"

date -u +%FT%TZ > "$DEST/last-success"
n_db=$(find "$DEST/dumps" -maxdepth 1 -name 'recipeflood-*.sql.gz' | wc -l)
n_snap=$(snapshots | wc -l)
log "✓ ok: $n_db dump(s), newest ${db_age}h old, $added new; $n_snap photo snapshot(s)${photo_note:+, $photo_note}; $(du -sh "$DEST" | cut -f1) total"
