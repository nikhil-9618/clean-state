"""Structural analysis of uploaded files.

These checks look at container structure rather than metadata: trailing data,
duplicate PDF revisions, embedded attachments, OOXML revision history. They are
used twice:

* as a gate before processing (blocking findings reject the upload);
* as part of the report, so CleanSlate can be truthful about what it did and
  did not verify.
"""

from __future__ import annotations

import struct
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from .formats import Format, FormatSpec

Severity = str  # "info" | "notice" | "warning"


@dataclass(frozen=True)
class Finding:
    id: str
    category: str
    severity: Severity
    detail: str


@dataclass
class StructuralReport:
    findings: list[Finding] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)
    blocking: bool = False

    def add(
        self,
        id: str,
        category: str,
        severity: Severity,
        detail: str,
        *,
        blocking: bool = False,
    ) -> None:
        self.findings.append(Finding(id, category, severity, detail))
        if blocking:
            self.blocking = True

    def as_dict(self) -> dict[str, object]:
        return {
            "findings": [
                {
                    "id": f.id,
                    "category": f.category,
                    "severity": f.severity,
                    "detail": f.detail,
                }
                for f in self.findings
            ],
            "counters": dict(self.counters),
        }


# --------------------------------------------------------------------------- #
# Bounded byte scanning helpers
# --------------------------------------------------------------------------- #

_MAX_SCAN_BYTES = 64 * 1024 * 1024


def _read_all(path: Path) -> bytes:
    """Read at most _MAX_SCAN_BYTES; uploads are already size capped."""
    with path.open("rb") as handle:
        return handle.read(_MAX_SCAN_BYTES)


def _count(haystack: bytes, needle: bytes) -> int:
    return haystack.count(needle)


def _tail_after_marker(data: bytes, marker: bytes) -> int:
    index = data.rfind(marker)
    if index < 0:
        return 0
    return len(data) - (index + len(marker))


# --------------------------------------------------------------------------- #
# Per-format analyzers
# --------------------------------------------------------------------------- #


def _analyze_jpeg(path: Path, report: StructuralReport) -> None:
    data = _read_all(path)
    soi = _count(data, b"\xff\xd8")
    eoi = _count(data, b"\xff\xd9")
    report.counters["jpeg_soi_markers"] = soi
    report.counters["jpeg_eoi_markers"] = eoi
    trailing = _tail_after_marker(data, b"\xff\xd9")
    report.counters["jpeg_trailing_bytes"] = trailing
    if eoi == 0:
        report.add(
            "jpeg_no_eoi",
            "structure",
            "warning",
            "No JPEG end-of-image marker was found; the file is truncated or malformed.",
        )
    elif trailing:
        report.add(
            "jpeg_trailing_data",
            "trailing_data",
            "notice",
            f"{trailing} bytes of data follow the last JPEG end-of-image marker. "
            "CleanSlate removes this trailer during sanitization.",
        )
    if soi > 1:
        report.add(
            "jpeg_multiple_images",
            "structure",
            "notice",
            f"{soi} JPEG start-of-image markers were found (the file may contain more than one image).",
        )


def _analyze_png(path: Path, report: StructuralReport) -> None:
    data = _read_all(path)
    offset = 8  # skip signature
    text_chunks = 0
    ichunks = 0
    crc_errors = 0
    end_offset: int | None = None
    length = len(data)
    while offset + 8 <= length and ichunks < 5000:
        (chunk_len,) = struct.unpack(">I", data[offset : offset + 4])
        chunk_type = data[offset + 4 : offset + 8]
        chunk_end = offset + 8 + chunk_len
        if chunk_end + 4 > length:
            break
        payload = data[offset + 8 : chunk_end]
        stored_crc = struct.unpack(">I", data[chunk_end : chunk_end + 4])[0]
        if zlib.crc32(chunk_type + payload) & 0xFFFFFFFF != stored_crc:
            crc_errors += 1
        if chunk_type in (b"tEXt", b"zTXt", b"iTXt"):
            text_chunks += 1
        if chunk_type == b"IEND":
            end_offset = chunk_end + 4
            break
        offset = chunk_end + 4
        ichunks += 1

    report.counters["png_text_chunks"] = text_chunks
    report.counters["png_chunks_scanned"] = ichunks
    report.counters["png_crc_errors"] = crc_errors
    if end_offset is None:
        report.add(
            "png_missing_iend",
            "structure",
            "warning",
            "The PNG IEND chunk was not found; the file is malformed.",
        )
        return
    trailing = length - end_offset
    report.counters["png_trailing_bytes"] = trailing
    if trailing:
        report.add(
            "png_trailing_data",
            "trailing_data",
            "notice",
            f"{trailing} bytes follow the PNG IEND chunk and are not part of the PNG container. "
            "CleanSlate removes this trailer during sanitization.",
        )
    if crc_errors:
        report.add(
            "png_crc_errors",
            "structure",
            "notice",
            f"{crc_errors} PNG chunk CRC error(s) were found; the file may be damaged.",
        )


