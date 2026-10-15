"""Shared test fixtures.

Every sample file is built at test time with Pillow for the image formats and
with real ExifTool writes for the metadata, so the suite exercises genuine
metadata (GPS, author, dates, XMP, OOXML docProps, QuickTime user data) rather
than stubs. The MP4 fixture is a 216-byte container assembled in code, which
ExifTool reads and writes normally.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import Settings, load_settings  # noqa: E402
from app.main import create_app  # noqa: E402


# --------------------------------------------------------------------------- #
# Tool discovery (container: on PATH; Windows dev: .tools/)
# --------------------------------------------------------------------------- #


def _resolve_tool(name: str, env_var: str, extra: tuple[Path, ...] = ()) -> str | None:
    configured = os.environ.get(env_var)
    if configured and Path(configured).exists():
        return configured
    found = shutil.which(name)
    if found:
        return found
    candidates = (PROJECT_ROOT / ".tools" / f"{name}.exe", *extra)
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


EXIFTOOL = _resolve_tool("exiftool", "EXIFTOOL_PATH")
QPDF = _resolve_tool("qpdf", "QPDF_PATH", extra=(PROJECT_ROOT / ".tools" / "qpdf" / "qpdf.exe",))

requires_exiftool = pytest.mark.skipif(not EXIFTOOL, reason="ExifTool binary not available")
requires_qpdf = pytest.mark.skipif(not QPDF, reason="qpdf binary not available")


# --------------------------------------------------------------------------- #
# Settings / app factories
# --------------------------------------------------------------------------- #


def build_settings(tmp_path: Path, **overrides: object) -> Settings:
    """Build Settings through the real loader with a controlled environment."""
    env = {
        "ENVIRONMENT": "test",
        "SECRET_KEY": "unit-test-secret-key-not-for-production",
        "TEMP_ROOT": str(tmp_path / "jobs"),
        "ALLOWED_ORIGINS": "https://cleanslate.example.pages.dev",
        "RATE_LIMIT_REQUESTS": "10000",
        "RATE_LIMIT_WINDOW_SECONDS": "60",
        "EXPOSE_API_DOCS": "false",
        "TRUST_PROXY_HEADERS": "false",
        "ENABLE_HSTS": "true",
        "CLEANUP_INTERVAL_SECONDS": "5",
        "JOB_TTL_SECONDS": "300",
        "DOWNLOAD_TOKEN_TTL_SECONDS": "300",
        "MAX_UPLOAD_BYTES": str(25 * 1024 * 1024),
        "MAX_REQUEST_BYTES": str(25 * 1024 * 1024 + 1024 * 1024),
        "EXIFTOOL_PATH": EXIFTOOL or "exiftool",
        "QPDF_PATH": QPDF or "qpdf",
    }
    env.update({key: str(value) for key, value in overrides.items()})
    saved = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(env)
        return load_settings()
    finally:
        os.environ.clear()
        os.environ.update(saved)


class AppFactory:
    """Creates isolated apps (and TestClients) that share one scratch root."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.created: list = []
        self.clients: list[TestClient] = []

    def app(self, **overrides: object):
        settings = build_settings(self.tmp_path, **overrides)
        application = create_app(settings)
        self.created.append(application)
        return application

    def client(self, **overrides: object) -> TestClient:
        application = self.app(**overrides)
        client = TestClient(application, raise_server_exceptions=False)
        client.__enter__()
        self.clients.append(client)
        return client


@pytest.fixture
def apps(tmp_path: Path) -> AppFactory:
    factory = AppFactory(tmp_path)
    yield factory
    for client in factory.clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(apps: AppFactory) -> TestClient:
    return apps.client()


# --------------------------------------------------------------------------- #
# Sample file builders
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Sample:
    name: str
    path: Path
    format: str
    secret_markers: tuple[bytes, ...] = ()

    def bytes(self) -> bytes:
        return self.path.read_bytes()

    def sha256(self) -> str:
        return hashlib.sha256(self.bytes()).hexdigest()


