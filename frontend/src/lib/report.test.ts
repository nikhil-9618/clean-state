import { describe, expect, it } from "vitest";

import { SERVER_PROCESSING_NOTICE } from "@/components/privacy-notice";
import {
  buildExposureReport,
  buildInspectionReport,
  buildSanitizationReport,
  escapeHtml,
  renderReportHtml,
} from "@/lib/report";
import { inspectResponse, sanitizeResponse } from "@/test/fixtures";
import { buildFingerprintReport } from "@/lib/fingerprint/collect";

describe("sanitization report accuracy", () => {
  it("mirrors the API counts instead of inventing numbers", () => {
    const report = buildSanitizationReport(sanitizeResponse, { includeMetadataValues: false });
    expect(report.summary).toEqual({
      removed: 2,
      retained: 1,
      changed: 0,
      added: 0,
      sensitive_removed: 2,
      sensitive_retained: 1,
    });
    expect((report.removed as unknown[]).length).toBe(2);
    expect((report.retained as unknown[]).length).toBe(1);
  });

  it("records the engine versions that were actually used", () => {
    const report = buildSanitizationReport(sanitizeResponse, { includeMetadataValues: false });
    expect(report.engine).toBe("exiftool");
    expect((report.verification as { engine_versions: Record<string, string> }).engine_versions.exiftool).toBe(
      "13.59",
    );
  });

  it("discloses server-side processing and the exact notice", () => {
    const report = buildSanitizationReport(sanitizeResponse, { includeMetadataValues: false });
    expect(report.generated_by.server_side_processing).toBe(true);
    expect(report.processing_notice).toBe(SERVER_PROCESSING_NOTICE);
  });

  it("excludes metadata values by default and includes them only on request", () => {
    const withoutValues = buildSanitizationReport(sanitizeResponse, { includeMetadataValues: false });
    const serialized = JSON.stringify(withoutValues);
    expect(serialized).not.toContain("Alice Test");
    expect(serialized).not.toContain("51 deg 30");

    const withValues = buildSanitizationReport(sanitizeResponse, { includeMetadataValues: true });
    expect(JSON.stringify(withValues)).toContain("Alice Test");
  });

  it("lists unverified categories in the same words as the API", () => {
    const report = buildSanitizationReport(sanitizeResponse, { includeMetadataValues: false });
    expect(report.unverified).toEqual(sanitizeResponse.unverified);
  });

  it("carries a disclaimer that rules out audit claims", () => {
    const report = buildSanitizationReport(sanitizeResponse, { includeMetadataValues: false });
    expect(String(report.disclaimer)).toContain("not a security audit");
  });
});

describe("inspection report", () => {
  it("keeps the structural findings and sensitivity counts", () => {
    const report = buildInspectionReport(inspectResponse, { includeMetadataValues: true });
    expect((report.metadata as unknown[]).length).toBe(3);
    expect(report.file).toMatchObject({ format: "jpeg", inspector_tags_read: 18 });
    expect((report.sensitivity_counts as Record<string, number>).high).toBe(2);
  });
});

describe("exposure report", () => {
  it("states that no signal left the browser", async () => {
    const fingerprint = await buildFingerprintReport({ canvasConsent: false });
    const report = buildExposureReport(fingerprint);
    expect(report.network_requests).toBe(0);
    expect(report.uniqueness_score).toBeNull();
    expect(String(report.notice)).toContain("transmitted to CleanSlate or to any third party");
    expect(report.generated_by.server_side_processing).toBe(false);
  });
});

describe("HTML rendering", () => {
  it("escapes hostile tag values so a report cannot execute script", () => {
    const hostile = structuredClone(sanitizeResponse);
    hostile.comparison.retained = [
      {
        key: "IFD0:Artist",
        group: "IFD0",
        tag: "Artist",
        value: "<script>alert('xss')</script>",
        sensitivity: "high",
      },
    ];

    const html = renderReportHtml(
      buildSanitizationReport(hostile, { includeMetadataValues: true }),
    );
    expect(html).not.toContain("<script>alert");
    expect(html).toContain("&lt;script&gt;");
  });

  it("escapes ampersands and quotes", () => {
    expect(escapeHtml(`A & B "quoted" <tag>`)).toBe("A &amp; B &quot;quoted&quot; &lt;tag&gt;");
  });

  it("renders the unverified section as a warning, not a footnote", () => {
    const html = renderReportHtml(
      buildSanitizationReport(sanitizeResponse, { includeMetadataValues: false }),
    );
    expect(html).toContain("Not verified / residual risk");
    expect(html).toContain("Steganographic payloads");
  });
});
