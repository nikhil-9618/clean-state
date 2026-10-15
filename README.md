# CleanSlate

**Secure digital hygiene for files and browsers.** CleanSlate inspects the metadata hidden inside
your files, produces a sanitized copy with real tools, and reports what your browser gives away to
every website — with no account, no analytics, no database and no permanent storage.

Two halves, built differently on purpose:

| Half | Where it runs | What it needs |
| --- | --- | --- |
| **File metadata** (inspect + sanitize) | Server-side, temporary | Python + FastAPI, ExifTool, qpdf, per-job scratch storage |
| **Browser fingerprint exposure** | Entirely in your browser | Nothing — no endpoint exists to receive it |

The separation is enforced in code, not just in prose: there is no fingerprint endpoint on the API
(`/api/health` reports `"fingerprint_collection": false`), and the dashboard performs zero network
requests after load.

---

## 1. What it actually does

### Metadata inspection
Uploads are validated (extension allowlist **and** magic-byte signature checks), written to a random
per-job scratch directory, and read with ExifTool (`-j -G1 -s -a`). Every tag is then classified by
sensitivity (`high` / `medium` / `low`) so GPS coordinates, serial numbers, author identity and
software fingerprints are visible before anything is changed.

### Sanitization
A sanitized *copy* is produced — your original file is never modified, and the server never writes
to the file you uploaded:

* **JPEG / PNG / TIFF / WebP** → `exiftool -all=`, plus `-Trailer:All=` when trailing data after the
  image end marker is detected, plus explicit tag deletion for TIFF (ExifTool cannot drop the whole
  IFD0 block, so structural image tags are skipped and metadata tags are deleted by name).
* **PDF** → ExifTool for the Info dictionary and XMP, then `qpdf --linearize` so the older revisions
  that still contain the removed metadata are physically dropped from the file.
* **DOCX / XLSX / PPTX** → ExifTool cannot write OOXML, so the package is rebuilt: `docProps/core.xml`
  and `docProps/app.xml` are replaced with generated minimal parts, their relationships and content
  types entries are removed, and the ZIP is rewritten.
* **MP4 / MOV** → `exiftool -all=` plus explicit deletion/handling of QuickTime movie-header and
  item-list fields that `-all=` leaves behind.

Options: preserve EXIF orientation (rewrites only the orientation value) and preserve the ICC colour
profile (copied back after deletion; the UI notes that an ICC profile can itself carry a description
string).

### Verification, then reporting
The sanitized copy is **re-read with the same reader** and compared field by field with the original.
The API reports `removed`, `retained`, `changed`, `added` separately, plus:

* `unverified` — the categories this pipeline does **not** claim to have removed (PDF attachments,
  hidden layers/JavaScript, Office tracked changes, in-stream video GPS, steganographic payloads);
* `verification.metadata_removed_verified` — only true when the re-scan agrees;
* an explicit refusal (**HTTP 422**) when the metadata engine could not rewrite the file at all, so
  a truncated or malformed container never comes back looking "cleaned".

### Download handling
The sanitized copy is served once through an unguessable single-use token, bound to the requesting
client (HMAC of the client address), expiring after 5 minutes, with `Content-Disposition:
attachment`, `nosniff` and a `default-src 'none'; sandbox` policy. The job's scratch directory is
deleted as soon as the response body has been sent.

### Browser exposure report
Reads user agent + client hints, screen/viewport, device pixel ratio, colour depth, languages,
timezone, platform, CPU threads, device memory, touch support, cookie/storage availability, privacy
preferences, accessibility/display preferences, the automation flag, WebGL renderer strings (with
disclosure) and — only after explicit consent — a canvas rendering hash. It reports signal exposure
by strength and states plainly that **no uniqueness percentage is shown**, because there is no
representative reference population to compute one from.

---

## 2. Repository layout

```
backend/                 FastAPI service (the only thing that touches files)
  app/                   config, security middleware, rate limiting, tools, exiftool, qpdf,
                         office package rebuild, structural analyser, comparison, job store
  tests/                 pytest suite (103 tests, runs against real ExifTool + qpdf)
  Dockerfile             multi-stage: lock / tools / base / test / runtime (non-root, uid 10001)
  requirements.in        direct dependencies
  requirements.lock.txt  pinned runtime lockfile
  .dockerignore
e2e/
  http_e2e.py            end-to-end verification against a *running* deployment (188 checks)
frontend/                React + TypeScript + Vite + Tailwind + shadcn/ui
  src/lib/api.ts         typed API client (zod-validated responses)
  src/lib/fingerprint/   client-side signal collection
  src/lib/report.ts      JSON + printable HTML report generation (in the browser)
  public/_headers        Cloudflare Pages security headers (CSP templated at build time)
  public/_redirects      SPA fallback
render.yaml              Render Blueprint for the free API service
docs/                    threat model, privacy & retention, deployment, verification record
```

---

## 3. Run it locally

Prerequisites: Docker **or** native ExifTool + qpdf, plus Node 20+ and Python 3.12+.

### Backend (Docker — closest to production)

```bash
docker build -t cleanslate-api --target test  ./backend   # runs the pytest suite in the image
docker build -t cleanslate-api --target runtime ./backend
docker run --rm -p 8787:8787 \
  -e ENVIRONMENT=development \
  -e ALLOWED_ORIGINS=http://localhost:5173 \
  cleanslate-api
curl -s http://127.0.0.1:8787/api/health
```

