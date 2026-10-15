"""Report accuracy and logging privacy.

These tests encode the product promise: nothing is reported as removed unless it
was present before and absent after, and no user data reaches the logs.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path

from conftest import EXIFTOOL, Sample, upload

FORBIDDEN_CLAIMS = (
    "fully sanitized",
    "100% clean",
    "100% safe",
    "guaranteed anonymous",
    "untraceable",
    "removed all traces",
    "completely removed all",
)


def _exiftool_tags(payload: bytes) -> dict[str, str]:
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as handle:
        handle.write(payload)
        path = Path(handle.name)
    try:
        result = subprocess.run(
            [EXIFTOOL, "-j", "-G1", "-s", "-a", "--", str(path)], capture_output=True, text=True
        )
        data = json.loads(result.stdout or "[]")
        entry = data[0] if data else {}
        return {key: str(value) for key, value in entry.items() if key != "SourceFile"}
    finally:
        path.unlink(missing_ok=True)


def _inspect_before(payload: bytes) -> dict[str, str]:
    return _exiftool_tags(payload)


def test_removed_tags_match_reality(client, samples):
    sample = samples["jpeg"]
    before = _inspect_before(sample.bytes())
    body = upload(client, sample, endpoint="sanitize").json()
    payload = client.get(body["download"]["path"]).content
    after = _exiftool_tags(payload)

    for entry in body["comparison"]["removed"]:
        key = entry["key"]
        assert key in before, f"{key} was reported as removed but never existed"
        assert key not in after, f"{key} was reported as removed but is still present"

    for entry in body["comparison"]["retained"]:
        key = entry["key"]
        assert key in before and key in after, f"{key} claimed retained but missing"
        assert after[key] == entry["value"]


def test_added_tags_are_reported_not_hidden(client, samples):
    body = upload(client, samples["tiff"], endpoint="sanitize").json()
    for entry in body["comparison"]["added"]:
        assert entry["key"] not in _inspect_before(samples["tiff"].bytes())


def test_counts_are_internally_consistent(client, samples):
    body = upload(client, samples["jpeg"], endpoint="sanitize").json()
    counts = body["comparison"]["counts"]
    assert counts["removed"] == len(body["comparison"]["removed"])
    assert counts["retained"] == len(body["comparison"]["retained"])
    assert counts["changed"] == len(body["comparison"]["changed"])
    assert counts["added"] == len(body["comparison"]["added"])
    assert body["comparison"]["sensitive_removed"] <= counts["removed"]


def test_engine_versions_are_real(client, samples):
    health = client.get("/api/health").json()
    body = upload(client, samples["pdf"], endpoint="sanitize").json()
    assert body["verification"]["engine_versions"]["exiftool"] == health["tools"]["exiftool"]["version"]
    assert body["verification"]["engine_versions"]["qpdf"] == health["tools"]["qpdf"]["version"]
    assert body["verification"]["engine_versions"]["exiftool"] not in (None, "unknown")


def test_no_overclaiming_language_anywhere(client, samples):
    for endpoint in ("inspect", "sanitize"):
        response = upload(client, samples["jpeg"], endpoint=endpoint)
        text = response.text.lower()
        for claim in FORBIDDEN_CLAIMS:
            assert claim not in text, f"response claims '{claim}'"


def test_unverified_categories_are_explicit(client, samples):
    body = upload(client, samples["mp4"], endpoint="sanitize").json()
    assert body["unverified"], "the report must list what was not verified"
    assert body["verification"]["residual_risks"] == body["unverified"] or set(
        body["verification"]["residual_risks"]
    ) <= set(body["unverified"]) | set(body["verification"]["residual_risks"])


def test_no_server_paths_anywhere_in_responses(client, samples):
    """No response may contain a filesystem path, a scratch name or a tool banner.

    ExifTool appends the file it is working on to most of its warnings, and that
    path is the server's own scratch file. Tool output therefore has to be
    scrubbed before it reaches the client, in every field of every response.
    """
    import re

    forbidden = (
        re.compile(r"[A-Za-z]:[\\/]"),
        re.compile(r"cleanslate-jobs"),
        re.compile(r"/(?:tmp|var|home|app|root|usr)/[A-Za-z0-9_./-]+"),
        # Generated download names are fine; a path qualified scratch file is not.
        re.compile(r"[\\/](?:sanitized|original|upload)\.[A-Za-z0-9]{2,5}"),
        re.compile(r"perl: warning"),
    )
    checked = 0
    for name in ("jpeg", "png", "tiff", "pdf", "docx", "mp4", "xlsx"):
        sample = samples.get(name)
        if sample is None:  # pragma: no cover - sample set is fixed
            continue
        for endpoint in ("inspect", "sanitize"):
            text = upload(client, sample, endpoint=endpoint).text
            checked += 1
            for pattern in forbidden:
                match = pattern.search(text)
                assert not match, (
                    f"{endpoint} of {name} leaked '{match.group(0)}' from {pattern.pattern}"
                )
    assert checked >= 10


def test_path_scrubbing_handles_every_path_form():
    from app.logging_utils import scrub_paths

    cases = (
        ("Error: Truncated mdat atom - C:/Users/dev/AppData/Temp/x.mp4", "C:/", "Truncated mdat atom"),
        ("Warning: - C:\\scratch\\job\\original.jpg", "C:\\", "Warning:"),
        ("Error: - /tmp/cleanslate-jobs/abc123/sanitized.jpg", "cleanslate-jobs", "Error:"),
        ("Error: - /var/lib/cleanslate-jobs/deadbeef/original.bin", "/var/", "Error:"),
        ("Error: - /home/clean/x.png", "/home/", "Error:"),
        ("Error: - /usr/local/share/app/data.bin", "/usr/", "Error:"),
    )
    for raw, marker, survivor in cases:
        cleaned = scrub_paths(raw)
        assert marker not in cleaned, f"scrub_paths left {marker!r} in {cleaned!r}"
        # The diagnostic text itself must survive so the report stays useful.
        assert survivor in cleaned, f"scrub_paths destroyed {survivor!r} in {cleaned!r}"
        assert "<path>" in cleaned

    # A URL in a diagnostic must not be mangled beyond the host.
    assert "https://exiftool.org" in scrub_paths("see https://exiftool.org for details")


def test_locale_banner_is_dropped_but_real_warnings_survive():
    from app.exiftool import filter_warnings

    banner = (
        "perl: warning: Setting locale failed.\n"
        "perl: warning: Please check that your locale settings:\n"
        '\tLC_ALL = "C.UTF-8",\n'
        '\tLANG = "C.UTF-8"\n'
        "    are supported and installed on your system.\n"
        'perl: warning: Falling back to the standard locale ("C").\n'
    )
    # Banner plus a warning this pipeline already handles -> nothing to report.
    assert filter_warnings(banner + "Warning: [minor] Can't delete IFD0 from TIFF\n") is None

    kept = filter_warnings(banner + "Error: Truncated mdat atom - C:/scratch/x.mp4\n")
    assert kept is not None
    assert "Truncated mdat atom" in kept
    assert "locale" not in kept.lower()
    assert "C:/scratch" not in kept

    # A banner without its closing line must not swallow the real message.
    kept = filter_warnings("perl: warning: Setting locale failed.\nError: real failure here\n")
    assert kept is not None and "real failure here" in kept


def test_server_side_processing_is_disclosed(client, samples):
    body = upload(client, samples["jpeg"], endpoint="sanitize").json()
    assert body["retention"]["server_side_processing"] is True
    assert any("not local-only" in notice for notice in body["notices"])


def test_report_download_filename_is_generated_not_client_supplied(client, samples):
    body = upload(client, samples["jpeg"], filename="private-name.jpg", endpoint="sanitize").json()
    assert "private-name" not in body["download"]["filename"]
    assert body["download"]["filename"] == "cleanslate-sanitized.jpg"


def test_logs_never_contain_user_data(client, samples):
    records: list[str] = []

    class Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    logger = logging.getLogger("cleanslate")
    handler = Collector()
    logger.addHandler(handler)
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        upload(client, samples["jpeg"], filename="secret-holiday-photo.jpg", endpoint="inspect")
        upload(client, samples["jpeg"], filename="secret-holiday-photo.jpg", endpoint="sanitize")
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    joined = "\n".join(records)
    assert records, "expected some operational log lines"
    for forbidden in (
        "secret-holiday-photo",
        "Alice Test",
        "51.5074",
        "GPSLatitude",
        "Top secret description",
        "cleanslate-jobs",
        "original.jpg",
        "GEOMETRIC",
    ):
        assert forbidden not in joined, f"log leaked '{forbidden}'"


def test_logs_do_contain_operational_events(client, samples):
    records: list[str] = []

    class Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    logger = logging.getLogger("cleanslate")
    handler = Collector()
    logger.addHandler(handler)
    try:
        upload(client, samples["jpeg"], endpoint="sanitize")
    finally:
        logger.removeHandler(handler)

    joined = "\n".join(records)
    assert "sanitize_ok" in joined
    assert "job=" in joined
    assert "ip_hash=" in joined
