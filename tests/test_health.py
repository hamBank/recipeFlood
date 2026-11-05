"""GET /health: the fleet spec's contract (OBS-1, BLD-2), see API.md."""

import json

from backend import version as version_module


def test_health_reports_the_fleet_contract(client, tmp_path, monkeypatch):
    version_file = tmp_path / "version.json"
    version_file.write_text(
        json.dumps({"build_sha": "abc1234", "frontend_sha": "def5678", "built_at": "2026-11-05T00:00:00Z"})
    )
    monkeypatch.setattr(version_module, "VERSION_FILE", version_file)

    body = client.get("/health").json()

    assert set(body) == {"status", "backend_sha", "frontend_sha", "build_sha", "built_at", "started_at"}
    assert body["status"] == "ok"
    assert body["build_sha"] == "abc1234"
    assert body["frontend_sha"] == "def5678"
    assert body["built_at"] == "2026-11-05T00:00:00Z"
    assert body["started_at"] == version_module.STARTED_AT
    assert body["backend_sha"]


def test_health_without_a_build_reports_nulls_not_an_error(client, tmp_path, monkeypatch):
    # The service can come up before the frontend build has written the file.
    monkeypatch.setattr(version_module, "VERSION_FILE", tmp_path / "missing.json")
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert (body["build_sha"], body["frontend_sha"], body["built_at"]) == (None, None, None)


def test_a_version_file_from_before_the_contract_reads_as_unbuilt(client, tmp_path, monkeypatch):
    # The old {version, built_at} shape: the smoke check must see no
    # build_sha (and fail) rather than a misleading match.
    old = tmp_path / "version.json"
    old.write_text(json.dumps({"version": "abc1234", "built_at": "2026-11-01T00:00:00Z"}))
    monkeypatch.setattr(version_module, "VERSION_FILE", old)
    body = client.get("/health").json()
    assert body["build_sha"] is None
