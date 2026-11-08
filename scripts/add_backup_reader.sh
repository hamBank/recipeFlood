#!/usr/bin/env bash
# add_backup_reader.sh — run as root on the APP server (once). Lets the backup server
# PULL backups, with a key that can do exactly one thing: read-only rsync of the backup dir.
#
#   sudo scripts/add_backup_reader.sh [--from ADDR] [--backup-dir DIR] [--app-dir DIR] [--user NAME] PUBKEY_FILE|-
#   scripts/add_backup_reader.sh --print-line [--from ADDR] PUBKEY_FILE|-      # no changes, no root
#
# It creates a login-less system user (default rfbackup) whose only authorized key is
#     restrict,from="ADDR",command="rrsync -ro /var/backups/recipeflood" ssh-ed25519 AAAA… rf-offsite-backup
# `restrict` turns off forwarding, ptys and agent use; the forced command means the key
# cannot run a shell or write anything, and cannot read outside the backup dir, so the
# app's .env is out of its reach by path. The user is also unprivileged, and this script
# checks that it cannot read .env anyway, and that it can read every backup file.
set -Eeuo pipefail

BACKUP_DIR="/var/backups/recipeflood"; APP_DIR="/opt/recipeFlood"; BACKUP_USER="rfbackup"
FROM=""; PRINT=0; KEYSRC=""
MARK="rf-offsite-backup"

usage() { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-2}"; }
die()   { echo "✗ $*" >&2; exit 1; }

while (( $# )); do
  case "$1" in
    --from)       FROM="${2:?--from needs an address}"; shift 2;;
    --backup-dir) BACKUP_DIR="${2:?}"; shift 2;;
    --app-dir)    APP_DIR="${2:?}"; shift 2;;
    --user)       BACKUP_USER="${2:?}"; shift 2;;
    --print-line) PRINT=1; shift;;
    -h|--help)    usage 0;;
    -)            [[ -z "$KEYSRC" ]] || usage; KEYSRC="-"; shift;;
    -*)           echo "unknown option $1" >&2; usage;;
    *)            [[ -z "$KEYSRC" ]] || usage; KEYSRC="$1"; shift;;
  esac
done
[[ -n "$KEYSRC" ]] || usage

if [[ "$KEYSRC" == "-" ]]; then KEY_LINE="$(grep -v '^#' | grep -v '^[[:space:]]*$' | head -1 || true)"
else [[ -r "$KEYSRC" ]] || die "cannot read $KEYSRC"; KEY_LINE="$(grep -v '^#' "$KEYSRC" | grep -v '^[[:space:]]*$' | head -1 || true)"; fi
[[ -n "$KEY_LINE" ]] || die "no public key found in $KEYSRC"

# Only a bare public key: an options prefix would let the caller smuggle in their own command=.
if ! [[ "$KEY_LINE" =~ ^(ssh-ed25519|ecdsa-sha2-nistp(256|384|521)|ssh-rsa|sk-ssh-ed25519@openssh\.com)[[:space:]]+([A-Za-z0-9+/=]+)([[:space:]].*)?$ ]]; then
  die "that is not a bare ssh public key (expected 'ssh-ed25519 AAAA… comment')"
fi
KEY_TYPE="${BASH_REMATCH[1]}"; KEY_BLOB="${BASH_REMATCH[3]}"
if [[ -n "$FROM" && ! "$FROM" =~ ^[A-Za-z0-9.:/,*?!-]+$ ]]; then die "--from contains unexpected characters"; fi
[[ "$BACKUP_DIR" =~ ^/[A-Za-z0-9._/-]+$ ]] || die "--backup-dir must be a plain absolute path"
[[ "$APP_DIR" =~ ^/[A-Za-z0-9._/-]+$ ]]    || die "--app-dir must be a plain absolute path"

RRSYNC="$(command -v rrsync || true)"
if [[ -z "$RRSYNC" ]]; then
  (( PRINT )) && RRSYNC="/usr/bin/rrsync" || die "rrsync not found: install the rsync package"
fi

OPTS="restrict"
[[ -n "$FROM" ]] && OPTS+=",from=\"$FROM\""
OPTS+=",command=\"$RRSYNC -ro $BACKUP_DIR\""
LINE="$OPTS $KEY_TYPE $KEY_BLOB $MARK"

if (( PRINT )); then echo "$LINE"; exit 0; fi

(( EUID == 0 )) || die "run as root (or use --print-line to see what would be installed)"
[[ -d "$BACKUP_DIR" ]] || die "$BACKUP_DIR does not exist: is --backup-dir right, and has deploy.sh run?"

if ! id "$BACKUP_USER" >/dev/null 2>&1; then
  # A real shell: sshd runs the forced command through it.
  useradd --system --create-home --home-dir "/var/lib/$BACKUP_USER" --shell /bin/sh "$BACKUP_USER"
  echo "✓ created user $BACKUP_USER"
fi
# '!' (locked) is refused by sshd when PAM is off; '*' means "no password, key only".
usermod -p '*' "$BACKUP_USER"

HOME_DIR="$(getent passwd "$BACKUP_USER" | cut -d: -f6)"
install -d -m 700 -o "$BACKUP_USER" -g "$(id -gn "$BACKUP_USER")" "$HOME_DIR/.ssh"
AK="$HOME_DIR/.ssh/authorized_keys"
touch "$AK"
grep -vF " $MARK" "$AK" > "$AK.new" || true       # replace any earlier key of ours
echo "$LINE" >> "$AK.new"
install -m 600 -o "$BACKUP_USER" -g "$(id -gn "$BACKUP_USER")" "$AK.new" "$AK"; rm -f "$AK.new"
echo "✓ installed key in $AK"

# What this user can read matters more than what it is told to read.
ok=1
as_reader() { runuser -u "$BACKUP_USER" -- "$@"; }
if [[ -e "$APP_DIR/.env" ]] && as_reader test -r "$APP_DIR/.env"; then
  echo "✗ $BACKUP_USER can read $APP_DIR/.env: tighten it (chmod 600, owned by the app user)" >&2; ok=0
fi
if ! as_reader test -r "$BACKUP_DIR" -a -x "$BACKUP_DIR"; then
  echo "✗ $BACKUP_USER cannot list $BACKUP_DIR: the pull would fail. Fix with: chmod o+rx $BACKUP_DIR" >&2; ok=0
else
  shopt -s nullglob
  n=0
  for f in "$BACKUP_DIR"/recipeflood-*.sql.gz "$BACKUP_DIR"/uploads-*.tar.gz; do
    n=$((n+1))
    as_reader test -r "$f" || { echo "✗ $BACKUP_USER cannot read $f: the pull would fail. Fix with: chmod o+r $f" >&2; ok=0; }
  done
  (( n )) || echo "! no backups in $BACKUP_DIR yet: the first pull will fail until the backup timers have run" >&2
fi
(( ok )) || exit 1
echo "✓ $BACKUP_USER can read the backups in $BACKUP_DIR and cannot read $APP_DIR/.env"
