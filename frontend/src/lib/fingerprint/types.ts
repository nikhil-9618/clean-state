/** Types for the client-side browser exposure report. Nothing here is ever sent anywhere. */

export type Exposure = "common" | "notable" | "high";

export type ConsentLevel = "none" | "webgl" | "canvas";

export interface BrowserSignal {
  id: string;
  label: string;
  value: string;
  exposure: Exposure;
  /** Why this signal matters for linkability. */
  rationale: string;
  consent: ConsentLevel;
}

export interface SkippedSignal {
  id: string;
  label: string;
  reason: string;
}

export interface ExposureCounts {
  common: number;
  notable: number;
  high: number;
}

export interface FingerprintReport {
  version: 1;
  collectedAt: string;
  collectedIn: "browser";
  signals: BrowserSignal[];
  skipped: SkippedSignal[];
  counts: ExposureCounts;
  /** Explicitly null: CleanSlate has no reference population to compare against. */
  uniquenessScore: null;
  /** Set by the collector: it never performs a network request. */
  networkRequests: 0;
  consent: { webgl: boolean; canvas: boolean };
  disclaimer: string;
  limitations: string[];
}

export const EXPOSURE_LABELS: Record<Exposure, string> = {
  common: "Common",
  notable: "Notable",
  high: "High",
};

export const UNIQUENESS_DISCLAIMER =
  "CleanSlate does not display a uniqueness percentage, because a statistically valid one would " +
  "require a representative reference population that this application does not have. What you see " +
  "is a record of which signals your browser exposes, not a measure of how rare you are.";

export const FINGERPRINT_LIMITATIONS = [
  "Signals are read from the browser APIs that this page is allowed to call. Anything the browser " +
    "does not expose (or randomises) is not visible here.",
  "Browsers may report spoofed, reduced or randomised values (privacy modes, enterprise policies, " +
    "mobile WebViews), so a report can differ from what other sites observe.",
  "No reference population is available to CleanSlate, so no uniqueness or entropy score is computed.",
  "Nothing in this report is transmitted to the CleanSlate server, stored, or written to browser storage.",
];
