# CleanSlate threat model

Scope: the publicly reachable, login-free CleanSlate deployment — a static React frontend on a free
hosting plan and a Python/FastAPI metadata API on a free container plan. This document is a design
and review artifact, **not** the output of a penetration test. See
[VERIFICATION.md](VERIFICATION.md) for what was actually exercised.

---

## 1. What is worth protecting

| Asset | Where it lives | Why it matters |
| --- | --- | --- |
| Uploaded file contents and metadata values | API scratch directory, in memory during a request | Highest-value asset: private photos, documents, GPS coordinates, author identities |
| Sanitized copy awaiting download | API scratch directory | Same data, minus the fields that were removed — still sensitive |
| Download tokens | API memory only | Anyone holding a live token can fetch another user's sanitized copy |
| `SECRET_KEY` | API environment | Used to HMAC client addresses and derive job/token identifiers |
| Hosting provider credentials | Provider dashboard (never in the repo) | Deploy access; compromise means code replacement |
| Visitor browser signals | Browser tab only | Must never be transmitted or persisted by design |
| Service availability | API process | A public attacker can exhaust CPU, disk or request budget |

Not stored anywhere, by design: accounts, databases, long-term file storage, analytics, cookies,
fingerprint history.

---

## 2. Trust boundaries

```
Visitor browser ──HTTPS──> Frontend host (static)        [untrusted input source]
        │
        └──HTTPS──> CleanSlate API (public, no auth)     [trusted code, untrusted input]
                          │  argv only, no shell
                          ├──> exiftool subprocess       [untrusted file in, minimal env]
                          ├──> qpdf subprocess           [untrusted file in, minimal env]
                          └──> per-job scratch dir       [ephemeral, random name]
```

1. **Browser → API.** Every request is attacker-controlled: file bytes, filenames, multipart
   boundaries, options JSON, headers, rate and timing.
2. **API → tools.** ExifTool and qpdf parse attacker-supplied bytes. A parser memory-safety bug is
   the most likely route from "we process your file" to "we run your code".
3. **API → network.** The worker should not be able to reach cloud metadata endpoints or internal
   services on behalf of an attacker.
4. **Hosting provider → API.** The provider's operators and any snapshot of the ephemeral disk can
   see a file while it is being processed. This is disclosed to the user before every upload and is
   not something the code can prevent.

Explicit non-boundary: **CORS is not access control.** It is a browser policy. Any client — curl, a
script, a server — can call the public API directly with or without an allowed `Origin`. CORS exists
only so that *other websites* cannot make a visitor's browser read API responses. Rate limiting,
upload validation and short token lifetimes are what actually constrain abuse.

---

## 3. Threats and mitigations

### 3.1 Malicious file (parser exploit, zip bomb, decompression bomb)
* **Allowlist by extension *and* signature.** The declared MIME type is never trusted; magic bytes
  are checked against the format the extension claims, and unsupported types are rejected with 415.
* **Size ceiling.** 25 MiB default upload cap, enforced while reading the stream (the body cap sits
  above it so oversized multipart requests are refused with 413 rather than buffered).
* **OOXML handling is defensive.** Only relationship and content-type parts are parsed, and any part
  that contains a `<!DOCTYPE` or `<!ENTITY` declaration is refused outright before parsing (which
  removes the billion-laughs/XXE class from this path entirely), each part is capped at 1 MiB
  (`MAX_PARSE_BYTES`), and a parse failure leaves the part untouched and *reported* instead of
  silently dropping it. All other package parts are copied byte-for-byte, never parsed.
* **Structural parsers are bounded.** TIFF/PNG/JPEG/MP4 sniffers validate lengths before unpacking,
  and malformed input raises a controlled error rather than an unhandled `struct.error`.
* **Timeouts everywhere.** Per-tool subprocess timeouts plus an overall request budget; on timeout the
  whole process group is killed so a wedged grandchild cannot survive.

### 3.2 Malformed container that cannot actually be rewritten
Reported honestly rather than masked: if the sanitizer's output is byte-identical to the original
*and* the tool reported a genuine error, the request fails with **422** — the user is never handed
back an unchanged file labelled "sanitized". (This was found by end-to-end testing against a
truncated MP4, then fixed and covered by a regression test.)

### 3.3 Path traversal and filename abuse
* Client filenames are never used for filesystem paths. Scratch names are generated
  (`secrets.token_urlsafe(32)`) and the on-disk names inside a job are fixed constants.
* The upload name is used only for logging-free reporting and for the *sanitized* download name,
  which is itself generated (`cleanslate-sanitized.<ext>`), so a name like `../../evil.jpg` cannot
  influence the filesystem or the response `Content-Disposition`.
* Verified by test: a traversal-style filename is processed and no file appears outside the scratch
  directory.

### 3.4 Command injection
* No shell is ever used. Every tool invocation is an argv array passed to
  `asyncio.create_subprocess_exec`, with `--` before the path.
* User input never reaches an argument: options are validated by a pydantic model with
  `extra="forbid"` and mapped to a fixed set of flags; unknown keys are rejected with 400.

### 3.5 Secret reachability from a compromised tool
* Subprocesses receive a **constructed minimal environment** — `PATH`, `LANG`, `LC_ALL`, `HOME`
  (an empty per-instance dir) and `TMPDIR` — so `SECRET_KEY` and any provider-injected variable are
  not present in the child process.
