import { FileUp, FolderOpen, X } from "lucide-react";
import { useCallback, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface FilePickerProps {
  file: File | null;
  onFile: (file: File | null) => void;
  maxBytes: number;
  acceptedExtensions: string[];
  disabled?: boolean;
  onRejection?: (message: string) => void;
}

/**
 * Drop zone and picker. The size and extension checks here are convenience
 * only: the API re-validates everything by file content, because nothing a
 * browser says about a file can be trusted.
 */
export function FilePicker({
  file,
  onFile,
  maxBytes,
  acceptedExtensions,
  disabled = false,
  onRejection,
}: FilePickerProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const accept = acceptedExtensions.join(",");

  const accept_file = useCallback(
    (candidate: File | undefined) => {
      if (!candidate) return;
      if (candidate.size > maxBytes) {
        onRejection?.(
          `${candidate.name} is ${formatBytes(candidate.size)}, above this deployment's ${formatBytes(maxBytes)} limit.`,
        );
        return;
      }
      onFile(candidate);
    },
    [maxBytes, onFile, onRejection],
  );

  return (
    <div
      className={cn(
        "rounded-lg border-2 border-dashed border-border/80 bg-card/40 p-6 text-center transition-colors",
        dragging && "border-mint-500 bg-mint-500/5",
        disabled && "opacity-60",
      )}
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        if (disabled) return;
        accept_file(event.dataTransfer.files?.[0]);
      }}
      data-testid="file-picker"
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="sr-only"
        disabled={disabled}
        onChange={(event) => accept_file(event.target.files?.[0])}
        data-testid="file-input"
      />

      {file ? (
        <div className="flex flex-col items-center gap-3">
          <div className="flex items-center gap-2 text-sm">
            <FileUp className="size-4 text-mint-400" aria-hidden />
            <span className="font-medium">{file.name}</span>
            <span className="text-muted-foreground">{formatBytes(file.size)}</span>
          </div>
          <div className="flex flex-wrap items-center justify-center gap-2">
            <Button variant="outline" size="sm" onClick={() => inputRef.current?.click()} disabled={disabled}>
              <FolderOpen />
              Choose another file
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onFile(null)}
              disabled={disabled}
              aria-label="Remove selected file"
            >
              <X />
              Remove
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3">
          <FileUp className="size-8 text-mint-400" aria-hidden />
          <div>
            <p className="text-sm font-medium">Drop a file here, or choose one</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Up to {formatBytes(maxBytes)} · {acceptedExtensions.join(" ")}
            </p>
          </div>
          <Button variant="secondary" size="sm" onClick={() => inputRef.current?.click()} disabled={disabled}>
            <FolderOpen />
            Select file
          </Button>
        </div>
      )}
    </div>
  );
}
