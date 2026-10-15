# Verification record

What was actually executed, on what, and what came back. **No penetration test or third-party
security audit was performed.** This is a functional, security-control and dependency record, not a
security audit, and the "not verified" section is as important as the results.

Run date: 2026-10-15. Host: Windows 11, native (no container — see §6).

| Tool | Version |
| --- | --- |
| ExifTool | 13.59 (official Windows build; same upstream version pinned in the container) |
| qpdf | 12.4.2 |
| Python (local venv) | 3.14.7 |
| Container base (build target) | `python:3.12-slim-trixie` |
| Node / npm | 22.x / 10.x, Vite 6.4.4, Vitest 5.0.4 |
| Browser used for the UI run | Chromium 130 (the bundled preview browser) |

---

## 1. Backend test suite — 103 passed

```bash
cd backend && python -m pytest -q
# 103 passed, 1 warning in 140.13s
```

Real fixtures, real tools: the suite generates its samples with Pillow plus the actual ExifTool
binary (JPEG with GPS/author/orientation, PNG text chunks, TIFF, WebP, PDF, DOCX/XLSX/PPTX packages,
MP4 containers) and asserts against ExifTool/qpdf output rather than mocks. Coverage by file:

| Area | File | What it proves |
| --- | --- | --- |
| Health, headers, CORS, limits | `test_health_and_http.py` | Endpoints, security headers, exact-origin CORS, documented limits |
| Inspection | `test_inspect.py` | Metadata is really read; unsupported/mismatched files rejected; no server paths in responses; sample files unchanged on disk |
| Image sanitization | `test_sanitize_images.py` | GPS/author/software removal, orientation and ICC handling, trailing-data removal |
| Document sanitization | `test_sanitize_documents.py` | PDF + qpdf linearize, OOXML package rebuild, MP4 user-data removal **and the honest 422 refusal on a truncated container** |
| Security controls | `test_security.py` | Traversal, injection-style names/options, oversize, signature mismatch, CORS preflight, generic errors |
| Cleanup, tokens, limits | `test_cleanup_and_tokens.py` | No scratch after inspect/failure, TTL sweep, startup purge, cross-client download denial, job caps |
| Tool failure paths | `test_tool_failures.py` | Missing ExifTool, timeout, non-zero exit, truncated output are handled and reported |
| Report truthfulness & logs | `test_report_truthfulness.py` | Removed/retained match an independent ExifTool re-read, no overclaiming language, no user data in logs, no paths anywhere in responses, path-scrubbing and locale-banner units |

## 2. Frontend test suite — 46 passed, typecheck clean, build clean

```bash
cd frontend && npm test          # 46 passed (4 files)
cd frontend && npm run typecheck # no output = clean
VITE_API_BASE_URL="https://cleanslate-api.onrender.com" npm run build
# dist/index.html 1.31 kB · assets/index-*.css 22.13 kB (gzip 5.31) · assets/index-*.js 402.16 kB (gzip 122.04)
```

Covers the API client (zod validation, error mapping, cancellation, non-JSON bodies), fingerprint
collection (consent gating, no network, no storage writes, canvas only with consent), report builders
(JSON/HTML escaping of hostile tag values, no invented uniqueness score) and the consent/upload UI.

Build output check: `dist/_headers` contains the templated CSP with the exact API origin in
`connect-src` (verified by reading the built file), `dist/_redirects` ships the SPA fallback, and no
test fixture is present in `dist/`.

## 3. End-to-end run against a live API — 188/188 checks passed

```bash
# API running with real tools:
cd backend && ENVIRONMENT=development ALLOWED_ORIGINS=http://localhost:5173 \
  python -m uvicorn app.main:app --host 127.0.0.1 --port 8787
# then:
python e2e/http_e2e.py http://127.0.0.1:8787     # 188/188 checks passed (exit status 0)
```

This drives the deployed shape of the service over real HTTP (multipart uploads, real uvicorn, real
ExifTool/qpdf) and **independently re-checks every sanitized copy with the command-line tools** rather
than trusting the API's own report. Per format (JPEG, PNG, TIFF, WebP, PDF, DOCX, MP4) it asserts:

