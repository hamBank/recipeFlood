"""deploy/backup-server/recipeflood-pull-backup.sh: the off-box copy (fleet spec DEP-6).

Runs the real script and a real rsync against a local directory standing in for the
app server's /var/backups/recipeflood, so the pull, the verification, the dated
history, the freshness check and the retention rules are exercised end to end. The
remote-path tests go one step further: a stand-in for ssh runs the app server's forced
command, the real `rrsync -ro`, so the pull meets the same confinement it will in
production. Only ssh itself (the key, the host key, sshd) is not covered here.
"""
import gzip
import io
import os
import shutil
import subprocess
import tarfile
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


def _tarball(path: Path, photos: dict[str, bytes] | None = None, age=2 * HOUR):
    """An uploads tarball, as recipeflood-backup-uploads writes it. Deterministic, like
    `tar czf` of an unchanged directory: same photos, same bytes."""
    photos = {"recipes/scone.jpg": b"\xff\xd8 scone"} if photos is None else photos
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in sorted(photos.items()):
            info = tarfile.TarInfo(f"uploads/{name}")
            info.size, info.mtime = len(data), 1_700_000_000
            tar.addfile(info, io.BytesIO(data))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(buf.getvalue(), mtime=0))
    _age(path, age)
    return path


@pytest.fixture
def world(tmp_path):
    """The app server's backup dir, its app dir (with secrets), and an empty destination."""
    src = tmp_path / "var-backups-recipeflood"
    src.mkdir()
    app = tmp_path / "opt-recipeFlood"
    app.mkdir()
    (app / ".env").write_text("JWT_SECRET=secret\nANTHROPIC_API_KEY=sk-secret\n")
    return {"src": src, "app": app, "dest": tmp_path / "dest", "tmp": tmp_path}


def run(world, **env):
    base = {
        "PATH": os.environ["PATH"], "HOME": str(world["tmp"]),
        "RF_PULL_CONF": "/nonexistent", "SRC_ROOT": str(world["src"]), "SRC_HOST": "",
        "DEST": str(world["dest"]),
    }
    return subprocess.run(["bash", str(SCRIPT)], env={**base, **{k: str(v) for k, v in env.items()}},
                          capture_output=True, text=True, timeout=60)


def names(d: Path):
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


def both(world, day=1, age=2 * HOUR):
    """The two nightly files for one weekday."""
    return (_dump(world["src"] / f"recipeflood-{day}.sql.gz", age=age),
            _tarball(world["src"] / f"uploads-{day}.tar.gz", age=age))


def stamp(path: Path) -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime(path.stat().st_mtime))


# ── the pull and the dated history ────────────────────────────────────────────

def test_pulls_both_kinds_under_dated_names_and_leaves_the_source_alone(world):
    db, up = both(world)
    r = run(world)
    assert r.returncode == 0, r.stdout + r.stderr
    assert names(world["dest"] / "dumps") == [f"recipeflood-{stamp(db)}.sql.gz"]
    assert names(world["dest"] / "uploads") == [f"uploads-{stamp(up)}.tar.gz"]
    assert db.exists() and up.exists()                                  # source untouched
    assert (world["dest"] / "last-success").exists()
    assert "✓ ok: 1 dump(s)" in r.stdout and "1 uploads tarball(s)" in r.stdout


def test_a_weekday_file_overwritten_at_the_source_keeps_its_old_copy_here(world):
    # The app's names repeat weekly: Monday's dump replaces last Monday's. A plain
    # mirror would hold seven days; the dated history holds every one.
    _dump(world["src"] / "recipeflood-1.sql.gz", age=7 * DAY + HOUR)
    _tarball(world["src"] / "uploads-1.tar.gz", age=7 * DAY + HOUR)
    run(world, MAX_AGE_HOURS=9999)
    both(world, day=1)                                                   # a week later
    r = run(world)
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(names(world["dest"] / "dumps")) == 2
    assert len(names(world["dest"] / "uploads")) == 2


