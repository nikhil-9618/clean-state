"""Health, limits, security headers, CORS and generic error responses."""

from __future__ import annotations

import pytest

from app.service import PROCESSING_NOTICE

REQUIRED_NOTICE = (
    "Your file will be processed by the CleanSlate server. Temporary processing files are deleted "
    "according to the configured cleanup policy. Do not upload highly sensitive files unless you "
    "trust the hosting provider and understand its infrastructure access."
)


def test_health_reports_tool_availability(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "cleanslate-api"
    assert body["fingerprint_collection"] is False
    assert body["tools"]["exiftool"]["available"] is True
    assert body["tools"]["exiftool"]["version"]
    assert body["accepts_uploads"] is True
    assert body["storage"]["jobs"] == 0
    # No secrets or configuration leaks in the health payload.
    serialized = response.text.lower()
    for forbidden in ("secret_key", "unit-test-secret", "token"):
        assert forbidden not in serialized


def test_limits_expose_live_values_and_formats(client, apps):
    settings = apps.created[0].state.settings
    body = client.get("/api/v1/limits").json()
    assert body["max_upload_bytes"] == settings.max_upload_bytes
    assert body["max_upload_mib"] == pytest.approx(settings.max_upload_bytes / (1024 * 1024), rel=0.01)
    assert body["server_side_processing"] is True
    assert body["fingerprint_collection"] is False
    formats = {item["format"] for item in body["accepted_formats"]}
    assert {"jpeg", "png", "tiff", "webp", "pdf", "docx", "xlsx", "pptx", "mp4"} <= formats
    assert body["processing_notice"] == REQUIRED_NOTICE
    assert PROCESSING_NOTICE == REQUIRED_NOTICE


def test_security_headers_on_api_responses(client):
    response = client.get("/api/health")
    headers = response.headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert headers["cache-control"] == "no-store"
    assert headers["cross-origin-resource-policy"] == "same-origin"
    assert headers["permissions-policy"]
    assert headers["strict-transport-security"].startswith("max-age=")
    assert headers.get("x-request-id")
    assert "server" not in {key.lower() for key in headers}


def test_hsts_can_be_disabled(apps):
    client = apps.client(ENABLE_HSTS="false")
    response = client.get("/api/health")
    assert "strict-transport-security" not in {key.lower() for key in response.headers}


def test_cors_allows_only_configured_origin(client):
    allowed = client.get(
        "/api/health", headers={"Origin": "https://cleanslate.example.pages.dev"}
    )
    assert allowed.headers.get("access-control-allow-origin") == "https://cleanslate.example.pages.dev"
    assert "access-control-allow-credentials" not in {k.lower() for k in allowed.headers}

    blocked = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert blocked.status_code == 200
    assert "access-control-allow-origin" not in {k.lower() for k in blocked.headers}


def test_cors_preflight(client):
    response = client.options(
        "/api/v1/metadata/inspect",
        headers={
            "Origin": "https://cleanslate.example.pages.dev",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://cleanslate.example.pages.dev"
    assert "POST" in response.headers["access-control-allow-methods"]

    rejected = client.options(
        "/api/v1/metadata/inspect",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in {k.lower() for k in rejected.headers}


def test_cors_is_not_authentication(client, samples):
    """The API is public by design: requests without an Origin header work."""
    from conftest import upload

    response = upload(client, samples["jpeg"], endpoint="inspect")
    assert response.status_code == 200


def test_unknown_route_is_generic_404(client):
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["request_id"]
    assert "traceback" not in response.text.lower()


def test_wrong_method_is_generic(client):
    response = client.get("/api/v1/metadata/inspect")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_invalid_options_field_is_generic_400(client, samples):
    from conftest import upload

    response = upload(client, samples["jpeg"], endpoint="sanitize", options={"unknown_key": True})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert "unknown_key" not in response.text
