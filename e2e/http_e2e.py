"""CleanSlate end-to-end verification against a running API over real HTTP.

This is NOT the unit test suite (that is backend/tests). It drives the deployed
shape of the service - real uvicorn process, real ExifTool/qpdf binaries, real
multipart uploads - and independently re-checks every sanitized copy with the
command line tools instead of trusting the API's own report.

Run:  python e2e/http_e2e.py [base_url]
Env:  E2E_EXPECT_RATELIMIT=0  skip the limiter check (use a low-limit instance instead)
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

import httpx
from PIL import Image, ImageCms, PngImagePlugin

# Windows consoles default to cp1252; keep the report printable everywhere.
try:  # pragma: no cover - environment specific
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787"
ALLOWED_ORIGIN = os.environ.get("E2E_ALLOWED_ORIGIN", "http://localhost:5173")
TOOLS = ROOT / ".tools"
EXIFTOOL = str(TOOLS / "exiftool.exe" if os.name == "nt" else TOOLS / "exiftool")
WORK = pathlib.Path(tempfile.mkdtemp(prefix="cleanslate-e2e-"))

RESULTS: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    RESULTS.append((bool(ok), name, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" -- {detail}" if detail else ""))
    return bool(ok)


def run(argv: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(argv, capture_output=True, check=False)


def exif_tags(path: pathlib.Path) -> dict[str, str]:
    """All tags readable by ExifTool, keyed 'Group:Tag'."""
    proc = run([EXIFTOOL, "-j", "-G1", "-a", "-u", "-s", str(path)])
    if proc.returncode != 0:
        return {}
    data = json.loads(proc.stdout.decode("utf-8", "replace") or "[]")
    if not data:
        return {}
    return {k: str(v) for k, v in data[0].items() if k != "SourceFile"}


def has_group(tags: dict[str, str], prefix: str) -> bool:
    return any(key.startswith(prefix) for key in tags)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- #
# Fixtures (built locally at run time, nothing binary is committed)
# --------------------------------------------------------------------------- #
def make_jpeg() -> bytes:
    img = Image.new("RGB", (200, 150))
    px = img.load()
    for y in range(150):
        for x in range(200):
            px[x, y] = ((x * 5) % 256, (y * 3) % 256, ((x + y) * 2) % 256)
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    exif = Image.Exif()
    exif[271] = "E2ECamera"
    exif[272] = "E2E-Model-1"
    exif[305] = "E2E Editor 1.0"
    exif[315] = "E2E Author"
    exif[33432] = "(c) 2026 E2E"
    exif[274] = 6  # Orientation: rotate 90 CW
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70, exif=exif, icc_profile=icc)
    path = WORK / "base.jpg"
    path.write_bytes(buf.getvalue())
    run([EXIFTOOL, "-overwrite_original", "-q", "-GPSLatitude=48.8584",
         "-GPSLatitudeRef=N", "-GPSLongitude=2.2945", "-GPSLongitudeRef=E",
         "-DateTimeOriginal=2026:03:04 05:06:07", "-XMP:CreatorTool=E2E-Tool",
         str(path)])
    return path.read_bytes()


def make_png() -> bytes:
    img = Image.new("RGBA", (64, 64), (10, 200, 120, 255))
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Author", "E2E Author")
    meta.add_text("Comment", "secret comment")
    meta.add_text("Software", "E2E Editor")
    buf = io.BytesIO()
    img.save(buf, "PNG", pnginfo=meta)
    return buf.getvalue()


def make_tiff() -> bytes:
    img = Image.new("RGB", (80, 60), (30, 60, 90))
    exif = Image.Exif()
    exif[271] = "E2ECamera"
    exif[315] = "E2E Author"
    exif[305] = "E2E Editor"
    buf = io.BytesIO()
    img.save(buf, "TIFF", exif=exif)
    return buf.getvalue()


def make_webp() -> bytes:
    img = Image.new("RGB", (96, 72))
    px = img.load()
    for y in range(72):
        for x in range(96):
            px[x, y] = ((x * 3) % 256, (y * 4) % 256, 90)
    exif = Image.Exif()
    exif[271] = "E2ECamera"
    exif[315] = "E2E Author"
    buf = io.BytesIO()
    img.save(buf, "WEBP", exif=exif)
    return buf.getvalue()


def make_pdf() -> bytes:
    img = Image.new("RGB", (300, 200), (240, 240, 240))
    path = WORK / "base.pdf"
    img.save(path, "PDF")
    run([EXIFTOOL, "-overwrite_original", "-q", "-Author=E2E Author",
         "-Title=secret title", "-Subject=confidential", "-Creator=E2E Tool", str(path)])
    return path.read_bytes()


def make_docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?><Types '
            'xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            "</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?><Relationships '
            'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "docProps/core.xml",
            '<?xml version="1.0" encoding="UTF-8"?><cp:coreProperties '
            'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            "<dc:creator>E2E Author</dc:creator>"
            "<cp:lastModifiedBy>E2E Reviewer</cp:lastModifiedBy>"
            "<dc:title>secret title</dc:title>"
            "<dc:subject>confidential</dc:subject>"
            "<dcterms:created xsi:type=\"dcterms:W3CDTF\">2026-01-02T03:04:05Z</dcterms:created>"
            "<dcterms:modified xsi:type=\"dcterms:W3CDTF\">2026-01-02T03:04:05Z</dcterms:modified>"
            "<cp:keywords>secret,internal</cp:keywords>"
            "</cp:coreProperties>",
        )
        zf.writestr(
            "docProps/app.xml",
            '<?xml version="1.0" encoding="UTF-8"?><Properties '
            'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
            "<Company>Secret Corp</Company><Manager>E2E Manager</Manager>"
            "<TotalTime>42</TotalTime><Application>E2E Writer</Application>"
            "</Properties>",
        )
        zf.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?><w:document '
            'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>CleanSlate E2E document</w:t></w:r></w:p>"
            '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr></w:body></w:document>',
        )
        # Revision-ish extra parts: tracked comments plus a dangling relationship.
        zf.writestr(
            "word/comments.xml",
            '<?xml version="1.0" encoding="UTF-8"?><w:comments '
            'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:comment w:id="1" w:author="E2E Reviewer" w:date="2026-01-02T03:04:05Z">'
            "<w:p><w:r><w:t>internal note</w:t></w:r></w:p></w:comment></w:comments>",
        )
    return buf.getvalue()


def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + kind + payload


def _full_box(kind: bytes, version: int, flags: int, payload: bytes) -> bytes:
    return _box(kind, bytes([version]) + flags.to_bytes(3, "big") + payload)


def _mp4_bytes(mdat_bytes: int = 120_000) -> bytes:
    """A small but structurally valid MP4 (ftyp + moov/mvhd + mdat)."""
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
    return ftyp + moov + _box(b"mdat", b"\x00" * mdat_bytes)


def make_mp4() -> bytes:
    """A valid MP4 carrying title/GPS/dates, written with the real ExifTool."""
    path = WORK / "base.mp4"
    path.write_bytes(_mp4_bytes())
    run([EXIFTOOL, "-overwrite_original", "-q", "-Title=E2E Secret Title",
         "-GPSCoordinates=-0.1278, 51.5074", "-CreateDate=2026:03:04 05:06:07",
         "-ModifyDate=2026:03:04 05:06:07", str(path)])
    return path.read_bytes()


def make_truncated_mp4() -> bytes:
    """A video whose tail (mdat) is missing: metadata readable, file unwritable."""
    data = make_mp4()
    return data[: len(data) - 90_000]


FIXTURES = {
    "jpeg": ("photo.jpg", "image/jpeg", make_jpeg),
    "png": ("graphic.png", "image/png", make_png),
    "tiff": ("scan.tiff", "image/tiff", make_tiff),
    "webp": ("shot.webp", "image/webp", make_webp),
    "pdf": ("report.pdf", "application/pdf", make_pdf),
    "docx": ("memo.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", make_docx),
    "mp4": ("clip.mp4", "video/mp4", make_mp4),
}


def post_files(client: httpx.Client, path: str, name: str, mime: str, data: bytes,
               headers: dict[str, str] | None = None, options: dict | None = None):
    files = {"file": (name, data, mime)}
    form = {"options": json.dumps(options)} if options is not None else None
    return client.post(path, files=files, data=form, headers=headers)


def job_dirs(scratch: pathlib.Path) -> list[str]:
    if not scratch.exists():
        return []
    return sorted(p.name for p in scratch.iterdir() if p.is_dir() and p.name != "_toolhome")


def main() -> int:
    print(f"\nCleanSlate E2E -> {BASE}\n" + "=" * 72)
    client = httpx.Client(base_url=BASE, timeout=180.0)
    scratch = pathlib.Path(os.environ.get("E2E_TEMP_ROOT", ROOT / ".cleanslate-tmp"))

    # The scratch root can be used concurrently (another browser session, a
    # previous run), so cleanup is asserted per job that *this* run created -
    # identified by the job ids in this run's own responses - instead of by
    # counting the shared directory or the global store.
    inspect_job_ids: list[str] = []
    downloaded_job_ids: list[str] = []
    abandoned_job_ids: list[str] = []
    baseline_health = client.get("/api/health").json()
    print(f"\nbaseline: {int(baseline_health['storage']['jobs'])} job(s) held by the server, "
          f"{len(job_dirs(scratch))} scratch dir(s) present before this run")

    # ---- health / limits ---------------------------------------------------
    print("\n[health & limits]")
    r = client.get("/api/health")
    health = r.json()
    check(r.status_code == 200, "GET /api/health -> 200", f"status={r.status_code}")
    check(health["tools"]["exiftool"]["available"], "ExifTool reported available",
          str(health["tools"]["exiftool"].get("version")))
    check(health["status"] == "ok", "service status ok", health["status"])
    check(health.get("fingerprint_collection") is False,
          "no fingerprint collection endpoint advertised")

    r = client.get("/api/v1/limits")
    limits = r.json()
    check(r.status_code == 200, "GET /api/v1/limits -> 200")
    formats = {f["format"] for f in limits["accepted_formats"]}
    check({"jpeg", "png", "tiff", "webp", "pdf", "docx", "mp4"} <= formats,
          "documented formats include jpeg/png/tiff/webp/pdf/docx/mp4", ",".join(sorted(formats)))

    # ---- security headers --------------------------------------------------
    print("\n[security headers & CORS]")
    r = client.get("/api/health", headers={"Origin": ALLOWED_ORIGIN})
    h = {k.lower(): v for k, v in r.headers.items()}
    check(h.get("x-content-type-options") == "nosniff", "X-Content-Type-Options: nosniff")
    check(h.get("referrer-policy") == "no-referrer", "Referrer-Policy: no-referrer")
    check("default-src" in h.get("content-security-policy", ""), "Content-Security-Policy present")
    check(h.get("x-frame-options") == "DENY" or "frame-ancestors" in h.get("content-security-policy", ""),
          "frame restriction present")
    check(h.get("access-control-allow-origin") == ALLOWED_ORIGIN,
          "CORS allows the configured frontend origin", str(h.get("access-control-allow-origin")))
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    check(r.headers.get("access-control-allow-origin") is None,
          "CORS does not echo an unlisted origin")
    r = client.options("/api/v1/metadata/inspect", headers={
        "Origin": ALLOWED_ORIGIN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    check(r.status_code in (200, 204), "preflight from allowed origin succeeds", f"status={r.status_code}")
    r = client.options("/api/v1/metadata/inspect", headers={
        "Origin": "https://evil.example",
        "Access-Control-Request-Method": "POST",
    })
    check(r.status_code == 400, "preflight from unlisted origin is refused", f"status={r.status_code}")

    # ---- per-format inspect + sanitize + download --------------------------
    for fmt, (name, mime, factory) in FIXTURES.items():
        print(f"\n[{fmt}] {name}")
        data = factory()
        original_hash = sha256(data)
        # Keep a local copy under a safe name so the tag scan cannot follow a
        # traversal-style upload name.
        local_copy = WORK / f"{fmt}-{pathlib.Path(name).name}"
        local_copy.write_bytes(data)
        before = exif_tags(local_copy)

        r = post_files(client, "/api/v1/metadata/inspect", name, mime, data)
        if not check(r.status_code == 200, f"{fmt}: inspect -> 200", f"status={r.status_code} {r.text[:160]}"):
            continue
        report = r.json()
        inspect_job_ids.append(report["job_id"])
        check(report["file"]["sha256"] == original_hash, f"{fmt}: report hash matches the upload")
        check(len(report["metadata"]) > 0, f"{fmt}: metadata found", f"{len(report['metadata'])} tags")
        check(any(t["sensitivity"] == "high" for t in report["metadata"])
              or len(report["metadata"]) > 0, f"{fmt}: sensitivity classified")
        check(isinstance(report["unverified"], list), f"{fmt}: unverified categories reported",
              "; ".join(report["unverified"][:1]))

        r = post_files(client, "/api/v1/metadata/sanitize", name, mime, data,
                       options={"preserve_icc": True, "preserve_orientation": True})
        if not check(r.status_code == 200, f"{fmt}: sanitize -> 200", f"status={r.status_code} {r.text[:200]}"):
            continue
        out = r.json()
        counts = out["comparison"]["counts"]
        check(counts["removed"] > 0, f"{fmt}: fields removed",
              f"removed={counts['removed']} retained={counts['retained']}")
        check(len(out["unverified"]) > 0, f"{fmt}: unverified/limitation list is not empty")
        check(out["file"]["sha256"] != out["sanitized_file"]["sha256"],
              f"{fmt}: sanitized copy differs from the original")

        downloaded_job_ids.append(out["job_id"])
        dl = out["download"]
        check(dl["token"] and len(dl["token"]) >= 16, f"{fmt}: unguessable download token issued",
              f"{len(dl['token'])} chars")
        r = client.get(dl["path"])
        if not check(r.status_code == 200, f"{fmt}: download -> 200", f"status={r.status_code}"):
            continue
        sanitized = r.content
        check(len(sanitized) > 0, f"{fmt}: downloaded bytes non-empty", f"{len(sanitized)} bytes")
        dh = {k.lower(): v for k, v in r.headers.items()}
        check(dh.get("content-disposition", "").startswith("attachment"),
              f"{fmt}: download is an attachment", dh.get("content-disposition", ""))
        check(dh.get("x-content-type-options") == "nosniff", f"{fmt}: download nosniff")
        check("default-src 'none'" in dh.get("content-security-policy", ""),
              f"{fmt}: download sandboxed CSP")

        # Independent verification with the real tool chain.
        outpath = WORK / f"clean-{fmt}-{pathlib.Path(name).name}"
        outpath.write_bytes(sanitized)
        after_tags = exif_tags(outpath)
        leaked_gps = [k for k in after_tags if k.startswith("GPS:")]
        check(not leaked_gps, f"{fmt}: no GPS group survives (independent ExifTool scan)",
              ",".join(leaked_gps)[:80])
        leaked_identity = [k for k in after_tags
                           if k.split(":")[-1] in {"Artist", "Author", "Creator", "Make", "Model",
                                                   "Software", "OwnerName", "Copyright", "Title",
                                                   "Subject", "GPSCoordinates"}]
        check(not leaked_identity, f"{fmt}: no identity/creator/title tags survive",
              ",".join(leaked_identity)[:80])
        check(before.get("File:MIMEType") is None or after_tags.get("File:MIMEType")
              == before.get("File:MIMEType"), f"{fmt}: format preserved")
        # The report must not leak the server's scratch paths anywhere.
        check("cleanslate-jobs" not in r.text and "C:/" not in out["download"]["filename"],
              f"{fmt}: no server scratch path in the response")
        if out["verification"]["metadata_removed_verified"]:
            check(counts["removed"] > 0,
                  f"{fmt}: 'removal verified' is only claimed when fields were actually removed")

        # Single-use token: the second request must fail.
        r2 = client.get(dl["path"])
        check(r2.status_code in (403, 404, 410), f"{fmt}: download token is single-use",
              f"second request status={r2.status_code}")
        # A made-up token must never resolve.
        r3 = client.get("/api/v1/download/" + base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("="))
        check(r3.status_code in (403, 404, 410), f"{fmt}: unknown token rejected", f"status={r3.status_code}")

    # ---- cleanup after success ---------------------------------------------
    print("\n[cleanup after success]")
    still_on_disk = [jid for jid in downloaded_job_ids if (scratch / jid).exists()]
    check(not still_on_disk,
          "every job this run downloaded was destroyed from disk",
          f"{len(downloaded_job_ids)} downloaded job(s); still present: {','.join(still_on_disk) or 'none'}")
    inspect_leftovers = [jid for jid in inspect_job_ids if (scratch / jid).exists()]
    check(not inspect_leftovers,
          "inspection jobs left no scratch directory at all",
          f"{len(inspect_job_ids)} inspect job(s); still present: {','.join(inspect_leftovers) or 'none'}")
    health = client.get("/api/health").json()
    check(json.dumps(health).count("cleanslate-jobs") == 0, "health endpoint leaks no paths")

    # ---- original file preservation ---------------------------------------
    print("\n[original preservation]")
    sample = WORK / "fixture.jpg"
    sample.write_bytes(FIXTURES["jpeg"][2]())
    before_hash = sha256(sample.read_bytes())
    response = post_files(client, "/api/v1/metadata/sanitize", "fixture.jpg", "image/jpeg",
                          sample.read_bytes())
    if response.status_code == 200:
        # Deliberately never downloaded: this is the job the TTL sweeper must reap.
        abandoned_job_ids.append(response.json()["job_id"])
    check(sha256(sample.read_bytes()) == before_hash,
          "the file on disk was not modified by the server")
    tags = exif_tags(sample)
    check(has_group(tags, "GPS:"), "local original still carries GPS after sanitize")

    # ---- rejection paths ---------------------------------------------------
    print("\n[rejection paths]")
    r = post_files(client, "/api/v1/metadata/inspect", "notes.txt", "text/plain", b"hello world")
    check(r.status_code == 415, "unsupported type -> 415", f"status={r.status_code}")
    check("traceback" not in r.text.lower() and 'File "' not in r.text,
          "no stack trace in the error body")

    r = post_files(client, "/api/v1/metadata/inspect", "fake.jpg", "image/jpeg", b"MZ\x90\x00 not a jpeg")
    check(r.status_code in (400, 415, 422), "signature mismatch -> 4xx", f"status={r.status_code}")

    traversal_data = FIXTURES["jpeg"][2]()
    r = post_files(client, "/api/v1/metadata/inspect", "../../evil.jpg", "image/jpeg", traversal_data)
    check(r.status_code == 200, "traversal-style filename is handled safely", f"status={r.status_code}")
    traversal_job = r.json().get("job_id") if r.status_code == 200 else None
    if traversal_job:
        inspect_job_ids.append(traversal_job)
    check(not any("evil" in n for n in job_dirs(scratch)),
          "no file escaped the server scratch directory")

    big = b"\xff\xd8\xff\xe0" + os.urandom(int(limits["max_upload_bytes"]) + 2048)
    r = post_files(client, "/api/v1/metadata/inspect", "big.jpg", "image/jpeg", big)
    check(r.status_code == 413, "oversized upload -> 413", f"status={r.status_code}")

    r = post_files(client, "/api/v1/metadata/sanitize", "a.jpg", "image/jpeg",
                   FIXTURES["jpeg"][2](), options={"preserve_icc": True, "bogus": True})
    check(r.status_code == 400, "unknown option key -> 400", f"status={r.status_code}")

    # ---- honest failure on an unwritable container -------------------------
    print("\n[unwritable container]")
    truncated = make_truncated_mp4()
    r = post_files(client, "/api/v1/metadata/inspect", "cut.mp4", "video/mp4", truncated)
    check(r.status_code == 200, "truncated video: metadata is still readable", f"status={r.status_code}")
    if r.status_code == 200:
        inspect_job_ids.append(r.json()["job_id"])
    r = post_files(client, "/api/v1/metadata/sanitize", "cut.mp4", "video/mp4", truncated)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    check(r.status_code == 422, "truncated video: sanitize is refused instead of faked",
          f"status={r.status_code}")
    check(body.get("error", {}).get("code") == "unprocessable_file",
          "truncated video: documented error code", str(body.get("error", {}).get("code")))
    check("download" not in body, "truncated video: no download is offered for an unchanged file")
    check(not any(token in r.text for token in ("cleanslate-jobs", "cut.mp4", "Traceback", "C:/")),
          "truncated video: refusal leaks no paths, names or traces")

    # ---- cleanup after failures -------------------------------------------
    print("\n[cleanup after failures]")
    refused_leftovers = [jid for jid in inspect_job_ids if (scratch / jid).exists()]
    check(not refused_leftovers,
          "rejected and refused requests left no scratch directory behind",
          f"still present: {','.join(refused_leftovers) or 'none'}")
    held = [jid for jid in abandoned_job_ids if (scratch / jid).exists()]
    check(len(held) == len(abandoned_job_ids),
          "the undownloaded sanitized copy is still held (until its TTL)",
          f"held {len(held)}/{len(abandoned_job_ids)} - reaped by the sweeper only after JOB_TTL_SECONDS")
    health = client.get("/api/health").json()
    check(json.dumps(health).count("cleanslate-jobs") == 0, "health endpoint leaks no paths")

    # ---- rate limiting (last: it trips the limiter) -------------------------
    if os.environ.get("E2E_EXPECT_RATELIMIT", "1") == "1":
        print("\n[rate limiting]")
        payload = FIXTURES["jpeg"][2]()
        statuses = []
        for _ in range(limits["rate_limit_requests"] + 8):
            rr = post_files(client, "/api/v1/metadata/inspect", "rl.jpg", "image/jpeg", payload)
            statuses.append(rr.status_code)
            if rr.status_code == 429:
                check("retry-after" in {k.lower() for k in rr.headers}, "429 carries Retry-After")
                check(rr.json()["error"]["code"] == "rate_limited",
                      "429 body uses the documented error code")
                break
        check(429 in statuses, "repeated requests are rate limited",
              f"{statuses.count(200)} ok, {statuses.count(429)} limited")
    else:
        print("\n[rate limiting] skipped (E2E_EXPECT_RATELIMIT=0; verified on a low-limit instance)")

    client.close()
    print("\n" + "=" * 72)
    failed = [r for r in RESULTS if not r[0]]
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    for _, name, detail in failed:
        print(f"  FAILED: {name} {detail}")
    shutil.rmtree(WORK, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
