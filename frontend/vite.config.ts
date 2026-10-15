import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type Plugin } from "vite";

/**
 * Security headers are templated so the deployed policy contains the exact API
 * origin instead of a wildcard:
 *   - `public/_headers` is rewritten for Cloudflare Pages (and any host that
 *     honours that file);
 *   - the inline CSP meta tag in `index.html` is generated for hosts that do not
 *     read `_headers`.
 * In dev the meta tag is removed entirely: `vite dev` needs inline scripts for
 * HMR and is never the deployed configuration.
 */
function securityHeadersPlugin(apiOrigin: string): Plugin {
  const connectSrc = ["'self'", ...(apiOrigin ? [apiOrigin] : [])].join(" ");
  const csp = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src ${connectSrc}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'none'",
    "frame-ancestors 'none'",
    "manifest-src 'self'",
    "worker-src 'none'",
  ].join("; ");

  return {
    name: "cleanslate-security-headers",
    transformIndexHtml: {
      order: "pre",
      handler(html, ctx) {
        if (ctx.server) {
          return html.replace(/\n\s*<meta http-equiv="Content-Security-Policy"[^>]*\/>/, "");
        }
        return html.replace(/__CSP__/g, csp);
      },
    },
    closeBundle() {
      const headersPath = resolve(process.cwd(), "dist/_headers");
      if (!existsSync(headersPath)) return;
      const updated = readFileSync(headersPath, "utf8").replaceAll("__API_ORIGIN__", apiOrigin);
      writeFileSync(headersPath, updated);
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiBase = (env.VITE_API_BASE_URL ?? "").trim().replace(/\/+$/, "");
  let apiOrigin = "";
  try {
    if (apiBase) apiOrigin = new URL(apiBase).origin;
  } catch {
    apiOrigin = "";
  }

  return {
    plugins: [react(), securityHeadersPlugin(apiOrigin)],
    resolve: {
      alias: { "@": resolve(process.cwd(), "src") },
    },
    server: {
      port: 5173,
      strictPort: false,
      // Without VITE_API_BASE_URL the app calls relative /api paths; vite proxies
      // them to the local API container so development mirrors production CORS.
      proxy: env.VITE_API_BASE_URL
        ? undefined
        : {
            "/api": {
              target: env.DEV_API_TARGET || "http://127.0.0.1:8787",
              changeOrigin: false,
            },
          },
    },
    preview: { port: 4173 },
    build: {
      outDir: "dist",
      sourcemap: false,
      target: "es2022",
    },
    test: {
      globals: true,
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      include: ["src/**/*.test.{ts,tsx}"],
      css: false,
      restoreMocks: true,
    },
  };
});
