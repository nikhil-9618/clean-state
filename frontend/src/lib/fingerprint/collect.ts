/**
 * Browser signal collection — client-side only.
 *
 * Rules enforced in this module:
 *   - no network access of any kind (no fetch, no XHR, no sendBeacon, no image
 *     beacons) and no writes to localStorage/sessionStorage/cookies;
 *   - high-effort techniques (canvas rendering) run only after explicit consent;
 *   - every signal carries a rationale so the report explains itself;
 *   - no uniqueness score is invented.
 */
import {
  FINGERPRINT_LIMITATIONS,
  UNIQUENESS_DISCLAIMER,
  type BrowserSignal,
  type ExposureCounts,
  type FingerprintReport,
  type SkippedSignal,
} from "./types";

interface Sources {
  navigator: Navigator;
  screen: Screen;
  window: Window;
}

function defaultSources(): Sources {
  return { navigator: window.navigator, screen: window.screen, window };
}

function safe<T>(read: () => T, fallback: T): T {
  try {
    const value = read();
    return value === undefined || value === null ? fallback : value;
  } catch {
    return fallback;
  }
}

function signal(
  id: string,
  label: string,
  value: string,
  exposure: BrowserSignal["exposure"],
  rationale: string,
  consent: BrowserSignal["consent"] = "none",
): BrowserSignal {
  return { id, label, value: value === "" ? "not exposed" : value, exposure, rationale, consent };
}

/** Signals that need no consent because the browser exposes them to every page. */
export function collectBasicSignals(sources: Sources = defaultSources()): BrowserSignal[] {
  const { navigator: nav, screen: scr } = sources;
  const signals: BrowserSignal[] = [];

  signals.push(
    signal(
      "user_agent",
      "User-Agent",
      safe(() => nav.userAgent, "not exposed"),
      "notable",
      "The full version string plus platform narrows your browser build, including minor versions that " +
        "differ between patch releases.",
    ),
  );

  const uaData = (nav as Navigator & { userAgentData?: { brands?: unknown[]; mobile?: boolean } })
    .userAgentData;
  if (uaData) {
    const brands = Array.isArray(uaData.brands)
      ? uaData.brands
          .map((brand) => (typeof brand === "object" && brand !== null ? String((brand as { brand?: string }).brand) : ""))
          .filter(Boolean)
          .join(", ")
      : "not exposed";
    signals.push(
      signal(
        "user_agent_data",
        "User-Agent Client Hints (brands)",
        `${brands}${uaData.mobile ? " · mobile" : ""}`,
        "notable",
        "Client hints are designed to replace the raw UA string, but the brand list and mobile flag are " +
          "still a stable, high-cardinality combination.",
      ),
    );
  } else {
    signals.push(
      signal(
        "user_agent_data",
        "User-Agent Client Hints (brands)",
        "not exposed by this browser",
        "common",
        "This browser does not implement the hints API, which removes one identifying surface.",
      ),
    );
  }

  signals.push(
    signal(
      "screen",
      "Screen & viewport",
      safe(
        () => `${scr.width}×${scr.height} (available ${scr.availWidth}×${scr.availHeight})`,
        "not exposed",
      ),
      "notable",
      "Screen dimensions combine with zoom level and window size to form a distinctive device profile.",
    ),
  );

  signals.push(
    signal(
      "pixel_ratio",
      "Device pixel ratio",
      safe(() => String(window.devicePixelRatio), "not exposed"),
      "common",
      "Useful for display classification, but shared by many devices of the same class.",
    ),
  );

  signals.push(
    signal(
      "color_depth",
      "Colour depth",
      safe(() => `${scr.colorDepth}-bit`, "not exposed"),
      "common",
      "Rarely unique on its own; supports device classification rather than identification.",
    ),
  );

  signals.push(
    signal(
      "language",
      "Languages",
      safe(() => [nav.language, ...(nav.languages ?? [])].filter(Boolean).join(", "), "not exposed"),
      "notable",
      "Language preference ordering is personal and stable across sessions.",
    ),
  );

  const timezone = safe(() => Intl.DateTimeFormat().resolvedOptions().timeZone, "not exposed");
  const offsetMinutes = safe(() => -new Date().getTimezoneOffset(), Number.NaN);
  signals.push(
    signal(
      "timezone",
      "Timezone",
      Number.isNaN(offsetMinutes)
        ? timezone
        : `${timezone} (UTC${offsetMinutes >= 0 ? "+" : "−"}${String(Math.abs(Math.trunc(offsetMinutes / 60))).padStart(2, "0")}:${String(Math.abs(offsetMinutes % 60)).padStart(2, "0")})`,
      "high",
      "Timezone plus language is one of the strongest coarse location signals, and it narrows the " +
        "candidate population to a region and even a specific hour offset.",
    ),
  );

  signals.push(
    signal(
      "platform",
      "Platform hint",
      safe(() => (nav as Navigator & { platform?: string }).platform || "not exposed", "not exposed"),
      "notable",
      "The platform string separates operating-system families and is retained in saved profiles.",
    ),
  );

  signals.push(
    signal(
      "hardware_concurrency",
      "CPU threads",
      safe(() => `${nav.hardwareConcurrency ?? "unknown"} logical cores`, "not exposed"),
      "notable",
      "CPU class is stable for the life of the device and feeds device-linking heuristics.",
    ),
  );

  const deviceMemory = (nav as Navigator & { deviceMemory?: number }).deviceMemory;
  signals.push(
    signal(
      "device_memory",
      "Device memory hint",
      deviceMemory ? `approximately ${deviceMemory} GB` : "not exposed by this browser",
      deviceMemory ? "notable" : "common",
      "Memory class narrows the device model family; Chromium-based browsers only expose it in coarse buckets.",
    ),
  );

  signals.push(
    signal(
      "touch",
      "Touch support",
      safe(
        () =>
          `maxTouchPoints=${nav.maxTouchPoints ?? 0}, ontouchstart=${"ontouchstart" in window ? "yes" : "no"}`,
        "not exposed",
      ),
      "common",
      "Separates pointer types and device categories (desktop versus tablet or phone).",
    ),
  );

  signals.push(
    signal(
      "cookies",
      "Cookie availability",
      safe(() => (nav.cookieEnabled ? "cookies enabled" : "cookies blocked"), "not exposed"),
      "common",
      "Reported for transparency. This page sets no cookies, and this check only reads the browser flag " +
        "without writing one.",
    ),
  );

  signals.push(
    signal(
      "storage",
      "Storage availability",
      describeStorage(),
      "common",
      "Shown because storage access enables persistent linking when a site chooses to use it. CleanSlate " +
        "never writes to local or session storage.",
    ),
  );

  signals.push(
    signal(
      "privacy_signals",
      "Privacy preferences",
      safe(
        () =>
          [
            (nav as Navigator & { globalPrivacyControl?: boolean }).globalPrivacyControl
              ? "Global Privacy Control: on"
              : "Global Privacy Control: not set",
            nav.doNotTrack ? `Do Not Track: ${nav.doNotTrack}` : "Do Not Track: not set",
          ].join(" · "),
        "not reported",
      ),
      "common",
      "These are opt-out signals a browser sends; sites are not obliged to honour them, and DNT is " +
        "deprecated in most browsers.",
    ),
  );

  signals.push(
    signal(
      "prefers",
      "Accessibility & display preferences",
      describePreferences(),
      "common",
      "Reduced-motion and colour-scheme preferences leak little on their own, but are per-user settings.",
    ),
  );

  signals.push(
    signal(
      "webdriver",
      "Automation flag",
      safe(
        () => ((nav as Navigator & { webdriver?: boolean }).webdriver ? "webdriver: present" : "webdriver: absent"),
        "not exposed",
      ),
      "common",
      "Indicates a scripted browser. Informational for a human visitor.",
    ),
  );

  return signals;
}

