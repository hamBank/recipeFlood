#!/usr/bin/env bash
# recipeflood-pull-backup.sh — runs on the BACKUP server. Pulls Recipe Flood's nightly
# backups from the app server over rsync/ssh, checks they are sound and fresh, keeps a
# dated history of them, and prunes that history (fleet spec DEP-6: an off-box copy).
#
# Pull, not push: the app server holds no credentials for the backup server, so
# compromising the app cannot reach the backups. The app server lets this key do one
# thing: read-only rsync of /var/backups/recipeflood (see scripts/add_backup_reader.sh).
#
# What is pulled (the whole of the directory rrsync confines us to):
#   recipeflood-<1-7>.sql.gz   the nightly pg_dump (02:45): recipes, pantry, lists, users.
#   uploads-<1-7>.tar.gz       the nightly uploads tarball (03:15): the recipe photos,
#                              which exist nowhere else.
# The app names them by weekday, so each one is overwritten a week later. This script
# therefore files every new one it sees under a dated name (from the file's mtime, UTC):
#   data/dumps/recipeflood-YYYYMMDD-HHMMSS.sql.gz   data/uploads/uploads-YYYYMMDD-HHMMSS.tar.gz
# and keeps KEEP_DAYS of those. An uploads tarball identical to the previous one (no
# photo changed) is hard-linked to it, so a quiet week costs no extra space.
# NOT pulled, and unreachable to the key: the app's .env (secrets). Keep a copy of it
# in your password manager (DEPLOYMENT.md, "Off-box backups").
#
# Fails (non-zero, so the systemd unit's Result shows it) if: the pull fails, a pulled
# file is not a sound backup, or the newest dump or uploads tarball is older than
# MAX_AGE_HOURS (which means the app server's own backup job has stopped).
#
# Config: /etc/recipeflood-pull-backup.conf (shell KEY=VALUE; override path with RF_PULL_CONF).
set -Eeuo pipefail
umask 077

CONF="${RF_PULL_CONF:-/etc/recipeflood-pull-backup.conf}"
if [[ -r "$CONF" ]]; then set -a; source "$CONF"; set +a; fi

SRC_HOST="${SRC_HOST:-}"                          # user@host of the app server; empty = local path (tests)
SRC_ROOT="${SRC_ROOT:-/var/backups/recipeflood}"  # used only when SRC_HOST is empty
DEST="${DEST:-${STATE_DIRECTORY:-/var/lib/recipeflood-backup}/data}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
KNOWN_HOSTS="${KNOWN_HOSTS:-$HOME/.ssh/known_hosts}"
KEEP_DAYS="${KEEP_DAYS:-90}"                      # our history (the app keeps 7 days)
MIN_KEEP="${MIN_KEEP:-7}"                         # never prune below this many of each kind
MAX_AGE_HOURS="${MAX_AGE_HOURS:-30}"              # newest of each kind must be younger than this
RSYNC_TIMEOUT="${RSYNC_TIMEOUT:-120}"

log()  { echo "$(date '+%F %T') $*"; }
die()  { log "✗ $*" >&2; exit 1; }
trap 'log "✗ failed at line $LINENO: $BASH_COMMAND" >&2' ERR

command -v rsync >/dev/null || die "rsync is not installed"
[[ "$KEEP_DAYS" =~ ^[0-9]+$ && "$MIN_KEEP" =~ ^[0-9]+$ && "$MAX_AGE_HOURS" =~ ^[0-9]+$ ]] \
  || die "KEEP_DAYS, MIN_KEEP and MAX_AGE_HOURS must be whole numbers"

mkdir -p "$DEST/incoming" "$DEST/dumps" "$DEST/uploads" "$DEST/quarantine"
chmod 700 "$DEST"
exec 9>"$DEST/.lock"
flock -n 9 || die "another pull is already running"

if [[ -n "$SRC_HOST" ]]; then
  [[ -r "$SSH_KEY" ]]     || die "ssh key $SSH_KEY is missing or unreadable"
  [[ -r "$KNOWN_HOSTS" ]] || die "$KNOWN_HOSTS is missing: connect once by hand to accept the app server's host key"
  RSH="ssh -i $SSH_KEY -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KNOWN_HOSTS -o ConnectTimeout=20"
  # Tests only: a stand-in for ssh that runs the app server's forced command
  # (rrsync -ro) locally, so the pull meets the real confinement.
  RSH="${RF_PULL_TEST_RSH:-$RSH}"
  SRC="${SRC_HOST}:./"                            # rrsync resolves this to its root
