# slicepoint-viewer

One React codebase, two builds:

| Build | Command | Output | Talks to |
|---|---|---|---|
| **Static** (ADR 0001 §9, tier 0/1) | `pnpm build` | `dist/slicepoint-viewer.html`, one file | nothing: CSP `default-src 'none'`, no network code compiled in |
| **Live** (tier 2) | `pnpm build:live` | `dist-live/` (`index.html` + `assets/`) | the slicepoint-api service that serves it, same origin only |

The static file is what a hospital opens next to patient data, so it must be provably
offline. The live build exists to start and follow jobs on a SlicePoint service, so it has
to make requests; it is kept out of the static file entirely rather than switched off at
runtime (see "Two builds" below).

## The static viewer

The static SlicePoint viewer (ADR 0001 §9, tier 0/1). It opens a `result.json` written by
`slicepoint assess` and shows the verdict, the five health checks with their evidence,
performance, results by group, cases to review, notes, methods and limits, the thresholds
the run used, and provenance. It is one HTML file that runs in a browser with no server.
It makes **no network requests**: no analytics, fonts or CDNs. The file you open is read
in the browser and is never uploaded.

It shows what the result contains and computes no statistics. Anything optional the result
lacks (thresholds, by-group table, cases to review, Dice markers) is shown as "not recorded
in this result". Provisional 0-100 scores stay hidden unless the file carries them (written
with `--show-provisional-scores`). Even then they appear only after the reader ticks a box
labelled as unratified.

## How a hospital uses it

1. Get `slicepoint-viewer.html`, the one file built from this folder (see Build), from
   whoever set SlicePoint up. It works on Windows, macOS and Linux in a current Chrome, Edge,
   Firefox or Safari.
2. Run an assessment as usual: `slicepoint assess ... --out result.json`.
3. Double-click `slicepoint-viewer.html`. It opens from `file://`, offline. Then click
   **Open result.json**, or drag the file onto the page.
4. Read the verdict first, then the check cards. "Show the numbers" opens a check's
   sub-factors and evidence. The tabs hold performance, results by group, the cases to
   review (sortable, with filters) and methods and provenance.

The page carries a strict Content-Security-Policy (`default-src 'none'`; the inline
script and style are allowed by hash). The browser itself would block any request even if
the code tried to make one. **Try a sample** opens results from the synthetic hackathon
practice data that are built into the page. To share one result with a colleague, send
the `result.json` and the viewer file together, or use the self-contained HTML report
(`--html report.html`), which is also the better choice for printing.

A site with IT support (tier 1) can serve `dist/index.html` (the same file) from any
static web server. No server-side code is needed.

## The live viewer

Served by slicepoint-api at `/` when `SLICEPOINT_UI_DIR` points at `dist-live/` (see
`slicepoint/api/README.md`). It adds, on top of the same result screen:

- **Sign in**: paste the service token once. The page posts it to `POST /v1/session`,
  clears the field and never stores it (no localStorage, no sessionStorage). The browser
  then holds only an HttpOnly session cookie the page cannot read. **Sign out** ends the
  session on the server.
- **Assessments**: every job with its site, dataset, state, verdict and created time. The
  list refreshes itself while any job is queued or running. "Finished" means the pipeline
  ran, not that the site passed.
- **Start an assessment**: site dataset (from `GET /v1/datasets`), site id, optional site
  name, and either a stored reference (from `GET /v1/references`) or a reference dataset
  with its reference site id. Site ids are typed, never guessed from folder names.
  Provisional scores are off by default and labelled unratified.
- **Steps**: per-step progress (waiting, running, done, failed, skipped) with messages,
  polled until the job ends. A skipped step has its own glyph, words and dashed outline:
  it did not run and is not a pass.
- **Open result**: loads `/v1/assessments/{id}/result` and runs it through the same
  `viewmodel/load.ts` validation as a file opened in the static viewer, then shows it in
  the same `ResultScreen`. **HTML report** opens `/v1/assessments/{id}/report.html` in a
  new tab (the cookie works for GET).

Not in M5: building references, uploads, a database.

Every request sends `X-SlicePoint-CSRF: 1` and `credentials: "same-origin"`; the API
requires the header for cookie-authenticated unsafe methods. The API serves the page with
`default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:;
connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`.

## Two builds

- `index.html` -> `src/main.tsx` (static) and `live.html` -> `src/live/main.tsx` (live)
  are separate entries chosen by Vite's mode (`vite.config.ts`). The static entry never
  imports `src/live`, so the API client is not in its bundle at all.
- eslint forbids importing `src/live` from anywhere else, and allows `fetch` only in
  `src/live/client.ts`.
