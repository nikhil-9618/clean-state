/**
 * CleanSlate API client.
 *
 * Every response is validated with zod before it reaches the UI, so a changed
 * or unexpected payload surfaces as a clear error instead of silently rendering
 * invented data. Uploads use XMLHttpRequest only to expose real progress.
 *
 * There is no fingerprint endpoint here, and there never will be: browser
 * signals are collected and rendered entirely in the browser.
 */
import { z } from "zod";

import { API_BASE_URL, apiUrl } from "./env";

const sensitivitySchema = z.enum(["high", "medium", "low"]);

export const tagEntrySchema = z.object({
  key: z.string(),
  group: z.string(),
  tag: z.string(),
  value: z.string(),
  sensitivity: sensitivitySchema,
});

const changedEntrySchema = tagEntrySchema.extend({ value_after: z.string() });

export const fileInfoSchema = z.object({
  format: z.string(),
  label: z.string(),
  mime: z.string(),
  size_bytes: z.number(),
  sha256: z.string(),
  extension: z.string(),
  inspector_tags_read: z.number(),
  inspector_truncated: z.boolean(),
  tool_warnings: z.string().nullable().optional(),
});

export const structuralSchema = z.object({
  findings: z.array(
    z.object({
      id: z.string(),
      category: z.string(),
      severity: z.string(),
      detail: z.string(),
    }),
  ),
  counters: z.record(z.number()),
});

export const retentionSchema = z.object({
  job_ttl_seconds: z.number(),
  token_expires_in_seconds: z.number(),
  token_expires_at: z.string(),
  single_use_download: z.boolean(),
  bound_to_client_ip: z.boolean(),
  server_side_processing: z.boolean(),
  permanent_storage: z.literal(false),
  policy: z.string(),
});

export const comparisonSchema = z.object({
  removed: z.array(tagEntrySchema),
  added: z.array(tagEntrySchema),
  changed: z.array(changedEntrySchema),
  retained: z.array(tagEntrySchema),
  counts: z.record(z.number()),
  sensitive_removed: z.number(),
  sensitive_retained: z.number(),
});

export const verificationSchema = z.object({
  method: z.string(),
  engine: z.string(),
  engine_versions: z.record(z.string().nullable()),
  reinspection_tags_read: z.number(),
  metadata_removed_verified: z.boolean(),
  structural_recheck: z.enum(["passed", "flagged", "not_run"]),
  revision_history_rewritten: z.boolean().nullable(),
  residual_risks: z.array(z.string()),
  retained_by_design: z.array(z.string()),
  original_upload_deleted: z.boolean(),
  notes: z.array(z.string()),
});

export const inspectResponseSchema = z.object({
  job_id: z.string(),
  file: fileInfoSchema,
  metadata: z.array(tagEntrySchema),
  metadata_truncated: z.boolean(),
  structural: structuralSchema,
  sensitivity_counts: z.record(z.number()),
  unverified: z.array(z.string()),
  retention: retentionSchema,
  notices: z.array(z.string()),
});

export const sanitizeResponseSchema = z.object({
  job_id: z.string(),
  file: fileInfoSchema,
  sanitized_file: fileInfoSchema,
  engine: z.string(),
  engine_notes: z.array(z.string()),
  options: z.record(z.boolean()),
  comparison: comparisonSchema,
  structural_before: structuralSchema,
  structural_after: structuralSchema,
  unverified: z.array(z.string()),
  verification: verificationSchema,
  download: z.object({
    path: z.string(),
    token: z.string(),
    filename: z.string(),
    mime: z.string(),
    size_bytes: z.number(),
  }),
  retention: retentionSchema,
  notices: z.array(z.string()),
});

export const limitsResponseSchema = z.object({
  max_upload_bytes: z.number(),
  max_upload_mib: z.number(),
  accepted_formats: z.array(
    z.object({
      format: z.string(),
      label: z.string(),
      mime: z.string(),
      extensions: z.array(z.string()),
      sanitizer: z.string(),
      unverified_categories: z.array(z.string()),
      notes: z.string(),
    }),
  ),
  job_ttl_seconds: z.number(),
  download_token_ttl_seconds: z.number(),
  rate_limit_requests: z.number(),
  rate_limit_window_seconds: z.number(),
  server_side_processing: z.literal(true),
  fingerprint_collection: z.literal(false),
  download_bind_ip: z.boolean(),
  processing_notice: z.string(),
});

