/**
 * Report generation for inspections, sanitizations and browser exposure.
 *
 * Reports are produced in the browser from the API response that was just
 * displayed, so they cannot claim more than the server actually reported.
 * Including metadata values is opt-in: by default a report records tag names
 * and sensitivity only, so a downloaded file does not become a new copy of the
 * very metadata the user just removed.
 */
import { BUILD_INFO, API_BASE_URL } from "./env";
import { formatBytes } from "./format";
import type { InspectResponse, SanitizeResponse, TagEntry } from "./api";
import type { FingerprintReport } from "./fingerprint/types";

export interface ReportOptions {
  includeMetadataValues: boolean;
}

export interface ReportDocument {
  report_type: "metadata-inspection" | "metadata-sanitization" | "browser-exposure";
  report_version: 1;
  generated_at: string;
  generated_by: {
    app: string;
    version: string;
    generated_in: "browser";
    server_side_processing: boolean;
    api_origin: string | null;
  };
  [key: string]: unknown;
}

const REPORT_DISCLAIMER =
  "This report describes the result of one CleanSlate run. It is not a security audit, not a " +
  "penetration test, and not a guarantee that no identifying data remains: the 'unverified' section " +
  "lists exactly what this pipeline cannot confirm was removed.";

function tagEntry(entry: TagEntry, includeValues: boolean): Record<string, unknown> {
  return {
    group: entry.group,
    tag: entry.tag,
    sensitivity: entry.sensitivity,
    ...(includeValues ? { value: entry.value } : {}),
  };
}

export function buildInspectionReport(
  response: InspectResponse,
  options: ReportOptions,
  now: Date = new Date(),
): ReportDocument {
  return {
    report_type: "metadata-inspection",
    report_version: 1,
    generated_at: now.toISOString(),
    generated_by: {
      app: BUILD_INFO.appName,
      version: BUILD_INFO.version,
      generated_in: "browser",
      server_side_processing: response.retention.server_side_processing,
      api_origin: API_BASE_URL || null,
    },
    processing_notice: response.notices[0] ?? null,
    file: {
      format: response.file.format,
      label: response.file.label,
      size_bytes: response.file.size_bytes,
      sha256: response.file.sha256,
      inspector_tags_read: response.file.inspector_tags_read,
      inspector_truncated: response.file.inspector_truncated,
      tool_warnings: response.file.tool_warnings ?? null,
    },
    sensitivity_counts: response.sensitivity_counts,
    metadata: response.metadata.map((entry) => tagEntry(entry, options.includeMetadataValues)),
    metadata_values_included: options.includeMetadataValues,
    structural: response.structural,
    unverified: response.unverified,
    retention: response.retention,
    notices: response.notices,
    disclaimer: REPORT_DISCLAIMER,
  };
}

export function buildSanitizationReport(
  response: SanitizeResponse,
  options: ReportOptions,
  now: Date = new Date(),
): ReportDocument {
  const { comparison } = response;
  return {
    report_type: "metadata-sanitization",
    report_version: 1,
    generated_at: now.toISOString(),
    generated_by: {
      app: BUILD_INFO.appName,
      version: BUILD_INFO.version,
      generated_in: "browser",
      server_side_processing: response.retention.server_side_processing,
      api_origin: API_BASE_URL || null,
    },
    processing_notice: response.notices[0] ?? null,
    file: {
      format: response.file.format,
      label: response.file.label,
      size_bytes: response.file.size_bytes,
      sha256: response.file.sha256,
      inspector_tags_read: response.file.inspector_tags_read,
    },
    sanitized_file: {
      format: response.sanitized_file.format,
      size_bytes: response.sanitized_file.size_bytes,
      sha256: response.sanitized_file.sha256,
      inspector_tags_read: response.sanitized_file.inspector_tags_read,
      tool_warnings: response.sanitized_file.tool_warnings ?? null,
    },
    engine: response.engine,
    engine_notes: response.engine_notes,
    options: response.options,
    summary: {
      removed: comparison.counts.removed ?? comparison.removed.length,
      retained: comparison.counts.retained ?? comparison.retained.length,
      changed: comparison.counts.changed ?? comparison.changed.length,
      added: comparison.counts.added ?? comparison.added.length,
      sensitive_removed: comparison.sensitive_removed,
      sensitive_retained: comparison.sensitive_retained,
    },
    removed: comparison.removed.map((entry) => tagEntry(entry, options.includeMetadataValues)),
    retained: comparison.retained.map((entry) => tagEntry(entry, options.includeMetadataValues)),
    changed: comparison.changed.map((entry) => ({
      ...tagEntry(entry, options.includeMetadataValues),
      ...(options.includeMetadataValues ? { value_after: entry.value_after } : {}),
    })),
    added: comparison.added.map((entry) => tagEntry(entry, options.includeMetadataValues)),
    metadata_values_included: options.includeMetadataValues,
    structural: {
      before: response.structural_before.findings,
      after: response.structural_after.findings,
    },
    unverified: response.unverified,
    verification: response.verification,
    download: {
      filename_hint: response.download.filename,
      size_bytes: response.download.size_bytes,
      single_use: response.retention.single_use_download,
      expires_at: response.retention.token_expires_at,
    },
    retention: response.retention,
    notices: response.notices,
    disclaimer: REPORT_DISCLAIMER,
  };
}

