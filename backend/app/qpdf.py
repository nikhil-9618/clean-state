"""qpdf integration.

Used for PDFs only: after ExifTool writes the metadata deletion it appends an
incremental update, which keeps the previous revision (with the old metadata)
recoverable inside the file. ``qpdf --linearize`` rebuilds the file so that
history is gone. If qpdf is unavailable the API reports the PDF's history as
NOT verified instead of pretending it was removed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from .errors import cannot_process, timeout_error
from .tools import ToolInfo, ToolRunner

VERSION_ARGS = ("--version",)


async def version(runner: ToolRunner, configured_path: str) -> ToolInfo:
    return await runner.probe("qpdf", configured_path, VERSION_ARGS)


async def linearize(
    runner: ToolRunner,
    source: Path,
    destination: Path,
    *,
    configured_path: str,
    timeout: float,
) -> tuple[bool, str | None]:
    """Rewrite ``source`` into ``destination`` dropping incremental history.

    Returns ``(succeeded, note)``. Failure never raises: the caller keeps the
    ExifTool output and marks PDF revision history as unverified.
    """
    try:
        result = await runner.run(
            [configured_path, "--linearize", "--", str(source), str(destination)],
            timeout=timeout,
            tool="qpdf",
            allow_failure=True,
        )
    except asyncio.TimeoutError:
        raise timeout_error("PDF rewriting timed out.") from None
    except FileNotFoundError:
        return False, "qpdf is not available on this instance."

    if result.returncode != 0 or not destination.exists() or destination.stat().st_size == 0:
        return False, f"qpdf exited with code {result.returncode}."
    return True, None


def unavailable_note() -> str:
    return (
        "qpdf is not installed on this instance, so the PDF was rewritten by ExifTool only. "
        "Metadata was removed from the current revision, but earlier revisions may remain "
        "recoverable inside the file."
    )


def raise_unavailable() -> None:  # pragma: no cover - defensive
    raise cannot_process("PDF rewriting is unavailable on this instance.")
