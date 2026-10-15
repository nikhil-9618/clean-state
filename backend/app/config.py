"""Environment-driven configuration with fail-fast validation.

Everything is read from the environment once at import time so the deployed
container is configured purely by env vars. Nothing here ever logs a value.
"""

from __future__ import annotations

import os
import secrets
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


class ConfigError(RuntimeError):
    """Raised when the process is misconfigured and must not start."""


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ConfigError(f"{name} must be a boolean (true/false)")


def _int(name: str, default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:  # pragma: no cover - defensive
        raise ConfigError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} must be <= {maximum}")
    return value


def _origins(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    origins: list[str] = []
    for chunk in raw.split(","):
        origin = chunk.strip().rstrip("/")
        if not origin:
            continue
        if "*" in origin:
            raise ConfigError(f"{name} must not contain wildcards")
        if not (origin.startswith("https://") or origin.startswith("http://")):
            raise ConfigError(f"{name} entries must be absolute http(s) origins")
        if origin not in origins:
            origins.append(origin)
    return tuple(origins)


@dataclass(frozen=True)
class Settings:
    environment: str
    allowed_origins: tuple[str, ...]

    max_upload_bytes: int
    max_request_bytes: int
    max_concurrent_jobs: int
    max_temp_bytes: int

    exiftool_timeout_seconds: int
    qpdf_timeout_seconds: int
    request_timeout_seconds: int

    job_ttl_seconds: int
    download_token_ttl_seconds: int
    download_bind_ip: bool
    cleanup_interval_seconds: int

    rate_limit_requests: int
    rate_limit_window_seconds: int

    trust_proxy_headers: bool
    enable_hsts: bool
    expose_api_docs: bool

    secret_key: str
    exiftool_path: str
    qpdf_path: str
    temp_root: str

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def allowed_origins_display(self) -> str:
        return ", ".join(self.allowed_origins) if self.allowed_origins else "(none)"


def load_settings() -> Settings:
    environment = (os.environ.get("ENVIRONMENT") or "development").strip().lower()
    if environment not in {"development", "production", "test"}:
        raise ConfigError("ENVIRONMENT must be development, test or production")

    max_upload = _int("MAX_UPLOAD_BYTES", 25 * 1024 * 1024, minimum=1024, maximum=200 * 1024 * 1024)
    max_request = _int(
        "MAX_REQUEST_BYTES",
        max_upload + 1024 * 1024,
        minimum=2048,
        maximum=256 * 1024 * 1024,
    )
    if max_request < max_upload:
        raise ConfigError("MAX_REQUEST_BYTES must be >= MAX_UPLOAD_BYTES")

    secret = os.environ.get("SECRET_KEY", "").strip()
    if not secret:
        if environment == "production":
            raise ConfigError("SECRET_KEY must be set in production")
        # Ephemeral per-process secret: fine locally, means tokens do not
        # survive a restart (documented behaviour).
        secret = secrets.token_urlsafe(48)

    temp_root = os.environ.get("TEMP_ROOT", "").strip()
    if not temp_root:
        temp_root = str(Path(tempfile.gettempdir()) / "cleanslate-jobs")

    settings = Settings(
        environment=environment,
        allowed_origins=_origins(
            "ALLOWED_ORIGINS",
            ("http://localhost:5173", "http://localhost:4173") if environment != "production" else (),
        ),
        max_upload_bytes=max_upload,
        max_request_bytes=max_request,
        max_concurrent_jobs=_int("MAX_CONCURRENT_JOBS", 6, minimum=1, maximum=64),
        max_temp_bytes=_int("MAX_TEMP_BYTES", 128 * 1024 * 1024, minimum=1024 * 1024),
        exiftool_timeout_seconds=_int("EXIFTOOL_TIMEOUT_SECONDS", 20, minimum=1, maximum=120),
        qpdf_timeout_seconds=_int("QPDF_TIMEOUT_SECONDS", 20, minimum=1, maximum=120),
        request_timeout_seconds=_int("REQUEST_TIMEOUT_SECONDS", 45, minimum=5, maximum=300),
        job_ttl_seconds=_int("JOB_TTL_SECONDS", 300, minimum=30, maximum=3600),
        download_token_ttl_seconds=_int("DOWNLOAD_TOKEN_TTL_SECONDS", 300, minimum=30, maximum=3600),
        download_bind_ip=_bool("DOWNLOAD_BIND_IP", True),
        cleanup_interval_seconds=_int("CLEANUP_INTERVAL_SECONDS", 15, minimum=5, maximum=300),
        rate_limit_requests=_int("RATE_LIMIT_REQUESTS", 30, minimum=1, maximum=10000),
        rate_limit_window_seconds=_int("RATE_LIMIT_WINDOW_SECONDS", 60, minimum=1, maximum=3600),
        trust_proxy_headers=_bool("TRUST_PROXY_HEADERS", False),
        enable_hsts=_bool("ENABLE_HSTS", True),
        expose_api_docs=_bool("EXPOSE_API_DOCS", False),
        secret_key=secret,
        exiftool_path=(os.environ.get("EXIFTOOL_PATH") or "exiftool").strip(),
        qpdf_path=(os.environ.get("QPDF_PATH") or "qpdf").strip(),
        temp_root=temp_root,
    )

    if settings.is_production:
        if not settings.allowed_origins:
            raise ConfigError(
                "ALLOWED_ORIGINS must list the exact frontend origin(s) in production"
            )
        if _bool("EXPOSE_API_DOCS", False):
            raise ConfigError("EXPOSE_API_DOCS must be false in production")

    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
