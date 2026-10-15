import { Info, ShieldAlert } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

/**
 * The exact notice the product promises to show before any upload. Kept as a
 * constant so tests can assert the wording and so no future refactor can soften
 * it accidentally.
 */
export const SERVER_PROCESSING_NOTICE =
  "Your file will be processed by the CleanSlate server. Temporary processing files are deleted " +
  "according to the configured cleanup policy. Do not upload highly sensitive files unless you " +
  "trust the hosting provider and understand its infrastructure access.";

export interface PrivacyNoticeProps {
  acknowledged: boolean;
  onAcknowledged: (value: boolean) => void;
  retentionSeconds?: number | null;
}

export function PrivacyNotice({ acknowledged, onAcknowledged, retentionSeconds }: PrivacyNoticeProps) {
  const retention =
    typeof retentionSeconds === "number" && retentionSeconds > 0
      ? `removed after the download, or within ${Math.round(retentionSeconds / 60)} minutes at the latest`
      : "removed as soon as the result is downloaded, or when the job expires";

  return (
    <Alert variant="warning" className="items-start">
      <ShieldAlert />
      <AlertTitle>Before you upload</AlertTitle>
      <AlertDescription className="space-y-2">
        <p className="text-sm text-amber-100">{SERVER_PROCESSING_NOTICE}</p>
        <p className="text-xs text-amber-100/75">
          This is not local-only processing — the file leaves your device and is held in a private per-job
          scratch directory on the API host while it is processed, then {retention}.
        </p>
        <label className="flex items-start gap-2 pt-1 text-sm text-foreground">
          <input
            type="checkbox"
            className="mt-0.5 size-4 accent-[#3EE9C0]"
            checked={acknowledged}
            onChange={(event) => onAcknowledged(event.target.checked)}
            data-testid="privacy-acknowledgement"
          />
          <span>I understand my file is sent to the CleanSlate server, and that it is never kept.</span>
        </label>
      </AlertDescription>
    </Alert>
  );
}

export function LocalOnlyNotice() {
  return (
    <Alert variant="info">
      <Info />
      <AlertTitle>This part runs entirely in your browser</AlertTitle>
      <AlertDescription>
        Fingerprint signals are read locally, rendered locally and never transmitted. This dashboard has
        nothing to send them to.
      </AlertDescription>
    </Alert>
  );
}
