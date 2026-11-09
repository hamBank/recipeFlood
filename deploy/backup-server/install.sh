#!/usr/bin/env bash
# install.sh — run as root on the BACKUP server (idempotent). Installs the pull script,
# its systemd service + timer, a config template and a dedicated key, and enables the
# timer. It does not start a pull: finish the steps it prints first.
set -Eeuo pipefail
# Stop loudly: without this, a failing command under set -e ends the script with no word
# of where, and the "Remaining steps" below (with the keys to authorise) never appear.
trap 'echo "✗ install.sh failed at line $LINENO: $BASH_COMMAND (exit $?)" >&2' ERR
cd "$(dirname "$0")"
[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
for c in rsync ssh ssh-keygen flock systemctl gzip tar cmp; do command -v "$c" >/dev/null || { echo "✗ missing: $c" >&2; exit 1; }; done

STATE=/var/lib/recipeflood-backup
if ! id rfpull >/dev/null 2>&1; then
  useradd --system --home-dir "$STATE" --create-home --shell /usr/sbin/nologin rfpull
  echo "✓ created user rfpull"
fi
usermod -p '*' rfpull 2>/dev/null || true
install -d -m 700 -o rfpull -g rfpull "$STATE" "$STATE/.ssh"

# Where the copies go: the unit's Environment=DEST= line, the one place it is set.
DEST="$(sed -n 's/^Environment=DEST=//p' recipeflood-pull-backup.service)"
[[ -n "$DEST" ]] || { echo "✗ no Environment=DEST= in recipeflood-pull-backup.service" >&2; exit 1; }
# The parent must already exist: creating it here would put the backups on the root
# filesystem if the backup disk isn't mounted.
[[ -d "$(dirname "$DEST")" ]] || { echo "✗ $(dirname "$DEST") does not exist: is the backup disk mounted?" >&2; exit 1; }
install -d -m 700 -o rfpull -g rfpull "$DEST"
runuser -u rfpull -- test -w "$DEST" || { echo "✗ rfpull cannot write $DEST: a parent directory blocks it (it needs o+x on each)" >&2; exit 1; }
echo "✓ backups go to $DEST"

install -m 755 recipeflood-pull-backup.sh /usr/local/sbin/recipeflood-pull-backup.sh
install -m 644 recipeflood-pull-backup.service /etc/systemd/system/recipeflood-pull-backup.service
install -m 644 recipeflood-pull-backup.timer   /etc/systemd/system/recipeflood-pull-backup.timer
if [[ ! -e /etc/recipeflood-pull-backup.conf ]]; then
  install -m 640 -o root -g rfpull recipeflood-pull-backup.conf.example /etc/recipeflood-pull-backup.conf
  echo "✓ wrote /etc/recipeflood-pull-backup.conf: check SRC_HOST"
fi

# Two keys, because the app server confines each to one directory: the database dumps,
# and the photos. Neither can read the other's directory, or the app's .env.
KEY="$STATE/.ssh/id_ed25519"
PHOTOS_KEY="$STATE/.ssh/id_ed25519_photos"
for k in "$KEY:rf-pull" "$PHOTOS_KEY:rf-pull-photos"; do
  if [[ ! -e "${k%%:*}" ]]; then
    runuser -u rfpull -- ssh-keygen -q -t ed25519 -N '' -C "${k#*:}@$(hostname)" -f "${k%%:*}"
    echo "✓ generated ${k%%:*}"
  fi
done
touch "$STATE/.ssh/known_hosts"; chown rfpull:rfpull "$STATE/.ssh/known_hosts"

systemctl daemon-reload
systemctl enable recipeflood-pull-backup.timer >/dev/null
systemctl start recipeflood-pull-backup.timer

cat <<MSG

Installed. Remaining steps:

 1. On the APP server, authorise both keys. Each can only read-only rsync one directory:
        # the database dumps (/var/backups/recipeflood)
        echo '$(cat "$KEY.pub")' | sudo scripts/add_backup_reader.sh --from <this server's IP> -
        # the photos (/opt/recipeFlood/uploads)
        echo '$(cat "$PHOTOS_KEY.pub")' | sudo scripts/add_backup_reader.sh --photos --from <this server's IP> -

 2. Check SRC_HOST in /etc/recipeflood-pull-backup.conf (rfbackup@<app host>).

 3. Pin the app server's host key: check its fingerprint on the app server
    (ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub) then here:
        sudo -u rfpull ssh-keyscan -t ed25519 <host> | sudo -u rfpull tee -a $STATE/.ssh/known_hosts
        sudo -u rfpull ssh-keygen -lf $STATE/.ssh/known_hosts      # compare with the fingerprint

 4. Run one pull and read the result:
        sudo systemctl start recipeflood-pull-backup.service
        journalctl -u recipeflood-pull-backup.service -n 20
    Then see the next scheduled run with: systemctl list-timers recipeflood-pull-backup.timer
MSG