export function buildExposureReport(
  report: FingerprintReport,
  now: Date = new Date(),
): ReportDocument {
  return {
    report_type: "browser-exposure",
    report_version: 1,
    generated_at: now.toISOString(),
    generated_by: {
      app: BUILD_INFO.appName,
      version: BUILD_INFO.version,
      generated_in: "browser",
      server_side_processing: false,
      api_origin: API_BASE_URL || null,
    },
    collected_at: report.collectedAt,
    consent: report.consent,
    uniqueness_score: null,
    network_requests: report.networkRequests,
    counts: report.counts,
    signals: report.signals.map((item) => ({
      id: item.id,
      label: item.label,
      value: item.value,
      exposure: item.exposure,
      rationale: item.rationale,
      consent: item.consent,
    })),
    skipped: report.skipped,
    disclaimer: report.disclaimer,
    limitations: report.limitations,
    notice:
      "This exposure report was produced entirely inside the browser. No signal in it was transmitted " +
      "to CleanSlate or to any third party.",
  };
}

export function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function rows(entries: unknown[], includeValuesKey: string[]): string {
  if (entries.length === 0) {
    return `<tr><td colspan="4" class="empty">none</td></tr>`;
  }
  return entries
    .map((entry) => {
      const record = entry as Record<string, unknown>;
      const cells = [
        escapeHtml(record.group),
        escapeHtml(record.tag),
        escapeHtml(record.sensitivity),
        ...includeValuesKey.map((key) => escapeHtml(record[key] ?? "")),
      ];
      return `<tr>${cells.map((cell) => `<td>${cell}</td>`).join("")}</tr>`;
    })
    .join("");
}

