"""deploy/backup-server/recipeflood-pull-backup.sh: the off-box copy (fleet spec DEP-6).

Runs the real script and a real rsync against local directories standing in for the
app server's /var/backups/recipeflood and /opt/recipeFlood/uploads, so the pull, the
verification, the dated history, the photo snapshots, the freshness check and the
retention rules are exercised end to end. The remote-path tests go one step further:
stand-ins for ssh run the app server's forced commands, the real `rrsync -ro <dir>`
for each key, so the pull meets the same confinement it will in production. Only ssh
itself (the keys, the host key, sshd) is not covered here.
"""
import gzip
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "deploy" / "backup-server" / "recipeflood-pull-backup.sh"
ADD_READER = ROOT / "scripts" / "add_backup_reader.sh"
HOUR = 3600
DAY = 86400

pytestmark = pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")
needs_rrsync = pytest.mark.skipif(shutil.which("rrsync") is None, reason="rrsync not installed")


def _age(path: Path, seconds: float):
    t = time.time() - seconds
    os.utime(path, (t, t))


def _dump(path: Path, age=2 * HOUR, complete=True, raw: bytes | None = None):
    """A gzipped plain pg_dump, as recipeflood-backup-db writes it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if raw is None:
        tail = "\n--\n-- PostgreSQL database dump complete\n--\n" if complete else "\nCOPY recipe (id"
        raw = gzip.compress(("-- PostgreSQL database dump\n" + "x" * 500 + tail).encode())
    path.write_bytes(raw)
    _age(path, age)
    return path


def _photo(world, name: str, data: bytes = b"\xff\xd8 jpeg", age=5 * DAY):
    p = world["photos"] / "recipes" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    _age(p, age)
    return p


@pytest.fixture
def world(tmp_path):
    """The app server's backup dir and uploads dir, its secrets, and an empty destination."""
    src = tmp_path / "var-backups-recipeflood"
    src.mkdir()
    app = tmp_path / "opt-recipeFlood"
    (app / "uploads").mkdir(parents=True)
    (app / ".env").write_text("JWT_SECRET=secret\nANTHROPIC_API_KEY=sk-secret\n")
    w = {"src": src, "app": app, "photos": app / "uploads", "dest": tmp_path / "dest", "tmp": tmp_path}
    _photo(w, "scone.jpg", b"scone")
    _photo(w, "pavlova.jpg", b"pavlova")
    return w


def run(world, **env):
    base = {
        "PATH": os.environ["PATH"], "HOME": str(world["tmp"]),
        "RF_PULL_CONF": "/nonexistent", "SRC_ROOT": str(world["src"]), "SRC_HOST": "",
        "SRC_PHOTOS_ROOT": str(world["photos"]), "DEST": str(world["dest"]),
    }
    return subprocess.run(["bash", str(SCRIPT)], env={**base, **{k: str(v) for k, v in env.items()}},
                          capture_output=True, text=True, timeout=60)


def ok(world, **env):
    r = run(world, **env)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def names(d: Path):
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


def snapshots(world):
    d = world["dest"] / "photos"
    return sorted(p for p in d.iterdir() if p.is_dir() and p.name.startswith("20")) if d.exists() else []


def stamp(path: Path) -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime(path.stat().st_mtime))


def tonight(world, day=1, age=2 * HOUR):
    return _dump(world["src"] / f"recipeflood-{day}.sql.gz", age=age)


# ── the database dumps and their dated history ───────────────────────────────

def test_pulls_dumps_under_dated_names_and_leaves_the_source_alone(world):
    db = tonight(world)
    r = ok(world)
    assert names(world["dest"] / "dumps") == [f"recipeflood-{stamp(db)}.sql.gz"]
    assert db.exists()                                                   # source untouched
    assert (world["dest"] / "last-success").exists()
    assert "✓ ok: 1 dump(s)" in r.stdout


def test_a_weekday_dump_overwritten_at_the_source_keeps_its_old_copy_here(world):
    # The app's names repeat weekly: Monday's dump replaces last Monday's. A plain
    # mirror would hold seven days; the dated history holds every one.
    _dump(world["src"] / "recipeflood-1.sql.gz", age=7 * DAY + HOUR)
    ok(world, MAX_AGE_HOURS=9999)
    tonight(world, day=1)                                                # a week later
    ok(world)
    assert len(names(world["dest"] / "dumps")) == 2


