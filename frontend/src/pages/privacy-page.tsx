import { Cookie, Eye, Lock, Trash2 } from "lucide-react";

import { SERVER_PROCESSING_NOTICE } from "@/components/privacy-notice";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

export function PrivacyPage() {
  return (
    <div className="container space-y-8 py-10">
      <header className="space-y-3">
        <p className="text-xs uppercase tracking-[0.3em] text-mint-400">Privacy &amp; retention</p>
        <h1 className="text-3xl font-semibold tracking-tight">What CleanSlate collects: nothing personal</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          There is no account system, no database, no analytics, no advertising and no third-party script on
          this site. What remains is the honest description of how a file upload is handled.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Eye className="size-4 text-mint-400" aria-hidden />
              File processing
            </CardTitle>
            <CardDescription>Server-side, temporary, per job.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <p className="text-amber-100">{SERVER_PROCESSING_NOTICE}</p>
            <ul className="list-disc space-y-1 pl-5">
              <li>Each upload gets a private scratch directory created with mode 0700 and a random name.</li>
              <li>The uploaded original is deleted as soon as processing finishes, before you see the result.</li>
              <li>
                A sanitized copy is kept only for the single-use download window (five minutes by default),
                then deleted by the cleanup sweeper.
              </li>
              <li>Reports are generated in your browser; the server never stores a report.</li>
              <li>No database exists in this system, so there is nothing to breach later.</li>
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Lock className="size-4 text-mint-400" aria-hidden />
              Logging policy
            </CardTitle>
            <CardDescription>Operational counters only.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <p>The API logs, at most:</p>
            <ul className="list-disc space-y-1 pl-5">
              <li>an opaque job identifier and an HMAC-derived client key (never the raw IP address);</li>
              <li>format family, byte counts, durations, tool versions and outcome status;</li>
              <li>tag counts — not tag names or values.</li>
            </ul>
            <p>The API never logs:</p>
            <ul className="list-disc space-y-1 pl-5">
              <li>your file name or any client-supplied text;</li>
              <li>metadata values, GPS coordinates, or extracted document properties;</li>
              <li>download tokens, stack traces, or browser fingerprint signals.</li>
            </ul>
            <p>
              Tool warnings that a user sees are scrubbed of filesystem paths before they are returned.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Cookie className="size-4 text-mint-400" aria-hidden />
              Cookies, storage and fingerprinting
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <p>CleanSlate sets no cookies and writes nothing to local or session storage.</p>
            <p>
              The browser exposure dashboard reads signals locally, keeps them in page memory, and discards
              them when you reload or clear them. There is no fingerprint endpoint on the API — by design,
              not by policy.
            </p>
            <p>
              The site sets <code className="font-mono">Referrer-Policy: no-referrer</code> and a strict
              Content-Security-Policy with no third-party origins, so no external resource is loaded.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Trash2 className="size-4 text-mint-400" aria-hidden />
              Data retention summary
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <ul className="list-disc space-y-1 pl-5">
              <li>Uploaded original: deleted at the end of the request, always.</li>
              <li>Sanitized copy: until one download or the job TTL, whichever comes first.</li>
              <li>Reports and comparison data: kept only in your browser.</li>
              <li>Logs: operational counters, no user data, retained by the hosting provider per its own policy.</li>
              <li>Backups of uploaded files: none, because nothing is stored to begin with.</li>
            </ul>
          </CardContent>
        </Card>
      </div>

      <Separator />

      <p className="text-xs text-muted-foreground">
        One limitation worth stating plainly: because the API is a hosted service, the hosting provider's
        infrastructure administrators could in principle observe a file while it is being processed. If that
        is unacceptable for a given file, do not upload it.
      </p>
    </div>
  );
}
