import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// jsdom ships no canvas implementation: getContext() throws "Not implemented" and
// prints a virtual-console error on every call. The collector already treats a
// missing context as "WebGL/canvas unavailable", so expose the same shape a
// browser without WebGL gives. Tests that need real canvas behaviour (the
// consent-gated hashing test) stub getContext themselves.
if (typeof HTMLCanvasElement !== "undefined") {
  HTMLCanvasElement.prototype.getContext = (() => null) as unknown as HTMLCanvasElement["getContext"];
}

// jsdom does not implement matchMedia, which the fingerprint collector reads.
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
