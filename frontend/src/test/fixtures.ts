import type { InspectResponse, LimitsResponse, SanitizeResponse } from "@/lib/api";

const NOTICE =
  "Your file will be processed by the CleanSlate server. Temporary processing files are deleted " +
  "according to the configured cleanup policy. Do not upload highly sensitive files unless you " +
  "trust the hosting provider and understand its infrastructure access.";

export const RETENTION = {
  job_ttl_seconds: 300,
  token_expires_in_seconds: 300,
  token_expires_at: new Date(Date.now() + 300_000).toISOString(),
  single_use_download: true,
  bound_to_client_ip: true,
  server_side_processing: true as const,
  permanent_storage: false as const,
  policy:
    "Uploaded originals are deleted immediately after processing. A sanitized copy is kept only in the " +
    "per-job scratch directory until it is downloaded once or the job TTL expires, whichever comes first.",
};

export const FILE_INFO = {
  format: "jpeg",
  label: "JPEG image",
  mime: "image/jpeg",
  size_bytes: 1187,
  sha256: "a".repeat(64),
  extension: ".jpg",
  inspector_tags_read: 18,
  inspector_truncated: false,
  tool_warnings: null,
};

export const sanitizeResponse: SanitizeResponse = {
  job_id: "job-abc123xyz",
  file: FILE_INFO,
  sanitized_file: { ...FILE_INFO, label: "JPEG image (sanitized)", size_bytes: 812, sha256: "b".repeat(64) },
  engine: "exiftool",
  engine_notes: ["ExifTool 13.59: all deletable metadata groups removed (-all=)."],
  options: { preserve_icc: true, preserve_orientation: true },
  comparison: {
    removed: [
      {
        key: "GPS:GPSLatitude",
        group: "GPS",
        tag: "GPSLatitude",
        value: "51 deg 30' 26.64\" N",
        sensitivity: "high",
      },
      {
        key: "IFD0:Artist",
        group: "IFD0",
        tag: "Artist",
        value: "Alice Test",
        sensitivity: "high",
      },
    ],
    added: [],
    changed: [],
    retained: [
      {
        key: "IFD0:Orientation",
        group: "IFD0",
        tag: "Orientation",
        value: "Rotate 90 CW",
        sensitivity: "medium",
      },
    ],
    counts: { removed: 2, added: 0, changed: 0, retained: 1 },
    sensitive_removed: 2,
    sensitive_retained: 1,
  },
  structural_before: { findings: [], counters: { jpeg_trailing_bytes: 0 } },
  structural_after: { findings: [], counters: { jpeg_trailing_bytes: 0 } },
  unverified: [
    "Steganographic payloads and data hidden inside image sample bytes",
    "Adobe APP14 colour-transform marker (retained on purpose: it can affect how colours are decoded)",
  ],
  verification: {
    method:
      "The sanitized copy was re-read with the same metadata reader and the before/after tag maps were compared field by field.",
    engine: "exiftool",
    engine_versions: { exiftool: "13.59", qpdf: null },
    reinspection_tags_read: 6,
    metadata_removed_verified: true,
    structural_recheck: "passed",
    revision_history_rewritten: null,
    residual_risks: ["Steganographic payloads and data hidden inside image sample bytes"],
    retained_by_design: ["EXIF:Orientation (6)"],
    original_upload_deleted: true,
    notes: ["ExifTool 13.59: all deletable metadata groups removed (-all=)."],
  },
  download: {
    path: "/api/v1/download/token-abcdefghijklmnop",
    token: "token-abcdefghijklmnop",
    filename: "cleanslate-sanitized.jpg",
    mime: "image/jpeg",
    size_bytes: 812,
  },
  retention: RETENTION,
  notices: [NOTICE, "This is server-side processing, not local-only processing."],
};

export const inspectResponse: InspectResponse = {
  job_id: "job-inspect",
  file: FILE_INFO,
  metadata: [
    {
      key: "GPS:GPSLatitude",
      group: "GPS",
      tag: "GPSLatitude",
      value: "51 deg 30' 26.64\" N",
      sensitivity: "high",
    },
    { key: "IFD0:Artist", group: "IFD0", tag: "Artist", value: "Alice Test", sensitivity: "high" },
    { key: "IFD0:Software", group: "IFD0", tag: "Software", value: "FixtureWriter", sensitivity: "medium" },
  ],
  metadata_truncated: false,
  structural: {
    findings: [
      {
        id: "jpeg_trailing_data",
        category: "trailing_data",
        severity: "notice",
        detail: "24 bytes of data follow the last JPEG end-of-image marker.",
      },
    ],
    counters: { jpeg_soi_markers: 1, jpeg_eoi_markers: 1, jpeg_trailing_bytes: 24 },
  },
  sensitivity_counts: { high: 2, medium: 1, low: 0 },
  unverified: ["Steganographic payloads and data hidden inside image sample bytes"],
  retention: { ...RETENTION, token_expires_in_seconds: 0, token_expires_at: new Date().toISOString() },
  notices: [NOTICE, "Nothing was stored for this inspection."],
};

export const limitsResponse: LimitsResponse = {
  max_upload_bytes: 25 * 1024 * 1024,
  max_upload_mib: 25,
  accepted_formats: [
    {
      format: "jpeg",
      label: "JPEG image",
      mime: "image/jpeg",
      extensions: [".jpg", ".jpeg"],
      sanitizer: "exiftool",
      unverified_categories: ["Steganographic payloads"],
      notes: "",
    },
  ],
  job_ttl_seconds: 300,
  download_token_ttl_seconds: 300,
  rate_limit_requests: 30,
  rate_limit_window_seconds: 60,
  server_side_processing: true,
  fingerprint_collection: false,
  download_bind_ip: true,
  processing_notice: NOTICE,
};
