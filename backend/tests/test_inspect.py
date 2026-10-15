"""POST /api/v1/metadata/inspect behaviour."""

from __future__ import annotations

from conftest import Sample, upload


def test_inspect_jpeg_returns_real_metadata(client, samples):
    sample = samples["jpeg"]
    response = upload(client, sample, endpoint="inspect")
    assert response.status_code == 200
    body = response.json()

    assert body["file"]["format"] == "jpeg"
    assert body["file"]["sha256"] == sample.sha256()
    assert body["file"]["size_bytes"] == len(sample.bytes())
    assert body["file"]["inspector_tags_read"] > 5

    keys = {entry["key"] for entry in body["metadata"]}
    assert "GPS:GPSLatitude" in keys
    assert "IFD0:Artist" in keys

    gps = next(entry for entry in body["metadata"] if entry["key"] == "GPS:GPSLatitude")
    assert gps["sensitivity"] == "high"
    assert body["sensitivity_counts"]["high"] >= 2

    # Container groups must not be reported as user metadata.
    assert not any(key.startswith(("System:", "File:", "ExifTool:")) for key in keys)


def test_inspect_reports_retention_and_notice(client, samples):
    body = upload(client, samples["png"], endpoint="inspect").json()
    assert body["retention"]["permanent_storage"] is False
    assert body["retention"]["server_side_processing"] is True
    assert any("Nothing was stored" in notice for notice in body["notices"])
    assert any("Do not upload highly sensitive files" in notice for notice in body["notices"])


def test_inspect_flags_trailing_data(client, samples):
    body = upload(client, samples["png_trailer"], endpoint="inspect").json()
    ids = {finding["id"] for finding in body["structural"]["findings"]}
    assert "png_trailing_data" in ids
    assert body["structural"]["counters"]["png_trailing_bytes"] > 0


def test_inspect_flags_docx_revision_history(client, samples):
    body = upload(client, samples["docx"], endpoint="inspect").json()
    ids = {finding["id"] for finding in body["structural"]["findings"]}
    assert "ooxml_revision_history" in ids
    assert "ooxml_docprops_present" in ids
    assert any("w:rsid" in item for item in body["unverified"])
    assert any("revision" in item.lower() for item in body["unverified"])


def test_inspect_reports_added_metadata_separately(client, samples):
    """ExifTool can add an XMP toolkit tag when reading; it must not be listed as user metadata."""
    body = upload(client, samples["jpeg"], endpoint="inspect").json()
    groups = {entry["group"] for entry in body["metadata"]}
    assert "ExifTool" not in groups


def test_inspect_rejects_unsupported_gif(client, samples):
    response = upload(client, samples["gif"], endpoint="inspect")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_file_type"


def test_inspect_rejects_random_bytes(client, samples):
    response = upload(client, samples["random"], endpoint="inspect")
    assert response.status_code == 415


def test_inspect_rejects_zip_that_is_not_office(client, samples):
    response = upload(client, samples["zip"], endpoint="inspect")
    assert response.status_code == 415


def test_inspect_rejects_extension_content_mismatch(client, samples):
    response = upload(client, samples["png"], filename="disguised.jpg", endpoint="inspect")
    assert response.status_code == 415
    assert "does not match its file extension" in response.json()["error"]["message"]


def test_inspect_rejects_empty_file(client, samples):
    response = upload(client, samples["empty"], endpoint="inspect")
    assert response.status_code == 415


def test_inspect_handles_truncated_jpeg_without_crashing(client, samples):
    """A truncated JPEG that ExifTool can still parse is reported with warnings, not invented data."""
    response = upload(client, samples["jpeg_truncated"], endpoint="inspect")
    assert response.status_code in (200, 415, 422)
    if response.status_code == 200:
        body = response.json()
        ids = {finding["id"] for finding in body["structural"]["findings"]}
        assert "jpeg_no_eoi" in ids
    else:
        assert response.json()["error"]["code"] in {"unprocessable_file", "unsupported_file_type"}


def test_inspect_requires_a_file(client):
    response = client.post("/api/v1/metadata/inspect")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_inspect_accepts_file_without_extension(client, samples):
    response = upload(client, samples["jpeg"], filename="no-extension", endpoint="inspect")
    assert response.status_code == 200


def test_inspect_mp4_metadata(client, samples):
    body = upload(client, samples["mp4"], endpoint="inspect").json()
    keys = {entry["key"] for entry in body["metadata"]}
    assert "QuickTime:CreateDate" in keys
    assert any(key.endswith("Title") for key in keys)


def test_inspect_does_not_expose_server_paths(client, samples):
    body = upload(client, samples["jpeg"], endpoint="inspect").json()
    serialized = str(body)
    assert "cleanslate-jobs" not in serialized
    assert "original." not in serialized
    assert "upload.part" not in serialized


def test_inspect_sample_is_unchanged_on_disk(client, samples):
    sample: Sample = samples["jpeg"]
    before = sample.sha256()
    upload(client, sample, endpoint="inspect")
    assert sample.sha256() == before