function describeStorage(): string {
  try {
    const local = typeof localStorage !== "undefined";
    const session = typeof sessionStorage !== "undefined";
    const cookie = window.navigator.cookieEnabled;
    return `localStorage=${local ? "available" : "blocked"}, sessionStorage=${session ? "available" : "blocked"}, cookies=${cookie ? "available" : "blocked"}`;
  } catch {
    return "storage access blocked by the browser";
  }
}

function describePreferences(): string {
  try {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    return `reduced-motion=${reduced ? "reduce" : "no-preference"}, colour-scheme=${dark ? "dark" : "light"}`;
  } catch {
    return "not exposed";
  }
}

export interface WebglResult {
  signal: BrowserSignal | null;
  skipped: SkippedSignal | null;
}

/**
 * WebGL details are collected with disclosure (no consent gate): the browser
 * exposes them to any page, and the report labels the unmasked renderer string
 * as a high-exposure signal.
 */
export function collectWebglSignal(targetWindow: Window = window): WebglResult {
  try {
    const canvas = targetWindow.document.createElement("canvas");
    const context =
      (canvas.getContext("webgl") as WebGLRenderingContext | null) ??
      (canvas.getContext("experimental-webgl") as WebGLRenderingContext | null);
    if (!context) {
      return {
        signal: null,
        skipped: {
          id: "webgl",
          label: "WebGL renderer",
          reason: "WebGL is unavailable or disabled in this browser.",
        },
      };
    }
    const debugInfo = context.getExtension("WEBGL_debug_renderer_info");
    const vendor = String(context.getParameter(context.VENDOR) ?? "unknown");
    const renderer = String(context.getParameter(context.RENDERER) ?? "unknown");
    const unmaskedVendor = debugInfo
      ? String(context.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL) ?? "")
      : "";
    const unmaskedRenderer = debugInfo
      ? String(context.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) ?? "")
      : "";
    const versions = `${String(context.getParameter(context.VERSION) ?? "unknown")} · GLSL ${String(
      context.getParameter(context.SHADING_LANGUAGE_VERSION) ?? "unknown",
    )}`;
    const detail = [vendor, renderer, unmaskedVendor, unmaskedRenderer]
      .filter((part, index, all) => part && all.indexOf(part) === index)
      .join(" / ");
    return {
      signal: signal(
        "webgl",
        "WebGL renderer & driver",
        `${detail || "unknown"} — ${versions}`,
        unmaskedRenderer || unmaskedVendor ? "high" : "notable",
        "Renderer and driver strings often identify the exact GPU model, its driver branch, and " +
          "sometimes the virtualised platform. Browser privacy modes frequently spoof these values, so a " +
          "generic string may be fake rather than harmless.",
        "webgl",
      ),
      skipped: null,
    };
  } catch {
    return {
      signal: null,
      skipped: {
        id: "webgl",
        label: "WebGL renderer",
        reason: "WebGL probing was blocked by this browser.",
      },
    };
  }
}