The container runs as uid 10001 with a writable scratch directory at `/tmp/cleanslate-jobs`; it
never needs the Docker socket, a persistent volume or incoming traffic other than HTTP.

### Backend (native, no Docker)

```bash
# Linux/macOS
apt-get install -y exiftool qpdf          # or: brew install exiftool qpdf
python3 -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements.lock.txt -r backend/requirements-dev.in
cd backend && ENVIRONMENT=development ALLOWED_ORIGINS=http://localhost:5173 \
  python -m uvicorn app.main:app --host 127.0.0.1 --port 8787
```

```powershell
# Windows PowerShell (paths to local tool binaries can be set explicitly)
py -3 -m venv .venv
.\.venv\Scripts\pip install -r backend\requirements.lock.txt -r backend\requirements-dev.in
cd backend
$env:ENVIRONMENT = "development"
$env:ALLOWED_ORIGINS = "http://localhost:5173"
$env:EXIFTOOL_PATH = "C:\tools\exiftool.exe"
$env:QPDF_PATH = "C:\tools\qpdf.exe"
..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8787
```

### Frontend

```bash
cd frontend
npm ci                 # uses the committed package-lock.json
npm run dev            # http://localhost:5173 — proxies /api to 127.0.0.1:8787 when no
                       # VITE_API_BASE_URL is set, so dev mirrors production CORS
```

Set `VITE_API_BASE_URL` (see [frontend/.env.example](frontend/.env.example)) to call a deployed API
instead. That value is also templated into the CSP `connect-src` and `public/_headers` at build
time, so it must be the exact origin, never a wildcard.

### Tests

```bash
cd backend && python -m pytest -q          # 103 tests against real ExifTool + qpdf
cd frontend && npm test                    # 46 tests (vitest + jsdom)
cd frontend && npm run typecheck
python e2e/http_e2e.py http://127.0.0.1:8787   # end-to-end, against a running API
```

---

## 4. API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Service + tool versions, storage counters, `accepts_uploads` |
| `GET` | `/api/v1/limits` | Live upload limit, accepted formats, retention and rate-limit values, processing notice |
| `POST` | `/api/v1/metadata/inspect` | `multipart/form-data` field `file` → metadata report |
| `POST` | `/api/v1/metadata/sanitize` | field `file` + optional `options` JSON → comparison + download |
| `GET` | `/api/v1/download/{token}` | Single-use sanitized copy, then the scratch directory is deleted |

There is deliberately **no** fingerprint endpoint.

---

## 5. Security posture (short version)

Full detail, including residual risks and threat-by-threat mitigations, is in
[docs/THREAT_MODEL.md](docs/THREAT_MODEL.md).

* Allowlisted formats with magic-byte signature validation, 25 MiB upload cap and a body cap above it.
* Per-IP rate limiting (default 30 requests / 60 s), request timeouts, per-tool subprocess timeouts
  killed by process group.
* Subprocesses always receive an **argv array** (never a shell) and a minimal environment
  (`PATH`, `LANG`, `LC_ALL`, `HOME`, `TMPDIR`) so no application secret is reachable from a tool.
* Randomized per-job scratch directories, path-traversal rejection, guaranteed cleanup on success,
  failure, timeout and process restart (startup purge).
* Non-root worker (uid 10001) in the container, no host mounts, no Docker socket, no inbound port
  other than the API itself.
* Exact-match CORS allowlist (wildcards rejected at startup), generic public errors (no stack
  traces), `nosniff`, `no-referrer`, CSP, frame denial and HSTS on the API; the same set plus a
  strict CSP on the static frontend.
* No logging of file names, metadata values, GPS coordinates, tokens or raw IPs — IPs are reduced to
  a truncated HMAC before they can reach a log line, and tool output is scrubbed of server paths.
* Pinned dependency lockfiles (`requirements.lock.txt`, `package-lock.json`) auditable with
  `pip-audit` and `npm audit`.

**No penetration test or third-party security audit has been performed on this project.** The
[verification record](docs/VERIFICATION.md) lists exactly what was tested and what was not.

---

## 6. Honest limitations

* ExifTool removes the metadata it understands. It does **not** remove PDF attachments, hidden PDF
  layers, form-field values, JavaScript actions, Office revision history/tracked changes,
  in-stream video GPS tracks, vendor-specific atoms, or data hidden inside image pixels. Each report
  lists those categories per file under "not verified as removed".
* The free tier is a small shared instance, and the file leaves your device. The UI says so before
  every upload. **If a file is sensitive enough that a hosting provider must not see it, clean it
  locally instead.**
* The API sleeps on the free plan (see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)), so the first
  request after idle can take about a minute.
* Structural analysis (trailing data, revision markers, embedded objects) is heuristic and
  read-only; it flags what it can see and never claims more.

---

## 7. Deployment

Frontend on **Cloudflare Pages** (free `*.pages.dev` subdomain) and the API on **Render** free
Docker web services, with all current plan limits documented and verified. Step-by-step commands for
PowerShell and Linux, environment variables, CORS wiring, HTTPS verification, a troubleshooting
table and a verification checklist are in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

---

## 8. License and third-party components

CleanSlate is provided as-is for personal and internal use; see the deployment guide for the free
hosting terms you must accept. Third-party components: ExifTool (Artistic License/GPL, installed
from the official distribution inside the image), qpdf (Apache 2.0), FastAPI/Starlette/Uvicorn
(MIT/BSD), React/Vite/Tailwind/shadcn-ui (MIT). No analytics, advertising, session-replay or
third-party fonts/scripts are used, in application code or in the deployed page.