def _analyze_webp(path: Path, report: StructuralReport) -> None:
    data = _read_all(path)
    if len(data) < 12:
        report.add("webp_truncated", "structure", "warning", "The WebP header is truncated.")
        return
    (declared,) = struct.unpack("<I", data[4:8])
    actual = len(data) - 8
    report.counters["webp_declared_bytes"] = declared
    report.counters["webp_actual_bytes"] = actual
    offset = 12
    chunks: dict[str, int] = {}
    while offset + 8 <= len(data):
        fourcc = data[offset : offset + 4].decode("ascii", "replace")
        (size,) = struct.unpack("<I", data[offset + 4 : offset + 8])
        chunks[fourcc] = chunks.get(fourcc, 0) + 1
        offset += 8 + size + (size % 2)
    report.counters["webp_exif_chunks"] = chunks.get("EXIF", 0)
    report.counters["webp_xmp_chunks"] = chunks.get("XMP ", 0)
    report.counters["webp_icc_chunks"] = chunks.get("ICCP", 0)
    if declared != actual:
        report.add(
            "webp_size_mismatch",
            "trailing_data",
            "notice",
            f"The RIFF header declares {declared} bytes but the file contains {actual} bytes. "
            "CleanSlate rebuilds the container during sanitization.",
        )
    unknown = sorted(set(chunks) - {"VP8 ", "VP8L", "VP8X", "EXIF", "XMP ", "ICCP", "ANIM", "ANMF", "ALPH"})
    if unknown:
        report.add(
            "webp_unknown_chunks",
            "embedded_content",
            "warning",
            "Unknown WebP chunks are present (" + ", ".join(unknown[:8]) + "). "
            "CleanSlate does not remove unknown private chunks.",
        )


def _analyze_tiff(path: Path, report: StructuralReport) -> None:
    data = _read_all(path)
    little = data[:2] == b"II"
    fmt = "<I" if little else ">I"
    if len(data) < 8:
        report.add("tiff_truncated", "structure", "warning", "The TIFF header is truncated.")
        return
    ifd_count = 0
    offset = struct.unpack(fmt, data[4:8])[0]
    seen: set[int] = set()
    while 0 < offset < len(data) - 2 and ifd_count < 64:
        if offset in seen:
            report.add("tiff_ifd_cycle", "structure", "warning", "The TIFF IFD chain contains a loop.")
            break
        seen.add(offset)
        (entries,) = struct.unpack("<H" if little else ">H", data[offset : offset + 2])
        offset = offset + 2 + entries * 12
        if len(data) < offset + 4:
            break
        offset = struct.unpack(fmt, data[offset : offset + 4])[0]
        ifd_count += 1
    report.counters["tiff_ifd_chain_length"] = ifd_count
    if offset not in (0,) and (offset >= len(data) or offset < 8):
        report.counters["tiff_trailing_bytes"] = max(0, len(data) - (offset or 0))
    report.add(
        "tiff_no_structural_cleanup",
        "structure",
        "info",
        "TIFF image data and its IFD layout are preserved; only metadata tags are cleared "
        "(including common IFD0 metadata tags).",
    )


