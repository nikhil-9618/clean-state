import { ArrowRight, FileSearch, Fingerprint, Lock, ServerCog, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";

import { SERVER_PROCESSING_NOTICE } from "@/components/privacy-notice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const FEATURES = [
  {
    icon: FileSearch,
    title: "Real metadata inspection",
    body: "ExifTool reads the file and every tag is grouped and labelled: GPS coordinates, serial numbers, author names, software versions, timestamps.",
  },
  {
    icon: ShieldCheck,
    title: "Sanitization with proof",
    body: "The sanitized copy is re-read and compared field by field with the original. Whatever cannot be verified is listed as unverified.",
  },
  {
    icon: Fingerprint,
    title: "Browser exposure report",
    body: "Screen, timezone, hardware hints, WebGL and an opt-in canvas test — read in your browser, explained, never transmitted.",
  },
];

export function HomePage() {
  return (
    <div className="relative">
      <div className="pointer-events-none absolute inset-0 surface-grid" aria-hidden />

      <section className="container relative py-16">
        <Badge variant="outline" className="mb-5">
          No account · no analytics · no permanent storage
        </Badge>
        <h1 className="max-w-3xl text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">
          Clean your files, then see what your browser <span className="text-mint-400">gives away</span>.
        </h1>
        <p className="mt-5 max-w-2xl text-muted-foreground">
          CleanSlate removes the metadata hidden inside your files with real tools, shows you the
          before/after difference, and reports the fingerprint signals any website can read. Everything is
          explained, nothing is oversold.
        </p>

        <div className="mt-8 flex flex-wrap gap-3">
          <Button size="lg" asChild>
            <Link to="/metadata/sanitize">
              Clean a file
              <ArrowRight />
            </Link>
          </Button>
          <Button size="lg" variant="secondary" asChild>
            <Link to="/metadata/inspect">
              Inspect first
              <ArrowRight />
            </Link>
          </Button>
          <Button size="lg" variant="ghost" asChild>
            <Link to="/fingerprint">Check browser exposure</Link>
          </Button>
        </div>

        <div className="mt-14 grid gap-6 md:grid-cols-3">
          {FEATURES.map((feature) => (
            <Card key={feature.title}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <feature.icon className="size-4 text-mint-400" aria-hidden />
                  {feature.title}
                </CardTitle>
                <CardDescription>{feature.body}</CardDescription>
              </CardHeader>
            </Card>
          ))}
        </div>
      </section>

      <section className="container relative pb-16">
        <h2 className="text-2xl font-semibold tracking-tight">Where your data goes</h2>

        <div className="mt-6 grid gap-6 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <ServerCog className="size-4 text-amber-300" aria-hidden />
                Files — processed on the server, then deleted
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-muted-foreground">
              <p className="text-amber-100">{SERVER_PROCESSING_NOTICE}</p>
              <ul className="list-disc space-y-1 pl-5">
                <li>Your original file is never modified; the server works on a private copy.</li>
                <li>Everything is deleted when you download it, or within minutes if you never do.</li>
                <li>No database, no accounts, no permanent retention, no logging of metadata values.</li>
              </ul>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Lock className="size-4 text-mint-400" aria-hidden />
                Browser signals — never leave your tab
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-muted-foreground">
              <ul className="list-disc space-y-1 pl-5">
                <li>No endpoint exists that could receive fingerprint signals.</li>
                <li>Nothing is written to cookies or browser storage.</li>
                <li>The canvas test runs only after you enable it; no uniqueness score is invented.</li>
              </ul>
              <p className="text-xs">
                Per-file details of what could not be verified are in{" "}
                <Link className="text-mint-400 hover:underline" to="/limitations">
                  limitations
                </Link>
                .
              </p>
            </CardContent>
          </Card>
        </div>
      </section>
    </div>
  );
}
