"""Sanitization of PDF, OOXML (DOCX/XLSX/PPTX) and MP4."""

from __future__ import annotations

import io
import subprocess
import zipfile

import pytest

from conftest import QPDF, Sample, _build_mp4, _exiftool_write, requires_qpdf, upload


def _download(client, body) -> bytes:
    response = client.get(body["download"]["path"])
    assert response.status_code == 200
    return response.content


def _qpdf_check(payload: bytes) -> tuple[int, str]:
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
        handle.write(payload)
        path = Path(handle.name)
    try:
        result = subprocess.run([QPDF, "--check", str(path)], capture_output=True, text=True)
        return result.returncode, result.stdout + result.stderr
    finally:
        path.unlink(missing_ok=True)


@requires_qpdf
def test_sanitize_pdf_uses_qpdf_and_removes_old_revisions(client, samples):
    body = upload(client, samples["pdf"], endpoint="sanitize").json()
    assert body["engine"] == "exiftool+qpdf"
    assert body["verification"]["revision_history_rewritten"] is True
    assert any("linearize" in note for note in body["engine_notes"])

    payload = _download(client, body)
    # The original metadata values are not recoverable anywhere in the file.
    assert b"PDF_SECRET_AUTHOR" not in payload
    assert b"PDF_SECRET_TITLE" not in payload
    # The PDF is still structurally valid according to qpdf itself.
    code, output = _qpdf_check(payload)
    assert code == 0, output


def test_sanitize_pdf_reports_unverified_categories(client, samples):
    body = upload(client, samples["pdf"], endpoint="sanitize").json()
    assert any("Embedded file attachments" in item for item in body["unverified"])
    assert any("JavaScript" in item for item in body["unverified"])


def test_sanitize_docx_removes_docprops_and_keeps_body(client, samples):
    original = samples["docx"]
    body = upload(client, original, endpoint="sanitize").json()
    assert body["engine"] == "ooxml-repackage"
    assert any("read-only" in note for note in body["engine_notes"])
    assert any("docProps/core.xml" in note for note in body["engine_notes"])

    payload = _download(client, body)
    assert b"Secret Author" not in payload
    assert b"Secret Company Ltd" not in payload

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        assert "word/document.xml" in names
        assert not any(name.startswith("docProps/") for name in names)
        # Document body is byte-for-byte identical.
        with zipfile.ZipFile(original.path) as original_archive:
            assert archive.read("word/document.xml") == original_archive.read("word/document.xml")
        # The package relationship file no longer points at docProps.
        rels = archive.read("_rels/.rels")
        assert b"docProps" not in rels


def test_sanitize_docx_flags_revision_history_as_unverified(client, samples):
    body = upload(client, samples["docx"], endpoint="sanitize").json()
    assert any("w:rsid" in item for item in body["unverified"])
    assert body["verification"]["metadata_removed_verified"] is True
    assert body["verification"]["revision_history_rewritten"] is None


def test_sanitize_xlsx_and_pptx(client, samples):
    for key in ("xlsx", "pptx"):
        body = upload(client, samples[key], endpoint="sanitize").json()
        payload = _download(client, body)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            assert not any(name.startswith("docProps/") for name in archive.namelist())
        assert b"Secret Author" not in payload


def test_sanitize_docx_compares_metadata(client, samples):
    body = upload(client, samples["docx"], endpoint="sanitize").json()
    removed = " ".join(entry["key"] for entry in body["comparison"]["removed"])
    assert "docProps" in removed or "Creator" in removed or "Author" in removed


def test_sanitize_mp4_removes_user_data_and_zeroes_dates(client, samples):
    body = upload(client, samples["mp4"], endpoint="sanitize").json()
    assert body["engine"] == "exiftool"

    payload = _download(client, body)
    assert b"MP4_SECRET_TITLE" not in payload
    assert b"2024:01:02" not in payload
    assert len(payload) > 100

    # Still a readable MP4 container with its media data intact.
    assert payload[4:8] == b"ftyp"
    assert b"moov" in payload
    assert b"mdat" in payload
    assert body["structural_after"]["counters"].get("mp4_has_moov") == 1


def test_sanitize_mp4_reports_unverified_stream_metadata(client, samples):
    body = upload(client, samples["mp4"], endpoint="sanitize").json()
    assert any("Timed/in-stream metadata" in item for item in body["unverified"])


def test_sanitize_truncated_video_fails_instead_of_returning_the_original(
    client, tmp_path
):
    """A truncated container is readable but cannot be rewritten.

    ExifTool still reads the metadata out of such a file (interrupted download,
    damaged card) but refuses to write it back, so nothing is removed. The API
    must refuse the request rather than return the untouched original as a
    "sanitized" download, and the refusal must not leak server paths.
    """
    path = tmp_path / "truncated.mp4"
    _build_mp4(path, mdat_bytes=200_000)
    _exiftool_write(path, [
        "-Title=TRUNCATED_SECRET", "-GPSCoordinates=-0.1278, 51.5074",
        "-CreateDate=2024:01:02 03:04:05",
    ])
    raw = path.read_bytes()
    path.write_bytes(raw[: len(raw) - 150_000])
    sample = Sample("truncated.mp4", path, "mp4", (b"TRUNCATED_SECRET",))
    # The metadata is still readable, which is exactly why this case is dangerous.
    assert b"TRUNCATED_SECRET" in sample.bytes()

    response = upload(client, sample, endpoint="sanitize")
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "unprocessable_file"
    assert "could not be sanitized" in body["error"]["message"]
    assert "download" not in body
    for forbidden in (
        "cleanslate-jobs", "sanitized.mp4", "truncated.mp4", "TRUNCATED_SECRET",
        "Traceback", "Backtrace", "C:/", "C:\\", "/tmp/",
    ):
        assert forbidden not in response.text


def test_sanitize_document_without_docprops_is_a_noop_for_properties(client, samples, tmp_path):
    """A package with no docProps must still be processed safely."""
    from conftest import Sample, _build_ooxml  # test-only helper reuse

    path = tmp_path / "plain.docx"
    _build_ooxml(
        path,
        "word/document.xml",
        '<?xml version="1.0"?><w:document xmlns:w="http://x"><w:body/></w:document>',
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    )
    with zipfile.ZipFile(path) as archive:
        payload_zip = {name: archive.read(name) for name in archive.namelist()}
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in payload_zip.items():
            if not name.startswith("docProps/"):
                archive.writestr(name, data)

    sample = Sample("plain.docx", path, "docx")
    body = upload(client, sample, endpoint="sanitize").json()
    assert any("none present" in note or "docProps" in note for note in body["engine_notes"])
    downloaded = _download(client, body)
    with zipfile.ZipFile(io.BytesIO(downloaded)) as archive:
        assert "word/document.xml" in archive.namelist()


def test_sanitize_rejects_archive_bomb(client, samples, tmp_path):
    """A highly compressible package that expands far beyond the upload is rejected."""
    from conftest import Sample

    bomb = tmp_path / "bomb.docx"
    payload = b"A" * (12 * 1024 * 1024)
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document xmlns:w='http://x'/>")
        archive.writestr("word/big.bin", payload)
    sample = Sample("bomb.docx", bomb, "docx")
    response = upload(client, sample, endpoint="sanitize")
    assert response.status_code == 415
    assert "archive bomb" in response.json()["error"]["message"]