def _exiftool_write(path: Path, args: list[str]) -> None:
    result = subprocess.run(
        [EXIFTOOL or "exiftool", "-overwrite_original", *args, str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"fixture ExifTool write failed: {result.stderr.strip()}")


def _build_ooxml(path: Path, body_part: str, body_xml: str, body_content_type: str) -> None:
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/{body_part}" ContentType="{body_content_type}"/>'
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        f'relationships/officeDocument" Target="{body_part}"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/'
        'relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        "</Relationships>"
    )
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/'
        'core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:creator>Secret Author</dc:creator>"
        "<cp:lastModifiedBy>Secret Editor</cp:lastModifiedBy>"
        "<dc:title>Secret Document Title</dc:title>"
        "</cp:coreProperties>"
    )
    app_props = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
        "<Application>SecretApp 1.0</Application>"
        "<Company>Secret Company Ltd</Company>"
        "</Properties>"
    )
    members = {
        "[Content_Types].xml": content_types,
        "_rels/.rels": rels,
        "docProps/core.xml": core,
        "docProps/app.xml": app_props,
        body_part: body_xml,
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)


def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + kind + payload


def _full_box(kind: bytes, version: int, flags: int, payload: bytes) -> bytes:
    return _box(kind, bytes([version]) + flags.to_bytes(3, "big") + payload)


def _build_mp4(path: Path, mdat_bytes: int = 64) -> None:
    """A tiny but structurally valid MP4 (ftyp + moov/mvhd + mdat)."""
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2mp41")
    mvhd_payload = (
        struct.pack(">II", 0, 0)
        + struct.pack(">I", 1000)
        + struct.pack(">I", 0)
        + struct.pack(">I", 0x00010000)
        + struct.pack(">H", 0x0100)
        + b"\x00\x00"
        + struct.pack(">II", 0, 0)
        + struct.pack(">9i", 0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000)
        + b"\x00" * 24
        + struct.pack(">I", 2)
    )
    moov = _box(b"moov", _full_box(b"mvhd", 0, 0, mvhd_payload))
    mdat = _box(b"mdat", b"\x00" * mdat_bytes)
    path.write_bytes(ftyp + moov + mdat)


