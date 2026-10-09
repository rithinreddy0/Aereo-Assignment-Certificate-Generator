# Folio · Detailed API reference

A practical contract for creating batches, following progress, and retrieving PDF certificates.

[README](../README.md) · [Technical guide](TECHNICAL_GUIDE.md)

Jump to [connection basics](#connection-basics), [authentication](#authentication-and-headers),
[job submission](#post-apijobs), [errors](#error-bodies), or the
[complete PowerShell walkthrough](#complete-powershell-walkthrough).

## Connection basics

- Local base URL: `http://127.0.0.1:8000`.
- Deployed backend base URL: `https://folio-aereo-api.onrender.com`.
- Live explorer: [interactive API docs](https://aereo-assignment-certificate-genera.vercel.app/docs).
- Request bodies: JSON, with `Content-Type: application/json`.
- JSON endpoints return `application/json`; file endpoints return PDF or ZIP bytes.
- All job/certificate path IDs are UUIDs. The recipient result's `id` is its certificate ID.
- Invalid UUID syntax returns 422; a valid but unknown UUID returns 404.
- Stored timestamps are UTC ISO strings; `issued_on` is a calendar date, not a timestamp.
- Swagger: `/docs`; machine-readable schema: `/openapi.json`; alternate reference: `/redoc`.
- Locally, run the API **and** `python -m app.worker`, using the same data directory.
  The deployed backend sets `CERT_EMBEDDED_WORKER=true` and starts its worker automatically.

The public demo accepts at most 500 recipients per job; the local configured default is 10,000.
The body-size default is 8 MiB in both modes. Cold starts on free hosting can delay the first request.

Examples use representative IDs/times. Copy real returned IDs when testing. curl examples use
POSIX-shell line continuations; on Windows use `curl.exe` with the appropriate shell syntax or
the PowerShell walkthrough below.

## Authentication and headers

Authentication is disabled by default. If `CERT_API_KEY` is set, every `/api/` request must use
the correct `X-API-Key` or a valid browser-session cookie.

```bash
curl http://127.0.0.1:8000/api/templates -H 'X-API-Key: your-configured-key'
```

In Swagger, click **Authorize** and enter the key value alone. In the browser workspace, use
**Connection settings**. `/health`, docs, and static assets remain public.

`Idempotency-Key` is an optional **POST /api/jobs** header, 1–128 characters. Same key + identical
parsed payload returns the original job with 202; a changed payload returns 409. Use a fresh key
for an intentionally new batch. The header is not an authentication credential.

Idempotency compares canonical validated request data, not only the original raw JSON formatting.
Recipient order still matters. Changing the preset matters. Omitted/default Classic is equivalent
to explicit Classic. Keys are reserved for the database lifetime, not a timed retry window.

## GET /api/templates

**Purpose:** discover supported designs. **Success:** 200 JSON. **Auth:** required only when configured.

```bash
curl http://127.0.0.1:8000/api/templates
```

```json
{
  "default": "classic",
  "items": [
    {
      "id": "classic",
      "name": "Classic",
      "description": "Warm ivory, a double gold border, and timeless formal typography.",
      "accent_color": "#B18B43",
      "page_format": "A4 landscape"
    },
    {
      "id": "modern",
      "name": "Modern",
      "description": "A navy masthead and teal accents for courses and contemporary events.",
      "accent_color": "#16877B",
      "page_format": "A4 landscape"
    },
    {
      "id": "minimal",
      "name": "Minimal",
      "description": "Clean white space, fine charcoal lines, and understated typography.",
      "accent_color": "#303B36",
      "page_format": "A4 landscape"
    }
  ]
}
```

Use an item's `id` as `certificate.template`. A preset is a fixed design, not an uploaded document.

## POST /api/jobs

**Purpose:** validate and persist a batch. **Success:** 202 JSON. Acceptance does not mean completion.
**Headers:** `Content-Type`; optional `Idempotency-Key`; `X-API-Key` if configured.

### Request fields

Top level accepts exactly `certificate` and `recipients`; both are required. Extra fields are rejected.

Inside `certificate`:

- `organization`: required string, 1–120 trimmed characters. Printed issuing organization.
- `course`: required string, 1–120 trimmed characters. Course or event being recognized.
- `issued_on`: required real calendar date; send `YYYY-MM-DD`, for example `2026-10-08`.
- `signatory`: required string, 1–120 trimmed characters. Issuer's printed name.
- `title`: optional string, same length limits; default `Certificate of Completion`.
- `signatory_role`: optional string, same length limits; default `Program Director`.
- `template`: optional `classic`, `modern`, or `minimal`; default `classic`.

Inside each recipient object:

- `name`: required string, 1–120 trimmed characters.
- `email`: optional validated address string or null; default null. Omit it when unavailable—
  an empty string is invalid. Duplicate non-null emails are invalid within the batch, ignoring case.
- `reference`: optional string or null, up to 80 trimmed characters; default null. Printed on the PDF.

Unknown recipient fields are invalid. Numbers are not converted into names. Identical names are
allowed; recipients without email are not deduplicated. Shared/recipient text is NFC-normalized;
control and invisible formatting characters are rejected. Unicode length and font coverage are
separate constraints: accented Latin works; not every valid Unicode character can be printed.

`recipients` must be a nonempty list. The configured default is at most **10,000 recipients**, with
a hard schema cap of 100,000. The entire JSON body must also fit the default **8 MiB** limit.
Increasing one limit does not bypass the other. Browser CSV import submits this same JSON contract.

### Two validation boundaries

**Whole-request rejection (422):** bad envelope/shared fields, unknown template, empty recipient list,
too many recipients, or unsupported shared font text. No job is created.

**Individual INVALID row (202 accepted):** malformed recipient, blank name, invalid/duplicate email,
extra fields, or invalid recipient text structure. Other valid rows are queued. Unsupported font
glyphs in a structurally valid recipient name/reference become FAILED during PDF rendering.

### Example request

```json
{
  "certificate": {
    "template": "modern",
    "organization": "Aereo Academy",
    "course": "Python Backend Development",
    "issued_on": "2026-10-08",
    "signatory": "Vidya Pawar"
  },
  "recipients": [
    {
      "name": "Alex Morgan",
      "email": "alex@example.com",
      "reference": "STUDENT-001"
    },
    { "name": "Renée Müller", "email": "renee@example.com" },
    { "name": "" }
  ]
}
```

Save your request as JSON, or use the included `examples/job.json` (different demo names, Classic design):

```bash
curl -X POST http://127.0.0.1:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: folio-batch-001' \
  --data-binary @examples/job.json
```

### Representative response for the JSON example above

```json
{
  "id": "7401d4c6-9929-45cf-9e42-7cadb4888239",
  "status": "QUEUED",
  "total": 3,
  "succeeded": 0,
  "failed": 1,
  "invalid": 1,
  "pending": 2,
  "progress_percent": 33.33,
  "created_at": "2026-10-08T09:00:00+00:00",
  "finished_at": null,
  "certificate": {
    "organization": "Aereo Academy",
    "course": "Python Backend Development",
    "title": "Certificate of Completion",
    "issued_on": "2026-10-08",
    "signatory": "Vidya Pawar",
    "signatory_role": "Program Director",
    "template": "modern"
  }
}
```

The invalid row is already counted. A worker may progress quickly, so later requests can observe
RUNNING or a terminal outcome. Replaying an idempotent submission returns its current job state,
which may already be terminal, still with HTTP 202.

## GET /api/jobs/{job_id}

**Purpose:** inspect a batch and poll progress. **Success:** 200 with the same job structure above.
**Errors:** 401 if key required/incorrect, 404 if unknown UUID, 422 for malformed UUID syntax.

```bash
curl http://127.0.0.1:8000/api/jobs/7401d4c6-9929-45cf-9e42-7cadb4888239
```

For the mixed-validity example, the terminal counts are `total: 3`, `succeeded: 2`, `failed: 1`,
`invalid: 1`, `pending: 0`, and `progress_percent: 100`. Status is COMPLETED_WITH_ERRORS and
`finished_at` is a UTC timestamp.

### What each job field means

- `id`: opaque job UUID, used in job URLs.
- `status`: current batch lifecycle state.
- `total`: all submitted recipient rows, including invalid ones.
- `succeeded`: successfully completed PDFs.
- `failed`: every unsuccessful outcome, **including** invalid input rows.
- `invalid`: input-validation failures, a subset of `failed`.
- `pending`: rows without a final outcome; QUEUED or PROCESSING.
- `progress_percent`: rounded to two decimals; processed outcomes divided by total, times 100.
- `created_at`: persisted creation time, UTC.
- `finished_at`: UTC completion time, or null while not terminal.
- `certificate`: normalized shared fields and preset used for this batch.

`pending = total - succeeded - failed`. Do not add `invalid` to `failed` again.
100% means every row has an outcome, not that every row succeeded.

### Job statuses

- **QUEUED:** accepted, awaiting worker processing.
- **RUNNING:** the worker has begun this batch.
- **COMPLETED:** all recipients succeeded.
- **COMPLETED_WITH_ERRORS:** at least one success and at least one invalid/failed recipient.
- **FAILED:** zero successful recipients after all outcomes are recorded.

An all-invalid submission immediately becomes FAILED with 100% progress and no worker work.
Poll roughly every two seconds; when pending reaches zero, fetch the latest recipient results.
Status/counts are observed snapshots, not a notification stream or estimated completion time.

## GET /api/jobs

**Purpose:** paginated newest-first batch history. **Success:** 200 JSON.

Query parameters:

- `limit`: integer 1–100, default 25.
- `offset`: integer ≥ 0, default 0.

```bash
curl 'http://127.0.0.1:8000/api/jobs?limit=10&offset=0'
```

The response is `{ "items": [...JobView objects...], "total": 42, "limit": 10, "offset": 0 }`.
`total` counts all jobs; an offset past the end returns an empty items array, not 404.
Each item's shared certificate includes its selected preset. New jobs can shift offset-based
pages while you are browsing; this is not snapshot/cursor pagination.

## GET /api/jobs/{job_id}/certificates

**Purpose:** recipient outcomes in original submission order. **Success:** 200 JSON.
No PDF bytes are included in this list.

Query parameters:

- `limit`: integer 1–500, default 100.
- `offset`: integer ≥ 0, default 0.
- `status`: optional exact uppercase QUEUED, PROCESSING, COMPLETED, INVALID, or FAILED.
- `attention`: boolean, default false. If true, include INVALID and FAILED rows.

Do not combine `attention=true` with `status`; that returns 422. `total` counts rows matching
the filter, not the entire batch. An existing job with no matching rows returns 200 and an empty page.

```bash
curl 'http://127.0.0.1:8000/api/jobs/7401d4c6-9929-45cf-9e42-7cadb4888239/certificates?limit=100&offset=0'
curl 'http://127.0.0.1:8000/api/jobs/7401d4c6-9929-45cf-9e42-7cadb4888239/certificates?attention=true'
```

Representative completed/invalid outcomes:

```json
{
  "items": [
    {
      "id": "f5f16701-2f46-40d4-b51f-f9c67c9e38f1",
      "index": 0,
      "name": "Alex Morgan",
      "email": "alex@example.com",
      "reference": "STUDENT-001",
      "status": "COMPLETED",
      "error": null,
      "download_url": "/api/certificates/f5f16701-2f46-40d4-b51f-f9c67c9e38f1/download"
    },
    {
      "id": "3e3d3db5-1d16-4c16-81d1-f66509057b55",
      "index": 1,
      "name": "Renée Müller",
      "email": "renee@example.com",
      "reference": null,
      "status": "COMPLETED",
      "error": null,
      "download_url": "/api/certificates/3e3d3db5-1d16-4c16-81d1-f66509057b55/download"
    },
    {
      "id": "c2f3663d-ce90-42e8-9913-460a78ba4380",
      "index": 2,
      "name": null,
      "email": null,
      "reference": null,
      "status": "INVALID",
      "error": "name: String should have at least 1 character",
      "download_url": null
    }
  ],
  "total": 3,
  "limit": 100,
  "offset": 0
}
```

`index` identifies the original zero-based input row even when filters are used. Invalid metadata
may be null. Rows failing a
duplicate-email check may retain their already-validated metadata.

Recipient lifecycle: QUEUED → PROCESSING → COMPLETED or FAILED. INVALID rows are recorded at
submission and never rendered. Only COMPLETED has a `download_url`; join that relative path to
your base URL. Generic rendering failures expose a safe message; inspect worker logs for the cause.

## GET /api/certificates/{certificate_id}/preview

**Purpose:** display a completed certificate. **Success:** 200 PDF bytes.

```bash
curl http://127.0.0.1:8000/api/certificates/f5f16701-2f46-40d4-b51f-f9c67c9e38f1/preview \
  --output certificate-preview.pdf
```

`Content-Type: application/pdf`; `Content-Disposition: inline` with a UUID-based filename.
The bytes are the actual generated PDF, not the illustrative HTML card.
HEAD is also supported at the preview URL for headers without the PDF body; it is not shown in Swagger.

## GET /api/certificates/{certificate_id}/download

**Purpose:** download one completed PDF. **Success:** 200 PDF bytes.

```bash
curl http://127.0.0.1:8000/api/certificates/f5f16701-2f46-40d4-b51f-f9c67c9e38f1/download \
  --output certificate.pdf
```

`Content-Type: application/pdf`; `Content-Disposition: attachment` with a UUID-based filename.
An individual completed PDF is available even if other rows in its batch are still processing.

Both PDF endpoints return 404 for an unknown certificate, 409 if its row is not COMPLETED,
410 if its completed file is missing, and 422 for malformed UUID syntax (plus 401 when needed).

## GET /api/jobs/{job_id}/download

**Purpose:** retrieve successful PDFs as one ZIP. **Success:** 200 ZIP bytes.

```bash
curl http://127.0.0.1:8000/api/jobs/7401d4c6-9929-45cf-9e42-7cadb4888239/download \
  --output certificates.zip
```

`Content-Type: application/zip`; attachment filename `{job_id}.zip`. Entries are named by
certificate UUID, preventing duplicate-name collisions and unsafe user-provided filenames.
There is no extra result manifest in the ZIP; obtain names/status mapping from the recipient API.

Availability: pending must be zero and succeeded greater than zero. COMPLETED_WITH_ERRORS jobs
can be downloaded; failed/invalid rows are simply omitted. No successful output or an unfinished
job returns 409. Unknown job returns 404; a missing source PDF while building returns 410.

The first request builds the archive lazily on disk; later requests reuse it. A lock guards concurrent
builds; lock acquisition waits up to 60 seconds before returning 503. It is not an asynchronous ZIP
job, and building can take time. A cached ZIP may remain available even if a source PDF is later lost;
ZIP download is not a full storage-integrity check. Configure suitable client/proxy timeouts.

## GET /health

**Purpose:** API/database connectivity probe. **Success:** 200 JSON. **Auth:** not required.

```json
{ "status": "ok", "worker_required": true }
```

`worker_required` is `true` for a separately managed worker and `false` when the embedded worker
is configured (as in the live deployment). It does not prove that a worker is running,
that PDFs can be written, or that storage has enough free space.

## Error bodies

Application-level errors normally have a string `detail`, for example:

```json
{ "detail": "Wait until the job finishes before downloading its ZIP" }
```

Framework validation errors use a list of detail objects, for example:

```json
{
  "detail": [
    {
      "type": "literal_error",
      "loc": ["body", "certificate", "template"],
      "msg": "Input should be 'classic', 'modern' or 'minimal'",
      "input": "unknown",
      "ctx": { "expected": "'classic', 'modern' or 'minimal'" }
    }
  ]
}
```

Exact messages/extra validation keys may depend on the locked framework versions. Inspect status
and location/type, not just string-match every message. Recipient validation errors are stored
in `RecipientView.error` instead of becoming an HTTP rejection for the entire request.

- 401: missing/wrong configured credential; do not blindly retry without correcting it.
- 404: resource does not exist; check whether you copied a job ID or a certificate ID.
- 409: result unavailable or idempotency conflict; inspect detail before retrying.
- 410: storage inconsistency; inspect/recover the missing file, not a frontend formatting issue.
- 413: reduce request bytes or split into batches.
- 422: fix shared input, query parameters, UUID format, or configured recipient limit.
- 503: archive lock timeout; retry after a short delay.

## Complete PowerShell walkthrough

Run from the repository with both API/worker started. This script waits up to five minutes,
then re-fetches results before choosing a completed PDF. Use a fresh key for each intentional batch.

```powershell
$baseUrl = 'http://127.0.0.1:8000'
$headers = @{ 'Idempotency-Key' = [guid]::NewGuid().ToString() }
# If authentication is enabled, uncomment and set your configured key:
# $headers['X-API-Key'] = 'your-configured-key'

Invoke-RestMethod "$baseUrl/api/templates" -Headers $headers
$job = Invoke-RestMethod "$baseUrl/api/jobs" -Method Post `
  -ContentType 'application/json' -Body (Get-Content examples/job.json -Raw) -Headers $headers

$deadline = (Get-Date).AddMinutes(5)
do {
  $job = Invoke-RestMethod "$baseUrl/api/jobs/$($job.id)" -Headers $headers
  Write-Host "$($job.status): $($job.progress_percent)% | ready $($job.succeeded) | failed $($job.failed)"
  if ($job.pending -eq 0) { break }
  if ((Get-Date) -ge $deadline) { throw 'Timed out. Check worker logs and the data directory.' }
  Start-Sleep -Seconds 2
} while ($true)

$results = Invoke-RestMethod "$baseUrl/api/jobs/$($job.id)/certificates?limit=100" -Headers $headers
$results.items | Format-Table index,name,status,error
if ($job.succeeded -gt 0) {
  Invoke-WebRequest "$baseUrl/api/jobs/$($job.id)/download" -Headers $headers -OutFile certificates.zip
  # Ask the API for a success directly, even if the first unfiltered page has only errors.
  $ready = Invoke-RestMethod "$baseUrl/api/jobs/$($job.id)/certificates?status=COMPLETED&limit=1" -Headers $headers
  Invoke-WebRequest ($baseUrl + $ready.items[0].download_url) -Headers $headers -OutFile certificate.pdf
}
```

For batches larger than a result page, request additional offsets until every matching row is read.
New jobs cannot be cancelled/deleted through the current public API; there is no PATCH endpoint,
certificate email dispatch, verification API, or downloadable ZIP error manifest.

## Browser support routes

These are supporting frontend routes, not bulk-generation integration endpoints, and are hidden
from OpenAPI: `GET /`, `GET /ui-config`, `POST /ui-session`, and `DELETE /ui-session`.

`/ui-config` exposes configured limits and whether authentication is required. With authentication
enabled, POST `/ui-session` validates `X-API-Key` and issues an HttpOnly, SameSite=Strict browser
cookie (Secure over HTTPS). DELETE clears the cookie. Neither provides user accounts or ownership.
API clients should normally use `X-API-Key` directly.