export const healthResponseSchema = z.object({
  status: z.enum(["ok", "degraded"]),
  service: z.string(),
  version: z.string(),
  environment: z.string(),
  time: z.string(),
  tools: z.object({
    exiftool: z.object({ available: z.boolean(), version: z.string().nullable() }),
    qpdf: z.object({ available: z.boolean(), version: z.string().nullable() }),
  }),
  accepts_uploads: z.boolean(),
  fingerprint_collection: z.literal(false),
  storage: z.record(z.number()),
});

export type TagEntry = z.infer<typeof tagEntrySchema>;
export type FileInfo = z.infer<typeof fileInfoSchema>;
export type StructuralReport = z.infer<typeof structuralSchema>;
export type Retention = z.infer<typeof retentionSchema>;
export type InspectResponse = z.infer<typeof inspectResponseSchema>;
export type SanitizeResponse = z.infer<typeof sanitizeResponseSchema>;
export type LimitsResponse = z.infer<typeof limitsResponseSchema>;
export type HealthResponse = z.infer<typeof healthResponseSchema>;
export type Comparison = z.infer<typeof comparisonSchema>;
export type Verification = z.infer<typeof verificationSchema>;

export interface SanitizeOptions {
  preserveIcc: boolean;
  preserveOrientation: boolean;
}

export type ErrorCode =
  | "network_error"
  | "timeout"
  | "aborted"
  | "invalid_response"
  | "payload_too_large"
  | "unsupported_file_type"
  | "unprocessable_file"
  | "rate_limited"
  | "tool_unavailable"
  | "processor_busy"
  | "processing_timeout"
  | "invalid_request"
  | "not_found"
  | "internal_error"
  | "http_error";

export class CleanSlateApiError extends Error {
  readonly code: ErrorCode;
  readonly status: number;
  readonly retryAfterSeconds: number | null;

  constructor(
    message: string,
    options: { code: ErrorCode; status: number; retryAfterSeconds?: number | null },
  ) {
    super(message);
    this.name = "CleanSlateApiError";
    this.code = options.code;
    this.status = options.status;
    this.retryAfterSeconds = options.retryAfterSeconds ?? null;
  }
}

const FRIENDLY: Partial<Record<ErrorCode, string>> = {
  payload_too_large: "That file is larger than this deployment accepts. Check the limit shown above.",
  unsupported_file_type: "This file type is not on the allowlist. Nothing was uploaded to permanent storage.",
  unprocessable_file: "The file could not be processed. It may be malformed or truncated.",
  rate_limited: "Too many requests from your connection. Wait a moment and try again.",
  tool_unavailable: "The metadata engine is temporarily unavailable on this instance.",
  processor_busy: "The processor is at capacity right now. Try again in a few seconds.",
  processing_timeout: "Processing took too long and was stopped. The temporary files were deleted.",
  invalid_request: "The request was rejected as malformed.",
  not_found: "That download link is invalid, already used, or expired.",
  internal_error: "The server hit an internal error. Nothing was stored.",
  http_error: "The request failed.",
  invalid_response: "The API returned a response this client does not understand.",
  network_error: "Could not reach the CleanSlate API. Check the connection and the configured API origin.",
  timeout: "The request timed out. Free hosting plans can cold-start slowly; retry once.",
  aborted: "The upload was cancelled.",
};

function codeForStatus(status: number, serverCode?: string): ErrorCode {
  const known: ErrorCode[] = [
    "payload_too_large",
    "unsupported_file_type",
    "unprocessable_file",
    "rate_limited",
    "tool_unavailable",
    "processor_busy",
    "processing_timeout",
    "invalid_request",
    "not_found",
    "internal_error",
  ];
  if (serverCode && (known as string[]).includes(serverCode)) return serverCode as ErrorCode;
  if (status === 413) return "payload_too_large";
  if (status === 415) return "unsupported_file_type";
  if (status === 422) return "unprocessable_file";
  if (status === 429) return "rate_limited";
  if (status === 503) return "tool_unavailable";
  if (status === 504) return "processing_timeout";
  if (status === 400) return "invalid_request";
  if (status === 404) return "not_found";
  return "http_error";
}

