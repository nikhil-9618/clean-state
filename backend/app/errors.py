"""Typed API errors.

Every error that reaches a client is intentionally generic: a stable machine
code plus a short human sentence that never contains stack traces, tool stderr,
file names or metadata values. Details stay in the server log, scrubbed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ApiError(Exception):
    status_code: int
    code: str
    message: str
    retry_after: int | None = None
    headers: dict[str, str] | None = None

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return f"{self.code}: {self.message}"


def bad_request(message: str = "The request could not be processed.", code: str = "invalid_request") -> ApiError:
    return ApiError(400, code, message)


def unsupported_media(message: str = "This file type is not supported.") -> ApiError:
    return ApiError(415, "unsupported_file_type", message)


def payload_too_large(message: str = "The file exceeds the maximum accepted size.") -> ApiError:
    return ApiError(413, "payload_too_large", message)


def cannot_process(message: str = "This file could not be processed.") -> ApiError:
    return ApiError(422, "unprocessable_file", message)


def not_found(message: str = "Not found.") -> ApiError:
    return ApiError(404, "not_found", message)


def rate_limited(retry_after: int) -> ApiError:
    return ApiError(
        429,
        "rate_limited",
        "Too many requests from this client. Please slow down and retry shortly.",
        retry_after=retry_after,
        headers={"Retry-After": str(retry_after)},
    )


def tool_unavailable(tool: str) -> ApiError:
    return ApiError(
        503,
        "tool_unavailable",
        f"The processing tool ({tool}) is not available on this instance right now.",
        headers={"Retry-After": "30"},
    )


def timeout_error(message: str = "Processing took too long and was stopped.") -> ApiError:
    return ApiError(504, "processing_timeout", message)


def busy(message: str = "The processor is at capacity. Please retry in a moment.") -> ApiError:
    return ApiError(503, "processor_busy", message, retry_after=10, headers={"Retry-After": "10"})
