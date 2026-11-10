# slicepoint-api

The FastAPI service for SlicePoint (ADR 0001 sections 4 and 5, milestones M4 and M5). It is a
thin, job-based shell over `slicepoint-core`: the same `ParquetAdapter` ->
`ReferenceProfile` -> `Assessment.run()` path as the CLI and the notebook. Results are
the `AssessmentResult` contract from `slicepoint-schemas`, unchanged.

## Install and test

```bash
cd slicepoint
uv sync --all-packages --all-extras
uv run --directory api pytest        # auth, sessions, UI serving, path safety, jobs, parity, OpenAPI staleness
uv run --directory api mypy          # --strict with the pydantic plugin
```

The parity and job tests need `data/practice` (hospital a = reference, b to e = sites).

## Run

```bash
export SLICEPOINT_SERVICE_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export SLICEPOINT_DATA_ROOT=/path/to/data/practice
export SLICEPOINT_RESULTS_DIR=/path/to/slicepoint-results
uv run --directory api slicepoint-api            # or: python -m slicepoint_api
```

It listens on `127.0.0.1:8100` with a single process. Job state is held in memory and
written to the results folder, so do not run more than one worker.

| Variable | Default | Meaning |
|---|---|---|
| `SLICEPOINT_SERVICE_TOKEN` | required | Bearer token, at least 32 characters |
| `SLICEPOINT_DATA_ROOT` | required | Folder that holds the dataset folders |
| `SLICEPOINT_RESULTS_DIR` | required | Where jobs and reference profiles are written; must not be inside the data root |
| `SLICEPOINT_MAX_BODY_BYTES` | 1048576 | Request body cap |
| `SLICEPOINT_MAX_CONCURRENT_JOBS` | 1 | Jobs that run at the same time |
| `SLICEPOINT_MAX_QUEUED_JOBS` | 16 | Queued plus running jobs before new submissions get 503 |
| `SLICEPOINT_ENABLE_DOCS` | off | `1` serves `/docs` and `/openapi.json` (still behind the token) |
| `SLICEPOINT_UI_DIR` | unset | Folder with the live viewer build (`pnpm build:live` -> `slicepoint/viewer/dist-live`); served at `/`. Unset means no UI routes |
| `SLICEPOINT_SESSION_TTL_SECONDS` | 28800 | Browser session lifetime (8 hours; not sliding) |
| `SLICEPOINT_COOKIE_SECURE` | on | `0` drops the cookie's `Secure` flag, for plain-http loopback development only |
| `SLICEPOINT_API_HOST`, `SLICEPOINT_API_PORT` | 127.0.0.1, 8100 | Bind address |

The token variable is not `SLICEPOINT_API_TOKEN` on purpose. That name belongs to the
GPU segmentation worker, and the two services should not share a secret.

## The live viewer

```bash
cd slicepoint/viewer && pnpm build:live
export SLICEPOINT_UI_DIR="$PWD/dist-live"
export SLICEPOINT_COOKIE_SECURE=0     # only when browsing over plain http on loopback
uv run --directory ../api slicepoint-api   # then open http://127.0.0.1:8100/
```

The service refuses to start if `SLICEPOINT_UI_DIR` has no `index.html`. The built UI is
not shipped inside the Python package. `/`, `/index.html` and `/assets/*` are served
without auth (the shell holds no data) with a same-origin CSP: `default-src 'none';
script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self';
base-uri 'none'; form-action 'self'; frame-ancestors 'none'`. Only plain path segments
under the UI folder are served: no dot-files, no `..`, no symlinks out of it.

## Authentication

Two ways in, checked in an ASGI middleware before the body is read:

- **Bearer token** (`Authorization: Bearer <token>`): the CLI, scripts and FORGE. Unchanged
  from M4, and needs no CSRF header.
- **Session cookie**: the browser. `POST /v1/session` with `{"token": "..."}` checks the
  token with `hmac.compare_digest` and sets a cookie holding a random 256-bit session id,
  never the token. The server keeps only a hash of the id, in memory, with an expiry, so
  sessions end on restart. The cookie is `HttpOnly; SameSite=Strict; Path=/; Max-Age=<ttl>`
  and `Secure`. With `Secure` on it is named `__Host-slicepoint-session`; with
  `SLICEPOINT_COOKIE_SECURE=0` it is `slicepoint-session` (browsers reject `__Host-`
  without `Secure`). Run with `Secure` on whenever the service is reached over TLS.

CSRF: SameSite=Strict, plus a custom header. Every cookie-authenticated request with an
unsafe method (anything but GET, HEAD, OPTIONS) must send `X-SlicePoint-CSRF: 1`, or it
gets 403. `POST` and `DELETE /v1/session` need the header too. A cross-site form cannot
set a custom header, and a cross-site fetch that does would need a CORS preflight, which
this service never grants.

| Method and path | Auth | What it does |
|---|---|---|
| `GET /v1/session` | none | `{"signed_in": bool, "expires_at": ...}` for the cookie sent. It ignores the `Authorization` header, so it cannot be used to test tokens |
| `POST /v1/session` | CSRF header | Sign in. Body capped at 1 KiB. A wrong token is 401 and counts towards the same per-address limit as a bad bearer token (10 a minute, then 429) |
| `DELETE /v1/session` | CSRF header | Sign out: forgets the session and clears the cookie (204) |

An unknown, expired or signed-out cookie is 401 and counts towards the rate limit.

## Endpoints

