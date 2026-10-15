import { describe, expect, it, vi } from "vitest";

import {
  buildFingerprintReport,
  collectBasicSignals,
  collectCanvasSignal,
  collectWebglSignal,
} from "@/lib/fingerprint/collect";
import { UNIQUENESS_DISCLAIMER } from "@/lib/fingerprint/types";

function fakeCanvas2d() {
  return {
    textBaseline: "",
    font: "",
    fillStyle: "",
    strokeStyle: "",
    fillRect: vi.fn(),
    fillText: vi.fn(),
    beginPath: vi.fn(),
    arc: vi.fn(),
    stroke: vi.fn(),
  } as unknown as CanvasRenderingContext2D;
}

describe("consent controls", () => {
  it("does not touch canvas APIs when consent is refused", async () => {
    const getContext = vi.spyOn(HTMLCanvasElement.prototype, "getContext");
    const toDataURL = vi.spyOn(HTMLCanvasElement.prototype, "toDataURL");

    const result = await collectCanvasSignal(false);

    expect(getContext).not.toHaveBeenCalled();
    expect(toDataURL).not.toHaveBeenCalled();
    expect(result.signal).toBeNull();
    expect(result.skipped?.reason).toContain("not enabled");
  });

  it("reports the canvas test as skipped in a report without consent", async () => {
    const report = await buildFingerprintReport({ canvasConsent: false });
    expect(report.consent.canvas).toBe(false);
    expect(report.signals.some((signal) => signal.id === "canvas")).toBe(false);
    expect(report.skipped.some((item) => item.id === "canvas")).toBe(true);
  });

  it("runs the canvas test and hashes output when consent is granted", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(fakeCanvas2d());
    vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue("data:image/png;base64,QUJD");

    const result = await collectCanvasSignal(true);
    expect(result.signal).not.toBeNull();
    expect(result.signal?.exposure).toBe("high");
    expect(result.signal?.consent).toBe("canvas");
    expect(result.signal?.value).toContain("sha-256(canvas)");
  });
});

describe("report integrity", () => {
  it("never computes or implies a uniqueness score", async () => {
    const report = await buildFingerprintReport({ canvasConsent: false });
    expect(report.uniquenessScore).toBeNull();
    expect(report.networkRequests).toBe(0);
    expect(report.disclaimer).toBe(UNIQUENESS_DISCLAIMER);

    const serialized = JSON.stringify(report).toLowerCase();
    // The score field is explicitly null ...
    expect(serialized).toContain('"uniquenessscore":null');
    // ... and no numeric metric of rarity exists anywhere in the payload.
    for (const forbidden of ['"rarity"', '"entropy"', '"probability"', '"percentile"', '"score"']) {
      expect(serialized).not.toContain(forbidden);
    }
    // The disclaimer explains why there is no percentage instead of showing one.
    expect(report.disclaimer.toLowerCase()).toContain("does not display a uniqueness percentage");
  });

  it("performs no network requests while collecting", async () => {
    const fetchSpy = vi.fn(() => {
      throw new Error("network access attempted during fingerprint collection");
    });
    vi.stubGlobal("fetch", fetchSpy);
    const xhrConstructor = vi.fn();
    vi.stubGlobal("XMLHttpRequest", xhrConstructor);
    const beacon = vi.fn();
    vi.stubGlobal("navigator", { ...navigator, sendBeacon: beacon });

    await buildFingerprintReport({ canvasConsent: false });

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(xhrConstructor).not.toHaveBeenCalled();
    expect(beacon).not.toHaveBeenCalled();
  });

  it("does not write to browser storage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    await buildFingerprintReport({ canvasConsent: false });
    expect(setItem).not.toHaveBeenCalled();
  });

  it("labels every signal with an exposure class and a rationale", async () => {
    const report = await buildFingerprintReport({ canvasConsent: false });
    expect(report.signals.length).toBeGreaterThan(10);
    for (const signal of report.signals) {
      expect(["common", "notable", "high"]).toContain(signal.exposure);
      expect(signal.rationale.length).toBeGreaterThan(20);
      expect(signal.label.length).toBeGreaterThan(0);
    }
    expect(report.counts.high + report.counts.notable + report.counts.common).toBe(report.signals.length);
  });

  it("collects basic signals without any permission prompt", () => {
    const signals = collectBasicSignals();
    const ids = signals.map((signal) => signal.id);
    expect(ids).toContain("user_agent");
    expect(ids).toContain("timezone");
    expect(ids).toContain("screen");
    expect(ids).toContain("cookies");
    expect(ids).toContain("privacy_signals");
  });

  it("discloses WebGL as high exposure when unmasked values exist, otherwise skips it", () => {
    const result = collectWebglSignal();
    if (result.signal) {
      expect(result.signal.consent).toBe("webgl");
      expect(["notable", "high"]).toContain(result.signal.exposure);
    } else {
      expect(result.skipped?.reason).toBeTruthy();
    }
  });
});