def _analyze_pdf(path: Path, report: StructuralReport) -> None:
    data = _read_all(path)
    headers = _count(data, b"%PDF-")
    eofs = _count(data, b"%%EOF")
    trailing = _tail_after_marker(data, b"%%EOF")
    embedded = _count(data, b"/EmbeddedFile")
    javascript = _count(data, b"/JavaScript")
    encrypted = _count(data, b"/Encrypt")
    report.counters.update(
        {
            "pdf_incremental_revisions": max(0, eofs - 1),
            "pdf_header_count": headers,
            "pdf_embedded_files": embedded,
            "pdf_javascript_objects": javascript,
            "pdf_trailing_bytes": trailing,
        }
    )
    if eofs > 1:
        report.add(
            "pdf_incremental_updates",
            "revision_history",
            "notice",
            f"The PDF contains {eofs} revisions (incremental updates). Earlier revisions can hold "
            "older metadata values; CleanSlate rebuilds the file with qpdf --linearize so those "
            "revisions are dropped.",
        )
    if trailing:
        report.add(
            "pdf_trailing_data",
            "trailing_data",
            "notice",
            f"{trailing} bytes follow the final PDF end-of-file marker.",
        )
    if embedded:
        report.add(
            "pdf_embedded_files",
            "embedded_content",
            "warning",
            f"{embedded} embedded file attachment(s) were detected. CleanSlate does NOT remove PDF "
            "attachments - treat this file as still containing hidden payloads.",
        )
    if javascript:
        report.add(
            "pdf_javascript",
            "embedded_content",
            "warning",
            f"{javascript} JavaScript object(s) were detected. CleanSlate does not remove PDF JavaScript.",
        )
    if encrypted:
        report.add(
            "pdf_encrypted",
            "structure",
            "warning",
            "The PDF appears to be encrypted; processing may fail or be skipped by the tools.",
        )


def _analyze_mp4(path: Path, report: StructuralReport) -> None:
    with path.open("rb") as handle:
        size = 0
        boxes: list[str] = []
        while True:
            header = handle.read(8)
            if len(header) < 8:
                break
            (box_size,) = struct.unpack(">I", header[:4])
            box_type = header[4:8].decode("ascii", "replace")
            if box_size == 1:
                extended = handle.read(8)
                if len(extended) < 8:
                    break
                (box_size,) = struct.unpack(">Q", extended)
                box_size -= 16
            elif box_size == 0:
                box_size = -1
            boxes.append(box_type)
            size += 8
            if box_size < 0:
                break
            if box_size < 8:
                report.add(
                    "mp4_invalid_box",
                    "structure",
                    "warning",
                    "The MP4 box structure is invalid (a box declares a size below the minimum).",
                )
                break
            handle.seek(box_size - 8, 1)
            size += box_size - 8
            if len(boxes) > 500:
                break
    report.counters["mp4_top_level_boxes"] = len(boxes)
    report.counters["mp4_bytes_walked"] = size
    report.counters["mp4_has_moov"] = 1 if "moov" in boxes else 0
    if "ftyp" not in boxes:
        report.add("mp4_missing_ftyp", "structure", "warning", "The MP4 ftyp box was not found.")
    if "moov" not in boxes:
        report.add(
            "mp4_missing_moov",
            "structure",
            "warning",
            "No moov atom was found in the scanned region; writing metadata may fail.",
        )
    if "uuid" in boxes:
        report.add(
            "mp4_uuid_boxes",
            "embedded_content",
            "notice",
            "Vendor-specific uuid atoms are present; CleanSlate leaves unknown atoms untouched.",
        )
    if size < _read_all_size(path):
        report.counters["mp4_unwalked_bytes"] = _read_all_size(path) - size


def _read_all_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:  # pragma: no cover - defensive
        return 0


_OOXML_REVISION_NEEDLES = {
    b"w:rsid": "revision identifiers (w:rsid)",
    b"<w:ins ": "tracked insertions (w:ins)",
    b"<w:del ": "tracked deletions (w:del)",
    b"w:rsidR": "revision save ids (w:rsidR)",
}


