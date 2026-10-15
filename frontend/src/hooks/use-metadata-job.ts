import { useCallback, useState } from "react";

import { CleanSlateApiError, type UploadOptions } from "@/lib/api";

export type JobStatus = "idle" | "uploading" | "processing" | "done" | "error";

export interface MetadataJobState<T> {
  status: JobStatus;
  progress: number;
  result: T | null;
  error: CleanSlateApiError | Error | null;
}

/**
 * Upload state machine shared by the inspection and sanitization pages.
 * The upload progress bar is driven by real XHR events; once the body is fully
 * sent the status switches to "processing" (a free-tier instance may still be
 * busy with ExifTool), so the UI never claims to be uploading when it is not.
 */
export function useMetadataJob<T>(
  runner: (file: File, options: UploadOptions) => Promise<T>,
) {
  const [state, setState] = useState<MetadataJobState<T>>({
    status: "idle",
    progress: 0,
    result: null,
    error: null,
  });

  const run = useCallback(
    async (file: File) => {
      setState({ status: "uploading", progress: 0, result: null, error: null });
      try {
        const result = await runner(file, {
          onProgress: (percent) =>
            setState((previous) => ({
              ...previous,
              progress: percent,
              status: percent >= 100 ? "processing" : "uploading",
            })),
        });
        setState({ status: "done", progress: 100, result, error: null });
        return result;
      } catch (error) {
        const failure =
          error instanceof Error ? error : new Error("The request failed for an unknown reason.");
        setState({ status: "error", progress: 0, result: null, error: failure });
        return null;
      }
    },
    [runner],
  );

  const reset = useCallback(() => {
    setState({ status: "idle", progress: 0, result: null, error: null });
  }, []);

  return { ...state, run, reset };
}
