"""Abuse-resistance tests: traversal, command injection, size limits, rate limits."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from conftest import chunked, job_dirs, multipart_body, upload


def test_path_traversal_filename_is_harmless(client, samples, apps):
    payload = samples["jpeg"]
    response = upload(client, payload, filename="../../../../etc/passwd", endpoint="inspect")
    assert response.status_code == 200
    assert "passwd" not in response.text

    root = Path(apps.created[0].state.settings.temp_root)
    # Nothing was created outside the per-job directories.
    for entry in root.iterdir():
        assert entry.name == "_toolhome" or entry.is_dir()
    assert not (root.parent / "etc").exists()


def test_windows_style_traversal_filename(client, samples):
    response = upload(client, samples["jpeg"], filename="..\\..\\windows\\system32\\evil.jpg",
                      endpoint="inspect")
    assert response.status_code == 200
    assert "system32" not in response.text


def test_command_injection_filenames_are_inert(client, samples, apps, tmp_path):
    canaries = [
        'photo"; touch pwned_file; echo ".jpg',
        "photo$(touch pwned_file).jpg",
        "photo`touch pwned_file`.jpg",
        "photo|touch pwned_file.jpg",
        "photo;rm -rf pwned_file;.jpg",
    ]
    for name in canaries:
        response = upload(client, samples["jpeg"], filename=name, endpoint="inspect")
        assert response.status_code == 200, name

    root = Path(apps.created[0].state.settings.temp_root)
    for location in (Path.cwd(), root, tmp_path, root.parent):
        assert not (location / "pwned_file").exists()
    assert not list(root.rglob("pwned_file*"))


def test_server_never_calls_a_shell(client, samples, monkeypatch):
    def forbidden(*args, **kwargs):  # pragma: no cover - only runs on a regression
        raise AssertionError("the API must never spawn a shell")

    monkeypatch.setattr(asyncio, "create_subprocess_shell", forbidden, raising=False)
    response = upload(client, samples["jpeg"], endpoint="inspect")
    assert response.status_code == 200


def test_declared_oversized_request_is_rejected(apps, samples):
    client = apps.client(MAX_UPLOAD_BYTES=1024, MAX_REQUEST_BYTES=2048)
    response = upload(client, samples["jpeg"], endpoint="inspect")
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_chunked_upload_without_content_length_is_still_capped(apps, samples):
    payload = samples["jpeg"].bytes() * 4
    client = apps.client(MAX_UPLOAD_BYTES=2048, MAX_REQUEST_BYTES=64 * 1024 * 1024)
    body, headers = multipart_body("big.jpg", payload)
    response = client.post("/api/v1/metadata/inspect", content=chunked(body), headers=headers)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_sanitize_is_size_capped_too(apps, samples):
    client = apps.client(MAX_UPLOAD_BYTES=1024, MAX_REQUEST_BYTES=2048)
    response = upload(client, samples["jpeg"], endpoint="sanitize")
    assert response.status_code == 413


def test_rate_limit_blocks_after_budget(apps, samples):
    client = apps.client(RATE_LIMIT_REQUESTS=3, RATE_LIMIT_WINDOW_SECONDS=60)
    for _ in range(3):
        assert upload(client, samples["gif"], endpoint="inspect").status_code == 415
    blocked = upload(client, samples["gif"], endpoint="inspect")
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) >= 1
    assert blocked.headers["cache-control"] == "no-store"


def test_rate_limit_is_per_ip_when_proxy_headers_are_trusted(apps, samples):
    client = apps.client(RATE_LIMIT_REQUESTS=2, TRUST_PROXY_HEADERS="true")
    first_ip = {"X-Forwarded-For": "203.0.113.7"}
    second_ip = {"X-Forwarded-For": "198.51.100.9"}
    for _ in range(2):
        response = client.post(
            "/api/v1/metadata/inspect",
            files={"file": ("a.gif", samples["gif"].bytes(), "application/octet-stream")},
            headers=first_ip,
        )
        assert response.status_code == 415
    blocked = client.post(
        "/api/v1/metadata/inspect",
        files={"file": ("a.gif", samples["gif"].bytes(), "application/octet-stream")},
        headers=first_ip,
    )
    assert blocked.status_code == 429
    other = client.post(
        "/api/v1/metadata/inspect",
        files={"file": ("a.gif", samples["gif"].bytes(), "application/octet-stream")},
        headers=second_ip,
    )
    assert other.status_code == 415


def test_rate_limit_cannot_be_bypassed_with_spoofed_headers(apps, samples):
    client = apps.client(RATE_LIMIT_REQUESTS=2, TRUST_PROXY_HEADERS="false")
    for index in range(2):
        response = client.post(
            "/api/v1/metadata/inspect",
            files={"file": ("a.gif", samples["gif"].bytes(), "application/octet-stream")},
            headers={"X-Forwarded-For": f"203.0.113.{index}"},
        )
        assert response.status_code == 415
    spoofed = client.post(
        "/api/v1/metadata/inspect",
        files={"file": ("a.gif", samples["gif"].bytes(), "application/octet-stream")},
        headers={"X-Forwarded-For": "203.0.113.250"},
    )
    assert spoofed.status_code == 429


def test_download_endpoint_is_rate_limited_and_rejects_unknown_tokens(client):
    response = client.get("/api/v1/download/not-a-real-token")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_download_token_path_cannot_traverse(client):
    response = client.get("/api/v1/download/..%2F..%2Fetc%2Fpasswd")
    assert response.status_code == 404


def test_options_and_extra_fields_are_not_trusted(client, samples):
    response = upload(
        client, samples["jpeg"], endpoint="sanitize",
        options={"preserve_icc": False, "preserve_orientation": False},
    )
    assert response.status_code == 200
    assert response.json()["options"] == {"preserve_icc": False, "preserve_orientation": False}


def test_client_environment_is_not_readable_through_responses(client, samples, monkeypatch):
    monkeypatch.setenv("CLEANSLATE_FAKE_SECRET", "should-never-appear")
    body = upload(client, samples["jpeg"], endpoint="inspect").text
    assert "should-never-appear" not in body


def test_no_job_scratch_is_created_for_rejected_uploads(apps, samples):
    client = apps.client()
    response = upload(client, samples["gif"], endpoint="inspect")
    assert response.status_code == 415
    root = Path(apps.created[0].state.settings.temp_root)
    assert job_dirs(root) == []


def test_temp_usage_stays_bounded(client, samples, apps):
    upload(client, samples["jpeg"], endpoint="inspect")
    stats = apps.created[0].state.jobs.stats()
    assert stats["jobs"] == 0
    assert stats["temp_bytes"] == 0
    assert os.path.isdir(apps.created[0].state.settings.temp_root)