def test_a_second_run_with_nothing_new_adds_nothing(world):
    tonight(world)
    ok(world)
    r = ok(world)
    assert "0 new" in r.stdout and "photos unchanged" in r.stdout
    assert len(names(world["dest"] / "dumps")) == 1 and len(snapshots(world)) == 1


def test_only_dumps_are_pulled_from_the_backup_dir(world):
    tonight(world)
    (world["src"] / "recipeflood-2.sql.gz.tmp").write_bytes(b"half-written")
    (world["src"] / "uploads-1.tar.gz").write_bytes(b"the app's local photo copy")
    (world["src"] / ".env").write_text("secret")
    ok(world)
    assert names(world["dest"] / "incoming") == ["recipeflood-1.sql.gz"]
    assert not list(world["dest"].rglob(".env")) and not list(world["dest"].rglob("*.tmp"))
    assert not list(world["dest"].rglob("uploads-*.tar.gz"))


def test_local_copies_are_private(world):
    tonight(world).chmod(0o644)
    for p in world["photos"].rglob("*"):
        p.chmod(0o755 if p.is_dir() else 0o644)
    ok(world)
    for f in world["dest"].rglob("*"):
        assert f.stat().st_mode & 0o077 == 0, f


def test_a_dump_deleted_at_the_source_is_kept_here(world):
    db = tonight(world)
    ok(world)
    tonight(world, day=2, age=HOUR)
    db.unlink()
    ok(world)
    assert len(names(world["dest"] / "dumps")) == 2


# ── verification ──────────────────────────────────────────────────────────────

def test_a_truncated_dump_fails_the_run_and_is_quarantined_then_recovers(world):
    tonight(world)
    good = _dump(world["src"] / "recipeflood-2.sql.gz", age=HOUR)
    bad = _dump(world["src"] / "recipeflood-3.sql.gz", age=HOUR / 2, raw=good.read_bytes()[:20])
    r = run(world)
    assert r.returncode == 1 and "not a complete backup: recipeflood-3.sql.gz" in r.stdout + r.stderr
    assert "recipeflood-3.sql.gz" in names(world["dest"] / "quarantine")
    assert len(names(world["dest"] / "dumps")) == 2                     # the good ones were filed
    assert not (world["dest"] / "last-success").exists()
    # The source is fixed (e.g. the transfer had been cut off): the next run fetches it again.
    _dump(bad, age=HOUR / 4)
    ok(world)
    assert len(names(world["dest"] / "dumps")) == 3


def test_a_dump_without_the_completion_marker_is_rejected(world):
    tonight(world)
    _dump(world["src"] / "recipeflood-2.sql.gz", age=HOUR, complete=False)
    r = run(world)
    assert r.returncode == 1 and "not a complete backup: recipeflood-2.sql.gz" in r.stdout + r.stderr


def test_a_different_file_with_an_already_filed_timestamp_fails_instead_of_being_skipped(world):
    db = tonight(world)
    ok(world)
    # Same mtime, different (and unverified) content: it must not pass as "already filed".
    t = db.stat().st_mtime
    db.write_bytes(b"garbage")
    os.utime(db, (t, t))
    r = run(world)
    assert r.returncode == 1 and "differs from the copy already filed" in r.stdout + r.stderr


# ── freshness ─────────────────────────────────────────────────────────────────

def test_a_stale_database_dump_fails_with_a_clear_reason(world):
    tonight(world, age=50 * HOUR)
    r = run(world)
    assert r.returncode == 1
    out = r.stdout + r.stderr
    assert "database dump is 50h old" in out and "recipeflood-backup-db" in out
    assert not (world["dest"] / "last-success").exists()


def test_the_age_limit_is_configurable(world):
    tonight(world, age=50 * HOUR)
    ok(world, MAX_AGE_HOURS=72)


def test_no_dump_at_all_fails(world):
    r = run(world)
    assert r.returncode == 1 and "database backup has never run" in r.stdout + r.stderr


def test_a_missing_source_directory_fails_instead_of_passing_silently(world):
    shutil.rmtree(world["src"])
    r = run(world)
    assert r.returncode == 1 and "rsync of the backups failed" in r.stdout + r.stderr


# ── photos: dated snapshots that share unchanged files ───────────────────────

