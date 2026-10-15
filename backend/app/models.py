"""Response models (pydantic). Field names are part of the public API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolsStatus(StrictModel):
    exiftool: dict[str, object]
    qpdf: dict[str, object]


class HealthResponse(StrictModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    environment: str
    time: str
    tools: ToolsStatus
    accepts_uploads: bool
    fingerprint_collection: Literal[False] = False
    storage: dict[str, object]


class LimitsResponse(StrictModel):
    max_upload_bytes: int
    max_upload_mib: float
    accepted_formats: list[dict[str, object]]
    job_ttl_seconds: int
    download_token_ttl_seconds: int
    rate_limit_requests: int
    rate_limit_window_seconds: int
    server_side_processing: Literal[True] = True
    fingerprint_collection: Literal[False] = False
    download_bind_ip: bool
    processing_notice: str


class FileInfo(StrictModel):
    format: str
    label: str
    mime: str
    size_bytes: int
    sha256: str
    extension: str
    inspector_tags_read: int
    inspector_truncated: bool
    tool_warnings: str | None = None


class TagEntryModel(StrictModel):
    key: str
    group: str
    tag: str
    value: str
    sensitivity: Literal["high", "medium", "low"]


class ChangedEntryModel(TagEntryModel):
    value_after: str


class ComparisonModel(StrictModel):
    removed: list[TagEntryModel]
    added: list[TagEntryModel]
    changed: list[ChangedEntryModel]
    retained: list[TagEntryModel]
    counts: dict[str, int]
    sensitive_removed: int
    sensitive_retained: int


class StructuralFindingModel(StrictModel):
    id: str
    category: str
    severity: str
    detail: str


class StructuralModel(StrictModel):
    findings: list[StructuralFindingModel]
    counters: dict[str, int]


class VerificationModel(StrictModel):
    method: str
    engine: str
    engine_versions: dict[str, str | None]
    reinspection_tags_read: int
    metadata_removed_verified: bool
    structural_recheck: Literal["passed", "flagged", "not_run"]
    revision_history_rewritten: bool | None = None
    residual_risks: list[str]
    retained_by_design: list[str]
    original_upload_deleted: bool
    notes: list[str]


class RetentionModel(StrictModel):
    job_ttl_seconds: int
    token_expires_in_seconds: int
    token_expires_at: str
    single_use_download: bool
    bound_to_client_ip: bool
    server_side_processing: bool
    permanent_storage: Literal[False] = False
    policy: str


class DownloadModel(StrictModel):
    path: str
    token: str
    filename: str
    mime: str
    size_bytes: int


class InspectResponse(StrictModel):
    job_id: str
    file: FileInfo
    metadata: list[TagEntryModel]
    metadata_truncated: bool
    structural: StructuralModel
    sensitivity_counts: dict[str, int]
    unverified: list[str]
    retention: RetentionModel
    notices: list[str]


class SanitizeResponse(StrictModel):
    job_id: str
    file: FileInfo
    sanitized_file: FileInfo
    engine: str
    engine_notes: list[str]
    options: dict[str, bool]
    comparison: ComparisonModel
    structural_before: StructuralModel
    structural_after: StructuralModel
    unverified: list[str]
    verification: VerificationModel
    download: DownloadModel
    retention: RetentionModel
    notices: list[str]


class ErrorBody(StrictModel):
    code: str
    message: str


class ErrorResponse(StrictModel):
    error: ErrorBody
    request_id: str | None = Field(default=None)


class SanitizeOptionsModel(BaseModel):
    """Options accepted from the multipart ``options`` field."""

    model_config = ConfigDict(extra="forbid")

    preserve_icc: bool = True
    preserve_orientation: bool = True
