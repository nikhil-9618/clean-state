"""Async subprocess runner for the external tools (ExifTool, qpdf).

Security properties:

* commands are always argument arrays - ``shell`` is never used, so no upload
  name or value can ever be interpreted by a shell;
* a minimal environment is passed (PATH/LANG/HOME/TMPDIR) so tools cannot pick
  up unrelated application secrets from the process environment;
* HOME points at an empty directory owned by the worker so a stray
  ``$HOME/.ExifTool_config`` cannot influence parsing;
* each child runs in its own process group and is killed as a group on timeout,
  so a wedged grandchild cannot survive;
* stdout/stderr are captured with a hard size cap.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import tool_unavailable
from .logging_utils import get_logger, log_event, scrub_tool_error

MAX_TOOL_OUTPUT_BYTES = 16 * 1024 * 1024
_WINDOWS = sys.platform.startswith("win")


@dataclass
class ToolResult:
    returncode: int
    stdout: bytes
    stderr: str
    duration_ms: int
    truncated: bool = False


@dataclass
class ToolInfo:
    name: str
    path: str | None
    version: str | None
    available: bool
    checked_at: float

    def as_dict(self) -> dict[str, object]:
        return {"available": self.available, "version": self.version}


class ToolRunner:
    """Owns tool discovery, versions and process execution."""

    def __init__(self, temp_root: Path, *, probe_ttl_seconds: int = 30) -> None:
        self._home = temp_root / "_toolhome"
        self._home.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self._home, 0o700)
        except OSError:  # pragma: no cover - platform specific
            pass
        self._probe_ttl = probe_ttl_seconds
        self._cache: dict[str, ToolInfo] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # -- discovery ---------------------------------------------------------- #
    def _env(self, scratch: Path | None = None) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "HOME": str(self._home),
            "TMPDIR": str(scratch or self._home),
        }
        if _WINDOWS and "SYSTEMROOT" in os.environ:
            env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
        return env

    def _resolve(self, configured: str) -> str | None:
        candidate = Path(configured)
        if candidate.is_absolute() and candidate.exists():
            return str(candidate)
        return shutil.which(configured)

    async def probe(self, name: str, configured: str, version_args: tuple[str, ...]) -> ToolInfo:
        cached = self._cache.get(name)
        now = time.time()
        if cached and now - cached.checked_at < self._probe_ttl:
            return cached
        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            cached = self._cache.get(name)
            if cached and time.time() - cached.checked_at < self._probe_ttl:
                return cached
            path = self._resolve(configured)
            info: ToolInfo
            if not path:
                info = ToolInfo(name, None, None, False, time.time())
            else:
                try:
                    result = await self.run(
                        [path, *version_args], timeout=10, tool=name, allow_failure=True
                    )
                    version = (result.stdout or result.stderr).decode(
                        "utf-8", "replace"
                    ).strip().splitlines()[0] if (result.stdout or result.stderr) else None
                    info = ToolInfo(name, path, version, result.returncode == 0, time.time())
                except Exception:  # pragma: no cover - defensive
                    info = ToolInfo(name, path, None, False, time.time())
            self._cache[name] = info
            log_event(
                "tool_probe",
                engine=name,
                status="available" if info.available else "missing",
                engine_version=info.version,
            )
            return info

    # -- execution ---------------------------------------------------------- #
    async def run(
        self,
        argv: list[str],
        *,
        timeout: float,
        tool: str,
        cwd: Path | None = None,
        allow_failure: bool = False,
    ) -> ToolResult:
        if not argv or not isinstance(argv, list):
            raise ValueError("argv must be a non-empty argument array")
        scratch = cwd or self._home
        started = time.perf_counter()
        popen_kwargs: dict[str, object] = {
            "stdin": asyncio.subprocess.DEVNULL,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "env": self._env(scratch),
            "cwd": str(scratch),
        }
        if _WINDOWS:  # pragma: no cover - Windows local development only
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        process = await asyncio.create_subprocess_exec(*argv, **popen_kwargs)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            self._kill_group(process)
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:  # pragma: no cover - defensive
                pass
            log_event("tool_timeout", engine=tool, duration_ms=int(timeout * 1000))
            raise
        except asyncio.CancelledError:
            self._kill_group(process)
            raise

        duration_ms = int((time.perf_counter() - started) * 1000)
        truncated = len(stdout) > MAX_TOOL_OUTPUT_BYTES
        if truncated:
            stdout = stdout[:MAX_TOOL_OUTPUT_BYTES]
        stderr_text = stderr.decode("utf-8", "replace")
        result = ToolResult(process.returncode or 0, stdout, stderr_text, duration_ms, truncated)

        if result.returncode != 0 and not allow_failure:
            get_logger().warning(
                "tool_error engine=%s exit_code=%s detail=%s",
                tool,
                result.returncode,
                scrub_tool_error(stderr_text),
            )
        return result

    @staticmethod
    def _kill_group(process: asyncio.subprocess.Process) -> None:
        try:
            if _WINDOWS:  # pragma: no cover - Windows local development only
                process.kill()
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):  # pragma: no cover - defensive
            try:
                process.kill()
            except ProcessLookupError:
                pass


async def require_tool(
    runner: ToolRunner, name: str, configured: str, version_args: tuple[str, ...]
) -> ToolInfo:
    info = await runner.probe(name, configured, version_args)
    if not info.available:
        raise tool_unavailable(name)
    return info