* inspect returns the right hash and real tags, with sensitivity classification and an explicit
  "unverified" list;
* sanitize removes fields, produces bytes that differ from the original, and the downloaded copy is
  independently scanned: **no GPS group, no Artist/Author/Creator/Make/Model/Software/Copyright/Title/
  Subject/GPSCoordinates tags survive**, and the format/MIME type is preserved;
* the report never claims removal when nothing was removed;
* download headers are `attachment` + `nosniff` + sandboxed CSP;
* the download token works once and is refused afterwards (404), and a random token is refused;
* responses contain no scratch paths.

Cross-cutting checks: security headers and CSP, CORS allow/deny and preflight both ways,
`415` for unsupported types, `415` for a signature mismatch, `413` for an oversized body, `400` for an
unknown option key, traversal-style filename handled with nothing escaping the scratch directory, and
cleanup asserted **per job this run created** (by the job ids returned in its own responses: every
downloaded job's directory gone from disk, every inspection job leaving no directory at all, refused
requests leaving nothing, and the deliberately undownloaded copy still held until its TTL). That
formulation was chosen after an earlier version counted the shared scratch directory globally and
produced false failures while another browser session was using the same server.

**Failure the run originally found (now fixed and regression-tested):** a truncated MP4 was reported
`200` with `removed=0` while the engine's own error text — including the server scratch path — leaked
into the client's `residual_risks`. Fixed by (a) broadening path scrubbing to forward-slash Windows
paths and general absolute paths, (b) filtering perl's locale banner out of tool warnings, and
(c) refusing byte-identical output with `422 unprocessable_file` instead of returning the untouched
file as "sanitized".

## 4. Rate limiting — verified on the live process

A second instance was started with `RATE_LIMIT_REQUESTS=5`:

```
request 1..5: 200, 200, 200, 200, 200
request 6:    429  Retry-After=58  {"error":{"code":"rate_limited", ...}}
```

## 5. Browser verification (through the real UI)

| Step | Result |
| --- | --- |
| Load the site | Renders; the API answered and its tool versions were reported to the operator (`ExifTool 13.59`, `qpdf version 12.4.2`) |
| Wrong origin in `ALLOWED_ORIGINS` | Requests failed and the UI reported the API as unavailable — CORS working as designed; fixed by listing the exact origin |
| Attach a JPEG (96×72, GPS + camera + artist + XMP + ICC) | Accepted, 5.5–5.8 KiB; **Sanitize button stayed disabled until the server-processing notice was acknowledged** |
| Sanitize | `JPEG image · 5.5 KiB → 2.4 KiB · engine exiftool`; removed 15–20 fields (5–8 high risk), retained 31, changed 0, added 0 |
| Comparison view | Lists every removed field with group/tag/value/risk, plus the "not verified as removed" list and engine notes |
| Verification panel | `re-inspection matched the report`, `structural recheck: passed`, `original upload deleted: yes`, ICC listed as retained by design |
| Download | Real browser download of `cleanslate-sanitized.jpg`; API then reported `jobs: 0, temp_bytes: 0` and the scratch directory contained no job dirs |
| Re-use the download link | `404` (single use) |
| Reports | JSON and printable HTML reports generated in the browser with no error |
| Inspect page | Separate upload + consent + inspect flow works and renders GPS/EXIF tags |
| Fingerprint dashboard | 17 signals · 1 skipped · **network requests: 0**; only `GET /api/health` appears on the wire |
| Cookies / storage | `document.cookie` empty, `localStorage` and `sessionStorage` empty |
| Canvas consent | Toggle off → canvas reported as skipped; toggle on + re-run → `Canvas rendering hash` row appears (18 signals, 0 skipped) |
| Console | No errors; only Vite HMR and React DevTools notices (the React Router future-flag warnings disappeared after the v7 upgrade) |
| Re-run after the React Router 6 → 7 upgrade | Same flows re-executed end to end: sanitize 15 removed / 5 sensitive, comparison and download OK, all six routes resolve, fingerprint still `network requests: 0` |
| Re-run after the UI cleanup (see below) | Sanitize re-run through the cleaned interface: 16 removed / 5 sensitive, comparison table, plain-language "What was verified" panel and download all render; typecheck, 46 tests and the production build re-run green |

