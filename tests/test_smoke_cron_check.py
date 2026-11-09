"""The deploy's legacy-cron check (fleet spec DEP-5, smoke_check.sh's SMOKE_CRON_PATTERN).

The two backups used to run from /etc/cron.d/recipeflood. A deploy can't remove a crontab
line, so if one ever came back (restored from a backup, copied from an old checkout) it
would run the backup a second time next to its systemd timer, silently. deploy.sh passes
a pattern to the smoke check so the next deploy fails instead.

These tests read the pattern out of deploy.sh, so they test what the deploy really uses,
and run the real scripts/smoke_check.sh against a directory standing in for /etc/cron.d.
"""
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SMOKE = ROOT / "scripts" / "smoke_check.sh"
DEPLOY = (ROOT / "deploy.sh").read_text()

#: The two lines of the deleted deploy/recipeflood.cron (git show 2896794^:deploy/recipeflood.cron).
OLD_CRON = r"""# /etc/cron.d/recipeflood — Recipe Flood scheduled jobs
SHELL=/bin/bash

# Nightly database backup (02:45) — 7-day rotation by weekday number.
45 2 * * * postgres pg_dump recipeflood | gzip > /var/backups/recipeflood/recipeflood-$(date +\%u).sql.gz

# Nightly image backup (03:15).
15 3 * * * recipeFlood tar czf /var/backups/recipeflood/uploads-$(date +\%u).tar.gz -C /opt/recipeFlood uploads
"""


def deploy_pattern() -> str:
    m = re.search(r"SMOKE_CRON_PATTERN='([^']+)'", DEPLOY)
    assert m, "deploy.sh no longer passes SMOKE_CRON_PATTERN to the smoke check"
    return m.group(1)


def smoke(cron_dir: Path) -> subprocess.CompletedProcess:
    # Nothing listens on port 1: the /health check fails, which is irrelevant here, and the
    # script carries on to the cron section.
    env = {
        "PATH": os.environ["PATH"], "SMOKE_CHECK_WAIT": "1", "SMOKE_CHECK_TIMEOUT": "1",
        "SMOKE_CRON_PATTERN": deploy_pattern(), "SMOKE_CRON_FILES": f"{cron_dir}/*",
    }
    return subprocess.run(["bash", str(SMOKE), "http://127.0.0.1:1"], env=env,
                          capture_output=True, text=True, timeout=60)


def test_deploy_passes_the_pattern_and_the_app_user():
    assert 'SMOKE_APP_USER="$APP_USER"' in DEPLOY            # so `crontab -l -u recipeFlood` is read too
    assert "SMOKE_CRON_PATTERN=" in DEPLOY


def test_the_old_cron_lines_fail_the_check(tmp_path):
    (tmp_path / "recipeflood").write_text(OLD_CRON)
    r = smoke(tmp_path)
    assert "runs twice" in r.stdout and r.returncode == 1
    assert "pg_dump recipeflood" in r.stdout and "tar czf /var/backups/recipeflood/uploads" in r.stdout


def test_either_old_line_alone_is_enough(tmp_path):
    for line in OLD_CRON.splitlines():
        if line.startswith(("45 2", "15 3")):
            (tmp_path / "recipeflood").write_text(line + "\n")
            assert "runs twice" in smoke(tmp_path).stdout, line


def test_a_clean_cron_dir_passes_that_check(tmp_path):
    (tmp_path / "other-app").write_text("30 2 * * * root /opt/other/backup.sh\n")
    r = smoke(tmp_path)
    assert "No legacy cron entries duplicate the systemd timers" in r.stdout
    assert "runs twice" not in r.stdout


def test_a_commented_out_line_is_not_a_leftover(tmp_path):
    (tmp_path / "recipeflood").write_text("# " + OLD_CRON.splitlines()[4] + "\n")
    assert "runs twice" not in smoke(tmp_path).stdout


@pytest.mark.parametrize("unit", ["recipeflood-backup-db.service", "recipeflood-backup-uploads.service"])
def test_the_pattern_matches_what_the_timers_back_up_so_it_tracks_a_move(unit):
    # If a backup ever moves out of /var/backups/recipeflood, the pattern would stop
    # matching a cron line for it: this fails first and says to update both.
    exec_line = next(l for l in (ROOT / "deploy" / unit).read_text().splitlines() if l.startswith("ExecStart="))
    assert re.search(deploy_pattern(), exec_line), f"{unit} writes elsewhere: update SMOKE_CRON_PATTERN in deploy.sh"
