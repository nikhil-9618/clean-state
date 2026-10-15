/** Small formatting helpers shared by pages, reports and tests. */

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "unknown";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KiB", "MiB", "GiB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

export function formatMib(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(bytes % (1024 * 1024) === 0 ? 0 : 1)} MB`;
}

/** Human countdown between now and an ISO timestamp; never negative. */
export function countdownFrom(isoTimestamp: string, now: Date = new Date()): string {
  const target = new Date(isoTimestamp).getTime();
  if (Number.isNaN(target)) return "unknown";
  const remaining = Math.max(0, Math.floor((target - now.getTime()) / 1000));
  const minutes = Math.floor(remaining / 60);
  const seconds = remaining % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function formatLocalTimestamp(value: Date = new Date()): string {
  return value.toISOString();
}

export function formatDisplayTimestamp(value: Date = new Date()): string {
  return value.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  });
}

export function truncateMiddle(value: string, head = 10, tail = 8): string {
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

/**
 * Safe filename for a downloaded report: no paths, no control characters and
 * never derived from the user's original file name.
 */
export function reportFilename(kind: "sanitization" | "inspection" | "fingerprint", stamp: Date): string {
  const iso = stamp.toISOString().replace(/[:.]/g, "-").replace("Z", "Z");
  return `cleanslate-${kind}-report-${iso}.json`;
}