def test_a_second_run_with_nothing_new_adds_nothing(world):
    both(world)
    run(world)
    r = run(world)
    assert r.returncode == 0 and "0 new" in r.stdout
    assert len(names(world["dest"] / "dumps")) == 1


def test_only_backup_files_are_pulled_never_temporaries_or_secrets(world):
    both(world)
    (world["src"] / "recipeflood-2.sql.gz.tmp").write_bytes(b"half-written")
    (world["src"] / ".env").write_text("secret")
    (world["src"] / "notes.txt").write_text("x")
    assert run(world).returncode == 0
    assert names(world["dest"] / "incoming") == ["recipeflood-1.sql.gz", "uploads-1.tar.gz"]
    assert not list(world["dest"].rglob(".env")) and not list(world["dest"].rglob("*.tmp"))


def test_local_copies_are_private(world):
    db, _ = both(world)
    db.chmod(0o644)
    run(world)
    for f in (world["dest"]).rglob("*.gz"):
        assert f.stat().st_mode & 0o077 == 0, f
    assert world["dest"].stat().st_mode & 0o077 == 0


def test_a_file_deleted_at_the_source_is_kept_here(world):
    db, _ = both(world)
    run(world)
    both(world, day=2, age=HOUR)
    db.unlink()
    assert run(world).returncode == 0
    assert len(names(world["dest"] / "dumps")) == 2


def test_an_unchanged_uploads_tarball_is_hard_linked_not_copied(world):
    _dump(world["src"] / "recipeflood-1.sql.gz", age=26 * HOUR)
    first = _tarball(world["src"] / "uploads-1.tar.gz", age=26 * HOUR)
    run(world)
    both(world, day=2)                       # same photos: byte-identical tarball
    run(world)
    a, b = sorted((world["dest"] / "uploads").iterdir())
    assert a.stat().st_ino == b.stat().st_ino
    _tarball(world["src"] / "uploads-3.tar.gz", photos={"recipes/new.jpg": b"new"}, age=HOUR)
    run(world)
    files = sorted((world["dest"] / "uploads").iterdir())
    assert len(files) == 3 and files[2].stat().st_ino != files[1].stat().st_ino
    assert first.exists()


# ── verification ──────────────────────────────────────────────────────────────

def test_a_truncated_dump_fails_the_run_and_is_quarantined_then_recovers(world):
    both(world)
    good = _dump(world["src"] / "recipeflood-2.sql.gz", age=HOUR)
    bad = _dump(world["src"] / "recipeflood-3.sql.gz", age=HOUR / 2, raw=good.read_bytes()[:20])
    r = run(world)
    assert r.returncode == 1 and "not a complete backup: recipeflood-3.sql.gz" in r.stdout + r.stderr
    assert "recipeflood-3.sql.gz" in names(world["dest"] / "quarantine")
    assert len(names(world["dest"] / "dumps")) == 2                     # the good ones were filed
    assert not (world["dest"] / "last-success").exists()
    # The source is fixed (e.g. the transfer had been cut off): the next run fetches it again.
    _dump(bad, age=HOUR / 4)
    r = run(world)
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(names(world["dest"] / "dumps")) == 3


def test_a_dump_without_the_completion_marker_is_rejected(world):
    both(world)
    _dump(world["src"] / "recipeflood-2.sql.gz", age=HOUR, complete=False)
    r = run(world)
    assert r.returncode == 1 and "not a complete backup: recipeflood-2.sql.gz" in r.stdout + r.stderr


def test_a_different_file_with_an_already_filed_timestamp_fails_instead_of_being_skipped(world):
    db, _ = both(world)
    assert run(world).returncode == 0
    # Same mtime, different (and unverified) content: it must not pass as "already filed".
    t = db.stat().st_mtime
    db.write_bytes(b"garbage")
    os.utime(db, (t, t))
    r = run(world)
    assert r.returncode == 1 and "differs from the copy already filed" in r.stdout + r.stderr


def test_a_corrupt_uploads_tarball_is_rejected(world):
    both(world)
    bad = _tarball(world["src"] / "uploads-2.tar.gz", age=HOUR)
    bad.write_bytes(gzip.compress(b"not a tar file at all" * 50))
    r = run(world)
    assert r.returncode == 1 and "not a complete backup: uploads-2.tar.gz" in r.stdout + r.stderr


