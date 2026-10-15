"""FastAPI application for CleanSlate.

Surface (deliberately small):

* ``GET  /api/health``                  - liveness plus tool availability
* ``GET  /api/v1/limits``               - live limits so the UI never invents numbers
* ``POST /api/v1/metadata/inspect``     - metadata inspection
* ``POST /api/v1/metadata/sanitize``    - sanitization + comparison + one-time download
* ``GET  /api/v1/download/{token}``     - single-use, expiring, IP-bound download

There is no fingerprint endpoint: browser signals never reach the server.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, exiftool, qpdf
from .config import Settings, get_settings
from .errors import ApiError, bad_request, not_found, rate_limited
from .formats import SPECS
from .jobs import JobStore, ip_key
from .logging_utils import hash_ip, log_event
from .models import (
    ErrorResponse,
    HealthResponse,
    InspectResponse,
    LimitsResponse,
    SanitizeOptionsModel,
    SanitizeResponse,
)
from .ratelimit import RateLimiter
from .security import BodySizeMiddleware, RequestIdMiddleware, SecurityHeadersMiddleware
from .service import PROCESSING_NOTICE, Options, inspect_upload, sanitize_upload
from .tools import ToolRunner

SERVICE_NAME = "cleanslate-api"


def client_ip(request: Request, settings: Settings) -> str | None:
    """Resolve the client IP, trusting proxy headers only when configured."""
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def error_response(status_code: int, code: str, message: str, request_id: str | None) -> JSONResponse:
    body = ErrorResponse.model_validate(
        {"error": {"code": code, "message": message}, "request_id": request_id}
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    jobs: JobStore = app.state.jobs
    runner: ToolRunner = app.state.runner

    purged = await jobs.prepare()
    sweeper = asyncio.create_task(jobs.sweep_loop())
    et_info = await exiftool.version(runner, settings.exiftool_path)
    log_event(
        "startup",
        status=settings.environment,
        engine="exiftool",
        engine_version=et_info.version,
        reason=f"purged={purged}",
    )
    try:
        yield
    finally:
        sweeper.cancel()
        try:
            await sweeper
        except asyncio.CancelledError:
            pass
        await jobs.shutdown()
        log_event("shutdown", status=settings.environment)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="CleanSlate API",
        version=__version__,
        description=(
            "Metadata inspection and sanitization for a public, no-login digital hygiene tool. "
            "No accounts, no database, no permanent storage."
        ),
        docs_url="/docs" if settings.expose_api_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.expose_api_docs else None,
        lifespan=lifespan,
    )

    runner = ToolRunner(Path(settings.temp_root))
    app.state.settings = settings
    app.state.runner = runner
    app.state.jobs = JobStore(
        Path(settings.temp_root),
        job_ttl_seconds=settings.job_ttl_seconds,
        token_ttl_seconds=settings.download_token_ttl_seconds,
        max_jobs=settings.max_concurrent_jobs,
        max_temp_bytes=settings.max_temp_bytes,
        bind_ip=settings.download_bind_ip,
        cleanup_interval_seconds=settings.cleanup_interval_seconds,
        secret=settings.secret_key,
    )
    app.state.limiter = RateLimiter(
        settings.rate_limit_requests, settings.rate_limit_window_seconds
    )

    # Middleware order: last added is outermost, so security headers wrap
    # everything (including CORS preflights and body-size rejections) and CORS
    # headers are added before the body gate can short-circuit.
    app.add_middleware(BodySizeMiddleware, settings=settings)
    if settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.allowed_origins),
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "Accept"],
            expose_headers=["X-Request-Id", "Retry-After"],
            allow_credentials=False,
            max_age=600,
        )
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)

    register_error_handlers(app)
    register_routes(app)
    return app


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        headers = dict(exc.headers or {})
        if exc.retry_after and "Retry-After" not in headers:
            headers["Retry-After"] = str(exc.retry_after)
        response = error_response(exc.status_code, exc.code, exc.message, _request_id(request))
        for key, value in headers.items():
            response.headers[key] = value
        return response

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            400, "invalid_request", "The request was malformed or missing required fields.",
            _request_id(request),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed", 413: "payload_too_large"}.get(
            exc.status_code, "request_failed"
        )
        message = {
            404: "Not found.",
            405: "This method is not allowed on this endpoint.",
            413: "The request body is too large.",
        }.get(exc.status_code, "The request could not be completed.")
        return error_response(exc.status_code, code, message, _request_id(request))

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Only the exception type is logged; no message, no traceback, no user data.
        log_event(
            "unhandled_error",
            route=request.url.path,
            reason=type(exc).__name__,
            status=500,
        )
        return error_response(
            500, "internal_error", "An internal error occurred. Please try again.", _request_id(request)
        )


def _request_id(request: Request) -> str | None:
    state = getattr(request, "state", None)
    return getattr(state, "request_id", None) if state else None


def register_routes(app: FastAPI) -> None:
    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, object]:
        return {
            "service": SERVICE_NAME,
            "version": __version__,
            "endpoints": [
                "/api/health",
                "/api/v1/limits",
                "/api/v1/metadata/inspect",
                "/api/v1/metadata/sanitize",
            ],
            "fingerprint_collection": False,
            "docs": "/docs" if app.state.settings.expose_api_docs else None,
        }

    @app.get("/api/health", response_model=HealthResponse)
    async def health(request: Request) -> HealthResponse:
        settings: Settings = request.app.state.settings
        runner: ToolRunner = request.app.state.runner
        jobs: JobStore = request.app.state.jobs
        et_info = await exiftool.version(runner, settings.exiftool_path)
        qpdf_info = await qpdf.version(runner, settings.qpdf_path)
        status = "ok" if et_info.available else "degraded"
        return HealthResponse(
            status=status,
            service=SERVICE_NAME,
            version=__version__,
            environment=settings.environment,
            time=datetime.now(tz=timezone.utc).isoformat(),
            tools={
                "exiftool": et_info.as_dict(),
                "qpdf": qpdf_info.as_dict(),
            },
            accepts_uploads=et_info.available,
            storage=jobs.stats(),
        )

    @app.get("/api/v1/limits", response_model=LimitsResponse)
    async def limits(request: Request) -> LimitsResponse:
        settings: Settings = request.app.state.settings
        accepted = [
            {
                "format": spec.fmt.value,
                "label": spec.label,
                "mime": spec.mime,
                "extensions": list(spec.extensions),
                "sanitizer": spec.sanitizer.value,
                "unverified_categories": list(spec.unverified),
                "notes": spec.notes,
            }
            for spec in SPECS.values()
        ]
        return LimitsResponse(
            max_upload_bytes=settings.max_upload_bytes,
            max_upload_mib=round(settings.max_upload_bytes / (1024 * 1024), 2),
            accepted_formats=accepted,
            job_ttl_seconds=settings.job_ttl_seconds,
            download_token_ttl_seconds=settings.download_token_ttl_seconds,
            rate_limit_requests=settings.rate_limit_requests,
            rate_limit_window_seconds=settings.rate_limit_window_seconds,
            download_bind_ip=settings.download_bind_ip,
            processing_notice=PROCESSING_NOTICE,
        )

    @app.post("/api/v1/metadata/inspect", response_model=InspectResponse)
    async def inspect_endpoint(
        request: Request, file: UploadFile = File(..., description="File to inspect")
    ) -> InspectResponse:
        settings, runner, jobs, ip_hash = _context(request, "inspect")
        try:
            return await asyncio.wait_for(
                inspect_upload(
                    upload=file, ip_hash=ip_hash, settings=settings, runner=runner, jobs=jobs
                ),
                timeout=settings.request_timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise ApiError(504, "processing_timeout", "Processing took too long and was stopped.") from None

    @app.post("/api/v1/metadata/sanitize", response_model=SanitizeResponse)
    async def sanitize_endpoint(
        request: Request,
        file: UploadFile = File(..., description="File to sanitize"),
        options: str | None = Form(None, description="JSON options object"),
    ) -> SanitizeResponse:
        settings, runner, jobs, ip_hash = _context(request, "sanitize")
        parsed = _parse_options(options)
        try:
            return await asyncio.wait_for(
                sanitize_upload(
                    upload=file,
                    options=parsed,
                    ip_hash=ip_hash,
                    settings=settings,
                    runner=runner,
                    jobs=jobs,
                ),
                timeout=settings.request_timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise ApiError(504, "processing_timeout", "Processing took too long and was stopped.") from None

    @app.get("/api/v1/download/{token}", include_in_schema=True)
    async def download_endpoint(request: Request, token: str) -> FileResponse:
        settings, _runner, jobs, ip_hash = _context(request, "download")
        job = await jobs.claim_token(token, ip_hash)
        path = job.download_path()
        filename = job.download_name or "cleanslate-sanitized.bin"
        log_event("download_ok", job=job.id[:8], format=job.format, status="ok", ip_hash=ip_hash)
        return FileResponse(
            path,
            media_type=job.download_mime or "application/octet-stream",
            filename=filename,
            headers={
                # Safe download headers: always an attachment, never sniffed,
                # never cached, and the smallest possible sandbox policy.
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
            },
            # The scratch directory (and with it the sanitized copy) is deleted
            # as soon as the response body has been sent.
            background=BackgroundTask(jobs.destroy, job),
        )


def _parse_options(raw: str | None) -> Options:
    if not raw:
        return Options()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise bad_request("The options field must be a JSON object.") from None
    try:
        model = SanitizeOptionsModel.model_validate(payload)
    except ValidationError:
        raise bad_request("The options field contained unsupported keys or values.") from None
    return Options(preserve_icc=model.preserve_icc, preserve_orientation=model.preserve_orientation)


def _context(request: Request, route: str):
    settings: Settings = request.app.state.settings
    runner: ToolRunner = request.app.state.runner
    jobs: JobStore = request.app.state.jobs
    limiter: RateLimiter = request.app.state.limiter
    ip = client_ip(request, settings)
    key = ip_key(ip, settings.secret_key)
    allowed, retry_after = limiter.check(key)
    if not allowed:
        log_event("rate_limited", route=route, ip_hash=key, status="blocked")
        raise rate_limited(retry_after)
    return settings, runner, jobs, key


app = create_app()
