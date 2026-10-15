import { Loader2, Play, RotateCcw } from "lucide-react";
import type { ReactNode } from "react";

import { FilePicker } from "@/components/file-picker";
import { PrivacyNotice } from "@/components/privacy-notice";
import { ErrorBlock } from "@/components/state-blocks";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import type { JobStatus } from "@/hooks/use-metadata-job";
import { formatBytes } from "@/lib/format";

export interface UploadStageProps {
  file: File | null;
  onFile: (file: File | null) => void;
  acknowledged: boolean;
  onAcknowledged: (value: boolean) => void;
  maxBytes: number;
  acceptedExtensions: string[];
  retentionSeconds?: number | null;
  status: JobStatus;
  progress: number;
  error: Error | null;
  onStart: () => void;
  onReset: () => void;
  startLabel: string;
  processingLabel: string;
  rejectionMessage: string | null;
  onRejection: (message: string) => void;
  options?: ReactNode;
}

export function UploadStage({
  file,
  onFile,
  acknowledged,
  onAcknowledged,
  maxBytes,
  acceptedExtensions,
  retentionSeconds,
  status,
  progress,
  error,
  onStart,
  onReset,
  startLabel,
  processingLabel,
  rejectionMessage,
  onRejection,
  options,
}: UploadStageProps) {
  const busy = status === "uploading" || status === "processing";

  return (
    <div className="space-y-4">
      <FilePicker
        file={file}
        onFile={(next) => {
          onRejection("");
          onFile(next);
        }}
        maxBytes={maxBytes}
        acceptedExtensions={acceptedExtensions}
        disabled={busy}
        onRejection={onRejection}
      />

      {rejectionMessage ? (
        <p className="text-sm text-amber-200" data-testid="rejection-message">
          {rejectionMessage}
        </p>
      ) : null}

      <PrivacyNotice
        acknowledged={acknowledged}
        onAcknowledged={onAcknowledged}
        retentionSeconds={retentionSeconds}
      />

      {options}

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={onStart} disabled={!file || !acknowledged || busy} data-testid="start-job">
          {busy ? <Loader2 className="animate-spin" /> : <Play />}
          {busy ? processingLabel : startLabel}
        </Button>
        <Button variant="ghost" onClick={onReset} disabled={busy || status === "idle"}>
          <RotateCcw />
          Clear
        </Button>
        {file ? (
          <span className="text-xs text-muted-foreground">
            Selected: {file.name} · {formatBytes(file.size)}
          </span>
        ) : null}
        {!acknowledged && file ? (
          <span className="text-xs text-amber-200">
            Acknowledge the server-processing notice to enable the button.
          </span>
        ) : null}
      </div>

      {busy ? (
        <div className="space-y-2" data-testid="upload-progress">
          <Progress value={status === "processing" ? 100 : progress} />
          <p className="text-xs text-muted-foreground">
            {status === "uploading"
              ? `Uploading ${progress}%`
              : "Upload complete — the server is running the metadata engine now."}
          </p>
        </div>
      ) : null}

      {error ? <ErrorBlock error={error} onRetry={file ? onStart : undefined} /> : null}
    </div>
  );
}
