"""ExifTool integration.

All calls go through :class:`app.tools.ToolRunner`, so argv-only execution,
timeouts and output caps apply. Tag values are returned to the requesting user
but are never logged.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from .errors import cannot_process, timeout_error
from .logging_utils import scrub_paths
from .tools import ToolInfo, ToolRunner

VERSION_ARGS = ("-ver",)
# -j JSON, -G1 family-1 group names, -s short tag names, -a allow duplicates.
INSPECT_ARGS = ("-j", "-G1", "-s", "-a")

# Groups that describe the container rather than authored metadata. They are
# reported separately and excluded from removed/retained comparisons.
# With -G1 the group is the family-1 location (IFD0, ExifIFD, GPS, PNG, ...),
# so the set below covers container/derived groups only.
NON_METADATA_GROUPS = {"ExifTool", "File", "System", "Composite", "JFIF", "Trailer", "ZIP"}

MAX_TAGS = 800

# ExifTool warnings that are expected and already handled by this pipeline. They
# must not be surfaced to users as failures.
_BENIGN_WARNING_PARTS = (
    "can't delete ifd0 from tiff",
    "does not exist",
    "isn't writable",
    "is not defined",
    "no writable tags set",
    "nothing to do",
)


def is_benign_warning(text: str | None) -> bool:
    if not text:
        return True
    lowered = text.lower()
    return any(part in lowered for part in _BENIGN_WARNING_PARTS)


def strip_locale_noise(text: str) -> str:
    """Remove perl's multi-line locale banner from tool stderr.

    ExifTool is a perl program. When the host perl cannot find the locale that
    the sandbox sets (typical on Windows development machines) it prints a
    six-line "Setting locale failed" banner before every real message. The
    banner is noise, contains no file data, and must not reach the user.
    """
    if "Setting locale failed" not in text:
        return text
    kept: list[str] = []
    skipping = False
    for line in text.splitlines():
        lowered = line.lower()
        if "setting locale failed" in lowered:
            skipping = True
            continue
        if skipping:
            # The banner ends at its last line, or at the first real message if
            # perl printed the banner without its closing line.
            if "falling back to the standard locale" in lowered:
                skipping = False
                continue
            if lowered.startswith(("warning:", "error:", "exiftool:")):
                skipping = False
            else:
                continue
        kept.append(line)
    return "\n".join(kept)


def filter_warnings(text: str | None, *, drop_reversible: bool = False) -> str | None:
    """Drop warnings this pipeline already handles; keep the rest verbatim."""
    if not text:
        return None
    kept: list[str] = []
    for line in strip_locale_noise(text).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if is_benign_warning(stripped):
            continue
        if drop_reversible and "reversible" in stripped.lower():
            continue
        kept.append(scrub_paths(stripped))
    if not kept:
        return None
    return " | ".join(kept)[:400]


@dataclass
class TagMap:
    """Parsed ExifTool output."""

    tags: dict[str, str] = field(default_factory=dict)
    file_info: dict[str, str] = field(default_factory=dict)
    tag_count: int = 0
    truncated: bool = False
    warnings: str | None = None
    exit_code: int = 0
    tool_version: str | None = None

    def metadata_tags(self) -> dict[str, str]:
        return {key: value for key, value in self.tags.items() if group_of(key) not in NON_METADATA_GROUPS}


def group_of(key: str) -> str:
    group, _, _tag = key.partition(":")
    return group or "Other"


def tag_of(key: str) -> str:
    group, sep, tag = key.partition(":")
    return tag if sep else group


async def version(runner: ToolRunner, configured_path: str) -> ToolInfo:
    return await runner.probe("exiftool", configured_path, VERSION_ARGS)


async def inspect(
    runner: ToolRunner,
    path: Path,
    *,
    configured_path: str,
    timeout: float,
    tool_version: str | None = None,
) -> TagMap:
    """Read all metadata from ``path`` as a flat ``{"GROUP:Tag": "value"}`` map."""
    try:
        result = await runner.run(
            [configured_path, *INSPECT_ARGS, "--", str(path)], timeout=timeout, tool="exiftool"
        )
    except asyncio.TimeoutError:
        raise timeout_error("Metadata inspection timed out.") from None
    except FileNotFoundError:
        raise cannot_process("The processing tool could not be started.") from None

    if result.returncode >= 2:
        raise cannot_process("This file could not be read for metadata inspection.")

    try:
        payload = json.loads(result.stdout.decode("utf-8", "replace") or "[]")
    except json.JSONDecodeError:
        raise cannot_process("The metadata reader returned an unreadable response.") from None

    entry: dict[str, object] = {}
    if isinstance(payload, list) and payload:
        candidate = payload[0]
        if isinstance(candidate, dict):
            entry = candidate

    tags: dict[str, str] = {}
    file_info: dict[str, str] = {}
    truncated = False
    for key, value in entry.items():
        if len(tags) + len(file_info) >= MAX_TAGS:
            truncated = True
            break
        # Group-less pseudo tags ("SourceFile") carry the server-side scratch
        # path. They are dropped at the door: never returned, never logged.
        if ":" not in key:
            continue
        text = _stringify(value)
        if text is None:
            continue
        if key.startswith("File:"):
            file_info[key] = text
        else:
            tags[key] = text

    warnings = filter_warnings(result.stderr) if result.returncode == 1 else None
    return TagMap(
        tags=tags,
        file_info=file_info,
        tag_count=len(tags) + len(file_info),
        truncated=truncated or result.truncated,
        warnings=warnings,
        exit_code=result.returncode,
        tool_version=tool_version,
    )


def _stringify(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value if len(value) <= 4000 else value[:4000] + "…"
    if isinstance(value, list):
        joined = ", ".join(str(item) for item in value[:50])
        return joined[:4000]
    return str(value)[:4000]


async def write(
    runner: ToolRunner,
    path: Path,
    extra_args: list[str],
    *,
    configured_path: str,
    timeout: float,
) -> tuple[int, str | None]:
    """Apply metadata deletions in place to ``path`` using -overwrite_original.

    Returns ``(exit_code, warning_text)``. Exit code 1 (warnings) is returned to
    the caller instead of being treated as success, so the report can stay
    honest about partially processed files.
    """
    argv = [configured_path, *extra_args, "-overwrite_original", "--", str(path)]
    try:
        result = await runner.run(argv, timeout=timeout, tool="exiftool")
    except asyncio.TimeoutError:
        raise timeout_error("Sanitization timed out.") from None
    except FileNotFoundError:
        raise cannot_process("The processing tool could not be started.") from None

    if result.returncode >= 2:
        raise cannot_process(
            "This file could not be rewritten. The container may be malformed or the format "
            "may not be writable by the metadata engine."
        )
    warning = filter_warnings(result.stderr) if result.returncode == 1 else None
    return result.returncode, warning