* `HOME` points at an empty directory, so a stray `~/.ExifTool_config` cannot alter parsing.
* The container runs as a non-root user with no host mounts and no Docker socket, and the runtime
  image contains no shell tooling beyond `/bin/sh` for the entrypoint.
* Residual risk: an ExifTool/qpdf code-execution bug would still run as the API user inside the
  container and could read the scratch directory. That is why the worker is one container with one
  job model, no database and a 5-minute scratch lifetime.

### 3.6 Cross-user result access
* Job identifiers and download tokens are random (`token_urlsafe`), stored in memory only, and a
  token is consumed on first use.
* Tokens expire (`DOWNLOAD_TOKEN_TTL_SECONDS`, default 300 s) and are bound by default to an HMAC of
  the client address (`DOWNLOAD_BIND_IP=true`), so a leaked URL is not useful from another address.
* Unknown, expired and already-used tokens all return a 404/403/410 with no detail that would
  distinguish "wrong owner" from "does not exist".

### 3.7 Resource exhaustion (public, no login)
* Per-IP rate limiting (default 30 requests / 60 s) implemented as a sliding window over HMAC'd
  client keys, returning 429 with `Retry-After`.
* A hard cap on concurrent in-flight jobs (`MAX_CONCURRENT_JOBS`) and on total scratch bytes
  (`MAX_TEMP_BYTES`); exceeding either returns 503 `processor_busy` instead of filling the disk.
* Bounded tool output (16 MiB) and bounded tag counts (800 tags) so a pathological file cannot
  produce an unbounded response.
* The free instance is small by design; cold starts and slower processing are documented rather than
  hidden.
* Residual risk: rate limiting is per process, so a future multi-instance deployment would need a
  shared store. On a single free instance this is accurate.

### 3.8 Data retention and leakage through logs
* Uploaded originals are deleted when the request finishes; sanitized copies live only until one
  download or the job TTL (default 300 s); a sweeper reaps expired jobs and a startup purge clears
  anything left by a previous process.
* Logs contain event names, job-id prefixes, formats, tool versions, counters and HMAC'd IPs only.
  A test asserts that file names, metadata values, GPS coordinates and scratch paths never appear in
  log records.
* Tool stderr is scrubbed of filesystem paths before it can reach a user-visible field or a log line
  (ExifTool appends the file path to most warnings).
* No file contents are ever cached, queued or written to a database.

### 3.9 Client-side exposure
* The fingerprint dashboard performs no network requests after the page loads; the API exposes no
  endpoint to receive signals. The report counts its own network requests and displays `0`.
* Nothing is written to cookies, `localStorage` or `sessionStorage` (asserted in the browser during
  verification and in unit tests).
* The canvas test requires an explicit consent toggle; WebGL strings are collected with disclosure
  because any page can read them without asking.
* Reports are generated in the browser and downloaded as files — the server never receives them.
* Residual risk: the frontend host can serve modified JavaScript. A user who does not trust the
  hosting provider should work from a local build.

### 3.10 Transport and browser policy
* HTTPS-only endpoints on both hosts; HSTS enabled (`ENABLE_HSTS=true`) in production.
* API responses: `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `X-Frame-Options: DENY` (plus `frame-ancestors 'none'` in CSP), a restrictive CSP,
  `Cross-Origin-Opener-Policy`/`Cross-Origin-Resource-Policy`, and a sandboxed CSP on downloads.
* Frontend: the same headers via `public/_headers`, with `connect-src` templated at build time to the
  exact API origin, plus an inline CSP meta tag for hosts that ignore `_headers`.
* CORS is an exact-match allowlist; a wildcard in `ALLOWED_ORIGINS` fails startup deliberately.
* `TRUST_PROXY_HEADERS` is off by default so client addresses cannot be spoofed by sending
  `X-Forwarded-For`; it is enabled only on the deployed service, which sits behind Render's proxy.

### 3.11 Supply chain
* Both lockfiles are committed and pinned (`backend/requirements.lock.txt`, `frontend/package-lock.json`).
* The container installs ExifTool from the official distribution tarball with a **pinned SHA-256**
  check, then purges the build-only packages and apt lists.
* `pip-audit` and `npm audit` are available for advisory checks; the runbook in
  [VERIFICATION.md](VERIFICATION.md) records when they were last run.
* Residual risk: advisories published after the last audit, and the base image digest is not pinned.

---

## 4. Out of scope / accepted risks

* A determined attacker who can spend unlimited resources against a single free-tier instance can
  still degrade availability; the goal is bounded impact, not DDoS resistance.
* The hosting provider (and anyone with platform access) can read a file while it is processed. This
  is disclosed in the UI before upload and cannot be engineered away on a free plan.
* Metadata removal is best-effort per format; unverifiable categories are listed rather than
  claimed. Categories that survive are documented in the report and in
  [limitations](https://localhost/limitations) inside the app.
* No account system exists, so there is no per-user quota, no abuse attribution beyond an HMAC'd IP,
  and no way to revoke a single visitor's access other than the rate limiter.
* Third-party services (frontend host, container host, DNS/TLS) are trusted for availability and TLS
  termination but never receive fingerprint signals.