export function renderReportHtml(document: ReportDocument): string {
  const typed = document as ReportDocument & {
    summary?: Record<string, number>;
    removed?: unknown[];
    retained?: unknown[];
    changed?: unknown[];
    added?: unknown[];
    signals?: unknown[];
    unverified?: unknown[];
    limitations?: string[];
    engine_notes?: string[];
    verification?: { method?: string; engine?: string; engine_versions?: Record<string, string>; residual_risks?: string[]; retained_by_design?: string[]; notes?: string[] };
    file?: Record<string, unknown>;
    sanitized_file?: Record<string, unknown>;
    engine?: string;
    disclaimer?: string;
    skipped?: unknown[];
  };

  const valueColumns =
    "metadata_values_included" in document && document.metadata_values_included ? ["value"] : [];

  const limits = (typed.unverified ?? []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const limitations = (typed.limitations ?? []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const notes = (typed.engine_notes ?? []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const residual = (typed.verification?.residual_risks ?? [])
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
  const byDesign = (typed.verification?.retained_by_design ?? [])
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="referrer" content="no-referrer" />
<title>CleanSlate ${escapeHtml(document.report_type)} report</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; padding: 32px; background:#060B16; color:#E6EEF8; font-family: Inter, system-ui, sans-serif; line-height:1.55; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  h2 { font-size: 15px; text-transform: uppercase; letter-spacing:.08em; color:#7BF3D6; margin: 28px 0 8px; }
  .meta { color:#9FB3C8; font-size: 13px; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; margin-top: 8px; }
  th, td { border-bottom: 1px solid #1B2740; padding: 6px 8px; text-align: left; vertical-align: top; }
  th { color:#9FB3C8; font-weight: 600; }
  .empty { color:#7A8BA3; font-style: italic; }
  .callout { border:1px solid #22C7A4; background: rgba(62,233,192,0.06); padding: 12px 14px; border-radius: 10px; font-size: 13px; }
  .warn { border:1px solid #C77A22; background: rgba(233,192,62,0.07); padding: 12px 14px; border-radius: 10px; font-size: 13px; }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color:#5EEAD4; word-break: break-all; }
  ul { margin: 6px 0 0 18px; padding: 0; font-size: 13px; }
  .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(200px,1fr)); gap: 10px; margin-top: 8px; }
  .card { border:1px solid #1B2740; border-radius: 10px; padding: 10px 12px; }
  .card span { display:block; color:#9FB3C8; font-size: 11px; text-transform: uppercase; letter-spacing:.06em; }
  .card strong { font-size: 16px; color:#7BF3D6; }
</style>
</head>
<body>
  <h1>CleanSlate ${escapeHtml(document.report_type.replaceAll("-", " "))} report</h1>
  <p class="meta">
    Generated ${escapeHtml(document.generated_at)} by ${escapeHtml(document.generated_by.app)}
    ${escapeHtml(document.generated_by.version)} in the browser ·
    Server-side processing: <strong>${document.generated_by.server_side_processing ? "yes" : "no"}</strong> ·
    API origin: <code>${escapeHtml(document.generated_by.api_origin ?? "not configured")}</code>
  </p>

  ${
    typed.file
      ? `<h2>File</h2>
  <div class="grid">
    <div class="card"><span>Format</span><strong>${escapeHtml(typed.file.label)}</strong></div>
    <div class="card"><span>Size</span><strong>${escapeHtml(formatBytes(Number(typed.file.size_bytes ?? 0)))}</strong></div>
    <div class="card"><span>Metadata tags read</span><strong>${escapeHtml(typed.file.inspector_tags_read)}</strong></div>
  </div>
  <p class="meta">SHA-256 (original): <code>${escapeHtml(typed.file.sha256)}</code></p>`
      : ""
  }

  ${
    typed.sanitized_file
      ? `<p class="meta">SHA-256 (sanitized copy): <code>${escapeHtml(typed.sanitized_file.sha256)}</code></p>
  <p class="meta">Engine: <code>${escapeHtml(typed.engine ?? "unknown")}</code></p>`
      : ""
  }

  ${
    typed.summary
      ? `<h2>Summary</h2>
  <div class="grid">
    <div class="card"><span>Removed</span><strong>${escapeHtml(typed.summary.removed)}</strong></div>
    <div class="card"><span>Retained</span><strong>${escapeHtml(typed.summary.retained)}</strong></div>
    <div class="card"><span>Changed</span><strong>${escapeHtml(typed.summary.changed)}</strong></div>
    <div class="card"><span>Added</span><strong>${escapeHtml(typed.summary.added)}</strong></div>
    <div class="card"><span>Sensitive removed</span><strong>${escapeHtml(typed.summary.sensitive_removed)}</strong></div>
  </div>`
      : ""
  }

  ${
    typed.removed
      ? `<h2>Removed fields</h2>
  <table><thead><tr><th>Group</th><th>Tag</th><th>Sensitivity</th>${valueColumns.map((c) => `<th>${c}</th>`).join("")}</tr></thead>
  <tbody>${rows(typed.removed, valueColumns)}</tbody></table>`
      : ""
  }

  ${
    typed.retained && typed.retained.length > 0
      ? `<h2>Retained fields</h2>
  <table><thead><tr><th>Group</th><th>Tag</th><th>Sensitivity</th>${valueColumns.map((c) => `<th>${c}</th>`).join("")}</tr></thead>
  <tbody>${rows(typed.retained, valueColumns)}</tbody></table>`
      : ""
  }

  ${
    typed.changed && typed.changed.length > 0
      ? `<h2>Changed fields</h2>
  <table><thead><tr><th>Group</th><th>Tag</th><th>Sensitivity</th>${valueColumns.map((c) => `<th>${c}</th>`).join("")}</tr></thead>
  <tbody>${rows(typed.changed, valueColumns)}</tbody></table>`
      : ""
  }

  ${
    typed.signals
      ? `<h2>Browser signals</h2>
  <table><thead><tr><th>Signal</th><th>Value</th><th>Exposure</th><th>Why it matters</th></tr></thead><tbody>
  ${typed.signals
    .map((entry) => {
      const record = entry as Record<string, unknown>;
      return `<tr><td>${escapeHtml(record.label)}</td><td><code>${escapeHtml(record.value)}</code></td><td>${escapeHtml(record.exposure)}</td><td>${escapeHtml(record.rationale)}</td></tr>`;
    })
    .join("")}
  </tbody></table>`
      : ""
  }

  ${
    typed.skipped && typed.skipped.length > 0
      ? `<h2>Skipped</h2><ul>${typed.skipped
          .map((entry) => {
            const record = entry as Record<string, unknown>;
            return `<li>${escapeHtml(record.label)} — ${escapeHtml(record.reason)}</li>`;
          })
          .join("")}</ul>`
      : ""
  }

  ${notes ? `<h2>Engine notes</h2><ul>${notes}</ul>` : ""}
  ${typed.verification?.method ? `<h2>Verification</h2><p class="meta">${escapeHtml(typed.verification.method)}</p>` : ""}
  ${byDesign ? `<h2>Retained by design</h2><ul>${byDesign}</ul>` : ""}

  ${
    limits || residual
      ? `<h2>Not verified / residual risk</h2>
  <div class="warn">
    <p style="margin:0 0 6px">CleanSlate does not claim these were removed:</p>
    <ul>${limits}${residual}</ul>
  </div>`
      : ""
  }

  ${limitations ? `<h2>Limitations</h2><ul>${limitations}</ul>` : ""}

  <h2>Disclaimer</h2>
  <div class="callout">${escapeHtml(typed.disclaimer ?? REPORT_DISCLAIMER)}</div>
</body>
</html>`;
}

export function downloadJson(filename: string, data: unknown): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  triggerDownload(blob, filename);
}

export function downloadHtml(filename: string, html: string): void {
  const blob = new Blob([html], { type: "text/html" });
  triggerDownload(blob, filename);
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  // Give the browser a moment to start the download before revoking.
  setTimeout(() => URL.revokeObjectURL(url), 4_000);
}
