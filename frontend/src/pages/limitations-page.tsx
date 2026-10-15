import { AlertTriangle, CheckCircle2, Server, XCircle } from "lucide-react";

import { LimitsStrip } from "@/components/limits-strip";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useQuery } from "@/hooks/use-query";
import { fetchLimits } from "@/lib/api";

const VERIFIED = [
  "Metadata inspection and sanitization run through the real ExifTool binary (13.59 in this build) and qpdf for PDF revision rewriting.",
  "Automated tests build files with genuine metadata (GPS, author, software, dates, XMP, OOXML docProps, QuickTime user data) and assert removed/retained results against an independent ExifTool read of the downloaded file.",
  "Trailing-data removal, single-use download tokens, IP binding, expiry, rate limiting, CORS, security headers and cleanup after success and failure are covered by the automated suite.",
  "The original uploaded file is deleted on every path, success or failure, and the scratch directory is removed after the download.",
];

const NOT_VERIFIED = [
  "No penetration test and no third-party security audit has been performed on this deployment.",
  "PDF embedded file attachments, portfolios, hidden layers, annotations and JavaScript actions are detected at most, never removed.",
  "Office tracked changes, revision identifiers (w:rsid), comments and embedded OLE objects are preserved because they are document content, not docProps metadata.",
  "Steganographic payloads, data hidden inside image pixel data, and unknown vendor chunks in WebP/MP4 containers are not addressed.",
  "Video in-stream timed metadata and GPS tracks are not removed: only container-level metadata is rewritten.",
  "Free hosting instances may sleep or cold-start, which can add seconds to a request. Nothing is silently retried.",
];

export function LimitationsPage() {
  const limits = useQuery(fetchLimits, []);

  return (
    <div className="container space-y-8 py-10">
      <header className="space-y-3">
        <p className="text-xs uppercase tracking-[0.3em] text-mint-400">Limitations</p>
        <h1 className="text-3xl font-semibold tracking-tight">What this tool does, and what it does not</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Digital hygiene tools are often vague about their own coverage. CleanSlate is explicit: the lists
          below are the same ones the report uses per file.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CheckCircle2 className="size-4 text-mint-400" aria-hidden />
              Verified in this build
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="list-disc space-y-2 pl-5 text-sm text-muted-foreground">
              {VERIFIED.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <XCircle className="size-4 text-amber-300" aria-hidden />
              Not verified, or explicitly out of scope
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="list-disc space-y-2 pl-5 text-sm text-muted-foreground">
              {NOT_VERIFIED.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>

      <LimitsStrip
        limits={limits.data}
        loading={limits.status === "loading"}
        error={limits.error}
        showFormats
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server className="size-4 text-mint-400" aria-hidden />
            Free-hosting consequences you should know about
          </CardTitle>
          <CardDescription>
            The API runs on a free container plan. These are the real constraints of that choice.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <ul className="list-disc space-y-1 pl-5">
            <li>
              The instance can sleep when idle, so the first request after a pause may take noticeably
              longer. Uploads use a three-minute timeout to accommodate that cold start.
            </li>
            <li>
              Memory and CPU are small, which is why uploads are capped, processing is single-worker, and a
              job concurrency limit rejects extra work instead of queueing it.
            </li>
            <li>
              Rate limiting is enforced per running instance. It is a real control, not an illusion, but a
              multi-instance deployment would need a shared limiter.
            </li>
            <li>
              The container holds no cloud credentials and no application secrets beyond its own HMAC key,
              and it makes no outbound network calls. Where the provider cannot enforce network egress
              restrictions, that limitation is stated rather than papered over.
            </li>
          </ul>
        </CardContent>
      </Card>

      <Alert variant="warning">
        <AlertTriangle />
        <AlertTitle>Interpret results accordingly</AlertTitle>
        <AlertDescription>
          A successful CleanSlate run means: the metadata categories listed as removed are gone from the
          sanitized copy, verified by re-reading it. It does not mean the file is anonymous, and it does not
          mean the document is safe to publish.
        </AlertDescription>
      </Alert>
    </div>
  );
}
