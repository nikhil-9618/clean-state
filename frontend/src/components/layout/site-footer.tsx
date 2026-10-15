import { Link } from "react-router-dom";

import { Separator } from "@/components/ui/separator";

export function SiteFooter() {
  return (
    <footer className="border-t border-border/60 bg-navy-950/60">
      <div className="container py-10">
        <div className="grid gap-8 text-sm md:grid-cols-[1.4fr_1fr_1fr]">
          <div>
            <p className="font-semibold">
              Clean<span className="text-mint-400">Slate</span>
            </p>
            <p className="mt-2 text-muted-foreground">
              Metadata inspection and cleaning, plus a browser exposure report. No account, no analytics,
              no permanent storage.
            </p>
          </div>
          <div>
            <p className="font-semibold">Where processing happens</p>
            <ul className="mt-2 space-y-1 text-muted-foreground">
              <li>File metadata: on the server, then deleted.</li>
              <li>Fingerprint signals: only in your browser.</li>
              <li>Reports: created and kept by your browser.</li>
            </ul>
          </div>
          <div>
            <p className="font-semibold">Read before you upload</p>
            <ul className="mt-2 space-y-1">
              <li>
                <Link className="text-mint-400 hover:underline" to="/privacy">
                  Privacy &amp; data retention
                </Link>
              </li>
              <li>
                <Link className="text-mint-400 hover:underline" to="/limitations">
                  Limitations &amp; what is not verified
                </Link>
              </li>
            </ul>
          </div>
        </div>

        <Separator className="my-6" />

        <p className="text-xs text-muted-foreground">
          CleanSlate removes the metadata it can verify and lists the rest as unverified. No penetration
          test or third-party security audit has been performed on this deployment.
        </p>
      </div>
    </footer>
  );
}
