import { Fingerprint, FileJson, Gauge, Play, Square, TriangleAlert } from "lucide-react";
import { useCallback, useState } from "react";

import { LocalOnlyNotice } from "@/components/privacy-notice";
import { EmptyState, InlineNote } from "@/components/state-blocks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import {
  buildFingerprintReport,
  collectBasicSignals,
  collectCanvasSignal,
  collectWebglSignal,
} from "@/lib/fingerprint/collect";
import { EXPOSURE_LABELS, type BrowserSignal, type FingerprintReport } from "@/lib/fingerprint/types";
import { reportFilename } from "@/lib/format";
import { buildExposureReport, downloadJson } from "@/lib/report";

function exposureVariant(exposure: BrowserSignal["exposure"]) {
  if (exposure === "high") return "high" as const;
  if (exposure === "notable") return "medium" as const;
  return "low" as const;
}

export function FingerprintPage() {
  const [report, setReport] = useState<FingerprintReport | null>(null);
  const [canvasConsent, setCanvasConsent] = useState(false);
  const [running, setRunning] = useState(false);

  const run = useCallback(async () => {
    setRunning(true);
    try {
      const next = await buildFingerprintReport({ canvasConsent });
      setReport(next);
    } finally {
      setRunning(false);
    }
  }, [canvasConsent]);

  // Preview of what runs without any consent, so the page is useful before the
  // optional canvas test is enabled. Read-only and network-free.
  const previewSignals = report ? report.signals : collectBasicSignals();

  return (
    <div className="container space-y-8 py-10">
      <header className="space-y-3">
        <h1 className="text-3xl font-semibold tracking-tight">What your browser tells every site</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          The signals browsers hand to ordinary pages, and what each one reveals. Everything runs in this
          tab: nothing is transmitted, nothing is written to cookies or storage, and the results disappear
          when you reload.
        </p>
      </header>

      <LocalOnlyNotice />

      <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Analysis controls</CardTitle>
            <CardDescription>
              The basic report needs no permission. The canvas test specifically requires your consent,
              because canvas rendering is the technique most often used to link devices.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <label className="flex items-start justify-between gap-3 rounded-md border border-border/60 bg-card/40 p-4 text-sm">
              <span>
                <span className="font-medium">Run the optional canvas rendering test</span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  Draws text and shapes onto an off-screen canvas and hashes the raster output locally. The
                  hash is shown to you and never sent anywhere. Leave it off and the test is skipped.
                </span>
              </span>
              <Switch
                checked={canvasConsent}
                onCheckedChange={setCanvasConsent}
                aria-label="Enable canvas rendering test"
                data-testid="canvas-consent"
              />
            </label>

            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={() => void run()} disabled={running} data-testid="run-fingerprint">
                {running ? <Square /> : <Play />}
                {running ? "Collecting…" : report ? "Run again" : "Run browser analysis"}
              </Button>
              {report ? (
                <Button
                  variant="secondary"
                  onClick={() =>
                    downloadJson(reportFilename("fingerprint", new Date()), buildExposureReport(report))
                  }
                  data-testid="download-fingerprint-report"
                >
                  <FileJson />
                  Download exposure report (JSON)
                </Button>
              ) : null}
              {report ? (
                <Button variant="ghost" onClick={() => setReport(null)}>
                  Clear results
                </Button>
              ) : null}
            </div>

            <InlineNote>
              WebGL renderer details are collected with disclosure rather than a consent gate, because any
              page can read them without asking. They are labelled as high exposure when the unmasked GPU
              strings are available.
            </InlineNote>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Gauge className="size-4 text-mint-400" aria-hidden />
              Exposure summary
            </CardTitle>
            <CardDescription>Counting signals by how strongly they narrow a population.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {(
              [
                ["high", "Usually narrow to a device or small group"],
                ["notable", "Contributes to device and region matching"],
                ["common", "Broadly shared, weak on its own"],
              ] as const
            ).map(([level, description]) => {
              const count = previewSignals.filter((signal) => signal.exposure === level).length;
              const webgl = collectWebglSignal();
              const included =
                level === "high" && webgl.signal?.exposure === "high" ? true : undefined;
              return (
                <div key={level} className="rounded-md border border-border/60 bg-card/40 p-3">
                  <div className="flex items-center justify-between">
                    <Badge variant={exposureVariant(level)}>{EXPOSURE_LABELS[level]}</Badge>
                    <span className="stat-value">{count + (included ? 1 : 0)}</span>
                  </div>
                  <p className="mt-1.5 text-xs text-muted-foreground">{description}</p>
                </div>
              );
            })}

            <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-100">
              <p className="flex items-center gap-2 font-medium">
                <TriangleAlert className="size-3.5" aria-hidden />
                No uniqueness percentage is shown
              </p>
              <p className="mt-1">
                A statistically valid uniqueness score needs a representative reference population.
                CleanSlate does not have one, so it does not invent a number.
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      {!report ? (
        <EmptyState
          title="Run the analysis to see the full report"
          description="The table below already shows the signals any page can read without permission. Running the analysis adds the WebGL detail and, if you enable it, the canvas hash."
          icon={<Fingerprint className="size-8" aria-hidden />}
        />
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Signal exposure report</CardTitle>
          <CardDescription>
            {report
              ? `Collected ${new Date(report.collectedAt).toLocaleTimeString()} · ${report.signals.length} signals · ${report.skipped.length} skipped · network requests: ${report.networkRequests}`
              : "Preview of the no-consent signals, read live from this browser."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <ul className="space-y-2">
            {previewSignals.map((signal) => (
              <li key={signal.id} className="rounded-md border border-border/60 bg-card/40 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{signal.label}</span>
                  <Badge variant={exposureVariant(signal.exposure)}>
                    {EXPOSURE_LABELS[signal.exposure]}
                  </Badge>
                  {signal.consent !== "none" ? <Badge variant="outline">{signal.consent} test</Badge> : null}
                </div>
                <p className="mt-1.5 break-words font-mono text-xs text-mint-300">{signal.value}</p>
                <p className="mt-1.5 text-xs text-muted-foreground">{signal.rationale}</p>
              </li>
            ))}
          </ul>

          {report && report.skipped.length > 0 ? (
            <div className="rounded-md border border-border/60 bg-card/30 p-3">
              <p className="text-sm font-medium">Skipped tests</p>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-xs text-muted-foreground">
                {report.skipped.map((item) => (
                  <li key={item.id}>
                    <span className="font-medium text-foreground">{item.label}</span>: {item.reason}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {!canvasConsent ? (
            <InlineNote>
              The canvas test is currently{" "}
              <span className="text-amber-200">disabled and will be reported as skipped</span>. Enable the
              switch above if you want that measurement.
            </InlineNote>
          ) : null}

          <details className="rounded-md border border-border/60 bg-card/30 p-3">
            <summary className="cursor-pointer text-xs text-muted-foreground">
              Limitations of this report
            </summary>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-muted-foreground">
              {(report?.limitations ?? [
                "Browsers may spoof or randomise these values, so results can differ from other sites.",
                "No reference population is available, so no uniqueness score is computed.",
              ]).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </details>
        </CardContent>
      </Card>
    </div>
  );
}

/** Re-exported for tests: the consent gate must be visible from the module. */
export { collectCanvasSignal };
