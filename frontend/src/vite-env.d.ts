/// <reference types="vite/client" />

/**
 * Environment variables injected at build time. Only VITE_-prefixed variables
 * are exposed to the bundle; nothing here is secret, and there is no API key in
 * this application.
 */
interface ImportMetaEnv {
  /** Absolute origin (+ optional base path) of the deployed CleanSlate API. */
  readonly VITE_API_BASE_URL?: string;
  /** Development only: where the vite proxy forwards /api requests. */
  readonly DEV_API_TARGET?: string;
}