def build_samples(root: Path) -> dict[str, Sample]:
    root.mkdir(parents=True, exist_ok=True)
    samples: dict[str, Sample] = {}

    # ---- JPEG with GPS, author, camera and orientation -------------------- #
    jpeg = root / "photo.jpg"
    Image.new("RGB", (64, 48), (12, 34, 56)).save(jpeg, "JPEG", quality=90)
    _exiftool_write(jpeg, [
        "-Artist=Alice Test", "-Software=FixtureWriter", "-Make=TestCam", "-Model=TestCam 1",
        "-Copyright=ACME", "-ImageDescription=Top secret description",
        "-DateTimeOriginal=2024:01:02 03:04:05",
        "-GPSLatitude=51.5074", "-GPSLatitudeRef=N", "-GPSLongitude=-0.1278", "-GPSLongitudeRef=W",
    ])
    samples["jpeg"] = Sample("photo.jpg", jpeg, "jpeg", (b"Top secret description",))

    rotated = root / "rotated.jpg"
    Image.new("RGB", (48, 64), (3, 4, 5)).save(rotated, "JPEG", quality=90)
    _exiftool_write(rotated, [
        "-Artist=Alice Test", "-Orientation#=6",
        "-GPSLatitude=51.5074", "-GPSLatitudeRef=N", "-GPSLongitude=-0.1278", "-GPSLongitudeRef=W",
    ])
    samples["jpeg_rotated"] = Sample("rotated.jpg", rotated, "jpeg")

    trailing = root / "trailing.jpg"
    trailing.write_bytes(jpeg.read_bytes() + b"JPEG_TRAILER_SECRET_MARKER")
    samples["jpeg_trailer"] = Sample(
        "trailing.jpg", trailing, "jpeg", (b"JPEG_TRAILER_SECRET_MARKER",)
    )

    truncated = root / "truncated.jpg"
    truncated.write_bytes(jpeg.read_bytes()[:200])
    samples["jpeg_truncated"] = Sample("truncated.jpg", truncated, "jpeg")

    # ---- PNG -------------------------------------------------------------- #
    png = root / "image.png"
    Image.new("RGB", (40, 30), (7, 8, 9)).save(png, "PNG")
    _exiftool_write(png, ["-Comment=PNG_COMMENT_SECRET", "-Description=PNG description",
                          "-Artist=PNG Artist", "-XMP:Creator=Alice Test"])
    samples["png"] = Sample("image.png", png, "png", (b"PNG_COMMENT_SECRET",))

    png_trailer = root / "trailing.png"
    png_trailer.write_bytes(png.read_bytes() + b"PNG_TRAILER_SECRET_MARKER")
    samples["png_trailer"] = Sample(
        "trailing.png", png_trailer, "png", (b"PNG_TRAILER_SECRET_MARKER",)
    )

    # ---- TIFF ------------------------------------------------------------- #
    tiff = root / "image.tif"
    Image.new("RGB", (40, 30), (10, 20, 30)).save(tiff, "TIFF")
    _exiftool_write(tiff, [
        "-Artist=Tiff Artist", "-Software=TiffSoft", "-Make=TiffMake", "-Model=TiffModel",
        "-Copyright=ACME", "-ImageDescription=TIFF_SECRET_DESCRIPTION",
        "-DateTimeOriginal=2024:01:02 03:04:05",
        "-GPSLatitude=1.5", "-GPSLatitudeRef=N", "-GPSLongitude=2.5", "-GPSLongitudeRef=E",
    ])
    samples["tiff"] = Sample("image.tif", tiff, "tiff", (b"TIFF_SECRET_DESCRIPTION",))

    # ---- WebP ------------------------------------------------------------- #
    webp = root / "image.webp"
    Image.new("RGB", (40, 30), (4, 5, 6)).save(webp, "WEBP")
    _exiftool_write(webp, ["-Artist=Webp Artist", "-Software=WebpSoft",
                           "-Comment=WEBP_COMMENT_SECRET"])
    samples["webp"] = Sample("image.webp", webp, "webp", (b"WEBP_COMMENT_SECRET",))

    # ---- PDF -------------------------------------------------------------- #
    pdf = root / "document.pdf"
    Image.new("RGB", (200, 200), (255, 255, 255)).save(pdf, "PDF")
    _exiftool_write(pdf, [
        "-Author=PDF_SECRET_AUTHOR", "-Title=PDF_SECRET_TITLE", "-Subject=PDF_SECRET_SUBJECT",
        "-Keywords=secret", "-Creator=SecretCreator",
    ])
    samples["pdf"] = Sample("document.pdf", pdf, "pdf", (b"PDF_SECRET_AUTHOR", b"PDF_SECRET_TITLE"))

    # ---- OOXML ------------------------------------------------------------ #
    docx = root / "notes.docx"
    _build_ooxml(
        docx,
        "word/document.xml",
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p w:rsidR="00AB12CD" w:rsidRDefault="00AB12CD">'
        "<w:r><w:t>Visible document content</w:t></w:r></w:p></w:body></w:document>",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    )
    samples["docx"] = Sample("notes.docx", docx, "docx", (b"Secret Author", b"Secret Company Ltd"))

    xlsx = root / "sheet.xlsx"
    _build_ooxml(
        xlsx,
        "xl/workbook.xml",
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheets><sheet name=\"Sheet1\" sheetId=\"1\"/></sheets></workbook>",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    )
    samples["xlsx"] = Sample("sheet.xlsx", xlsx, "xlsx", (b"Secret Author",))

    pptx = root / "deck.pptx"
    _build_ooxml(
        pptx,
        "ppt/presentation.xml",
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>',
        "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
    )
    samples["pptx"] = Sample("deck.pptx", pptx, "pptx", (b"Secret Author",))

    # ---- MP4 -------------------------------------------------------------- #
    mp4 = root / "video.mp4"
    _build_mp4(mp4)
    _exiftool_write(mp4, [
        "-Title=MP4_SECRET_TITLE", "-Comment=MP4 secret comment", "-Artist=Alice Test",
        "-CreateDate=2024:01:02 03:04:05", "-ModifyDate=2024:01:02 03:04:06",
        "-GPSCoordinates=-0.1278, 51.5074",
    ])
    samples["mp4"] = Sample("video.mp4", mp4, "mp4", (b"MP4_SECRET_TITLE", b"2024:01:02"))

    mp4_large = root / "video_large.mp4"
    _build_mp4(mp4_large, mdat_bytes=1_400_000)
    _exiftool_write(mp4_large, ["-Title=BIG_MP4_TITLE", "-CreateDate=2024:05:06 07:08:09"])
    samples["mp4_large"] = Sample("video_large.mp4", mp4_large, "mp4", (b"BIG_MP4_TITLE",))

    # ---- Unsupported / malformed ----------------------------------------- #
    gif = root / "animation.gif"
    Image.new("P", (16, 16)).save(gif, "GIF")
    samples["gif"] = Sample("animation.gif", gif, "gif")

    random_bytes = root / "random.bin"
    random_bytes.write_bytes(os.urandom(4096))
    samples["random"] = Sample("random.bin", random_bytes, "unknown")

    zip_not_office = root / "archive.zip"
    with zipfile.ZipFile(zip_not_office, "w") as archive:
        archive.writestr("readme.txt", "not an Office document")
    samples["zip"] = Sample("archive.zip", zip_not_office, "unknown")

    empty = root / "empty.jpg"
    empty.write_bytes(b"")
    samples["empty"] = Sample("empty.jpg", empty, "unknown")

    return samples


