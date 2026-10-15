import { describe, expect, it, vi } from "vitest";

import {
  CleanSlateApiError,
  inspectFile,
  sanitizeFile,
  inspectResponseSchema,
  sanitizeResponseSchema,
} from "@/lib/api";
import { inspectResponse, sanitizeResponse } from "@/test/fixtures";

class MockXhr {
  static instances: MockXhr[] = [];
  method = "";
  url = "";
  sent: FormData | null = null;
  status = 200;
  response = "";
  responseText = "";
  timeout = 0;
  upload: { onprogress: ((event: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = {
    onprogress: null,
  };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  onabort: (() => void) | null = null;

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  setRequestHeader() {
    /* no custom headers are needed for multipart uploads */
  }

  getResponseHeader(name: string) {
    return name.toLowerCase() === "retry-after" ? this.retryAfter ?? null : null;
  }

  retryAfter: string | null = null;

  send(form: FormData) {
    this.sent = form;
    MockXhr.instances.push(this);
  }

  abort() {
    this.onabort?.();
  }

  respondWith(status: number, body: string) {
    this.status = status;
    this.response = body;
    this.responseText = body;
    this.onload?.();
  }
}

function stubXhr() {
  MockXhr.instances = [];
  vi.stubGlobal("XMLHttpRequest", MockXhr as unknown as typeof XMLHttpRequest);
}

describe("response validation", () => {
  it("accepts a well-formed sanitize response", () => {
    expect(sanitizeResponseSchema.safeParse(sanitizeResponse).success).toBe(true);
  });

  it("rejects a sanitize response with a missing field instead of rendering it", async () => {
    const broken = { ...sanitizeResponse } as Record<string, unknown>;
    delete broken.comparison;

    stubXhr();
    const promise = sanitizeFile(new File(["x"], "a.jpg"), {
      preserveIcc: true,
      preserveOrientation: true,
    }).catch((error: CleanSlateApiError) => error);
    MockXhr.instances[0]!.respondWith(200, JSON.stringify(broken));

    const error = await promise;
    expect(error).toBeInstanceOf(CleanSlateApiError);
    expect((error as CleanSlateApiError).code).toBe("invalid_response");
  });

  it("rejects a non-JSON body", async () => {
    stubXhr();
    const promise = inspectFile(new File(["x"], "a.jpg")).catch(
      (error: CleanSlateApiError) => error,
    );
    MockXhr.instances[0]!.respondWith(200, "<html>proxy error</html>");
    await expect(promise).resolves.toMatchObject({ code: "invalid_response" });
  });

  it("validates the inspect schema independently", () => {
    expect(inspectResponseSchema.safeParse(inspectResponse).success).toBe(true);
    expect(inspectResponseSchema.safeParse({ ...inspectResponse, file: {} }).success).toBe(false);
  });
});

describe("error mapping", () => {
  const cases: [number, string][] = [
    [413, "payload_too_large"],
    [415, "unsupported_file_type"],
    [422, "unprocessable_file"],
    [429, "rate_limited"],
    [503, "tool_unavailable"],
    [504, "processing_timeout"],
    [500, "internal_error"],
  ];

  it.each(cases)("maps HTTP %i to %s", async (status, code) => {
    stubXhr();
    const promise = inspectFile(new File(["x"], "a.jpg"));
    MockXhr.instances[0]!.respondWith(
      status,
      JSON.stringify({ error: { code, message: "server message" }, request_id: "abc" }),
    );
    const error = (await promise.catch((caught: CleanSlateApiError) => caught)) as CleanSlateApiError;
    expect(error).toBeInstanceOf(CleanSlateApiError);
    expect(error.code).toBe(code);
    expect(error.status).toBe(status);
    // The user-facing message is our own wording, not raw server text.
    expect(error.message).not.toBe("server message");
  });

  it("exposes Retry-After seconds for rate limiting", async () => {
    stubXhr();
    const promise = inspectFile(new File(["x"], "a.jpg"));
    const xhr = MockXhr.instances[0]!;
    xhr.retryAfter = "42";
    xhr.respondWith(429, JSON.stringify({ error: { code: "rate_limited", message: "slow down" } }));
    const error = (await promise.catch((caught: CleanSlateApiError) => caught)) as CleanSlateApiError;
    expect(error.retryAfterSeconds).toBe(42);
  });

  it("reports a network failure clearly", async () => {
    stubXhr();
    const promise = inspectFile(new File(["x"], "a.jpg")).catch(
      (error: CleanSlateApiError) => error,
    );
    const xhr = MockXhr.instances[0]!;
    xhr.status = 0;
    xhr.onerror?.();
    await expect(promise).resolves.toMatchObject({ code: "network_error", status: 0 });
  });
});

describe("upload payload hygiene", () => {
  it("sends only the file and explicitly chosen options", async () => {
    stubXhr();
    const file = new File([new Uint8Array([1, 2, 3])], "photo.jpg", { type: "image/jpeg" });
    const promise = sanitizeFile(file, { preserveIcc: false, preserveOrientation: true });
    const xhr = MockXhr.instances[0]!;
    expect(xhr.method).toBe("POST");
    expect(xhr.url).toContain("/api/v1/metadata/sanitize");

    const form = xhr.sent!;
    const keys = Array.from(form.keys()).sort();
    expect(keys).toEqual(["file", "options"]);
    expect(JSON.parse(String(form.get("options")))).toEqual({
      preserve_icc: false,
      preserve_orientation: true,
    });
    // No fingerprint, device or identity data is ever attached.
    for (const forbidden of ["fingerprint", "userAgent", "user_agent", "signals", "device", "screen"]) {
      expect(form.get(forbidden)).toBeNull();
    }

    xhr.respondWith(200, JSON.stringify(sanitizeResponse));
    await expect(promise).resolves.toMatchObject({ engine: "exiftool" });
  });

  it("reports upload progress from real XHR events", async () => {
    stubXhr();
    const progress: number[] = [];
    const promise = inspectFile(new File(["x"], "a.jpg"), {
      onProgress: (value) => progress.push(value),
    });
    const xhr = MockXhr.instances[0]!;
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 100 });
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 100, total: 100 });
    xhr.respondWith(200, JSON.stringify(inspectResponse));
    await promise;
    expect(progress).toEqual([50, 100]);
  });
});