def test_the_first_pull_snapshots_every_photo(world):
    tonight(world)
    r = ok(world)
    (snap,) = snapshots(world)
    assert names(snap / "recipes") == ["pavlova.jpg", "scone.jpg"]
    assert (snap / "recipes" / "scone.jpg").read_bytes() == b"scone"
    assert "new photo snapshot" in r.stdout and "(2 files)" in r.stdout


def test_a_new_photo_makes_a_snapshot_that_shares_the_unchanged_ones(world):
    # The point of the snapshots: 90 days cost about one copy plus what changed.
    tonight(world)
    ok(world)
    _photo(world, "lamington.jpg", b"lamington", age=0)
    ok(world)
    first, second = snapshots(world)
    assert names(second / "recipes") == ["lamington.jpg", "pavlova.jpg", "scone.jpg"]
    assert (second / "recipes" / "scone.jpg").stat().st_ino == (first / "recipes" / "scone.jpg").stat().st_ino
    assert (second / "recipes" / "scone.jpg").stat().st_nlink == 2
    assert not (first / "recipes" / "lamington.jpg").exists()           # the old snapshot is as it was


def test_a_replaced_photo_is_a_new_file_and_the_old_snapshot_keeps_the_old_one(world):
    tonight(world)
    ok(world)
    _photo(world, "scone.jpg", b"a better scone photo", age=0)
    ok(world)
    first, second = snapshots(world)
    assert (first / "recipes" / "scone.jpg").read_bytes() == b"scone"
    assert (second / "recipes" / "scone.jpg").read_bytes() == b"a better scone photo"


def test_a_photo_deleted_in_the_app_stays_in_the_older_snapshot(world):
    tonight(world)
    _photo(world, "lamington.jpg", b"lamington")
    ok(world)
    (world["photos"] / "recipes" / "lamington.jpg").unlink()
    ok(world)
    first, second = snapshots(world)
    assert (first / "recipes" / "lamington.jpg").exists()
    assert not (second / "recipes" / "lamington.jpg").exists()


def test_unchanged_photos_keep_no_new_snapshot(world):
    tonight(world)
    ok(world)
    r = ok(world)
    assert len(snapshots(world)) == 1 and "photos unchanged (2 files)" in r.stdout
    assert not (world["dest"] / "photos" / ".partial").exists()


def test_photos_falling_by_half_fail_the_run_but_keep_everything(world):
    tonight(world)
    for i in range(6):
        _photo(world, f"extra-{i}.jpg", b"x%d" % i)
    ok(world)                                                            # 8 photos
    for p in (world["photos"] / "recipes").glob("extra-*"):
        p.unlink()
    r = run(world)                                                       # 2 photos
    assert r.returncode == 1 and "photo count fell from 8 to 2" in r.stdout + r.stderr
    first, second = snapshots(world)
    assert len(names(first / "recipes")) == 8 and len(names(second / "recipes")) == 2


def test_a_photo_drop_keeps_failing_and_prunes_nothing_until_acknowledged(world):
    # Otherwise the next pull compares against the smaller snapshot and passes, and a
    # single failed run is easy to miss.
    tonight(world)
    for i in range(6):
        _photo(world, f"extra-{i}.jpg", b"x%d" % i)
    ok(world)
    for p in (world["photos"] / "recipes").glob("extra-*"):
        p.unlink()
    assert run(world).returncode == 1
    first = snapshots(world)[0]
    ancient = first.with_name(time.strftime("%Y%m%d", time.gmtime(time.time() - 200 * DAY)) + "-030000")
    first.rename(ancient)
    r = run(world, KEEP_DAYS=90, MIN_KEEP=1)                             # nothing changed since
    assert r.returncode == 1 and "rm " in r.stdout + r.stderr and "PHOTOS-DROPPED" in r.stdout + r.stderr
    assert ancient.exists()                                              # not pruned while unacknowledged
    (world["dest"] / "PHOTOS-DROPPED").unlink()
    ok(world)


