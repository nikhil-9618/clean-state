"""Core workflow: validate -> inspect -> sanitize -> re-inspect -> compare -> report.

Cleanup rules enforced here:

* the uploaded original is deleted as soon as processing finishes, whether it
  succeeded or failed;
* the whole job directory is deleted on any failure (and on success for
  inspection, which keeps nothing);
* for sanitization the sanitized copy survives only until it is downloaded once
  or the job TTL expires (background sweeper).
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import anyio
from fastapi import UploadFile

from . import exiftool, qpdf
from .compare import compare, metadata_overview, unverified_categories
from .config import Settings
from .errors import cannot_process, payload_too_large, unsupported_media
from .exiftool import TagMap
from .formats import Format, FormatSpec, Sanitizer, safe_display_name, validate_upload
from .jobs import Job, JobStore
from .logging_utils import log_event
from .models import (
    ChangedEntryModel,
    ComparisonModel,
    DownloadModel,
    FileInfo,
    InspectResponse,
    RetentionModel,
    SanitizeResponse,
    StructuralFindingModel,
    StructuralModel,
    TagEntryModel,
    VerificationModel,
)
from .office import sanitize_ooxml, verify_ooxml
from .structural import StructuralReport, analyze
from .tools import ToolRunner, require_tool

CHUNK_SIZE = 1024 * 1024

PROCESSING_NOTICE = (
    "Your file will be processed by the CleanSlate server. Temporary processing files are deleted "
    "according to the configured cleanup policy. Do not upload highly sensitive files unless you "
    "trust the hosting provider and understand its infrastructure access."
)

RETENTION_POLICY = (
    "Uploaded originals are deleted immediately after processing. A sanitized copy is kept only in "
    "the per-job scratch directory until it is downloaded once or the job TTL expires, whichever "
    "comes first. Nothing is written to a database and no report is stored server-side."
)

_ORIENTATION_NUMBERS = {
    "horizontal (normal)": 1,
    "mirror horizontal": 2,
    "rotate 180": 3,
    "mirror vertical": 4,
    "mirror horizontal and rotate 270 cw": 5,
    "rotate 90 cw": 6,
    "mirror horizontal and rotate 90 cw": 7,
    "rotate 270 cw": 8,
}


@dataclass
class Prepared:
    spec: FormatSpec
    path: Path
    size: int
    sha256: str
    structural: StructuralReport
    display_name: str | None = None


@dataclass
class Options:
    preserve_icc: bool = True
    preserve_orientation: bool = True

    def as_dict(self) -> dict[str, bool]:
        return {
            "preserve_icc": self.preserve_icc,
            "preserve_orientation": self.preserve_orientation,
        }


@dataclass
class EngineOutcome:
    path: Path
    engine: str
    notes: list[str] = field(default_factory=list)
    versions: dict[str, str | None] = field(default_factory=dict)
    revision_history_rewritten: bool | None = None
    retained_by_design: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    residual_risks: list[str] = field(default_factory=list)
    # Set when the rewriting tool reported a genuine error (not one of the
    # warnings this pipeline already handles). Combined with an unchanged output
    # file it proves that no metadata was removed, which must never be reported
    # as a successful sanitization.
    tool_error: str | None = None


# TIFF cannot have its IFD0 block deleted by ExifTool (verified against 13.59), so
# metadata tags that survive `-all=` are deleted explicitly. Structural image
# tags must never be touched or the image breaks.
_TIFF_STRUCTURAL_TAGS = frozenset(
    {
        "ImageWidth", "ImageHeight", "BitsPerSample", "Compression",
        "PhotometricInterpretation", "StripOffsets", "SamplesPerPixel", "RowsPerStrip",
        "StripByteCounts", "PlanarConfiguration", "Predictor", "TileWidth", "TileLength",
        "TileOffsets", "TileByteCounts", "XResolution", "YResolution", "ResolutionUnit",
        "ColorMap", "ExtraSamples", "SampleFormat", "TransferFunction", "WhitePoint",
        "PrimaryChromaticities", "YCbCrCoefficients", "YCbCrSubSampling",
        "YCbCrPositioning", "ReferenceBlackWhite", "ExifOffset", "GPSInfo", "InteropOffset",
        "SubIFD", "SubIFD1", "ThumbnailOffset", "ThumbnailLength", "JPEGInterchangeFormat",
        "JPEGInterchangeFormatLength", "StripRowCounts", "FreeOffsets", "FreeByteCounts",
        "ImageLayer", "PixelScale", "ModelPixelScale", "ModelTiepoint", "GeoTiePoints",
        "ModelTransformation", "JPEGTables", "OcadRevisionDate", "OriginalFileName",
    }
)
_TIFF_METADATA_GROUPS = (
    "IFD0", "IFD1", "ExifIFD", "GPS", "InteropIFD", "SubIFD", "SubIFD1", "SubIFD2",
    "XMP", "IPTC", "Photoshop", "ICC_Profile",
)
_MP4_DATE_TAGS = (
    "CreateDate", "ModifyDate", "TrackCreateDate", "TrackModifyDate",
    "MediaCreateDate", "MediaModifyDate",
)


def _explicit_deletions(spec: FormatSpec, tags_before: TagMap, options: "Options") -> list[str]:
    """Extra `-Tag=` deletions for containers where `-all=` is not sufficient."""
    args: list[str] = []
    if spec.fmt is Format.TIFF:
        for key in sorted(tags_before.tags):
            group, _, tag = key.partition(":")
            if not any(group == prefix or group.startswith(prefix) for prefix in _TIFF_METADATA_GROUPS):
                continue
            if tag in _TIFF_STRUCTURAL_TAGS:
                continue
            if tag == "Orientation" and options.preserve_orientation:
                continue
            args.append(f"-{tag}=")
    elif spec.fmt is Format.MP4:
        present = {key.partition(":")[2] or key.partition(":")[0] for key in tags_before.tags}
        for tag in _MP4_DATE_TAGS:
            if tag in present:
                args.append(f"-{tag}=")
    return list(dict.fromkeys(args))


# --------------------------------------------------------------------------- #
# Upload intake
# --------------------------------------------------------------------------- #


async def prepare_upload(upload: UploadFile, job: Job, settings: Settings, jobs: JobStore) -> Prepared:
    staging = job.path / "upload.part"
    hasher = hashlib.sha256()
    total = 0
    with staging.open("wb") as handle:
        while True:
            chunk = await upload.read(CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > settings.max_upload_bytes:
                raise payload_too_large()
            hasher.update(chunk)
            await anyio.to_thread.run_sync(handle.write, chunk)

    spec = validate_upload(staging, total, upload.filename)
    structural = analyze(staging, spec)
    if structural.blocking:
        raise unsupported_media(
            "This file was rejected: the package expands far beyond its upload size "
            "(potential archive bomb)."
        )

    final = job.path / f"original{spec.extensions[0]}"
    await anyio.to_thread.run_sync(staging.replace, final)
    jobs.register_bytes(job, total)
    return Prepared(
        spec=spec,
        path=final,
        size=total,
        sha256=hasher.hexdigest(),
        structural=structural,
        display_name=safe_display_name(upload.filename),
    )


# --------------------------------------------------------------------------- #
# Sanitization engines
# --------------------------------------------------------------------------- #


async def _sanitize_exiftool(
    prepared: Prepared,
    destination: Path,
    settings: Settings,
    runner: ToolRunner,
    options: Options,
    tags_before: TagMap,
    et_version: str | None,
    *,
    drop_reversible_warning: bool = False,
) -> EngineOutcome:
    outcome = EngineOutcome(path=destination, engine="exiftool")
    outcome.versions["exiftool"] = et_version
    await anyio.to_thread.run_sync(_copy, prepared.path, destination)

    args = ["-all="]
    notes = [f"ExifTool {et_version or 'unknown'}: all deletable metadata groups removed (-all=)."]
    counters = prepared.structural.counters
    if counters.get("jpeg_trailing_bytes") or counters.get("png_trailing_bytes"):
        args.append("-Trailer:All=")
        notes.append("Trailing data after the image end marker was deleted (-Trailer:All=).")
    if prepared.spec.fmt is Format.TIFF:
        args.append("-CommonIFD0=")
        explicit = _explicit_deletions(prepared.spec, tags_before, options)
        args.extend(explicit)
        notes.append(
            f"TIFF keeps its IFD0 image block, so {len(explicit)} metadata tag(s) that survive -all= "
            "were deleted explicitly (structural image tags were left untouched)."
        )
    elif prepared.spec.fmt is Format.MP4:
        explicit = _explicit_deletions(prepared.spec, tags_before, options)
        args.extend(explicit)
        if explicit:
            notes.append(
                "QuickTime movie-header dates cannot be omitted, so they were zeroed "
                "(0000:00:00 00:00:00) instead of keeping the recording date."
            )

    if options.preserve_icc and prepared.spec.supports_icc:
        has_icc = any(key.startswith("ICC_Profile") for key in tags_before.tags)
        if has_icc:
            args += ["-tagsfromfile", "@", "-icc_profile"]
            notes.append(
                "ICC colour profile preserved so colours render unchanged. Note: ICC profiles can "
                "carry a profile description string."
            )
            outcome.retained_by_design.append("ICC colour profile (ICC_Profile)")

    exit_code, warning = await exiftool.write(
        runner, destination, args, configured_path=settings.exiftool_path,
        timeout=settings.exiftool_timeout_seconds,
    )
    if warning:
        if "icc_profile" in warning.lower():
            notes.append(
                "The ICC colour profile could not be preserved and was dropped, so colours may "
                "render differently."
            )
            outcome.residual_risks.append("ICC colour profile was dropped during rewriting")
        else:
            outcome.tool_error = warning
            outcome.warnings.append(f"ExifTool reported warnings: {warning}")
    if drop_reversible_warning:
        notes.append(
            "ExifTool warns that PDF metadata edits are reversible on their own; this pipeline "
            "follows that warning up with a qpdf --linearize rebuild."
        )

    if any("Thumbnail" in key for key in tags_before.tags) and prepared.spec.fmt is Format.TIFF:
        outcome.residual_risks.append(
            "Embedded thumbnail image data can remain inside a TIFF, because the IFD1 image block "
            "is image data rather than a deletable metadata tag."
        )

    orientation = _orientation_value(tags_before)
    if (
        options.preserve_orientation
        and prepared.spec.supports_orientation
        and orientation
        and orientation != 1
    ):
        exit_code, warning = await exiftool.write(
            runner,
            destination,
            [f"-Orientation#={orientation}"],
            configured_path=settings.exiftool_path,
            timeout=settings.exiftool_timeout_seconds,
        )
        notes.append(
            f"EXIF orientation ({orientation}) was restored after deletion so the image is not "
            "displayed rotated; no other EXIF tag was restored."
        )
        outcome.retained_by_design.append(f"EXIF:Orientation ({orientation})")
        if warning:
            outcome.warnings.append("Orientation could not be restored on this instance.")

    outcome.notes = notes
    return outcome


async def _sanitize_pdf(
    prepared: Prepared,
    destination: Path,
    settings: Settings,
    runner: ToolRunner,
    options: Options,
    tags_before: TagMap,
    et_version: str | None,
    qpdf_info,
) -> EngineOutcome:
    intermediate = destination.with_name(destination.name + ".exiftool")
    outcome = await _sanitize_exiftool(
        prepared,
        intermediate,
        settings,
        runner,
        options,
        tags_before,
        et_version,
        drop_reversible_warning=qpdf_info.available,
    )
    outcome.notes = [
        f"ExifTool {et_version or 'unknown'}: PDF Info dictionary and XMP metadata deleted from the "
        "current revision."
    ]
    versions = dict(outcome.versions)

    if qpdf_info.available:
        versions["qpdf"] = qpdf_info.version
        ok, note = await qpdf.linearize(
            runner,
            intermediate,
            destination,
            configured_path=settings.qpdf_path,
            timeout=settings.qpdf_timeout_seconds,
        )
        if ok:
            outcome.notes.append(
                f"qpdf {qpdf_info.version or ''}: --linearize rebuilt the PDF, so incremental-update "
                "revisions (which still contained the old metadata) are no longer present in the file.".strip()
            )
            intermediate.unlink(missing_ok=True)
            return EngineOutcome(
                path=destination,
                engine="exiftool+qpdf",
                notes=outcome.notes,
                versions=versions,
                revision_history_rewritten=True,
                retained_by_design=outcome.retained_by_design,
                warnings=outcome.warnings,
                residual_risks=outcome.residual_risks,
            )
        outcome.notes.append(f"qpdf did not rewrite the file ({note or 'unknown reason'}).")
        outcome.warnings.append("PDF revision history could not be verified as removed.")
        outcome.residual_risks.append("Earlier PDF revisions may remain recoverable in the file")
    else:
        outcome.notes.append(qpdf.unavailable_note())
        outcome.warnings.append("PDF revision history could not be verified as removed.")
        outcome.residual_risks.append("Earlier PDF revisions may remain recoverable in the file")
        versions["qpdf"] = None

    await anyio.to_thread.run_sync(_move, intermediate, destination)
    outcome.path = destination
    outcome.versions = versions
    outcome.revision_history_rewritten = False
    return outcome


async def _sanitize_ooxml(
    prepared: Prepared, destination: Path, et_version: str | None
) -> EngineOutcome:
    outcome = EngineOutcome(path=destination, engine="ooxml-repackage")
    outcome.versions = {"exiftool": et_version, "ooxml": "cleanslate-package-rebuild"}

    def _run() -> object:
        return sanitize_ooxml(prepared.path, destination)

    try:
        result = await anyio.to_thread.run_sync(_run)
    except Exception as exc:  # noqa: BLE001 - untrusted archive, report honestly
        log_event("ooxml_rebuild_failed", reason=type(exc).__name__, status="failed")
        raise cannot_process(
            "This Office package could not be rebuilt safely and was left unmodified. "
            "CleanSlate does not rewrite packages it cannot verify."
        ) from None
    removed_parts = list(getattr(result, "removed_parts", []))
    warnings = list(getattr(result, "warnings", []))

    ok, reason = await anyio.to_thread.run_sync(verify_ooxml, destination)
    if not ok:
        raise cannot_process(
            "The Office package could not be rebuilt safely: " + (reason or "integrity check failed")
        )

    outcome.notes = [
        "ExifTool reports OOXML (DOCX/XLSX/PPTX) as read-only, so CleanSlate rebuilt the ZIP package "
        "itself and removed the document-property parts, their relationships and their content-type "
        "overrides.",
        f"Removed package parts: {', '.join(removed_parts) if removed_parts else 'none present'}.",
        "All other package parts were copied byte-for-byte, so document content is unchanged.",
    ]
    for warning in warnings:
        outcome.warnings.append(warning)
    return outcome


async def _apply_sanitizer(
    prepared: Prepared,
    job: Job,
    settings: Settings,
    runner: ToolRunner,
    options: Options,
    tags_before: TagMap,
    et_version: str | None,
) -> EngineOutcome:
    spec = prepared.spec
    suffix = spec.extensions[0]
    if spec.sanitizer is Sanitizer.EXIFTOOL:
        return await _sanitize_exiftool(
            prepared, job.path / f"sanitized{suffix}", settings, runner, options, tags_before, et_version
        )
    if spec.sanitizer is Sanitizer.PDF_LAYER:
        qpdf_info = await qpdf.version(runner, settings.qpdf_path)
        return await _sanitize_pdf(
            prepared,
            job.path / f"sanitized{suffix}",
            settings,
            runner,
            options,
            tags_before,
            et_version,
            qpdf_info,
        )
    if spec.sanitizer is Sanitizer.OOXML:
        return await _sanitize_ooxml(prepared, job.path / f"sanitized{suffix}", et_version)
    raise cannot_process(
        "Metadata deletion is not supported for this file type. The file was left untouched."
    )


def _copy(source: Path, destination: Path) -> None:
    destination.write_bytes(source.read_bytes())


def _move(source: Path, destination: Path) -> None:
    source.replace(destination)


def _orientation_value(tags: TagMap) -> int | None:
    raw = next(
        (value for key, value in tags.tags.items() if key.partition(":")[2] == "Orientation" or key == "Orientation"),
        None,
    )
    if raw is None:
        return None
    text = raw.strip().lower()
    if text in _ORIENTATION_NUMBERS:
        return _ORIENTATION_NUMBERS[text]
    try:
        return int(text)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Public API operations
# --------------------------------------------------------------------------- #


async def inspect_upload(
    *,
    upload: UploadFile,
    ip_hash: str,
    settings: Settings,
    runner: ToolRunner,
    jobs: JobStore,
) -> InspectResponse:
    started = time.perf_counter()
    job = jobs.new_job(ip_hash)
    try:
        prepared = await prepare_upload(upload, job, settings, jobs)
        et_info = await require_tool(runner, "exiftool", settings.exiftool_path, exiftool.VERSION_ARGS)
        tags = await exiftool.inspect(
            runner,
            prepared.path,
            configured_path=settings.exiftool_path,
            timeout=settings.exiftool_timeout_seconds,
            tool_version=et_info.version,
        )
        now = time.time()
        metadata = metadata_overview(tags.tags)
        counts = {"high": 0, "medium": 0, "low": 0}
        for entry in metadata:
            counts[entry["sensitivity"]] += 1
        findings = prepared.structural.as_dict()["findings"]
        response = InspectResponse(
            job_id=job.id,
            file=FileInfo(
                format=prepared.spec.fmt.value,
                label=prepared.spec.label,
                mime=prepared.spec.mime,
                size_bytes=prepared.size,
                sha256=prepared.sha256,
                extension=prepared.spec.extensions[0],
                inspector_tags_read=tags.tag_count,
                inspector_truncated=tags.truncated,
                tool_warnings=tags.warnings,
            ),
            metadata=[TagEntryModel(**entry) for entry in metadata],
            metadata_truncated=tags.truncated,
            structural=StructuralModel(
                findings=[StructuralFindingModel(**finding) for finding in findings],
                counters=prepared.structural.counters,
            ),
            sensitivity_counts=counts,
            unverified=unverified_categories(
                prepared.spec, prepared.structural.as_dict()["findings"]
            ),
            retention=_retention(settings, now, now, token_ttl=0),
            notices=[
                PROCESSING_NOTICE,
                "Nothing was stored for this inspection: the uploaded copy was deleted when the "
                "response was produced. Browser-analysis results never leave your browser.",
            ],
        )
        log_event(
            "inspect_ok",
            job=job.id[:8],
            format=prepared.spec.fmt.value,
            tags=tags.tag_count,
            bytes=prepared.size,
            duration_ms=int((time.perf_counter() - started) * 1000),
            status="ok",
            ip_hash=ip_hash,
        )
        return response
    finally:
        await jobs.destroy(job)


async def sanitize_upload(
    *,
    upload: UploadFile,
    options: Options,
    ip_hash: str,
    settings: Settings,
    runner: ToolRunner,
    jobs: JobStore,
) -> SanitizeResponse:
    started = time.perf_counter()
    job = jobs.new_job(ip_hash)
    success = False
    try:
        prepared = await prepare_upload(upload, job, settings, jobs)
        et_info = await require_tool(runner, "exiftool", settings.exiftool_path, exiftool.VERSION_ARGS)
        tags_before = await exiftool.inspect(
            runner,
            prepared.path,
            configured_path=settings.exiftool_path,
            timeout=settings.exiftool_timeout_seconds,
            tool_version=et_info.version,
        )

        outcome = await _apply_sanitizer(
            prepared, job, settings, runner, options, tags_before, et_info.version
        )
        if not outcome.path.exists() or outcome.path.stat().st_size == 0:
            raise cannot_process("The sanitized copy could not be produced.")

        tags_after = await exiftool.inspect(
            runner,
            outcome.path,
            configured_path=settings.exiftool_path,
            timeout=settings.exiftool_timeout_seconds,
            tool_version=et_info.version,
        )
        structural_after = analyze(outcome.path, prepared.spec)
        diff = compare(tags_before.tags, tags_after.tags)

        sanitized_size = outcome.path.stat().st_size
        sanitized_hash = await anyio.to_thread.run_sync(_sha256, outcome.path)
        jobs.register_bytes(job, sanitized_size)

        # A byte-identical output combined with a real tool error means nothing
        # was removed. Reporting that as a sanitization would hand the user a
        # file that looks cleaned but is not, so the request fails instead.
        if sanitized_hash == prepared.sha256 and outcome.tool_error:
            raise cannot_process(
                "This file could not be sanitized: the metadata engine reported an error and "
                "left the file unchanged, so no metadata was removed. The file may be "
                "damaged or use a container variant the engine cannot rewrite."
            )

        job.format = prepared.spec.fmt.value
        job.engine = outcome.engine
        job.sanitized_path = outcome.path
        job.download_mime = prepared.spec.mime
        job.download_name = f"cleanslate-sanitized{prepared.spec.extensions[0]}"
        token, token_expires_at = jobs.issue_token(job, ip_hash)

        residual = unverified_categories(prepared.spec, structural_after.as_dict()["findings"])
        residual.extend(outcome.warnings)
        residual.extend(outcome.residual_risks)
        metadata_removed_verified = not outcome.warnings
        structural_recheck = (
            "flagged"
            if any(f.severity in {"notice", "warning"} for f in structural_after.findings)
            else "passed"
        )

        findings_before = prepared.structural.as_dict()["findings"]
        now = time.time()
        response = SanitizeResponse(
            job_id=job.id,
            file=FileInfo(
                format=prepared.spec.fmt.value,
                label=prepared.spec.label,
                mime=prepared.spec.mime,
                size_bytes=prepared.size,
                sha256=prepared.sha256,
                extension=prepared.spec.extensions[0],
                inspector_tags_read=tags_before.tag_count,
                inspector_truncated=tags_before.truncated,
                tool_warnings=tags_before.warnings,
            ),
            sanitized_file=FileInfo(
                format=prepared.spec.fmt.value,
                label=f"{prepared.spec.label} (sanitized)",
                mime=prepared.spec.mime,
                size_bytes=sanitized_size,
                sha256=sanitized_hash,
                extension=prepared.spec.extensions[0],
                inspector_tags_read=tags_after.tag_count,
                inspector_truncated=tags_after.truncated,
                tool_warnings=tags_after.warnings,
            ),
            engine=outcome.engine,
            engine_notes=outcome.notes,
            options=options.as_dict(),
            comparison=_comparison_model(diff.as_dict(), tags_before, tags_after),
            structural_before=StructuralModel(
                findings=[StructuralFindingModel(**finding) for finding in findings_before],
                counters=prepared.structural.counters,
            ),
            structural_after=StructuralModel(
                findings=[
                    StructuralFindingModel(**finding)
                    for finding in structural_after.as_dict()["findings"]
                ],
                counters=structural_after.counters,
            ),
            unverified=residual,
            verification=VerificationModel(
                method=(
                    "The sanitized copy was re-read with the same metadata reader and the "
                    "before/after tag maps were compared field by field."
                ),
                engine=outcome.engine,
                engine_versions=outcome.versions,
                reinspection_tags_read=tags_after.tag_count,
                metadata_removed_verified=metadata_removed_verified,
                structural_recheck=structural_recheck,
                revision_history_rewritten=outcome.revision_history_rewritten,
                residual_risks=residual,
                retained_by_design=outcome.retained_by_design,
                original_upload_deleted=True,
                notes=outcome.notes,
            ),
            download=DownloadModel(
                path=f"/api/v1/download/{token}",
                token=token,
                filename=job.download_name,
                mime=job.download_mime,
                size_bytes=sanitized_size,
            ),
            retention=_retention(settings, now, token_expires_at, token_ttl=settings.download_token_ttl_seconds),
            notices=[
                PROCESSING_NOTICE,
                "This is server-side processing, not local-only processing. The sanitized copy is "
                "temporary: download it once, then it is deleted.",
            ],
        )
        success = True
        log_event(
            "sanitize_ok",
            job=job.id[:8],
            format=prepared.spec.fmt.value,
            engine=outcome.engine,
            engine_version=outcome.versions.get("exiftool"),
            tags=tags_after.tag_count,
            removed=diff.as_dict()["counts"]["removed"],
            retained=diff.as_dict()["counts"]["retained"],
            bytes=sanitized_size,
            duration_ms=int((time.perf_counter() - started) * 1000),
            status="ok",
            ip_hash=ip_hash,
        )
        return response
    finally:
        # The uploaded original never outlives the request, success or failure.
        for stale in job.path.glob("original.*"):
            stale.unlink(missing_ok=True)
        (job.path / "upload.part").unlink(missing_ok=True)
        if not success:
            await jobs.destroy(job)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _comparison_model(payload: dict[str, object], before: TagMap, after: TagMap) -> ComparisonModel:
    return ComparisonModel(
        removed=[TagEntryModel(**entry) for entry in payload["removed"]],
        added=[TagEntryModel(**entry) for entry in payload["added"]],
        changed=[ChangedEntryModel(**entry) for entry in payload["changed"]],
        retained=[TagEntryModel(**entry) for entry in payload["retained"]],
        counts=dict(payload["counts"]),
        sensitive_removed=int(payload["sensitive_removed"]),
        sensitive_retained=int(payload["sensitive_retained"]),
    )


def _retention(
    settings: Settings, now: float, token_expires_at: float, *, token_ttl: int
) -> RetentionModel:
    return RetentionModel(
        job_ttl_seconds=settings.job_ttl_seconds,
        token_expires_in_seconds=token_ttl,
        token_expires_at=datetime.fromtimestamp(
            token_expires_at or now, tz=timezone.utc
        ).isoformat(),
        single_use_download=True,
        bound_to_client_ip=settings.download_bind_ip,
        server_side_processing=True,
        policy=RETENTION_POLICY,
    )
