# slicepoint-api

The FastAPI service for SlicePoint (ADR 0001 sections 4 and 5, milestone M4). It is a
thin, job-based shell over `slicepoint-core`: the same `ParquetAdapter` ->
`ReferenceProfile` -> `Assessment.run()` path as the CLI and the notebook. Results are
the `AssessmentResult` contract from `slicepoint-schemas`, unchanged.

## Install and test

```bash
cd slicepoint
uv sync --all-packages --all-extras
uv run --directory api pytest        # auth, path safety, jobs, parity with core, OpenAPI staleness
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
| `SLICEPOINT_API_HOST`, `SLICEPOINT_API_PORT` | 127.0.0.1, 8100 | Bind address |

The token variable is not `SLICEPOINT_API_TOKEN` on purpose. That name belongs to the
GPU segmentation worker, and the two services should not share a secret.

## Endpoints

All routes except `/healthz` need `Authorization: Bearer <token>`. An optional
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
- The token is checked with `hmac.compare_digest` in an ASGI middleware before the body
  is read. Repeated bad tokens from one address are throttled (429).
- The service refuses to start if the token is shorter than 32 characters or a required
  variable is missing.
- Keep the token in the environment or a secrets store. Never put it in a browser, in
  source control or in an AI prompt (see `segmentation/LOCAL_API.md`).
- Dataset names are relative to the data root. Absolute paths, `..` and symlinks that
  resolve outside the root are rejected, and error messages do not include server paths.
- Validation errors do not echo request values back. The docs routes are off by
  default. Responses carry `no-store`, `nosniff`, `DENY` and `no-referrer` headers.

## OpenAPI and TypeScript types

`openapi.json` is generated from the app and committed. A test fails if it is stale.

```bash
uv run --directory api slicepoint-api-openapi          # regenerate
uv run --directory api slicepoint-api-openapi --check  # exit 1 if stale
```

TypeScript types are meant to be generated from it with `openapi-typescript`, for
example `npx openapi-typescript slicepoint/api/openapi.json -o src/api/types.ts`. The
viewer is not wired to this yet.

## Out of scope for M4

- Uploads. Data is read only from folders under `SLICEPOINT_DATA_ROOT`.
- A database. Persistence is JSON files; SQLAlchemy and Alembic come later (ADR 0001 section 8).
- A live mode in the viewer. The viewer still renders a result JSON.
- The FORGE runner and the real segmentation, embedding, PGM and OpenCPU integrations.
  Their steps are reported as skipped.
- Per-user accounts. There is one shared token.