else
  RSH="ssh"
  SRC="${SRC_ROOT}/"
fi

# ── pull ─────────────────────────────────────────────────────────────────────
# incoming/ mirrors the app's seven rotating files of each kind. --chmod: our copies
# are private whatever the source modes were. No --delete, ever: our history is ours.
# The *.tmp files the app writes before its atomic mv are never matched.
log "pulling ${SRC_HOST:-$SRC_ROOT}"
rc=0
rsync -a --partial --timeout="$RSYNC_TIMEOUT" -e "$RSH" \
      --chmod=Fu=rw,Fg=,Fo=,Du=rwx,Dg=,Do= \
      --include='recipeflood-*.sql.gz' --include='uploads-*.tar.gz' --exclude='*' \
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
    *.tar.gz) tar -tzf "$f" >/dev/null 2>&1;;
    *)        return 1;;
  esac
}

bad=0; added=0
shopt -s nullglob
for f in "$DEST"/incoming/recipeflood-*.sql.gz "$DEST"/incoming/uploads-*.tar.gz; do
  base="$(basename "$f")"
  case "$base" in
    recipeflood-*) dir="$DEST/dumps";   prefix=recipeflood; ext=sql.gz;;
    uploads-*)     dir="$DEST/uploads"; prefix=uploads;     ext=tar.gz;;
  esac
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
  prev="$(find "$dir" -maxdepth 1 -name "$prefix-*.$ext" | sort | tail -1)"
  if [[ -n "$prev" ]] && cmp -s "$prev" "$f"; then
    ln "$prev" "$target"                          # unchanged since last time: no extra space
  else
    # A hard link to incoming/ costs no space; rsync replaces an incoming file by
    # writing a new one and renaming it, so this copy is never changed under us.
    ln "$f" "$target" 2>/dev/null || cp -p "$f" "$target"
  fi
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
up_age="$(age_of_newest 'uploads-*.tar.gz')"
[[ -n "$db_age" ]] || die "no recipeflood-*.sql.gz on the app server: its database backup has never run"
[[ -n "$up_age" ]] || die "no uploads-*.tar.gz on the app server: its uploads backup has never run"
(( db_age < MAX_AGE_HOURS )) || die "newest database dump is ${db_age}h old (limit ${MAX_AGE_HOURS}h): the app server's backup job may have stopped (recipeflood-backup-db)"
(( up_age < MAX_AGE_HOURS )) || die "newest uploads tarball is ${up_age}h old (limit ${MAX_AGE_HOURS}h): the app server's backup job may have stopped (recipeflood-backup-uploads)"

# ── retention (only reached when everything above passed) ─────────────────────
# By the date in the name, not the mtime: hard-linked copies share an mtime.
cutoff="$(date -u -d "-$KEEP_DAYS days" +%Y%m%d)"
prune() {                                         # prune <dir> <prefix> <ext>
  local dir="$1" prefix="$2" ext="$3" f stamp total=0 old=()
  for f in "$dir"/"$prefix"-*."$ext"; do
    total=$((total+1))
    stamp="${f##*/$prefix-}"; stamp="${stamp%%-*}"
    [[ "$stamp" < "$cutoff" ]] && old+=("$f")
  done
  (( ${#old[@]} )) || return 0
  if (( total - ${#old[@]} >= MIN_KEEP )); then
    rm -f -- "${old[@]}"; log "pruned ${#old[@]} $prefix file(s) older than ${KEEP_DAYS} days"
  else
    log "kept ${#old[@]} old $prefix file(s): pruning would leave fewer than $MIN_KEEP"
  fi
}
prune "$DEST/dumps" recipeflood sql.gz
prune "$DEST/uploads" uploads tar.gz

date -u +%FT%TZ > "$DEST/last-success"
n_db=$(find "$DEST/dumps" -maxdepth 1 -name 'recipeflood-*.sql.gz' | wc -l)
n_up=$(find "$DEST/uploads" -maxdepth 1 -name 'uploads-*.tar.gz' | wc -l)
log "✓ ok: $n_db dump(s), newest ${db_age}h old; $n_up uploads tarball(s), newest ${up_age}h old; $added new; $(du -sh "$DEST" | cut -f1) total"
