# Privacy and data retention

CleanSlate is built so that the *only* thing it keeps is nothing. This page states exactly what
happens to your file, your browser signals and your traffic, and where the limits of that promise
are.

---

## 1. Summary

| Data | Where it goes | How long it exists | Who can see it |
| --- | --- | --- | --- |
| Metadata inspect: uploaded file | API process + per-job scratch dir | Deleted when the request finishes (the job holds no downloadable copy) | The API process; the hosting provider's infrastructure |
| Metadata sanitize: uploaded original | API process + per-job scratch dir | Deleted as soon as processing finishes | Same as above |
| Sanitized copy | Per-job scratch dir until one download or expiry | Deleted right after the single download, or by the TTL sweeper (default 5 min) | Same as above, plus anyone holding the live download URL *from the same client address* |
| Download tokens | API memory only | Until used or expired (default 5 min, single use) | API process only |
| Reports (JSON / printable HTML) | Your browser | Until you close the tab, unless you save the file | You only — reports are generated in your browser, never uploaded |
| Browser fingerprint signals | Your browser tab | Until you close or reload the tab | You only — there is no endpoint that accepts them |
| Server logs | API host log stream | Provider's plan-dependent log retention | Operator + provider; they contain no file data (see §4) |
| Cookies / local storage | Not used | n/a | No cookies or `localStorage`/`sessionStorage` entries are ever written |
| Analytics / advertising / session replay | Not present | n/a | No third-party requests are made by the app |

There is **no account, no database and no permanent file storage**. Nothing you upload can be
retrieved later — not by you and not through the API.

---

## 2. File processing lifecycle

1. **Upload.** The frontend sends the file to the API over HTTPS. The API validates extension and
   magic bytes, streams the file into a freshly created random per-job directory, and enforces the
   upload limit while reading (default 25 MiB). The client's own file on disk is never touched or
   modified.
2. **Inspect.** ExifTool reads the copy in that directory. For an inspect request the uploaded copy
   is deleted when the response is produced; the job keeps no downloadable file.
3. **Sanitize.** A sanitized *copy* is written next to the original inside the same per-job
   directory. The uploaded original is deleted as soon as the rewrite completes.
4. **Verify.** The sanitized copy is re-read and compared with the original read; the comparison and
   the verification block are computed from those two real reads.
5. **Download (once).** A single-use token is issued. Retrieving it returns the sanitized copy with
   `Content-Disposition: attachment`, and the entire job directory is deleted as part of the same
   response's background task — i.e. after the bytes have been sent.
6. **Expiry (if you never download).** The job TTL sweeper deletes any job directory older than
   `JOB_TTL_SECONDS` (default 300 s). A startup purge clears anything a previous process left behind.
7. **Crash safety.** Job directories live under one configured root (`TEMP_ROOT`, default
   `/tmp/cleanslate-jobs`), so a container restart with an ephemeral filesystem wipes them; the
   startup purge covers the case where the filesystem survives.

Configured defaults (all environment-tunable, see [backend/.env.example](../backend/.env.example)):

| Variable | Default | Meaning |
| --- | --- | --- |
| `MAX_UPLOAD_BYTES` | 26214400 (25 MiB) | Largest accepted file |
| `JOB_TTL_SECONDS` | 300 | Longest an undownloaded sanitized copy can live |
| `DOWNLOAD_TOKEN_TTL_SECONDS` | 300 | Download link lifetime |
| `DOWNLOAD_BIND_IP` | `true` | Require the same client address to use the link |
| `MAX_TEMP_BYTES` | 134217728 (128 MiB) | Hard cap on scratch data held at once |
| `MAX_CONCURRENT_JOBS` | 6 | Jobs processed/held at once (2 in the free deployment blueprint) |
| `CLEANUP_INTERVAL_SECONDS` | 15 | Sweeper frequency |

---

## 3. What the server can and cannot see

* The API holds your file **in cleartext** while it processes it. It is not encrypted at rest, only in
  transit (HTTPS).
* The hosting provider's operators, and anyone who obtains an infrastructure-level snapshot of the
  ephemeral disk, could read a file while it is being processed. This is inherent to server-side
  processing and is stated in the app before every upload.
* The sanitized copy is protected only by an unguessable, single-use, expiring token bound to the
  requesting client address. It is not encrypted with a per-user key, because there is no user.
* **If a file is sensitive enough that a hosting provider must not see it, do not upload it.** Clean
  it locally with ExifTool/qpdf/mutool instead; the app says this in plain language rather than
  implying server-side processing is equivalent to local processing.

---

## 4. Logging and diagnostics

Logs are written as key=value lines and are deliberately boring:

* **Logged:** event names (`inspect_ok`, `sanitize_ok`, `download_ok`, `rate_limited`,
  `tool_timeout`, `tool_error`, `startup`, `shutdown`), a job-id prefix (8 chars of a random id), the
  detected format, engine name and version, tag/removal counters, durations, HTTP status, and a
  truncated HMAC of the client IP (`ip_hash=…`, 16 hex chars) used only for rate limiting and
  download binding.
* **Never logged:** file names, file contents, metadata values, GPS coordinates, tag values,
  download tokens, raw IP addresses, browser fingerprint signals, `Origin` values or request bodies.
* Tool stderr (which ExifTool decorates with the scratch file path) is scrubbed of filesystem paths
  before it is used anywhere, and is logged only as a short, path-free, value-free summary.
* Public error responses are generic; no stack traces, internal paths or tool output reach the
  client. Detailed diagnostics stay server-side.
* Automated tests assert all of the above (`backend/tests/test_report_truthfulness.py`,
  `test_inspect.py::test_inspect_does_not_expose_server_paths`).

---

## 5. Browser fingerprint data

* Collection happens in your tab only. The dashboard's own report shows `network requests: 0` for the
  analysis run, and the API exposes no endpoint that could receive the signals
  (`/api/health` → `"fingerprint_collection": false`).
* Nothing is written to cookies, `localStorage` or `sessionStorage` — verified in the browser during
  the verification run and covered by frontend tests.
* The canvas rendering test is off by default and runs only after an explicit consent toggle; WebGL
  renderer strings are collected with a disclosure because any site can read them without asking.
* No uniqueness percentage is produced, because CleanSlate has no representative reference
  population to compute one from. The report states this instead of inventing a number.
* Reports (JSON/HTML) are assembled in the browser from the response object and downloaded locally.

---

## 6. Frontend hosting and traffic

* The static site is served by a CDN/host that may keep standard access logs (IP, user agent, path)
  as part of normal operation. CleanSlate adds no analytics, no cookies and no third-party scripts,
  fonts or pixels, so the app itself contributes no tracking.
* No external requests are made from the page: fonts are system fonts, icons are bundled, and the
  only network calls are `GET /api/health`, `GET /api/v1/limits` and the upload/download requests you
  trigger.
* CORS on the API is an exact-match allowlist of configured frontend origins. It is a browser
  policy only — it does not make the API private, and the API is documented as public.

---

## 7. Deleting your data

You do not have to do anything: uploaded originals are deleted when processing finishes, and the
sanitized copy disappears after one download or at the job TTL. To end a session early, close the tab
(for fingerprint data) and stop using the download link (for a sanitized copy). If you want to force
removal of everything immediately, `docker restart` the API container or wait for the container to
spin down on the free plan — the scratch filesystem does not survive either.
