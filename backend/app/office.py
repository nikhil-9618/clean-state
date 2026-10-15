"""OOXML (DOCX/XLSX/PPTX) sanitization.

ExifTool documents Office Open XML as READ ONLY (it can extract docProps but
cannot rewrite the package), so CleanSlate does this part itself: the ZIP
package is rebuilt with the ``docProps`` metadata parts removed, together with
their package relationships and content-type overrides. Every other part is
copied byte-for-byte, so no document content is altered - which is also why
tracked changes, comments and embedded objects remain and are reported as
unverified rather than promised as removed.
"""

from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .logging_utils import get_logger

MAX_PARSE_BYTES = 1024 * 1024
_DROP_PREFIXES = ("docProps/",)
_CORE_REL_TARGET = b"docProps"


@dataclass
class OoxmlResult:
    removed_parts: list[str]
    warnings: list[str]
    body_parts: list[str]


def is_metadata_part(name: str) -> bool:
    return name.startswith(_DROP_PREFIXES)


def sanitize_ooxml(source: Path, destination: Path) -> OoxmlResult:
    """Rebuild an OOXML package without docProps metadata parts."""
    removed: list[str] = []
    warnings: list[str] = []
    body_parts: list[str] = []

    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        for info in infos:
            if is_metadata_part(info.filename):
                removed.append(info.filename)

        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as out:
            for info in infos:
                name = info.filename
                if is_metadata_part(name):
                    continue
                if name == "_rels/.rels":
                    data = archive.read(name)
                    new_data, changed = _strip_docprops_relationships(data, warnings)
                    out.writestr(_clone_info(info), new_data)
                    if changed:
                        removed.append("docProps relationships in _rels/.rels")
                    continue
                if name == "[Content_Types].xml":
                    data = archive.read(name)
                    new_data, changed = _strip_docprops_content_types(data, warnings)
                    out.writestr(_clone_info(info), new_data)
                    if changed:
                        removed.append("docProps content-type overrides in [Content_Types].xml")
                    continue
                body_parts.append(name)
                out.writestr(_clone_info(info), archive.read(name))

    return OoxmlResult(removed_parts=sorted(set(removed)), warnings=warnings, body_parts=body_parts)


def _clone_info(info: zipfile.ZipInfo) -> zipfile.ZipInfo:
    clone = zipfile.ZipInfo(info.filename, date_time=info.date_time)
    clone.compress_type = zipfile.ZIP_DEFLATED
    clone.external_attr = info.external_attr
    clone.internal_attr = info.internal_attr
    clone.create_system = info.create_system
    return clone


def _safe_parse(data: bytes, warnings: list[str], label: str):
    """Parse a small XML part, refusing entity-expansion vectors.

    OOXML relationship files never legitimately declare entities or a DOCTYPE,
    so anything that does is skipped (and reported) rather than parsed. This
    removes the billion-laughs class of attack from this code path entirely.
    """
    if len(data) > MAX_PARSE_BYTES:
        warnings.append(f"{label} is larger than {MAX_PARSE_BYTES} bytes and was left unchanged.")
        return None
    upper = data.upper()
    if b"<!ENTITY" in upper or b"<!DOCTYPE" in upper:
        warnings.append(
            f"{label} declares an XML DOCTYPE/ENTITY and was left unchanged for safety."
        )
        return None
    try:
        import xml.etree.ElementTree as ET

        return ET.fromstring(data)
    except Exception as exc:  # noqa: BLE001 - malformed XML must not crash a job
        warnings.append(f"{label} could not be parsed ({type(exc).__name__}) and was left unchanged.")
        return None


def _strip_docprops_relationships(data: bytes, warnings: list[str]) -> tuple[bytes, bool]:
    root = _safe_parse(data, warnings, "_rels/.rels")
    if root is None:
        return data, False
    changed = False
    for child in list(root):
        target = (child.get("Target") or "")
        rel_type = child.get("Type") or ""
        if "docProps" in target or "core-properties" in rel_type:
            root.remove(child)
            changed = True
    if not changed:
        return data, False
    return _serialize(root), True


def _strip_docprops_content_types(data: bytes, warnings: list[str]) -> tuple[bytes, bool]:
    root = _safe_parse(data, warnings, "[Content_Types].xml")
    if root is None:
        return data, False
    changed = False
    for child in list(root):
        part_name = child.get("PartName") or ""
        if part_name.startswith("/docProps/"):
            root.remove(child)
            changed = True
    if not changed:
        return data, False
    return _serialize(root), True


def _serialize(root) -> bytes:
    import xml.etree.ElementTree as ET

    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + ET.tostring(
        root, encoding="utf-8"
    )


def verify_ooxml(path: Path) -> tuple[bool, str | None]:
    """Confirm the rebuilt package is readable and still has its body part."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if not names:
                return False, "the rebuilt package is empty."
            has_body = any(
                name.startswith(("word/", "xl/", "ppt/"))
                for name in names
            )
            if not has_body:
                return False, "the rebuilt package lost its document body."
            bad = archive.testzip()
            if bad:
                return False, "the rebuilt package failed an integrity check."
            return True, None
    except (zipfile.BadZipFile, OSError) as exc:
        get_logger().warning("ooxml_verify_failed type=%s", type(exc).__name__)
        return False, "the rebuilt package could not be reopened."


def copy_file(source: Path, destination: Path) -> None:
    shutil.copyfile(source, destination)