Later UI revision, for the record: the permanent API status badge, the "live deployment limits" panel
and the API-origin/tool-version strings in the footer were **removed from the visitor-facing pages** as
noise. What remains is user-relevant: upload size and retention facts (on the limitations page), the
required server-processing notice on the upload pages, and a "Processing is unavailable right now"
warning that appears **only** when uploads would actually fail. Operator details (engine names,
versions, API origin, rate-limit counters) are no longer rendered anywhere in the UI.

## 6. Retention and cleanup observed on the live instance

* **After a download:** `/api/health` reported `jobs: 0, temp_bytes: 0` and the scratch root contained
  no job directory — the sanitized copy and its directory are gone the moment the bytes are sent.
* **After a refused request** (truncated MP4 → 422): no new job directory was left behind.
* **After an abandoned job** (sanitized but never downloaded) the TTL sweeper reaped it with no manual
  intervention. Measured directly against the running process, sampling `/api/health` every 10 s with
  `JOB_TTL_SECONDS=300`:

```
01:12:45  jobs 3  bytes 39627     <- three jobs created 5 minutes earlier, none downloaded
01:12:56  jobs 2  bytes 26418     <- sweeper pass at TTL
01:13:59  jobs 1  bytes 13209     <- second job reaped one interval later
01:14:40  jobs 0  bytes 0         <- all scratch data gone
```

  The scratch root afterwards contained only `_toolhome` (the empty HOME used for tool subprocesses).

## 7. Dependency and supply-chain checks

```bash
pip-audit -r backend/requirements.lock.txt   # No known vulnerabilities found
cd frontend && npm audit --omit=dev          # found 0 vulnerabilities
cd frontend && npm audit                     # 7 remaining (2 moderate, 5 high) - dev toolchain only
```

* **Runtime Python dependencies:** clean.
* **Production frontend dependencies:** clean. This required a real fix: `react-router-dom` 6.30.6 was
  flagged (GHSA-337j-9hxr-rhxg, SSR-hydration `deserializeErrors`) and was upgraded to **7.18.4**,
  then re-verified with typecheck, 46 tests and a production build. (The advisory concerns SSR
  hydration, which this client-only app does not use, but the upgrade removes the question entirely.)
* **Dev-only advisories (7, accepted with reasons):** `tinypool` RCE (GHSA-5gmw-xhrv-c9v3,
  GHSA-85c8-ppgw-ccpr) and `@vitest/mocker` path traversal (GHSA-82fw-gwwq-j7x9) were **fixed** by
  upgrading `vitest` 3 → **5.0.4** (2 criticals cleared). The remainder are inside the Tailwind v3
  build toolchain — `braces` (GHSA-vfj7-8cjw-p6xm) and `postcss` (GHSA-rj75-hqrm-r3gf) — and are
  ReDoS/CPU-exhaustion issues in build-time file globbing and CSS parsing. They never reach a browser
  or the deployed bundle, they require attacker-controlled input to the local build, and clearing
  them means a Tailwind 3 → 4 migration (CSS-first config, renamed utilities) that would risk visual
  regressions for no user-facing benefit. Recommended follow-up: migrate to Tailwind 4 and re-audit.
* **Lockfile portability:** every one of the 15 pins in `requirements.lock.txt` resolves to a
  `manylinux2014_x86_64`/`cp312` wheel, so the container install will not need a compiler.
* **ExifTool integrity:** the SHA-256 in `backend/Dockerfile`
  (`668ea3acececb7235fbd0f4900e72d5f12c9b07e5c778fd36cb1e9b5828fd65a`) was verified against the
  actual tarball downloaded from the pinned upstream URL.