# ── freshness ─────────────────────────────────────────────────────────────────

def test_a_stale_database_dump_fails_with_a_clear_reason(world):
    _dump(world["src"] / "recipeflood-1.sql.gz", age=50 * HOUR)
    _tarball(world["src"] / "uploads-1.tar.gz")
    r = run(world)
    assert r.returncode == 1
    out = r.stdout + r.stderr
    assert "database dump is 50h old" in out and "recipeflood-backup-db" in out
    assert not (world["dest"] / "last-success").exists()


def test_a_stale_uploads_tarball_fails_too(world):
    # The failure the old cron job hid for its whole life.
    _dump(world["src"] / "recipeflood-1.sql.gz")
    _tarball(world["src"] / "uploads-1.tar.gz", age=50 * HOUR)
    r = run(world)
    assert r.returncode == 1 and "uploads tarball is 50h old" in r.stdout + r.stderr


def test_the_age_limit_is_configurable(world):
    both(world, age=50 * HOUR)
    assert run(world, MAX_AGE_HOURS=72).returncode == 0


def test_no_dump_at_all_fails(world):
    _tarball(world["src"] / "uploads-1.tar.gz")
    r = run(world)
    assert r.returncode == 1 and "database backup has never run" in r.stdout + r.stderr


def test_no_uploads_tarball_at_all_fails(world):
    _dump(world["src"] / "recipeflood-1.sql.gz")
    r = run(world)
    assert r.returncode == 1 and "uploads backup has never run" in r.stdout + r.stderr


def test_a_missing_source_directory_fails_instead_of_passing_silently(world):
    shutil.rmtree(world["src"])
    r = run(world)
    assert r.returncode == 1 and "rsync of the backups failed" in r.stdout + r.stderr


# ── our own retention ─────────────────────────────────────────────────────────

def _history(world, n, days_ago):
    """n filed dumps dated days_ago, days_ago+1, …"""
    d = world["dest"] / "dumps"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        day = time.strftime("%Y%m%d", time.gmtime(time.time() - (days_ago + i) * DAY))
        (d / f"recipeflood-{day}-024500.sql.gz").write_bytes(b"old")


def test_old_history_is_pruned_but_never_below_the_minimum(world):
    _history(world, 10, days_ago=120)
    both(world)
    # 11 dumps, 10 older than KEEP_DAYS: pruning to 1 would leave fewer than MIN_KEEP.
    r = run(world, KEEP_DAYS=90, MIN_KEEP=7)
    assert r.returncode == 0 and "kept 10 old recipeflood file(s)" in r.stdout
    assert len(names(world["dest"] / "dumps")) == 11
    r = run(world, KEEP_DAYS=90, MIN_KEEP=1)
    assert "pruned 10 recipeflood file(s)" in r.stdout
    assert len(names(world["dest"] / "dumps")) == 1


def test_retention_goes_by_the_date_in_the_name_not_the_mtime(world):
    # Hard-linked tarballs share one mtime; the name carries each copy's own date.
    _history(world, 3, days_ago=10)
    for f in (world["dest"] / "dumps").iterdir():
        _age(f, 400 * DAY)
    both(world)
    run(world, KEEP_DAYS=90, MIN_KEEP=1)
    assert len(names(world["dest"] / "dumps")) == 4


def test_a_failed_run_prunes_nothing(world):
    _history(world, 10, days_ago=120)
    _dump(world["src"] / "recipeflood-1.sql.gz", age=50 * HOUR)
    _tarball(world["src"] / "uploads-1.tar.gz")
    assert run(world, KEEP_DAYS=90, MIN_KEEP=1).returncode == 1
    assert len(names(world["dest"] / "dumps")) == 11


# ── through the app server's real forced command (rrsync -ro) ────────────────