@needs_rrsync
def test_a_cut_off_photo_pull_leaves_no_half_snapshot(world):
    tonight(world)
    ok(world)
    _photo(world, "lamington.jpg", b"lamington", age=0)
    key = world["tmp"] / "key"; key.write_text("k")
    hosts = world["tmp"] / "known_hosts"; hosts.write_text("")
    dropped = world["tmp"] / "ssh-dropped"                  # the connection dies, as ssh's does
    dropped.write_text("#!/bin/bash\necho 'Connection reset by peer' >&2\nexit 255\n")
    dropped.chmod(0o755)
    r = run(world, SRC_HOST="rfbackup@app.example", SSH_KEY=key, PHOTOS_SSH_KEY=key, KNOWN_HOSTS=hosts,
            RF_PULL_TEST_RSH=_fake_ssh(world, world["src"], "ssh-backups"), RF_PULL_TEST_RSH_PHOTOS=dropped)
    assert r.returncode == 1 and "rsync of the photos failed" in r.stdout + r.stderr
    assert len(snapshots(world)) == 1                       # nothing half-made became a snapshot
    ok(world)                                               # and the next good run recovers
    assert len(snapshots(world)) == 2


def test_photos_can_be_left_out(world):
    tonight(world)
    ok(world, PULL_PHOTOS=0)
    assert snapshots(world) == []


def test_a_missing_photos_directory_fails(world):
    tonight(world)
    shutil.rmtree(world["photos"])
    r = run(world)
    assert r.returncode == 1 and "rsync of the photos failed" in r.stdout + r.stderr


# ── our own retention ─────────────────────────────────────────────────────────

def _history(world, n, days_ago):
    """n filed dumps and n photo snapshots dated days_ago, days_ago+1, …"""
    for i in range(n):
        day = time.strftime("%Y%m%d", time.gmtime(time.time() - (days_ago + i) * DAY))
        d = world["dest"] / "dumps"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"recipeflood-{day}-024500.sql.gz").write_bytes(b"old")
        s = world["dest"] / "photos" / f"{day}-030000" / "recipes"
        s.mkdir(parents=True, exist_ok=True)
        (s / "old.jpg").write_bytes(b"old")


def test_old_history_is_pruned_but_never_below_the_minimum(world):
    _history(world, 10, days_ago=120)
    tonight(world)
    # 11 of each, 10 older than KEEP_DAYS: pruning to 1 would leave fewer than MIN_KEEP.
    r = ok(world, KEEP_DAYS=90, MIN_KEEP=7)
    assert "kept 10 old dump(s)" in r.stdout and "kept 10 old photo snapshot(s)" in r.stdout
    assert len(names(world["dest"] / "dumps")) == 11 and len(snapshots(world)) == 11
    r = ok(world, KEEP_DAYS=90, MIN_KEEP=1)
    assert "pruned 10 dump(s)" in r.stdout and "pruned 10 photo snapshot(s)" in r.stdout
    assert len(names(world["dest"] / "dumps")) == 1 and len(snapshots(world)) == 1


def test_pruning_an_old_snapshot_leaves_the_photos_newer_ones_share(world):
    tonight(world)
    ok(world)
    first = snapshots(world)[0]
    _photo(world, "lamington.jpg", b"lamington", age=0)
    ok(world)
    old = first.with_name(time.strftime("%Y%m%d", time.gmtime(time.time() - 200 * DAY)) + "-030000")
    first.rename(old)                                                    # make the first one ancient
    ok(world, KEEP_DAYS=90, MIN_KEEP=1)
    (only,) = snapshots(world)
    assert (only / "recipes" / "scone.jpg").read_bytes() == b"scone"


def test_retention_goes_by_the_date_in_the_name_not_the_mtime(world):
    # Hard-linked photos keep their first mtime; the name carries each snapshot's date.
    _history(world, 3, days_ago=10)
    for f in (world["dest"] / "dumps").iterdir():
        _age(f, 400 * DAY)
    tonight(world)
    ok(world, KEEP_DAYS=90, MIN_KEEP=1)
    assert len(names(world["dest"] / "dumps")) == 4


def test_a_failed_run_prunes_nothing(world):
    _history(world, 10, days_ago=120)
    tonight(world, age=50 * HOUR)
    assert run(world, KEEP_DAYS=90, MIN_KEEP=1).returncode == 1
    assert len(names(world["dest"] / "dumps")) == 11


# ── through the app server's real forced commands (rrsync -ro) ───────────────

def _fake_ssh(world, root: Path, name: str) -> Path:
    """Stands in for `ssh rfbackup@app <rsync --server …>` arriving at a key whose forced
    command is `rrsync -ro <root>`: sshd puts the client's command in
    SSH_ORIGINAL_COMMAND and runs the forced command instead."""
    p = world["tmp"] / name
    p.write_text(
        "#!/bin/bash\n"
        'while [[ $# -gt 0 && "$1" != rsync ]]; do shift; done\n'
        'export SSH_ORIGINAL_COMMAND="$*"\n'
        f'exec rrsync -ro "{root}"\n')
    p.chmod(0o755)
    return p


