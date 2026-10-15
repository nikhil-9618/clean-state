"""Format allowlist, magic-number validation and client filename hygiene.

Design rules:

* content decides the format - the client's filename is never trusted for
  routing, never used to build a filesystem path and never logged;
* anything outside the allowlist is rejected with a generic 415;
* a client extension that contradicts the detected format is rejected outright
  (defense against renamed/polyglot uploads).
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .errors import unsupported_media


class Format(str, Enum):
    JPEG = "jpeg"
    PNG = "png"
    TIFF = "tiff"
    WEBP = "webp"
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    MP4 = "mp4"

    @property
    def value_str(self) -> str:
        return self.value


class Sanitizer(str, Enum):
    """Which engine actually writes the sanitized copy."""

    EXIFTOOL = "exiftool"
    PDF_LAYER = "exiftool+qpdf"
    OOXML = "ooxml-repackage"
    NONE = "none"


@dataclass(frozen=True)
class FormatSpec:
    fmt: Format
    label: str
    mime: str
    extensions: tuple[str, ...]
    sanitizer: Sanitizer
    # ExifTool can write these tags back safely for this format.
    supports_orientation: bool = False
    supports_icc: bool = False
    # Categories that this pipeline does *not* verify as removed. These strings
    # are shown to the user verbatim, so they must stay accurate.
    unverified: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""


JPEG_UNVERIFIED = (
    "Steganographic payloads and data hidden inside image sample bytes",
    "Adobe APP14 colour-transform marker (retained on purpose: it can affect how colours are decoded)",
)
PNG_UNVERIFIED = (
    "data hidden inside image pixel data or inside unknown private chunks",
)
TIFF_UNVERIFIED = (
    "Image data itself (ExifTool cannot delete the main IFD0 block of a TIFF)",
    "Unknown private IFD tags that ExifTool does not classify as deletable",
)
WEBP_UNVERIFIED = (
    "Unknown/vendor RIFF chunks and data hidden inside image pixel data",
)
PDF_UNVERIFIED = (
    "Embedded file attachments and portfolio objects (/EmbeddedFile)",
    "Hidden layers, form-field values, annotations and JavaScript actions",
    "Content inside image/vector streams (CleanSlate never re-renders page content)",
)
OOXML_UNVERIFIED = (
    "Tracked changes and revision identifiers inside document.xml (w:rsid, w:ins, w:del)",
    "Comments, footnotes and header/footer content",
    "Embedded OLE objects, embedded fonts and external data links",
)
MP4_UNVERIFIED = (
    "Timed/in-stream metadata and GPS tracks inside media streams",
    "Data in unknown or vendor-specific atoms",
)

SPECS: dict[Format, FormatSpec] = {
    Format.JPEG: FormatSpec(
        Format.JPEG, "JPEG image", "image/jpeg", (".jpg", ".jpeg", ".jpe"),
        Sanitizer.EXIFTOOL, supports_orientation=True, supports_icc=True,
        unverified=JPEG_UNVERIFIED,
    ),
    Format.PNG: FormatSpec(
        Format.PNG, "PNG image", "image/png", (".png",),
        Sanitizer.EXIFTOOL, supports_orientation=True, supports_icc=True,
        unverified=PNG_UNVERIFIED,
    ),
    Format.TIFF: FormatSpec(
        Format.TIFF, "TIFF image", "image/tiff", (".tif", ".tiff"),
        Sanitizer.EXIFTOOL, supports_orientation=True, supports_icc=True,
        unverified=TIFF_UNVERIFIED,
        notes="ExifTool cannot delete the IFD0 block itself; CleanSlate additionally clears "
              "common IFD0 metadata tags (tag group CommonIFD0).",
    ),
    Format.WEBP: FormatSpec(
        Format.WEBP, "WebP image", "image/webp", (".webp",),
        Sanitizer.EXIFTOOL, supports_orientation=True, supports_icc=True,
        unverified=WEBP_UNVERIFIED,
    ),
    Format.PDF: FormatSpec(
        Format.PDF, "PDF document", "application/pdf", (".pdf",),
        Sanitizer.PDF_LAYER, supports_orientation=False, supports_icc=False,
        unverified=PDF_UNVERIFIED,
        notes="Metadata is deleted by ExifTool and the file is then rebuilt with "
              "qpdf --linearize so incremental-update history (previous metadata revisions) "
              "is dropped instead of being left recoverable in the file.",
    ),
    Format.DOCX: FormatSpec(
        Format.DOCX, "Word document (OOXML)", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        (".docx",), Sanitizer.OOXML, unverified=OOXML_UNVERIFIED,
        notes="ExifTool cannot write OOXML, so CleanSlate rebuilds the ZIP package itself and "
              "drops docProps metadata parts plus their package relationships.",
    ),
    Format.XLSX: FormatSpec(
        Format.XLSX, "Excel workbook (OOXML)", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        (".xlsx",), Sanitizer.OOXML, unverified=OOXML_UNVERIFIED,
        notes="CleanSlate rebuilds the ZIP package and drops docProps metadata parts.",
    ),
    Format.PPTX: FormatSpec(
        Format.PPTX, "PowerPoint presentation (OOXML)",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        (".pptx",), Sanitizer.OOXML, unverified=OOXML_UNVERIFIED,
        notes="CleanSlate rebuilds the ZIP package and drops docProps metadata parts.",
    ),
    Format.MP4: FormatSpec(
        Format.MP4, "MP4 / QuickTime video", "video/mp4", (".mp4", ".m4v", ".mov"),
        Sanitizer.EXIFTOOL, unverified=MP4_UNVERIFIED,
        notes="ExifTool rewrites the QuickTime container; media streams are copied, never re-encoded. "
              "Movie-header creation/modification dates are zeroed because the container has no way "
              "to omit them; track and media streams keep their playback structure.",
    ),
}

ALL_EXTENSIONS: dict[str, Format] = {}
for _spec in SPECS.values():
    for _ext in _spec.extensions:
        ALL_EXTENSIONS[_ext] = _spec.fmt

_MP4_BRANDS = {
    b"isom", b"iso2", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"mp71",
    b"avc1", b"dash", b"m4v ", b"M4V ", b"M4A ", b"MSNV", b"qt  ", b"3gp4",
    b"3gp5", b"3g2a", b"f4v ", b"heic", b"mif1",
}

_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]+")


def safe_display_name(raw: str | None, limit: int = 120) -> str | None:
    """Return a display-only filename: no path separators, no control chars.

    The result is used for UI hints only - never for filesystem paths.
    """
    if not raw:
        return None
    candidate = raw.replace("\\", "/").split("/")[-1]
    candidate = _CONTROL_CHARS.sub("", candidate)
    candidate = _UNSAFE_NAME_CHARS.sub("_", candidate).strip("._")
    if not candidate:
        return None
    if len(candidate) > limit:
        stem, dot, ext = candidate.rpartition(".")
        if dot and len(ext) <= 8:
            candidate = stem[: limit - len(ext) - 1] + "." + ext
        else:
            candidate = candidate[:limit]
    return candidate


def extension_of(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = _CONTROL_CHARS.sub("", raw.replace("\\", "/").split("/")[-1]).lower()
    _, dot, ext = cleaned.rpartition(".")
    if not dot:
        return None
    return "." + ext if ext else None


def detect_format(path: Path) -> FormatSpec | None:
    """Detect the format from file content only."""
    with path.open("rb") as handle:
        head = handle.read(4096)

    if head.startswith(b"\xff\xd8\xff"):
        return SPECS[Format.JPEG]
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return SPECS[Format.PNG]
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return SPECS[Format.TIFF]
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return SPECS[Format.WEBP]
    if b"%PDF-" in head[:1024]:
        return SPECS[Format.PDF]
    if head[:4] == b"PK\x03\x04":
        return _detect_ooxml(path)
    if head[4:8] == b"ftyp" and head[8:12] in _MP4_BRANDS:
        return SPECS[Format.MP4]
    return None


def _detect_ooxml(path: Path) -> FormatSpec | None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except Exception:  # noqa: BLE001 - untrusted archive: treat every failure as "not OOXML"
        return None
    if "[Content_Types].xml" not in names:
        return None
    if any(name.startswith("word/") for name in names):
        return SPECS[Format.DOCX]
    if any(name.startswith("xl/") for name in names):
        return SPECS[Format.XLSX]
    if any(name.startswith("ppt/") for name in names):
        return SPECS[Format.PPTX]
    return None


def validate_upload(path: Path, size: int, client_filename: str | None) -> FormatSpec:
    """Validate an uploaded file, raising ApiError on anything unsupported."""
    if size <= 0:
        raise unsupported_media("The uploaded file is empty.")

    spec = detect_format(path)
    if spec is None:
        raise unsupported_media(
            "This file type is not supported. Supported: JPEG, PNG, TIFF, WebP, PDF, "
            "DOCX, XLSX, PPTX, MP4/MOV."
        )

    client_ext = extension_of(client_filename)
    if client_ext and client_ext in ALL_EXTENSIONS and ALL_EXTENSIONS[client_ext] is not spec.fmt:
        # Example: a PDF renamed to .jpg, or a ZIP renamed to .png.
        raise unsupported_media(
            "The file content does not match its file extension, so it was rejected."
        )
    return spec
