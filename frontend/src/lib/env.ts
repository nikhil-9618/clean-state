/**
 * Build-time configuration.
 *
 * VITE_API_BASE_URL must be the exact HTTPS origin of the deployed API. It is
 * also injected into the Content-Security-Policy `connect-src` directive at
 * build time (see vite.config.ts), so a wildcard is never needed.
 *
 * When the variable is empty:
 *   - in dev, requests go to relative `/api/...` and vite proxies them locally;
 *   - in a production build, the app reports a configuration error instead of
 *     silently failing against the wrong host.
 */
const raw = (import.meta.env.VITE_API_BASE_URL ?? "").trim().replace(/\/+$/, "");

export const API_BASE_URL = raw;
export const IS_DEVELOPMENT = Boolean(import.meta.env.DEV);
export const API_CONFIGURED = raw.length > 0;
export const API_MISCONFIGURED = !API_CONFIGURED && !IS_DEVELOPMENT;

export function apiUrl(path: string): string {
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE_URL}${suffix}`;
}

export const BUILD_INFO = {
  appName: "CleanSlate",
  version: "1.0.0",
  repositoryDocsPath: "/limitations",
} as const;