@pytest.fixture(scope="session")
def samples(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Sample]:
    if not EXIFTOOL:
        pytest.skip("ExifTool binary not available: cannot build metadata-bearing fixtures")
    root = tmp_path_factory.mktemp("samples")
    return build_samples(root)


# --------------------------------------------------------------------------- #
# Small helpers used across test modules
# --------------------------------------------------------------------------- #


def upload(client: TestClient, sample: Sample, *, filename: str | None = None, endpoint: str = "inspect",
           options: dict | None = None, extra_files: dict | None = None):
    files = {"file": (filename or sample.name, sample.bytes(), "application/octet-stream")}
    data = {}
    if options is not None:
        data["options"] = json.dumps(options)
    if extra_files:
        files.update(extra_files)
    return client.post(f"/api/v1/metadata/{endpoint}", files=files, data=data or None)


def fetch_download(client: TestClient, path: str):
    return client.get(path)


def job_dirs(settings_root: Path) -> list[str]:
    if not settings_root.exists():
        return []
    return sorted(entry.name for entry in settings_root.iterdir() if entry.name != "_toolhome")


def find_job(application, job_id: str):
    """Test-only access to the in-process job record (to assert real cleanup)."""
    return application.state.jobs._jobs.get(job_id)


def multipart_body(filename: str, payload: bytes, field: str = "file") -> tuple[bytes, dict[str, str]]:
    """Hand-built multipart body so a test can stream it without Content-Length."""
    boundary = "----cleanslate-test-boundary"
    body = (
        f"--{boundary}\r\n".encode()
        + f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode()
        + b"Content-Type: application/octet-stream\r\n\r\n"
        + payload
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def chunked(payload: bytes, size: int = 512):
    def generator():
        for offset in range(0, len(payload), size):
            yield payload[offset : offset + size]
    return generator()