export interface CanvasResult {
  signal: BrowserSignal | null;
  skipped: SkippedSignal | null;
}

/**
 * Canvas rendering is only executed with explicit consent, because it is the
 * one technique people most associate with fingerprinting.
 */
export async function collectCanvasSignal(
  consent: boolean,
  targetWindow: Window = window,
): Promise<CanvasResult> {
  if (!consent) {
    return {
      signal: null,
      skipped: {
        id: "canvas",
        label: "Canvas rendering hash",
        reason: "Skipped: you have not enabled the optional canvas test.",
      },
    };
  }
  try {
    const canvas = targetWindow.document.createElement("canvas");
    canvas.width = 320;
    canvas.height = 70;
    const context = canvas.getContext("2d");
    if (!context) {
      return {
        signal: null,
        skipped: {
          id: "canvas",
          label: "Canvas rendering hash",
          reason: "This browser did not provide a 2D canvas context.",
        },
      };
    }
    context.textBaseline = "top";
    context.font = "16px 'Arial'";
    context.fillStyle = "#3EE9C0";
    context.fillRect(0, 0, 120, 24);
    context.fillStyle = "#0B1220";
    context.fillText("CleanSlate 1.0 — canvas probe", 4, 4);
    context.strokeStyle = "rgba(94,234,212,0.7)";
    context.beginPath();
    context.arc(200, 32, 22, 0, Math.PI * 1.6, true);
    context.stroke();
    const dataUrl = canvas.toDataURL();
    const digest = await sha256Hex(dataUrl);
    return {
      signal: signal(
        "canvas",
        "Canvas rendering hash",
        `sha-256(canvas) = ${digest.slice(0, 24)}… (${dataUrl.length} bytes of raster output)`,
        "high",
        "Rendering differences come from fonts, GPU drivers and rasteriser versions, so the hash tends to " +
          "be stable per device. It is computed locally and never sent anywhere.",
        "canvas",
      ),
      skipped: null,
    };
  } catch {
    return {
      signal: null,
      skipped: {
        id: "canvas",
        label: "Canvas rendering hash",
        reason: "Canvas rendering failed or is blocked (for example by anti-fingerprinting protections).",
      },
    };
  }
}

async function sha256Hex(input: string): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) {
    // Insecure context: fall back to a clearly-labelled non-cryptographic digest.
    let hash = 0;
    for (let index = 0; index < input.length; index += 1) {
      hash = (hash * 31 + input.charCodeAt(index)) | 0;
    }
    return `noncrypto-${(hash >>> 0).toString(16)}`;
  }
  const bytes = new TextEncoder().encode(input);
  const digest = await subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function countExposure(signals: BrowserSignal[]): ExposureCounts {
  return {
    common: signals.filter((item) => item.exposure === "common").length,
    notable: signals.filter((item) => item.exposure === "notable").length,
    high: signals.filter((item) => item.exposure === "high").length,
  };
}

export interface CollectOptions {
  canvasConsent: boolean;
  targetWindow?: Window;
}

export async function buildFingerprintReport(
  options: CollectOptions,
): Promise<FingerprintReport> {
  const targetWindow = options.targetWindow ?? window;
  const signals = collectBasicSignals({
    navigator: targetWindow.navigator,
    screen: targetWindow.screen,
    window: targetWindow,
  });
  const skipped: SkippedSignal[] = [];

  const webgl = collectWebglSignal(targetWindow);
  if (webgl.signal) signals.push(webgl.signal);
  if (webgl.skipped) skipped.push(webgl.skipped);

  const canvas = await collectCanvasSignal(options.canvasConsent, targetWindow);
  if (canvas.signal) signals.push(canvas.signal);
  if (canvas.skipped) skipped.push(canvas.skipped);

  return {
    version: 1,
    collectedAt: new Date().toISOString(),
    collectedIn: "browser",
    signals,
    skipped,
    counts: countExposure(signals),
    uniquenessScore: null,
    networkRequests: 0,
    consent: { webgl: true, canvas: options.canvasConsent },
    disclaimer: UNIQUENESS_DISCLAIMER,
    limitations: FINGERPRINT_LIMITATIONS,
  };
}
