import { AlertTriangle, ShieldCheck } from "lucide-react";
import { Route, Routes } from "react-router-dom";

import { SiteFooter } from "@/components/layout/site-footer";
import { SiteHeader } from "@/components/layout/site-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { API_MISCONFIGURED } from "@/lib/env";
import { FingerprintPage } from "@/pages/fingerprint-page";
import { HomePage } from "@/pages/home-page";
import { InspectPage } from "@/pages/inspect-page";
import { LimitationsPage } from "@/pages/limitations-page";
import { NotFoundPage } from "@/pages/not-found-page";
import { PrivacyPage } from "@/pages/privacy-page";
import { SanitizePage } from "@/pages/sanitize-page";

export default function App() {
  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader />
      <main className="flex-1">
        {API_MISCONFIGURED ? (
          <div className="container mt-4">
            <Alert variant="warning">
              <AlertTriangle />
              <AlertTitle>This build has no API origin configured</AlertTitle>
              <AlertDescription>
                Set <code className="font-mono text-xs">VITE_API_BASE_URL</code> to the deployed API
                origin before building, otherwise uploads cannot reach the backend. Metadata tools are
                unavailable in this deployment; the browser exposure dashboard still works because it
                runs entirely in your browser.
              </AlertDescription>
            </Alert>
          </div>
        ) : null}
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/metadata/inspect" element={<InspectPage />} />
          <Route path="/metadata/sanitize" element={<SanitizePage />} />
          <Route path="/fingerprint" element={<FingerprintPage />} />
          <Route path="/limitations" element={<LimitationsPage />} />
          <Route path="/privacy" element={<PrivacyPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
        <div className="container pb-16">
          <Alert variant="info" className="mt-8">
            <ShieldCheck />
            <AlertTitle>No accounts, no analytics, no permanent storage</AlertTitle>
            <AlertDescription>
              CleanSlate has no login, no database, no advertising and no third-party requests. Metadata
              work is server-side and temporary; browser fingerprint analysis never leaves your browser.
            </AlertDescription>
          </Alert>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