- `scripts/check-build.mjs` fails the static build if the bundle contains a network API
  (`fetch(`, XHR, WebSocket, EventSource, `sendBeacon`) or a live-mode marker (`/v1/`, the
  CSRF header name, `credentials: "same-origin"`, the client's option names).
- `scripts/check-live.mjs` renames `live.html` to `index.html` and fails if the live page
  has an inline script or style, an inline event handler, anything outside `/assets/`, a
  network API other than `fetch`, an `Authorization`/`Bearer` header or `sessionStorage`.
- `src/live/api.generated.ts` holds the API types, generated with `openapi-typescript`
  from `slicepoint/api/openapi.json` (plus the site-id pattern the form checks).
  `pnpm gen:api` regenerates it; `pnpm check:api` (part of `verify` and `build:live`)
  fails if it is stale. Regenerate `openapi.json` first after an API change:
  `uv run --directory api slicepoint-api-openapi`.

## Develop

Node 22 and pnpm 9.

```bash
cd slicepoint/viewer
pnpm install
pnpm dev                 # Vite dev server; open http://localhost:5173/?sample=hospital_b
pnpm test                # vitest: view-models, every fixture against the schema, React Testing Library
pnpm typecheck           # tsc --noEmit (strict)
pnpm lint                # eslint, no warnings allowed
pnpm verify              # contract + API type checks, typecheck, lint, tests, both builds
```

Live mode against a local API (in `slicepoint/`, with the API running on 127.0.0.1:8100
and `SLICEPOINT_COOKIE_SECURE=0`, because the dev server is plain http):

```bash
pnpm dev:live            # Vite on http://localhost:5173, proxies /v1 to the API
SLICEPOINT_API_URL=http://127.0.0.1:9000 pnpm dev:live   # another API address
pnpm build:live          # dist-live/; serve with SLICEPOINT_UI_DIR=$PWD/dist-live
```

`?sample=<id>` opens one of the bundled samples (`hospital_b`, `hospital_a_override`,
`hospital_c_scores`). It can only
select bundled data and never loads anything, so it is also enabled in the built file
(for demos and automated screenshots).

## Build

```bash
pnpm build
```

The build writes `dist/slicepoint-viewer.html` (and the identical `dist/index.html`): one
file of about 0.9 MB (190 kB gzipped) with every script, style and sample inlined
(`vite-plugin-singlefile`). Most of the size is the seven bundled samples. `pnpm build`
first runs `check:contract` and `typecheck`. It then runs `scripts/check-build.mjs`,
which:

- fails if the page references any external resource (`src`/`href`, `<link>`, CSS
  `@import` or remote `url()`) or if the code uses a network API (`fetch`, XHR, WebSocket,
  EventSource, `sendBeacon`);
- adds the CSP meta tag with sha256 hashes of the inline script and style;
- lists the URL strings that remain in the code and are never requested (SVG/XML
  namespaces, and React's error-page link).

### Distribution

`dist/` is not committed. `pnpm build:core` builds the viewer and copies it into
slicepoint-core (`core/src/slicepoint_core/_viewer/`, which is committed), so
`slicepoint assess --viewer` writes it next to `result.json` and a hospital never needs
Node. Run it whenever the viewer or `AssessmentResult.schema.json` changes; core's
`tests/test_viewer.py` fails on a stale copy. The same file can also be attached to
GitHub releases.

## The contract

`src/contract/` is generated from
`slicepoint/schemas/jsonschema/AssessmentResult.schema.json`, the JSON Schema exported from
the Pydantic models in `slicepoint-schemas`:

| File | What it is |
|---|---|
| `assessment-result.generated.ts` | TypeScript types (`json-schema-to-typescript`) |
| `validate.generated.js` | an Ajv validator precompiled to standalone code (draft 2020-12, `date-time` formats), so the page needs no `eval` and the CSP stays strict |
| `schema-meta.generated.ts` | the `schema_version` the viewer reads, and the schema's sha256 |
| `index.ts` | hand-written stable aliases for the generated names |

```bash
pnpm gen:contract        # regenerate after the schema changes
pnpm check:contract      # fail if src/contract is stale (also run by pnpm build)
```

When it loads a file, the viewer:

1. parses the JSON;
2. checks `result_type`;
3. refuses any `schema_version` other than the one it was generated from, and names the
   version it found;
4. validates the whole file;
5. shows every failure as a readable message with the field path (for example
   `verdict.outcome: must be one of "go", "no_go", "borderline"`), never a blank page.

## Layout

| Path | What it holds |
|---|---|
| `src/live/` | Live build only: `client.ts` (the one fetch wrapper), `viewmodel.ts` (plain TS: job and step labels, form validation), `LiveApp.tsx`, `SignIn.tsx`, `Jobs.tsx`, `StartAssessment.tsx`, `api.generated.ts` |
| `src/components/ResultScreen.tsx` | The result header, provisional-score gate and tabs, shared by both builds |
| `src/viewmodel/` | Plain TypeScript, no React (enforced by eslint), so a Vue shell can reuse it (ADR 0001 §7). `load.ts` (parse and validate), `verdict.ts`, `checks.ts` (generic check cards, evidence drill-down, score gating), `performance.ts`, `strata.ts`, `cases.ts` (sorting and filtering), `about.ts` (methods, limits, thresholds, provenance), `labels.ts` and `format.ts` (the `report.py` label map and humanizer, effective-n formatting), `registry.ts` (display copy for the five built-in checks) |
| `src/components/` | React views over the view-models: hand-written shadcn-style primitives, tabs and SVG charts |
| `src/fixtures/` | Bundled samples; regenerate with `scripts/make-fixtures.sh` (needs the synced uv workspace in `slicepoint/` and `data/practice`) |
| `scripts/` | `gen-contract.mjs`, `gen-api.mjs`, `check-build.mjs`, `check-live.mjs`, `sync-core.mjs`, `make-fixtures.sh` |

Check cards are rendered from whatever is in `result.checks`. A check the viewer has no
copy for still gets a card, with its id and sub-factor ids made readable. The titles of
the five built-in checks mirror `slicepoint_schemas.checks.DEFAULT_CHECK_REGISTRY`,
because the result carries ids and not titles (the same as `report.py`).

Styling uses Tailwind CSS 4 with the stock shadcn/ui neutral tokens, light and dark, plus
status tokens. A status is always shown as text and a glyph, never by colour alone. No
font is downloaded: the page uses Inter if it is installed, and otherwise the system font.