def _remote(world, **env):
    key = world["tmp"] / "key"; key.write_text("k")
    pkey = world["tmp"] / "pkey"; pkey.write_text("k")
    hosts = world["tmp"] / "known_hosts"; hosts.write_text("")
    return run(world, SRC_HOST="rfbackup@app.example", SSH_KEY=key, PHOTOS_SSH_KEY=pkey, KNOWN_HOSTS=hosts,
               RF_PULL_TEST_RSH=_fake_ssh(world, world["src"], "ssh-backups"),
               RF_PULL_TEST_RSH_PHOTOS=_fake_ssh(world, world["photos"], "ssh-photos"), **env)


@needs_rrsync
def test_the_pull_works_through_both_keys_rrsync_read_only(world):
    db = tonight(world)
    r = _remote(world)
    assert r.returncode == 0, r.stdout + r.stderr
    assert names(world["dest"] / "dumps") == [f"recipeflood-{stamp(db)}.sql.gz"]
    (snap,) = snapshots(world)
    assert names(snap / "recipes") == ["pavlova.jpg", "scone.jpg"]
    assert not list(world["dest"].rglob(".env"))
    # The second pull adds --link-dest; rrsync must accept it, and the snapshots share.
    _photo(world, "lamington.jpg", b"lamington", age=0)
    r = _remote(world)
    assert r.returncode == 0, r.stdout + r.stderr
    first, second = snapshots(world)
    assert (second / "recipes" / "scone.jpg").stat().st_ino == (first / "recipes" / "scone.jpg").stat().st_ino


@needs_rrsync
def test_rrsync_confines_each_key_to_reading_its_own_directory(world):
    tonight(world)
    out = world["tmp"] / "out"; out.mkdir()
    for root, other in ((world["src"], world["photos"]), (world["photos"], world["src"])):
        ssh = _fake_ssh(world, root, f"ssh-{root.name}")

        def rsync(*args):
            return subprocess.run(["rsync", "-a", "-e", str(ssh), *args], capture_output=True, text=True, timeout=30)

        # The app's .env, the other key's directory and an absolute path all copy nothing.
        for path in ("h:../.env", f"h:../../{world['app'].name}/.env", f"h:{other}/", "h:/etc/passwd"):
            rsync(path, f"{out}/")
        assert not (out / ".env").exists() and not (out / "passwd").exists()
        assert not list(out.rglob("*.sql.gz")) or root == world["src"]
        # A push is refused, and nothing lands at the source.
        (out / "evil.jpg").write_text("x")
        r = rsync(f"{out}/evil.jpg", "h:./")
        assert r.returncode != 0 and not (root / "evil.jpg").exists()
        (out / "evil.jpg").unlink()
    # A shell is refused: the forced command only runs rsync.
    ssh = _fake_ssh(world, world["photos"], "ssh-shell")
    r = subprocess.run([str(ssh), "h", "rsync;", "sh", "-c", "touch pwned"], capture_output=True,
                       text=True, timeout=30, cwd=world["tmp"])
    assert r.returncode != 0 and not (world["tmp"] / "pwned").exists()


def test_a_remote_pull_without_a_key_or_pinned_host_key_refuses_to_start(world):
    tonight(world)
    r = run(world, SRC_HOST="rfbackup@app.example", SSH_KEY=world["tmp"] / "nokey")
    assert r.returncode == 1 and "ssh key" in r.stdout + r.stderr
    key = world["tmp"] / "key"
    key.write_text("k")
    r = run(world, SRC_HOST="rfbackup@app.example", SSH_KEY=key, KNOWN_HOSTS=world["tmp"] / "nohosts")
    assert r.returncode == 1 and "accept the app server's host key" in r.stdout + r.stderr
    hosts = world["tmp"] / "known_hosts"; hosts.write_text("")
    r = run(world, SRC_HOST="rfbackup@app.example", SSH_KEY=key, KNOWN_HOSTS=hosts,
            PHOTOS_SSH_KEY=world["tmp"] / "nophotoskey")
    assert r.returncode == 1 and "(photos) is missing" in r.stdout + r.stderr


