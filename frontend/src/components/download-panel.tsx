import { Clock, Download, FileJson, FileText } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import type { SanitizeResponse } from "@/lib/api";
import { downloadUrl } from "@/lib/api";
import { countdownFrom, formatBytes, reportFilename } from "@/lib/format";
import {
  buildSanitizationReport,
  downloadHtml,
  downloadJson,
  renderReportHtml,
  type ReportOptions,
} from "@/lib/report";

export interface DownloadPanelProps {
  response: SanitizeResponse;
}

export function DownloadPanel({ response }: DownloadPanelProps) {
  const [now, setNow] = useState(() => new Date());
  const [includeValues, setIncludeValues] = useState(false);
  const [opened, setOpened] = useState(false);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  const reportOptions = useMemo<ReportOptions>(() => ({ includeMetadataValues: includeValues }), [includeValues]);
  const remaining = countdownFrom(response.retention.token_expires_at, now);
  const expired = remaining === "0:00";

  return (
    <Card id="download">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Download className="size-4 text-mint-400" aria-hidden />
          Download the sanitized copy
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <Button asChild disabled={expired} data-testid="download-sanitized">
            <a href={downloadUrl(response.download.path)} download={response.download.filename} rel="noopener">
              <Download />
              {response.download.filename} ({formatBytes(response.download.size_bytes)})
            </a>
          </Button>
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Clock className="size-3.5" aria-hidden />
            {expired
              ? "This link has expired and the temporary copy was deleted."
              : `Available for ${remaining} · single-use link, then deleted`}
          </span>
        </div>

        <p className="text-xs text-muted-foreground">
          The link is bound to your client address and can be used once. If a download fails, run the
          sanitization again: the server does not keep a spare copy.
        </p>

        <div className="rounded-md border border-border/60 bg-card/40 p-3">
          <label className="flex items-start justify-between gap-3 text-sm">
            <span>
              <span className="font-medium">Include metadata values in the report</span>
              <span className="mt-1 block text-xs text-muted-foreground">
                Off by default so the report does not become a fresh copy of the values that were just
                removed. Tag names and sensitivity are always recorded.
              </span>
            </span>
            <Switch
              checked={includeValues}
              onCheckedChange={setIncludeValues}
              aria-label="Include metadata values in the report"
              data-testid="include-values-switch"
            />
          </label>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            onClick={() =>
              downloadJson(
                reportFilename("sanitization", new Date()),
                buildSanitizationReport(response, reportOptions),
              )
            }
            data-testid="download-json-report"
          >
            <FileJson />
            Download JSON report
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              downloadHtml(
                reportFilename("sanitization", new Date()).replace(/\.json$/, ".html"),
                renderReportHtml(buildSanitizationReport(response, reportOptions)),
              );
              setOpened(true);
            }}
          >
            <FileText />
            Download printable HTML report
          </Button>
        </div>

        {opened ? (
          <p className="text-xs text-muted-foreground">
            The HTML report is a self-contained file: open it and use your browser's print dialog if you
            want a PDF.
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">
            Reports are generated in your browser from the response above. Nothing is uploaded to
            produce them.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