All routes except `/healthz`, `/v1/session` and the UI need the bearer token or a
session cookie (see above). An optional
`X-SlicePoint-User` header is recorded on jobs and references as `requested_by`.
It is self-reported, because there is one shared token.

| Method and path | What it does |
|---|---|
| `GET /healthz` | Liveness only, no auth |
| `GET /v1/checks` | Check registry descriptors |
| `GET /v1/datasets` | Dataset folders under the data root (folders holding `features.parquet`), names only |
| `POST /v1/references` | Build a reference profile from a dataset (`site_id` required) and store it; 201, or 409 if the id exists |
| `GET /v1/references`, `GET /v1/references/{id}` | Stored reference profiles |
| `POST /v1/assessments` | Queue an assessment; 202 with a job id and a `Location` header |
| `GET /v1/assessments` | All jobs, newest first, including finished jobs from before a restart |
| `GET /v1/assessments/{id}` | Job status with each step's status, timings and message |
| `GET /v1/assessments/{id}/result` | The `AssessmentResult` JSON; 409 until the job has succeeded |
| `GET /v1/assessments/{id}/report.html` | The self-contained HTML report; 409 until the job has succeeded |

Assessment request body:

```json
{
  "dataset": "hospital_b",
  "site_id": "hospital_b",
  "reference_id": "ref-hospital_a",
  "site_name": "Hospital B",
  "profile": null,
  "on_inconsistency": "raise",
  "show_provisional_scores": false
}
```

Instead of `reference_id` you can send `reference_dataset` with `reference_site_id`. The
reference site id is required and never guessed. `profile` is an inline
`ThresholdProfile`; it defaults to `hackathon-default-v0`. Provisional 0 to 100 scores are
stripped from the result and the report unless `show_provisional_scores` is true.

### Jobs and steps

A job runs a declarative list of steps (`slicepoint_api/pipeline.py`):
`ingest_site`, `load_reference`, `embedding`, `segmentation`, `forge_pgm`, `opencpu`,
`run_checks`, `render_report`. Each step is `pending`, `running`, `succeeded`, `failed`
or `skipped`. The external-service steps go through the ports in
`slicepoint_core.ports`. With no service configured they are `skipped` with the message
"service not configured". A skipped step never counts as a pass. A job state of
`succeeded` means the pipeline ran, not that the site passed: read the verdict.

An input problem (a missing file, a bad column, mismatched embedding spaces) fails its
step with a one-line message that names files relative to the data root. Any other error
is logged on the server and shown to the client only as "internal error".

The runner sits behind a `JobRunner` protocol. The current one is an in-process thread
pool. The workflow engine is not chosen yet (ADR 0001 section 5).

### Files on disk

```text
$SLICEPOINT_RESULTS_DIR/
  <job_id>/job.json         job record: request, steps, audit fields
  <job_id>/result.json      AssessmentResult
  <job_id>/report.html      HTML report
  references/<id>/          reference.json, reference_arrays.npz, service.json
```

On startup the service reads every `job.json`. Finished jobs can be listed and read as
before. Jobs that were queued or running when the process stopped are not resumed; they
are reported as `failed` with an "interrupted" error.

The audit fields on each job are: `requested_by`, the API, core and schemas versions,
the dataset fingerprint, the reference id and fingerprint, the profile id, the model id,
the embedding space id and the final verdict.

## Security notes

- Binds to loopback by default. Put a TLS proxy in front of it before exposing it.
- The token and session cookies are checked with `hmac.compare_digest` and a hashed
  session map in an ASGI middleware before the body is read; only `POST /v1/session`
  reads a body (at most 1 KiB) before it checks the token. Repeated bad tokens or cookies
  from one address are throttled (429).
- The service refuses to start if the token is shorter than 32 characters or a required
  variable is missing.
- Keep the token in the environment or a secrets store. Never put it in source control or
  an AI prompt, and never store it in the browser (see `segmentation/LOCAL_API.md`). The
  live viewer only sends it once, to `POST /v1/session`, and keeps nothing but the
  HttpOnly cookie.
- Dataset names are relative to the data root. Absolute paths, `..` and symlinks that
  resolve outside the root are rejected, and error messages do not include server paths.
- Validation errors do not echo request values back. The docs routes are off by
  default. Responses carry `no-store`, `nosniff`, `DENY` and `no-referrer` headers, and a
  `default-src 'none'; frame-ancestors 'none'` CSP unless the route sets its own (the UI
  above; `report.html` gets its own meta CSP repeated as a header: inline styles only, no
  script, no network).

## OpenAPI and TypeScript types

`openapi.json` is generated from the app and committed. A test fails if it is stale.

```bash
uv run --directory api slicepoint-api-openapi          # regenerate
uv run --directory api slicepoint-api-openapi --check  # exit 1 if stale
```

The live viewer generates its TypeScript types from it with `openapi-typescript`
(`pnpm gen:api` in `slicepoint/viewer`); `pnpm check:api` fails if they are stale.

## Out of scope for M4 and M5

- Uploads. Data is read only from folders under `SLICEPOINT_DATA_ROOT`.
- A database. Persistence is JSON files; SQLAlchemy and Alembic come later (ADR 0001 section 8).
- Building references from the browser. Use `POST /v1/references` with the token.
- The FORGE runner and the real segmentation, embedding, PGM and OpenCPU integrations.
  Their steps are reported as skipped.
- Per-user accounts. There is one shared token; jobs started from the browser are recorded
  with `requested_by` "unknown" unless `X-SlicePoint-User` is sent.
