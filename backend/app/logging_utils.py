"""Logging helpers.

Privacy rules enforced here:

* never log file names, file contents, metadata values, GPS coordinates,
  browser signals, download tokens or raw client IPs;
* log only event names, coarse counters, tool versions, durations and opaque
  job identifiers;
* client IPs are reduced to a truncated HMAC before they reach a log line.

Anything that needs to report an upstream tool error runs it through
``scrub_tool_error`` first, which strips paths and clamps the length.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re

_LOGGER_NAME = "cleanslate"

# Matches absolute-looking paths, Windows drive paths and our scratch files.
#
# ExifTool prints Windows paths with forward slashes ("C:/Users/...") and
# rewrites the scratch path into warning text, so both separators must match.
# The POSIX branch requires at least one directory level and refuses to start
# inside a URL ("https://host/path") or a word.
_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/][^\s\"'|,;]*"
    r"|(?<![:\w/])/[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+/?"
    r"|[A-Za-z0-9_.\-]*cleanslate-jobs[^\s\"'|,;]*"
)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")


def configure_logging(level: str | None = None) -> None:
    """Configure a single stdout handler with a key=value format."""
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            fmt="ts=%(asctime)s level=%(levelname)s logger=%(name)s msg=%(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.setLevel((level or os.environ.get("LOG_LEVEL") or "INFO").upper())
    logger.propagate = False


def get_logger() -> logging.Logger:
    configure_logging()
    return logging.getLogger(_LOGGER_NAME)


def log_event(event: str, **fields: object) -> None:
    """Log an allowlisted event with flat key=value fields.

    Only scalars are accepted, and keys must be reviewed here so no personal
    data can sneak into logs later.
    """
    allowed = {
        "job",
        "format",
        "engine",
        "engine_version",
        "duration_ms",
        "bytes",
        "tags",
        "removed",
        "retained",
        "changed",
        "status",
        "reason",
        "ip_hash",
        "route",
        "count",
        "removed_parts",
        "exit_code",
        "detail",
    }
    parts = [event]
    for key, value in fields.items():
        if key not in allowed or value is None:
            continue
        text = str(value)
        text = text.replace("\n", " ").replace("\r", " ")[:160]
        parts.append(f"{key}={text}")
    get_logger().info(" ".join(parts))


def hash_ip(ip: str | None, secret: str) -> str:
    """Reduce a client IP to a truncated HMAC used for logs and IP binding."""
    if not ip:
        return "unknown"
    digest = hmac.new(secret.encode("utf-8"), ip.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:16]


def scrub_paths(text: str) -> str:
    """Replace filesystem paths with <path> in text that is shown to users.

    ExifTool appends the file path to many warnings, and those paths contain
    generated scratch names that must never leave the server.
    """
    return _PATH_RE.sub("<path>", text)


def scrub_tool_error(text: str | None, limit: int = 200) -> str:
    """Return a short, path-free, value-free description of a tool error."""
    if not text:
        return "no stderr"
    cleaned = _CONTROL_RE.sub(" ", text)
    cleaned = scrub_paths(cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned[:limit]