def _fake_ssh(world, root: Path) -> Path:
    """Stands in for `ssh rfbackup@app <rsync --server …>` arriving at a key whose forced
    command is `rrsync -ro <root>`: sshd puts the client's command in
    SSH_ORIGINAL_COMMAND and runs the forced command instead."""
    p = world["tmp"] / "fake-ssh"
    p.write_text(
        "#!/bin/bash\n"
        'while [[ $# -gt 0 && "$1" != rsync ]]; do shift; done\n'
        'export SSH_ORIGINAL_COMMAND="$*"\n'
        f'exec rrsync -ro "{root}"\n')
    p.chmod(0o755)
    return p


def _remote(world, **env):
    key = world["tmp"] / "key"; key.write_text("k")
    hosts = world["tmp"] / "known_hosts"; hosts.write_text("")
    return run(world, SRC_HOST="rfbackup@app.example", SSH_KEY=key, KNOWN_HOSTS=hosts,
               RF_PULL_TEST_RSH=_fake_ssh(world, world["src"]), **env)


@needs_rrsync
def test_the_pull_works_through_rrsync_read_only(world):
    db, up = both(world)
    r = _remote(world)
    assert r.returncode == 0, r.stdout + r.stderr
    assert names(world["dest"] / "dumps") == [f"recipeflood-{stamp(db)}.sql.gz"]
    assert names(world["dest"] / "uploads") == [f"uploads-{stamp(up)}.tar.gz"]


@needs_rrsync
def test_rrsync_confines_the_key_to_reading_the_backup_dir(world):
    both(world)
    ssh = _fake_ssh(world, world["src"])
    out = world["tmp"] / "out"; out.mkdir()

    def rsync(*args):
        return subprocess.run(["rsync", "-a", "-e", str(ssh), *args], capture_output=True, text=True, timeout=30)

    # A path outside the root (the app's .env) copies nothing.
    rsync(f"h:../{world['app'].name}/.env", f"{out}/")
    rsync("h:/etc/passwd", f"{out}/")
    assert not (out / ".env").exists() and not (out / "passwd").exists()
    # A push is refused, and nothing lands at the source.
    (out / "evil.sql.gz").write_text("x")
    r = rsync(f"{out}/evil.sql.gz", "h:./")
    assert r.returncode != 0 and not (world["src"] / "evil.sql.gz").exists()
    # A shell is refused: the forced command only runs rsync.
    r = subprocess.run([str(ssh), "h", "rsync;", "sh", "-c", "touch pwned"], capture_output=True,
                       text=True, timeout=30, cwd=world["tmp"])
    assert r.returncode != 0 and not (world["tmp"] / "pwned").exists()


def test_a_remote_pull_without_a_key_or_pinned_host_key_refuses_to_start(world):
    both(world)
    r = run(world, SRC_HOST="rfbackup@app.example", SSH_KEY=world["tmp"] / "nokey")
    assert r.returncode == 1 and "ssh key" in r.stdout + r.stderr
    key = world["tmp"] / "key"
    key.write_text("k")
    r = run(world, SRC_HOST="rfbackup@app.example", SSH_KEY=key, KNOWN_HOSTS=world["tmp"] / "nohosts")
    assert r.returncode == 1 and "accept the app server's host key" in r.stdout + r.stderr


def test_two_runs_at_once_do_not_overlap(world):
    both(world)
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


def test_the_authorized_key_is_read_only_and_confined_to_the_backup_dir():
    r = reader("--from", "203.0.113.7")
    assert r.returncode == 0, r.stderr
    line = r.stdout.strip()
    assert line.startswith('restrict,from="203.0.113.7",command="')
    assert ' -ro /var/backups/recipeflood"' in line
    assert "/opt/recipeFlood" not in line
    assert line.endswith("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UVd1G1ZS+8YHvVE9KlUE2HQkvZ5G rf-offsite-backup")
    assert "backup@vault" not in line                      # the caller's comment is replaced by our marker


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
    timer = (d / "recipeflood-pull-backup.timer").read_text()
    assert "Persistent=true" in timer and "OnCalendar=" in timer
    for script in (SCRIPT, d / "install.sh", ADD_READER):
        assert subprocess.run(["bash", "-n", str(script)]).returncode == 0
