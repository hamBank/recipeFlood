"""Fleet spec CFG-2: the app refuses to start with auth on and a public or
missing JWT_SECRET, and deploy.sh's preflight (scripts/check_config.py)
reports it before the restart."""

import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.config import DEFAULT_JWT_SECRET, Settings

REPO = Path(__file__).resolve().parent.parent


class TestSecretGuard:
    @pytest.mark.parametrize("secret", [DEFAULT_JWT_SECRET, "", "   "])
    def test_auth_on_refuses_a_public_or_empty_secret(self, secret):
        with pytest.raises(ValidationError, match="JWT_SECRET"):
            Settings(auth_enabled=True, jwt_secret=secret)

    def test_auth_on_with_a_real_secret_starts(self):
        assert Settings(auth_enabled=True, jwt_secret="x" * 32).jwt_secret == "x" * 32

    def test_auth_off_does_not_care(self):
        assert Settings(auth_enabled=False, jwt_secret=DEFAULT_JWT_SECRET).auth_enabled is False


class TestConfigPreflight:
    def _run(self, tmp_path, env_text):
        env_file = tmp_path / ".env"
        env_file.write_text(env_text)
        return subprocess.run(
            [sys.executable, "scripts/check_config.py", str(env_file)],
            cwd=REPO,
            capture_output=True,
            text=True,
            # The deploy's own environment must not hide a bad .env.
            env={"PATH": "/usr/bin:/bin", "AUTH_ENABLED": "false", "JWT_SECRET": "from-the-shell"},
        )

    def test_a_good_env_file_passes(self, tmp_path):
        result = self._run(tmp_path, "AUTH_ENABLED=true\nJWT_SECRET=" + "a" * 64 + "\n")
        assert result.returncode == 0, result.stderr
        assert "configuration OK" in result.stdout

    def test_a_missing_secret_fails_and_says_why(self, tmp_path):
        result = self._run(tmp_path, "AUTH_ENABLED=true\nJWT_SECRET=\n")
        assert result.returncode == 1
        assert "JWT_SECRET" in result.stderr

    def test_no_secret_line_at_all_fails(self, tmp_path):
        # AUTH_ENABLED defaults to true, so a .env missing both lines fails too.
        result = self._run(tmp_path, "DATABASE_URL=sqlite:///x.db\n")
        assert result.returncode == 1

    def test_the_failure_never_quotes_a_secret(self, tmp_path):
        # The message lands in the deploy log; pydantic would otherwise
        # quote every input value in it.
        result = self._run(
            tmp_path,
            "AUTH_ENABLED=true\nJWT_SECRET=\nDEPLOY_SECRET=hook-secret-value\nANTHROPIC_API_KEY=sk-ant-private\n",
        )
        assert result.returncode == 1
        assert "hook-secret-value" not in result.stderr
        assert "sk-ant-private" not in result.stderr