## 8. Not verified (explicit gaps)

1. **The Docker image was never built on this host.** The daemon was down, launching Docker Desktop
   from the agent session did not bring it up (`docker-desktop` and `Ubuntu` WSL distros both
   `Stopped`, no `com.docker.service` installed, no Docker Desktop process after repeated starts), and
   the WSL distro has no `make`/`pip`/`qpdf` to fall back on without installing system packages. There
   is also no `podman`/`nerdctl` alternative. `backend/Dockerfile` was therefore validated by
   inspection and by its inputs only: pinned base image, ExifTool tarball checksum verified against the
   real download, every runtime pin resolving to a `cp312`/`manylinux` wheel, non-root user, healthcheck,
   and a `test` stage that fails the build when pytest fails. A real `docker build` / `docker run` was
   **not** executed — treat the container as unverified until you run the commands in §9 (start Docker
   Desktop first).
2. **No deployment was performed.** Nothing was pushed to Render or Cloudflare Pages, and no live URL
   exists. Deploying requires your own accounts, so the exact steps are in
   [DEPLOYMENT.md](DEPLOYMENT.md) instead of a fabricated URL. The frontend build was validated
   locally with the production API origin, including the templated CSP.
3. **No security audit and no penetration test.** No fuzzing, no malformed-file corpus beyond the
   cases listed, no adversarial review of ExifTool/qpdf themselves. A parser bug in either tool is a
   residual risk (see the threat model).
4. **No load, concurrency or soak testing.** The job caps and rate limiter were exercised
   functionally, not under sustained traffic, and rate limiting is per process (accurate for a
   single-instance free deployment, insufficient for a multi-instance one).
5. **Only Windows was used for the local run.** Linux/macOS command paths are documented but were not
   executed, and the deployed (Linux, container) environment differs from the verified one in the
   ways listed in item 1.
6. **Test fixtures are small and synthetic.** They are real containers with real metadata, but not
   large media files, not adversarial, and not representative of every vendor variant.
7. **No accessibility audit, no cross-browser matrix.** The UI was exercised in one Chromium build;
   Firefox/Safari behaviour and a screen-reader pass were not tested.
8. **Cold-start behaviour on the free tier** (15-minute spin-down, ~1-minute wake) is documented from
   the provider's own documentation — it was not observed, because nothing was deployed.
9. **The OOXML and PDF paths were exercised with generated packages, not with real-world documents**
   (no Google Docs/Word/InDesign output, no encrypted or signed PDFs, no portfolio PDFs). Encrypted
   PDFs in particular are untested: qpdf would need a password, which this pipeline never supplies or
   accepts.
10. **No test of behaviour under a hostile `Origin` header on a mutation**, beyond the CORS checks:
    the API is public by design, so a foreign origin is refused by the browser policy, not by an
    authorization check (there is nothing to authorize).

## 9. Reproducing this record

```bash
# 1. Backend (real tools)
cd backend && python -m pytest -q

# 2. Frontend
cd frontend && npm ci && npm test && npm run typecheck && npm run build

# 3. End-to-end against a running API (start the API first, see README §3)
python e2e/http_e2e.py http://127.0.0.1:8787

# 4. Container (the step that is still outstanding - run this before deploying)
docker build -t cleanslate-api --target test ./backend      # fails the build if tests fail
docker build -t cleanslate-api --target runtime ./backend
docker run --rm -p 8787:8787 -e ENVIRONMENT=development \
  -e ALLOWED_ORIGINS=http://localhost:5173 cleanslate-api
curl -s http://127.0.0.1:8787/api/health
python e2e/http_e2e.py http://127.0.0.1:8787                # repeat against the container

# 5. Dependencies
pip-audit -r backend/requirements.lock.txt
cd frontend && npm audit --omit=dev
```

Then work through the deployment checklist in [DEPLOYMENT.md](DEPLOYMENT.md#6-deployment-verification-checklist)
on the real URLs, and record what you observe.
