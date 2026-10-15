"""Sanitization of image formats, download handling and original-file preservation."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess

from PIL import Image

from conftest import EXIFTOOL, Sample, fetch_download, find_job, upload


def _inspect_bytes(payload: bytes) -> dict[str, str]:
    """Re-read a downloaded file with the real ExifTool, independently of the API."""
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as handle:
        handle.write(payload)
        path = Path(handle.name)
    try:
        result = subprocess.run(
            [EXIFTOOL, "-j", "-G1", "-s", "-a", "--", str(path)],
            capture_output=True,
            text=True,
        )
        data = json.loads(result.stdout or "[]")
        entry = data[0] if data else {}
        return {key: str(value) for key, value in entry.items()}
    finally:
        path.unlink(missing_ok=True)


def _download(client, body) -> bytes:
    response = fetch_download(client, body["download"]["path"])
    assert response.status_code == 200
    return response.content


def test_sanitize_jpeg_removes_gps_and_author(client, samples, apps):
    sample = samples["jpeg"]
    response = upload(client, sample, endpoint="sanitize")
    assert response.status_code == 200
    body = response.json()

    removed_keys = {entry["key"] for entry in body["comparison"]["removed"]}
    assert "GPS:GPSLatitude" in removed_keys
    assert "IFD0:Artist" in removed_keys
    assert body["comparison"]["sensitive_removed"] >= 3
    assert body["engine"] == "exiftool"

    # The download must be a real file whose hash matches the reported hash.
    payload = _download(client, body)
    assert hashlib.sha256(payload).hexdigest() == body["sanitized_file"]["sha256"]

    # Independent verification with ExifTool: metadata is really gone.
    tags = _inspect_bytes(payload)
    assert not any(key.startswith("GPS:") for key in tags)
    assert "IFD0:Artist" not in tags
    assert tags["File:FileType"] == "JPEG"

    # The sanitized image still decodes and keeps its dimensions.
    with Image.open(io.BytesIO(payload)) as image:
        assert image.size == (64, 48)


def test_sanitize_never_modifies_the_original(client, samples):
    sample: Sample = samples["jpeg"]
    before = sample.sha256()
    upload(client, sample, endpoint="sanitize")
    assert sample.sha256() == before


def test_sanitize_deletes_the_uploaded_original(client, samples, apps):
    body = upload(client, samples["jpeg"], endpoint="sanitize").json()
    application = apps.created[0]
    job = find_job(application, body["job_id"])
    assert job is not None
    names = sorted(entry.name for entry in job.path.iterdir())
    assert names == [f"sanitized{body['sanitized_file']['extension']}"]


def test_download_is_single_use_and_cleans_up(client, samples, apps):
    body = upload(client, samples["jpeg"], endpoint="sanitize").json()
    application = apps.created[0]
    job = find_job(application, body["job_id"])
    assert job is not None
    directory = job.path

    first = fetch_download(client, body["download"]["path"])
    assert first.status_code == 200
    assert first.headers["content-disposition"].startswith("attachment;")
    assert first.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in first.headers["content-security-policy"]

    # Scratch data is deleted once the download completes.
    assert not directory.exists()

    second = fetch_download(client, body["download"]["path"])
    assert second.status_code == 404
    assert second.json()["error"]["code"] == "not_found"


def test_download_headers_hide_client_filenames(client, samples):
    body = upload(client, samples["jpeg"], filename="my secret holiday photo.jpg",
                  endpoint="sanitize").json()
    response = fetch_download(client, body["download"]["path"])
    assert response.status_code == 200
    assert "secret" not in response.headers["content-disposition"]
    assert "my secret holiday photo" not in response.text[:200]


def test_sanitize_strips_png_trailing_data(client, samples):
    body = upload(client, samples["png_trailer"], endpoint="sanitize").json()
    payload = _download(client, body)
    assert b"PNG_TRAILER_SECRET_MARKER" not in payload
    findings_after = {finding["id"] for finding in body["structural_after"]["findings"]}
    assert "png_trailing_data" not in findings_after
    assert body["verification"]["structural_recheck"] in {"passed", "flagged"}


def test_sanitize_strips_jpeg_trailing_data(client, samples):
    body = upload(client, samples["jpeg_trailer"], endpoint="sanitize").json()
    payload = _download(client, body)
    assert b"JPEG_TRAILER_SECRET_MARKER" not in payload


def test_sanitize_png_removes_text_chunks(client, samples):
    body = upload(client, samples["png"], endpoint="sanitize").json()
    payload = _download(client, body)
    assert b"PNG_COMMENT_SECRET" not in payload
    tags = _inspect_bytes(payload)
    assert not any(key.startswith(("PNG:", "XMP")) and key != "PNG:BitDepth" for key in tags
                   if key not in {"PNG:BitDepth", "PNG:ColorType", "PNG:Compression", "PNG:Filter",
                                  "PNG:ImageHeight", "PNG:ImageWidth", "PNG:Interlace"})
    with Image.open(io.BytesIO(payload)) as image:
        assert image.size == (40, 30)


def test_sanitize_webp_keeps_the_image(client, samples):
    body = upload(client, samples["webp"], endpoint="sanitize").json()
    payload = _download(client, body)
    assert b"WEBP_COMMENT_SECRET" not in payload
    with Image.open(io.BytesIO(payload)) as image:
        assert image.size == (40, 30)
    tags = _inspect_bytes(payload)
    assert "IFD0:Artist" not in tags
    assert tags["RIFF:ImageWidth"] == "40"


def test_sanitize_tiff_removes_ifd0_metadata_but_keeps_structure(client, samples):
    body = upload(client, samples["tiff"], endpoint="sanitize").json()
    payload = _download(client, body)
    assert b"TIFF_SECRET_DESCRIPTION" not in payload

    tags = _inspect_bytes(payload)
    assert "IFD0:Artist" not in tags
    assert "IFD0:Make" not in tags
    assert not any(key.startswith("GPS:") for key in tags)
    # Structural image tags must survive, otherwise the image is broken.
    for structural in ("IFD0:ImageWidth", "IFD0:BitsPerSample", "IFD0:Compression"):
        assert structural in tags
    with Image.open(io.BytesIO(payload)) as image:
        assert image.size == (40, 30)


def test_orientation_is_preserved_by_default(client, samples):
    body = upload(client, samples["jpeg_rotated"], endpoint="sanitize").json()
    payload = _download(client, body)
    tags = _inspect_bytes(payload)
    assert tags.get("IFD0:Orientation") == "Rotate 90 CW"
    assert any("Orientation" in entry for entry in body["verification"]["retained_by_design"])
    assert not any(key.startswith("GPS:") for key in tags)


def test_orientation_can_be_removed_on_request(client, samples):
    body = upload(
        client, samples["jpeg_rotated"], endpoint="sanitize",
        options={"preserve_orientation": False, "preserve_icc": False},
    ).json()
    payload = _download(client, body)
    tags = _inspect_bytes(payload)
    assert "IFD0:Orientation" not in tags
    assert body["options"]["preserve_orientation"] is False


def test_no_icc_claim_when_no_profile_present(client, samples):
    body = upload(client, samples["jpeg"], endpoint="sanitize").json()
    assert not any("ICC colour profile preserved" in note for note in body["engine_notes"])
    assert "ICC colour profile" not in " ".join(body["verification"]["retained_by_design"])


def test_sanitize_rejects_unsupported_format(client, samples):
    response = upload(client, samples["gif"], endpoint="sanitize")
    assert response.status_code == 415


def test_sanitize_reports_unverified_categories(client, samples):
    body = upload(client, samples["jpeg"], endpoint="sanitize").json()
    assert body["unverified"]
    assert any("APP14" in item for item in body["unverified"])
    assert any("steganograph" in item.lower() for item in body["unverified"])


def test_sanitized_report_is_honest_about_reinspection(client, samples):
    body = upload(client, samples["jpeg"], endpoint="sanitize").json()
    verification = body["verification"]
    assert verification["metadata_removed_verified"] is True
    assert verification["original_upload_deleted"] is True
    assert verification["reinspection_tags_read"] >= 0
    assert "compared" in verification["method"]
    assert body["retention"]["single_use_download"] is True
    assert body["retention"]["permanent_storage"] is False
