import { Eraser, ShieldCheck } from "lucide-react";
import { useCallback, useState } from "react";

import { ApiAvailabilityNotice } from "@/components/api-availability";
import { ComparisonView } from "@/components/comparison-view";
import { DownloadPanel } from "@/components/download-panel";
import { EmptyState } from "@/components/state-blocks";
import { StructuralFindings } from "@/components/structural-findings";
import { UnverifiedList } from "@/components/unverified-list";
import { UploadStage } from "@/components/upload-stage";
import { VerificationPanel } from "@/components/verification-panel";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { useMetadataJob } from "@/hooks/use-metadata-job";
import { useQuery } from "@/hooks/use-query";
import { fetchLimits, sanitizeFile, type SanitizeOptions, type SanitizeResponse } from "@/lib/api";
import { formatBytes } from "@/lib/format";

export function SanitizePage() {
  const limits = useQuery(fetchLimits, []);
  const [options, setOptions] = useState<SanitizeOptions>({ preserveIcc: true, preserveOrientation: true });
  const job = useMetadataJob<SanitizeResponse>((file, uploadOptions) =>
    sanitizeFile(file, options, uploadOptions),
  );
  const [file, setFile] = useState<File | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [rejection, setRejection] = useState<string | null>(null);

  const maxBytes = limits.data?.max_upload_bytes ?? 25 * 1024 * 1024;
  const extensions =
    limits.data?.accepted_formats.flatMap((format) => format.extensions) ?? [".jpg", ".png", ".pdf"];

  const start = useCallback(() => {
    if (!file) return;
    void job.run(file);
  }, [file, job]);

  const result = job.result;

  return (
    <div className="container space-y-8 py-10">
      <header className="space-y-3">
        <h1 className="text-3xl font-semibold tracking-tight">Remove metadata, keep the file usable</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          CleanSlate rewrites a copy of your file with the metadata engine, then re-reads the result and
          compares it field by field with the original. Your file on disk is never modified.
        </p>
      </header>

      <ApiAvailabilityNotice />

      <Card>
        <CardHeader>
          <CardTitle>1. Choose a file</CardTitle>
          <CardDescription>
          The uploaded original is deleted as soon as processing finishes; only the sanitized copy remains,
          until you download it once or it expires.
          </CardDescription>
        </CardHeader>
          <CardContent className="space-y-4">
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
              startLabel="Sanitize and compare"
              processingLabel="Sanitizing…"
              rejectionMessage={rejection}
              onRejection={setRejection}
              options={
                <div className="grid gap-3 rounded-md border border-border/60 bg-card/40 p-4 sm:grid-cols-2">
                  <label className="flex items-start justify-between gap-3 text-sm">
                    <span>
                      <span className="font-medium">Preserve orientation</span>
                      <span className="mt-1 block text-xs text-muted-foreground">
                        Re-writes the EXIF orientation value after deletion so rotated photos do not appear
                        sideways. No other EXIF field is restored.
                      </span>
                    </span>
                    <Switch
                      checked={options.preserveOrientation}
                      onCheckedChange={(value) =>
                        setOptions((previous) => ({ ...previous, preserveOrientation: value }))
                      }
                      aria-label="Preserve EXIF orientation"
                    />
                  </label>
                  <label className="flex items-start justify-between gap-3 text-sm">
                    <span>
                      <span className="font-medium">Preserve ICC colour profile</span>
                      <span className="mt-1 block text-xs text-muted-foreground">
                        Keeps colours stable by copying the embedded ICC profile back. Note that a profile
                        can contain a description string; turn this off for maximum removal.
                      </span>
                    </span>
                    <Switch
                      checked={options.preserveIcc}
                      onCheckedChange={(value) =>
                        setOptions((previous) => ({ ...previous, preserveIcc: value }))
                      }
                      aria-label="Preserve ICC colour profile"
                    />
                  </label>
                </div>
              }
            />
        </CardContent>
      </Card>

      {job.status === "idle" && !result ? (
        <EmptyState
          title="Nothing sanitized yet"
          description="The comparison view appears here: what was removed, what was kept, what changed, and an explicit list of what could not be verified."
          icon={<Eraser className="size-8" aria-hidden />}
        />
      ) : null}

      {result ? (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ShieldCheck className="size-4 text-mint-400" aria-hidden />
                Result summary
              </CardTitle>
              <CardDescription>
                {result.file.label} · {formatBytes(result.file.size_bytes)} →{" "}
                {formatBytes(result.sanitized_file.size_bytes)}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-5">
              {[
                { label: "Removed", value: result.comparison.removed.length },
                { label: "Retained", value: result.comparison.retained.length },
                { label: "Changed", value: result.comparison.changed.length },
                { label: "Added", value: result.comparison.added.length },
                { label: "Sensitive removed", value: result.comparison.sensitive_removed },
              ].map((item) => (
                <div key={item.label} className="rounded-md border border-border/60 bg-card/40 p-3">
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">{item.label}</p>
                  <p className="stat-value">{item.value}</p>
                </div>
              ))}
              </div>
              <p className="text-xs text-muted-foreground">
                Engine: {result.engine} · download link expires at{" "}
                {new Date(result.retention.token_expires_at).toLocaleTimeString()}
                {result.retention.bound_to_client_ip
                  ? " · single use, bound to your address" : " · single use"}.
              </p>
            </CardContent>
          </Card>

          <DownloadPanel response={result} />

          <Card>
            <CardHeader>
              <CardTitle>2. Before and after</CardTitle>
              <CardDescription>
                Computed from two real engine reads: the original file and the sanitized copy.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ComparisonView comparison={result.comparison} />
            </CardContent>
          </Card>

          <UnverifiedList items={result.unverified} />

          <div className="grid gap-6 lg:grid-cols-2">
            <VerificationPanel verification={result.verification} engineNotes={result.engine_notes} />
            <Card>
              <CardHeader>
                <CardTitle>Container checks on the sanitized copy</CardTitle>
                <CardDescription>
                  Re-run on the rewritten file, so trailer removal and PDF revision rebuilding are
                  observable rather than assumed.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <StructuralFindings report={result.structural_after} title="After sanitization" />
                <details>
                  <summary className="cursor-pointer text-xs text-muted-foreground">
                    Container findings before sanitization
                  </summary>
                  <div className="mt-2">
                    <StructuralFindings report={result.structural_before} />
                  </div>
                </details>
              </CardContent>
            </Card>
          </div>

        </div>
      ) : null}
    </div>
  );
}
