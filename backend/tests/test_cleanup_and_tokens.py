"""Cleanup guarantees, download-token lifecycle, cross-user isolation, capacity caps."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from conftest import job_dirs, upload


def test_inspection_leaves_no_scratch_data(client, samples, apps):
    for _ in range(2):
        assert upload(client, samples["jpeg"], endpoint="inspect").status_code == 200
    root = Path(apps.created[0].state.settings.temp_root)
    assert job_dirs(root) == []
    assert apps.created[0].state.jobs.stats()["jobs"] == 0


def test_failed_sanitization_leaves_no_scratch_data(client, samples, apps):
    response = upload(client, samples["random"], endpoint="sanitize")
    assert response.status_code == 415
    root = Path(apps.created[0].state.settings.temp_root)
    assert job_dirs(root) == []
    assert apps.created[0].state.jobs.stats()["jobs"] == 0
    assert apps.created[0].state.jobs.stats()["temp_bytes"] == 0


def test_cleanup_after_internal_failure(client, samples, apps, monkeypatch):
    from app.errors import cannot_process

    async def boom(*args, **kwargs):
        raise cannot_process("engine failure for test")

    monkeypatch.setattr("app.service.exiftool.write", boom)
    response = upload(client, samples["jpeg"], endpoint="sanitize")
    assert response.status_code == 422
    root = Path(apps.created[0].state.settings.temp_root)
    assert job_dirs(root) == []
    assert apps.created[0].state.jobs.stats()["jobs"] == 0


def test_expired_token_is_rejected_and_job_removed(client, samples, apps):
    body = upload(client, samples["jpeg"], endpoint="sanitize").json()
    application = apps.created[0]
    job = application.state.jobs._jobs[body["job_id"]]
    job.token_expires_at = time.time() - 1
    directory = job.path

    response = client.get(body["download"]["path"])
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert not directory.exists()


def test_expired_job_is_swept(client, samples, apps):
    client_with_short_ttl = apps.client(JOB_TTL_SECONDS="30")
    body = upload(client_with_short_ttl, samples["jpeg"], endpoint="sanitize").json()
    application = apps.created[-1]
    job = application.state.jobs._jobs[body["job_id"]]
    job.expires_at = time.time() - 1
    directory = job.path

    asyncio.run(application.state.jobs.sweep())
    assert not directory.exists()
    assert application.state.jobs.stats()["jobs"] == 0


def test_startup_purges_previous_scratch_data(tmp_path):
    from conftest import build_settings
    from app.main import create_app
    from fastapi.testclient import TestClient

    settings = build_settings(tmp_path, CLEANUP_INTERVAL_SECONDS="5")
    root = Path(settings.temp_root)
    stale = root / "stale-job-directory"
    stale.mkdir(parents=True)
    (stale / "leftover.bin").write_bytes(b"previous run data")

    application = create_app(settings)
    with TestClient(application, raise_server_exceptions=False):
        assert not stale.exists()
        assert root.exists()


def test_cross_user_download_is_denied_and_token_survives(apps, samples):
    client = apps.client(TRUST_PROXY_HEADERS="true")
    owner = {"X-Forwarded-For": "203.0.113.10"}
    attacker = {"X-Forwarded-For": "203.0.113.99"}

    response = client.post(
        "/api/v1/metadata/sanitize",
        files={"file": ("photo.jpg", samples["jpeg"].bytes(), "application/octet-stream")},
        headers=owner,
    )
    assert response.status_code == 200
    path = response.json()["download"]["path"]

    denied = client.get(path, headers=attacker)
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "not_found"

    allowed = client.get(path, headers=owner)
    assert allowed.status_code == 200
    assert len(allowed.content) > 100


def test_download_binding_can_be_disabled_explicitly(apps, samples):
    client = apps.client(TRUST_PROXY_HEADERS="true", DOWNLOAD_BIND_IP="false")
    response = client.post(
        "/api/v1/metadata/sanitize",
        files={"file": ("photo.jpg", samples["jpeg"].bytes(), "application/octet-stream")},
        headers={"X-Forwarded-For": "203.0.113.10"},
    )
    path = response.json()["download"]["path"]
    other_ip = client.get(path, headers={"X-Forwarded-For": "198.51.100.42"})
    assert other_ip.status_code == 200


def test_concurrent_job_cap_returns_503(apps, samples):
    client = apps.client(MAX_CONCURRENT_JOBS="1")
    first = upload(client, samples["jpeg"], endpoint="sanitize")
    assert first.status_code == 200
    second = upload(client, samples["jpeg"], endpoint="sanitize")
    assert second.status_code == 503
    assert second.json()["error"]["code"] == "processor_busy"
    assert second.headers["Retry-After"] == "10"


def test_temp_byte_cap_returns_503(apps, samples):
    # A 1 MiB scratch budget is smaller than one 1.4 MB upload, so the next
    # request is refused instead of filling the container's disk.
    client = apps.client(MAX_TEMP_BYTES=str(1024 * 1024), MAX_CONCURRENT_JOBS="8")
    first = upload(client, samples["mp4_large"], endpoint="sanitize")
    assert first.status_code == 200
    assert apps.created[0].state.jobs.stats()["temp_bytes"] > 1024 * 1024

    second = upload(client, samples["mp4_large"], endpoint="sanitize")
    assert second.status_code == 503
    assert second.json()["error"]["code"] == "processor_busy"


def test_job_ids_are_unguessable_and_distinct(client, samples):
    ids = set()
    for _ in range(3):
        body = upload(client, samples["jpeg"], endpoint="sanitize").json()
        ids.add(body["job_id"])
        assert len(body["job_id"]) >= 20
        assert len(body["download"]["token"]) >= 32
    assert len(ids) == 3