function errorFrom(status: number, body: string, retryAfter: number | null): CleanSlateApiError {
  let serverCode: string | undefined;
  let serverMessage: string | undefined;
  try {
    const parsed = z
      .object({ error: z.object({ code: z.string(), message: z.string() }) })
      .safeParse(JSON.parse(body));
    if (parsed.success) {
      serverCode = parsed.data.error.code;
      serverMessage = parsed.data.error.message;
    }
  } catch {
    serverMessage = undefined;
  }
  const code = codeForStatus(status, serverCode);
  const message = FRIENDLY[code] ?? serverMessage ?? FRIENDLY.http_error!;
  return new CleanSlateApiError(message, { code, status, retryAfterSeconds: retryAfter });
}

function parseRetryAfter(value: string | null): number | null {
  if (!value) return null;
  const seconds = Number.parseInt(value, 10);
  return Number.isFinite(seconds) ? seconds : null;
}

function validate<T>(schema: z.ZodType<T>, body: string): T {
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    throw new CleanSlateApiError(FRIENDLY.invalid_response!, {
      code: "invalid_response",
      status: 200,
    });
  }
  const result = schema.safeParse(parsed);
  if (!result.success) {
    throw new CleanSlateApiError(FRIENDLY.invalid_response!, {
      code: "invalid_response",
      status: 200,
    });
  }
  return result.data;
}

interface RawResponse {
  status: number;
  body: string;
  retryAfter: number | null;
}

export interface UploadOptions {
  onProgress?: (percent: number) => void;
  signal?: AbortSignal;
}

/** Upload timeout: generous enough for a free-tier cold start plus processing. */
const UPLOAD_TIMEOUT_MS = 180_000;

function sendForm(path: string, form: FormData, options: UploadOptions): Promise<RawResponse> {
  return new Promise<RawResponse>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", apiUrl(path), true);
    request.responseType = "text";
    request.timeout = UPLOAD_TIMEOUT_MS;

    request.upload.onprogress = (event) => {
      if (event.lengthComputable && options.onProgress) {
        options.onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      }
    };
    request.onload = () =>
      resolve({
        status: request.status,
        body: typeof request.response === "string" ? request.response : request.responseText,
        retryAfter: parseRetryAfter(request.getResponseHeader("Retry-After")),
      });
    request.onerror = () =>
      reject(new CleanSlateApiError(FRIENDLY.network_error!, { code: "network_error", status: 0 }));
    request.ontimeout = () =>
      reject(new CleanSlateApiError(FRIENDLY.timeout!, { code: "timeout", status: 0 }));
    request.onabort = () =>
      reject(new CleanSlateApiError(FRIENDLY.aborted!, { code: "aborted", status: 0 }));

    options.signal?.addEventListener("abort", () => request.abort(), { once: true });
    request.send(form);
  });
}

export async function inspectFile(
  file: File,
  options: UploadOptions = {},
): Promise<InspectResponse> {
  const form = new FormData();
  form.append("file", file, file.name);
  const response = await sendForm("/api/v1/metadata/inspect", form, options);
  if (response.status !== 200) throw errorFrom(response.status, response.body, response.retryAfter);
  return validate(inspectResponseSchema, response.body);
}

export async function sanitizeFile(
  file: File,
  sanitizeOptions: SanitizeOptions,
  options: UploadOptions = {},
): Promise<SanitizeResponse> {
  const form = new FormData();
  form.append("file", file, file.name);
  form.append(
    "options",
    JSON.stringify({
      preserve_icc: sanitizeOptions.preserveIcc,
      preserve_orientation: sanitizeOptions.preserveOrientation,
    }),
  );
  const response = await sendForm("/api/v1/metadata/sanitize", form, options);
  if (response.status !== 200) throw errorFrom(response.status, response.body, response.retryAfter);
  return validate(sanitizeResponseSchema, response.body);
}

async function getJson<T>(path: string, schema: z.ZodType<T>): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), { headers: { Accept: "application/json" } });
  } catch {
    throw new CleanSlateApiError(FRIENDLY.network_error!, { code: "network_error", status: 0 });
  }
  const body = await response.text();
  if (!response.ok) throw errorFrom(response.status, body, null);
  return validate(schema, body);
}

export function fetchLimits(): Promise<LimitsResponse> {
  return getJson("/api/v1/limits", limitsResponseSchema);
}

export function fetchHealth(): Promise<HealthResponse> {
  return getJson("/api/health", healthResponseSchema);
}

/** Absolute URL for the one-time download anchor. */
export function downloadUrl(path: string): string {
  return path.startsWith("http") ? path : `${API_BASE_URL}${path}`;
}