def test_two_runs_at_once_do_not_overlap(world):
    tonight(world)
    world["dest"].mkdir()
    holder = subprocess.Popen(["bash", "-c", f"exec 9>{world['dest']}/.lock; flock 9; sleep 5"])
    time.sleep(0.5)
    try:
        r = run(world)
        assert r.returncode == 1 and "already running" in r.stdout + r.stderr
    finally:
        holder.kill()


# ── scripts/add_backup_reader.sh (the app-server side) ───────────────────────

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UVd1G1ZS+8YHvVE9KlUE2HQkvZ5G backup@vault"


def reader(*args, stdin=KEY):
    return subprocess.run(["bash", str(ADD_READER), "--print-line", *args, "-"], input=stdin,
                          capture_output=True, text=True, timeout=30)


def test_the_backups_key_is_read_only_and_confined_to_the_backup_dir():
    r = reader("--from", "203.0.113.7")
    assert r.returncode == 0, r.stderr
    line = r.stdout.strip()
    assert line.startswith('restrict,from="203.0.113.7",command="')
    assert ' -ro /var/backups/recipeflood"' in line
    assert "/opt/recipeFlood" not in line
    assert line.endswith("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UVd1G1ZS+8YHvVE9KlUE2HQkvZ5G rf-offsite-backup")
    assert "backup@vault" not in line                      # the caller's comment is replaced by our marker


def test_the_photos_key_is_confined_to_the_uploads_dir_not_the_app_dir():
    line = reader("--photos", "--from", "203.0.113.7").stdout.strip()
    assert ' -ro /opt/recipeFlood/uploads"' in line
    assert line.endswith(" rf-offsite-photos")


def test_a_key_that_brings_its_own_options_is_refused():
    # An options prefix could smuggle in a different command=.
    r = reader(stdin='command="sh" ' + KEY)
    assert r.returncode == 1 and "not a bare ssh public key" in r.stderr


@pytest.mark.parametrize("value", ['1.2.3.4" ,command="sh', "1.2.3.4 5.6.7.8", "$(id)"])
def test_from_cannot_be_used_to_inject_options(value):
    r = reader("--from", value)
    assert r.returncode == 1 and "unexpected characters" in r.stderr


@pytest.mark.parametrize("flag", ["--backup-dir", "--app-dir"])
def test_the_directories_must_be_plain_paths(flag):
    r = reader(flag, '/var/x" -rw /')
    assert r.returncode == 1 and "plain absolute path" in r.stderr


# ── the files install.sh installs exist and agree with each other ────────────

def test_the_installer_and_units_agree():
    d = SCRIPT.parent
    installer = (d / "install.sh").read_text()
    for name in ("recipeflood-pull-backup.sh", "recipeflood-pull-backup.service",
                 "recipeflood-pull-backup.timer", "recipeflood-pull-backup.conf.example"):
        assert (d / name).exists() and name in installer
    service = (d / "recipeflood-pull-backup.service").read_text()
    assert "ExecStart=/usr/local/sbin/recipeflood-pull-backup.sh" in service
    assert "Type=oneshot" in service and "User=rfpull" in service
    assert "StateDirectory=recipeflood-backup" in service and "/var/lib/recipeflood-backup" in installer
    # The destination is opened in the sandbox and tied to its disk, at the same path.
    dest = [l.split("=", 2)[2] for l in service.splitlines() if l.startswith("Environment=DEST=")]
    assert dest == ["/lklBackup/sites_apps/recipeFlood"]
    assert f"ReadWritePaths={dest[0]}" in service.splitlines()
    assert f"RequiresMountsFor={dest[0]}" in service.splitlines()
    assert "Environment=DEST=" in installer                  # install.sh reads it from the unit
    # Both keys: the installer makes the one the script defaults to, and says to authorise it.
    assert "id_ed25519_photos" in installer and "id_ed25519_photos" in SCRIPT.read_text()
    assert "add_backup_reader.sh --photos" in installer
    timer = (d / "recipeflood-pull-backup.timer").read_text()
    assert "Persistent=true" in timer and "OnCalendar=" in timer
    for script in (SCRIPT, d / "install.sh", ADD_READER):
        assert subprocess.run(["bash", "-n", str(script)]).returncode == 0
    assert "trap " in installer and " ERR" in installer      # a failure says where (CLAUDE.md: stop loudly)