def analyze_ooxml(path: Path, spec: FormatSpec, report: StructuralReport) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            uncompressed = sum(info.file_size for info in infos)
            compressed = sum(max(info.compress_size, 1) for info in infos)
            report.counters["ooxml_parts"] = len(names)
            report.counters["ooxml_uncompressed_bytes"] = uncompressed
    except Exception as exc:  # noqa: BLE001 - third-party archives are untrusted
        report.add(
            "ooxml_unreadable",
            "structure",
            "warning",
            f"The Office package could not be opened as a ZIP archive ({type(exc).__name__}).",
        )
        return

    ratio = uncompressed / max(_read_all_size(path), 1)
    report.counters["ooxml_compression_ratio"] = int(ratio)
    if uncompressed > 400 * 1024 * 1024 or ratio > 200:
        report.add(
            "ooxml_archive_bomb",
            "structure",
            "warning",
            f"The package expands to {uncompressed} bytes ({ratio:.0f}x the upload). This is rejected "
            "as a potential archive bomb.",
            blocking=True,
        )

    metadata_parts = [n for n in names if n.startswith("docProps/")]
    report.counters["ooxml_docprops_parts"] = len(metadata_parts)
    if metadata_parts:
        report.add(
            "ooxml_docprops_present",
            "metadata_container",
            "info",
            "Document property parts are present (" + ", ".join(sorted(metadata_parts)[:6]) + "). "
            "CleanSlate removes these parts from the sanitized copy.",
        )

    body_name = next(
        (n for n in names if n.startswith("word/document.xml") or n.startswith("xl/workbook.xml")
         or n.startswith("ppt/presentation.xml")),
        None,
    )
    if body_name:
        try:
            with zipfile.ZipFile(path) as archive:
                body = archive.read(body_name)
        except (KeyError, zipfile.BadZipFile):  # pragma: no cover - defensive
            body = b""
        found = [label for needle, label in _OOXML_REVISION_NEEDLES.items() if needle in body]
        report.counters["ooxml_revision_markers"] = len(found)
        if found:
            report.add(
                "ooxml_revision_history",
                "revision_history",
                "warning",
                "Revision history is present (" + ", ".join(found) + "). CleanSlate does NOT remove "
                "tracked changes or revision ids - review the document before sharing it.",
            )

    comment_parts = [n for n in names if "comments" in n.lower()]
    if comment_parts:
        report.add(
            "ooxml_comments",
            "embedded_content",
            "warning",
            "Comment parts are present (" + ", ".join(sorted(comment_parts)[:4]) + "). "
            "CleanSlate keeps document content, so comments are preserved.",
        )

    embedded = [n for n in names if "embeddings/" in n or n.lower().endswith((".bin", ".emf", ".wmf"))]
    if embedded:
        report.add(
            "ooxml_embedded_objects",
            "embedded_content",
            "warning",
            "Embedded objects are present (" + ", ".join(sorted(embedded)[:4]) + "). "
            "These can contain their own metadata and are not sanitized.",
        )

    macros = [n for n in names if "vbaProject" in n]
    if macros:
        report.add(
            "ooxml_macros",
            "embedded_content",
            "warning",
            "This package contains a macro project (vbaProject). CleanSlate does not remove macros.",
        )

    external_links = 0
    try:
        with zipfile.ZipFile(path) as archive:
            for name in names:
                if name.endswith(".rels"):
                    rels = archive.read(name)
                    external_links += rels.count(b'TargetMode="External"')
    except (KeyError, zipfile.BadZipFile):  # pragma: no cover - defensive
        pass
    if external_links:
        report.counters["ooxml_external_links"] = external_links
        report.add(
            "ooxml_external_links",
            "embedded_content",
            "notice",
            f"{external_links} external relationship(s) were detected; they can leak activity when the "
            "document is opened. CleanSlate does not remove them.",
        )


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def analyze(path: Path, spec: FormatSpec) -> StructuralReport:
    """Run the structural analyzer for the detected format.

    Untrusted bytes reach these parsers, so any unexpected parser failure is
    recorded as a finding instead of surfacing as a 500. The report then states
    that structural analysis did not complete.
    """
    report = StructuralReport()
    try:
        _analyze_dispatch(path, spec, report)
    except Exception as exc:  # noqa: BLE001 - malformed input must never crash the API
        report.add(
            "analysis_failed",
            "structure",
            "notice",
            "Structural analysis of this file could not be completed "
            f"({type(exc).__name__}); metadata processing was still attempted, but container-level "
            "checks could not be verified.",
        )
    return report


def _analyze_dispatch(path: Path, spec: FormatSpec, report: StructuralReport) -> None:
    if spec.fmt is Format.JPEG:
        _analyze_jpeg(path, report)
    elif spec.fmt is Format.PNG:
        _analyze_png(path, report)
    elif spec.fmt is Format.WEBP:
        _analyze_webp(path, report)
    elif spec.fmt is Format.TIFF:
        _analyze_tiff(path, report)
    elif spec.fmt is Format.PDF:
        _analyze_pdf(path, report)
    elif spec.fmt is Format.MP4:
        _analyze_mp4(path, report)
    elif spec.fmt in (Format.DOCX, Format.XLSX, Format.PPTX):
        analyze_ooxml(path, spec, report)
