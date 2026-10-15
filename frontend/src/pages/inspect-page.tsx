import { FileSearch, FileJson, ScanSearch } from "lucide-react";
import { useCallback, useState } from "react";

import { ApiAvailabilityNotice } from "@/components/api-availability";
import { MetadataTable } from "@/components/metadata-table";
import { EmptyState, InlineNote } from "@/components/state-blocks";
import { StructuralFindings } from "@/components/structural-findings";
import { UnverifiedList } from "@/components/unverified-list";
import { UploadStage } from "@/components/upload-stage";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useMetadataJob } from "@/hooks/use-metadata-job";
import { useQuery } from "@/hooks/use-query";
import { fetchLimits, inspectFile, type InspectResponse } from "@/lib/api";
import { formatBytes, reportFilename, truncateMiddle } from "@/lib/format";
import { buildInspectionReport, downloadJson } from "@/lib/report";

export function InspectPage() {
  const limits = useQuery(fetchLimits, []);
  const job = useMetadataJob<InspectResponse>(inspectFile);
  const [file, setFile] = useState<File | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [rejection, setRejection] = useState<string | null>(null);

  const maxBytes = limits.data?.max_upload_bytes ?? 25 * 1024 * 1024;
  const extensions =
    limits.data?.accepted_formats.flatMap((format) => format.extensions) ??
    [".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".pdf", ".docx", ".xlsx", ".pptx", ".mp4", ".mov"];

  const start = useCallback(() => {
    if (!file) return;
    void job.run(file);
  }, [file, job]);

  const result = job.result;

  return (
    <div className="container space-y-8 py-10">
      <header className="space-y-3">
        <h1 className="text-3xl font-semibold tracking-tight">See what your file really carries</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Every tag in the file is read and grouped, with the fields most likely to identify you or a
          device flagged first: GPS coordinates, serial numbers, author names, software versions,
          timestamps. Inspection changes nothing.
        </p>
      </header>

      <ApiAvailabilityNotice />

      <Card>
        <CardHeader>
          <CardTitle>1. Choose a file</CardTitle>
          <CardDescription>
            Nothing is stored: no report is kept, nothing is written to a database, and the uploaded copy
            is deleted when the request finishes.
          </CardDescription>
        </CardHeader>
          <CardContent>
            <UploadStage
              file={file}
              onFile={setFile}
              acknowledged={acknowledged}
              onAcknowledged={setAcknowledged}
              maxBytes={maxBytes}
              acceptedExtensions={extensions}
              retentionSeconds={limits.data?.job_ttl_seconds ?? null}
              status={job.status}
              progress={job.progress}
              error={job.error}
              onStart={start}
              onReset={() => {
                job.reset();
                setFile(null);
              }}
              startLabel="Inspect metadata"
              processingLabel="Inspecting…"
              rejectionMessage={rejection}
              onRejection={setRejection}
            />
        </CardContent>
      </Card>

      {job.status === "idle" && !result ? (
        <EmptyState
          title="No inspection yet"
          description="Pick a JPEG, PNG, TIFF, WebP, PDF, Office document or MP4/MOV file. The report appears here with every metadata field CleanSlate could read from it."
          icon={<ScanSearch className="size-8" aria-hidden />}
        />
      ) : null}

      {result ? (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FileSearch className="size-4 text-mint-400" aria-hidden />
                {result.file.label}
              </CardTitle>
              <CardDescription>
                {formatBytes(result.file.size_bytes)} · {result.file.inspector_tags_read} tags read
                {result.metadata_truncated ? " · tag list truncated for safety" : ""}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4" data-inspect-summary>

              <div className="grid gap-3 sm:grid-cols-4">
                {(["high", "medium", "low"] as const).map((level) => (
                  <div key={level} className="rounded-md border border-border/60 bg-card/40 p-3">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">{level} risk</p>
                    <p className="stat-value">{result.sensitivity_counts[level] ?? 0}</p>
                  </div>
                ))}
                <div className="rounded-md border border-border/60 bg-card/40 p-3">
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Format</p>
                  <p className="stat-value">{result.file.format}</p>
                </div>
              </div>

              <InlineNote>
                SHA-256 of the inspected file:{" "}
                <code className="font-mono">{truncateMiddle(result.file.sha256, 16, 12)}</code>. Use it to
                confirm that a later sanitized copy corresponds to the same original.
              </InlineNote>

              {result.file.tool_warnings ? (
                <p className="text-xs text-amber-200">
                  Engine warning (paths removed): {result.file.tool_warnings}
                </p>
              ) : null}

              <div className="flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() =>
                    downloadJson(
                      reportFilename("inspection", new Date()),
                      buildInspectionReport(result, { includeMetadataValues: true }),
                    )
                  }
                >
                  <FileJson />
                  Download inspection report (JSON)
                </Button>
                <span className="self-center text-xs text-muted-foreground">
                  Generated in your browser; including values is your choice for an inspection.
                </span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Metadata fields</CardTitle>
              <CardDescription>
                Values are shown to you because they belong to your file. They are never written to the
                server log.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <MetadataTable entries={result.metadata} />
            </CardContent>
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Container checks</CardTitle>
                <CardDescription>
                  Structure-level findings, such as data appended after the image end marker or Office
                  revision history.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <StructuralFindings report={result.structural} />
              </CardContent>
            </Card>

            <UnverifiedList items={result.unverified} intro="Inspection is read-only, so nothing is removed yet. These are the categories that a sanitization run on this format cannot confirm:" />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Retention for this request</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">
              <p>{result.retention.policy}</p>
            </CardContent>
          </Card>
        </div>
      ) : null}
    </div>
  );
}
