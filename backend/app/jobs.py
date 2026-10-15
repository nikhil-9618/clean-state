"""Per-job scratch directories and single-use download tokens.

Guarantees implemented here:

* one isolated directory per job, created with mode 0700, named with 128 bits of
  randomness (never derived from user input);
* every path handed back is verified to sit inside the scratch root, so crafted
  identifiers cannot traverse out of it;
* the store tracks total scratch bytes and job count to keep the free-tier
  container inside its disk budget;
* a background sweeper plus a startup purge delete expired directories, and
  every request path deletes its directory on failure;
* download tokens are single-use, expiring, and (by default) bound to a hashed
  client IP so one visitor cannot fetch another visitor's result - an invalid
  or foreign token is indistinguishable from a missing one (404).
"""

from __future__ import annotations

import asyncio
import os
import secrets
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ApiError, busy, not_found
from .logging_utils import hash_ip, log_event

JOB_ID_BYTES = 16


@dataclass
class Job:
    id: str
    path: Path
    ip_hash: str
    created_at: float
    expires_at: float
    token: str | None = None
    token_expires_at: float = 0.0
    token_ip_hash: str | None = None
    consumed: bool = False
    format: str | None = None
    engine: str | None = None
    size_bytes: int = 0
    download_name: str = ""
    download_mime: str = "application/octet-stream"
    sanitized_path: Path | None = None
    extra: dict[str, object] = field(default_factory=dict)

    def download_path(self) -> Path:
        return self.sanitized_path or (self.path / "sanitized.out")


class JobStore:
    def __init__(
        self,
        temp_root: Path,
        *,
        job_ttl_seconds: int,
        token_ttl_seconds: int,
        max_jobs: int,
        max_temp_bytes: int,
        bind_ip: bool,
        cleanup_interval_seconds: int,
        secret: str,
    ) -> None:
        self.root = Path(temp_root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.job_ttl_seconds = job_ttl_seconds
        self.token_ttl_seconds = token_ttl_seconds
        self.max_jobs = max_jobs
        self.max_temp_bytes = max_temp_bytes
        self.bind_ip = bind_ip
        self.cleanup_interval_seconds = cleanup_interval_seconds
        self.secret = secret
        self._jobs: dict[str, Job] = {}
        self._tokens: dict[str, str] = {}
        self._bytes = 0
        self._closing = False

    # -- lifecycle ---------------------------------------------------------- #
    async def prepare(self) -> int:
        """Remove scratch data left behind by a previous run. Returns count."""
        removed = 0
        for entry in self.root.iterdir():
            if entry.name == "_toolhome":
                continue
            try:
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
                removed += 1
            except OSError:  # pragma: no cover - defensive
                continue
        if removed:
            log_event("scratch_purge", count=removed, reason="startup")
        return removed

    def new_job(self, ip_hash: str) -> Job:
        self._purge_expired()
        if len(self._jobs) >= self.max_jobs:
            raise busy("The processor already holds the maximum number of jobs.")
        if self._bytes > self.max_temp_bytes:
            raise busy("Temporary storage is currently full.")
        job_id = secrets.token_urlsafe(JOB_ID_BYTES)
        path = self._safe_path(job_id)
        path.mkdir(mode=0o700, parents=False, exist_ok=False)
        now = time.time()
        job = Job(
            id=job_id,
            path=path,
            ip_hash=ip_hash,
            created_at=now,
            expires_at=now + self.job_ttl_seconds,
        )
        self._jobs[job_id] = job
        log_event("job_created", job=job_id[:8], ip_hash=ip_hash)
        return job

    def register_bytes(self, job: Job, delta: int) -> None:
        job.size_bytes += max(delta, 0)
        self._bytes += max(delta, 0)

    async def destroy(self, job: Job | None) -> None:
        if job is None:
            return
        self._jobs.pop(job.id, None)
        if job.token:
            self._tokens.pop(job.token, None)
        self._bytes = max(0, self._bytes - job.size_bytes)
        await asyncio.to_thread(shutil.rmtree, job.path, True)

    # -- tokens ------------------------------------------------------------- #
    def issue_token(self, job: Job, ip_hash: str) -> tuple[str, float]:
        token = secrets.token_urlsafe(32)
        expires_at = min(time.time() + self.token_ttl_seconds, job.expires_at)
        job.token = token
        job.token_expires_at = expires_at
        job.token_ip_hash = ip_hash if self.bind_ip else None
        job.consumed = False
        self._tokens[token] = job.id
        return token, expires_at

    async def claim_token(self, token: str, ip_hash: str) -> Job:
        """Validate and consume a download token. Always raises 404 on failure."""
        self._purge_expired()
        job_id = self._tokens.get(token)
        if not job_id:
            raise not_found("This download link is not valid or has expired.")
        job = self._jobs.get(job_id)
        if job is None or job.token != token or job.consumed:
            raise not_found("This download link is not valid or has expired.")
        if job.token_expires_at and time.time() > job.token_expires_at:
            await self.destroy(job)
            raise not_found("This download link is not valid or has expired.")
        if job.token_ip_hash and job.token_ip_hash != ip_hash:
            # Cross-user access attempt: same generic response, job preserved.
            log_event("download_ip_mismatch", job=job.id[:8], ip_hash=ip_hash)
            raise not_found("This download link is not valid or has expired.")
        if not job.download_path().exists():
            await self.destroy(job)
            raise not_found("This download link is not valid or has expired.")
        # Single use: invalidate immediately so a leaked URL cannot be replayed.
        job.consumed = True
        self._tokens.pop(token, None)
        return job

    # -- maintenance -------------------------------------------------------- #
    def _purge_expired(self) -> None:
        now = time.time()
        expired = [job for job in self._jobs.values() if job.expires_at <= now]
        for job in expired:
            self._jobs.pop(job.id, None)
            if job.token:
                self._tokens.pop(job.token, None)
            self._bytes = max(0, self._bytes - job.size_bytes)
            try:
                shutil.rmtree(job.path, ignore_errors=True)
            except OSError:  # pragma: no cover - defensive
                pass
        if expired:
            log_event("scratch_purge", count=len(expired), reason="expired")

    async def sweep(self) -> None:
        self._purge_expired()

    async def sweep_loop(self) -> None:
        while not self._closing:
            try:
                await asyncio.sleep(self.cleanup_interval_seconds)
                await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - sweeper must never die
                log_event("sweeper_error", detail=type(exc).__name__)

    async def shutdown(self) -> None:
        self._closing = True
        for job in list(self._jobs.values()):
            await self.destroy(job)

    # -- paths -------------------------------------------------------------- #
    def _safe_path(self, job_id: str) -> Path:
        if not job_id or "/" in job_id or "\\" in job_id or ".." in job_id:
            raise ApiError(400, "invalid_identifier", "Invalid job identifier.")
        candidate = (self.root / job_id).resolve()
        root = self.root.resolve()
        if root not in candidate.parents:
            raise ApiError(400, "invalid_identifier", "Invalid job identifier.")
        return candidate

    def stats(self) -> dict[str, int]:
        return {
            "jobs": len(self._jobs),
            "temp_bytes": self._bytes,
            "max_jobs": self.max_jobs,
            "max_temp_bytes": self.max_temp_bytes,
        }


def ip_key(ip: str | None, secret: str) -> str:
    return hash_ip(ip, secret)


def ensure_secure_permissions(path: Path) -> None:
    """Best-effort 0700 on the scratch directory."""
    if os.name == "posix":
        try:
            os.chmod(path, 0o700)
        except OSError:  # pragma: no cover - defensive
            pass
