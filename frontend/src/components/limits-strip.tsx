import { Info } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import type { LimitsResponse } from "@/lib/api";
import { formatBytes } from "@/lib/format";

export interface LimitsStripProps {
  limits: LimitsResponse | null;
  loading: boolean;
  error: Error | null;
  /** Show the per-format support table (only used on the limitations page). */
  showFormats?: boolean;
}

/**
 * Compact statement of what this deployment accepts and how long it keeps
 * anything. Operator details (rate-limit counters, IP binding, engine names)
 * are intentionally not surfaced here.
 */
export function LimitsStrip({ limits, loading, error, showFormats = false }: LimitsStripProps) {
  if (error) {
    return (
      <Card className="border-amber-500/40">
        <CardContent className="p-4 text-sm text-amber-100">
          The service limits could not be read. Uploads are still validated by the server.
        </CardContent>
      </Card>
    );
  }

  const retention = limits ? Math.round(limits.job_ttl_seconds / 60) : null;
  const linkMinutes = limits ? Math.round(limits.download_token_ttl_seconds / 60) : null;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">Upload limits and retention</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {loading || !limits ? (
          <p className="text-muted-foreground">Reading limits…</p>
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">up to {formatBytes(limits.max_upload_bytes)} per file</Badge>
              <Badge variant="outline">deleted within {retention} min</Badge>
              <Badge variant="outline">download link: {linkMinutes} min, single use</Badge>
            </div>
            <p className="flex items-start gap-2 text-xs text-muted-foreground">
              <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              Nothing is stored permanently: the uploaded original is deleted when processing finishes and
              the sanitized copy disappears after one download or when it expires.
            </p>
          </>
        )}

        {showFormats && limits ? (
          <>
            <Separator />
            <div>
              <p className="mb-2 text-sm font-medium">Supported formats</p>
              <div className="space-y-2">
                {limits.accepted_formats.map((format) => (
                  <div key={format.format} className="rounded-md border border-border/60 bg-card/40 p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{format.label}</span>
                      <code className="font-mono text-xs text-muted-foreground">
                        {format.extensions.join(" ")}
                      </code>
                    </div>
                    {format.notes ? <p className="mt-1.5 text-xs">{format.notes}</p> : null}
                    {format.unverified_categories.length > 0 ? (
                      <details className="mt-2">
                        <summary className="cursor-pointer text-xs text-amber-200">
                          Not verified for this format ({format.unverified_categories.length})
                        </summary>
                        <ul className="mt-1 list-disc space-y-1 pl-5 text-xs text-muted-foreground">
                          {format.unverified_categories.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </details>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
