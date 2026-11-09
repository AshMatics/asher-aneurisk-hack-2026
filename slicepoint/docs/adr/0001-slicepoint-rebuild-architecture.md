# ADR 0001: SlicePoint rebuild architecture

- **Status:** Accepted (2026-11-09, Dr. Kalafut)
- **Date:** 2026-11-09
- **Deciders:** John Kalafut (Asher Informatics), SlicePoint student team
- **Supersedes:** the Base44 POC (`unselfish-safe-scan-check.base44.app`), documented in
  `docs/Slicepoint POC Reconstruction Spec.pdf`

## Context

SlicePoint answers one question for a hospital: *is this imaging AI a fit for our patients
and scanners before we turn it on?* It returns a GO / NO-GO verdict backed by five
data-health checks scored 0 to 100.

The hackathon POC runs on Base44 with no code export available. All of its computation
lives in Colab notebooks (`slicepoint/python_notebooks/`). The browser only renders JSON
files that the user uploads. Nothing is persisted. Thresholds are hard-coded. The demo
compares Hospital A against itself, so every check passes. A separately trained
segmentation model and a FastAPI comparison service (`slicepoint/segmentation/`) could
not be integrated because of Base44's limits.

SlicePoint is intended to stay open source (MIT, pending a written grant from the team).
Its primary role is a **pre-deployment fit check (AI-Select)**, with some after-go-live
monitoring (AI-Watch). Asher also intends to offer it free to medium-sized hospitals as a
standalone open-source tool, in the spirit of Epic's open-source Seismometer package.
Running it standalone, without FORGE, is therefore a first-class mode and not a
degraded one. FORGE integration is additive.

## Decision

### 1. Layered architecture with explicit contracts between layers

```text
 Sources            Ingestion adapters         Ingestion surface          Analysis core services          API              UI
 ───────            ──────────────────         ─────────────────          ──────────────────────          ───              ──
 curated parquet ─► ParquetAdapter (today) ─►                       ┌─► Embedding service (data-space marker)
 DICOM (PACS)    ─► oxidicom listener (TBD)─►  CuratedDataset       ├─► Check registry (5 checks, pluggable)  ─► FastAPI /v1 ─► React
 reports (text)  ─► report adapter (TBD)   ─►  (slicepoint-schemas) ├─► Statistics (Wilson, BA, strata)
 NIfTI + masks   ─► NIfTI adapter          ─►                       └─► Segmentation worker (GPU, existing)
                                                      ▲                    ▲
                                                      │   Orchestrator     │   (assessment pipeline; local or FORGE runner)
                                                      └────────┬───────────┘
                                                               ├─► FORGE core services: cohort planning, PGM sample/population synthesis
                                                               ├─► OpenCPU (R statistics)
                                                               ▼
                                                     Assessment store + audit
```

### 2. Ingestion is a stub, and we say so

Today every input is a **hand-curated parquet set made for the hackathon**: `features`,
`labels`, `predictions` and `embeddings`, joined on `case_id`. The embeddings were
precomputed upstream.

> **Input datasets must be curated and adapters built. This is TBD.** The rebuild does
> not claim a production ingestion path.

What we commit to now:

- The **ingestion surface** is the `CuratedDataset` contract in `slicepoint-schemas`,
  derived from the current features and embedding parquet schema. Analysis code depends
  only on this contract, never on a file format or a source system.
- An `IngestionAdapter` protocol with one working implementation (`ParquetAdapter`).
  Other adapters are named stubs that raise `NotImplementedError`.
- Where FORGE already has building blocks, adapters wrap them instead of reinventing
  them. Candidates are the **oxidicom** DICOM listener (FNNDSC / ChRIS project) for
  DICOM receipt, and FORGE de-identification and cohort tooling. Each one gets its own
  ADR when it is adopted.

### 3. Embedding generation moves into the analysis core

In the POC, embeddings arrive pre-made in `embeddings.parquet`. In the rebuild,
**producing embeddings is an analysis core service**, not an ingestion concern. The
reason is that an embedding of the input data (CT, MR, or the radiology report text)
is itself a *marker of data space*. It can be compared across sites, across time, and
against a model's training distribution, much as VAE latent spaces and reconstruction
error are used to judge whether a model is being run on data it understands.

Concretely:

- `EmbeddingSpace` is a versioned, first-class object: encoder id, version, modality,
  dimension and preprocessing hash. Two embedding sets are comparable **only** when
  their space ids match. The schema enforces this.
- Precomputed embeddings are still accepted at the ingestion surface, tagged with the
  space they claim to come from.
- Reference (training/validation) distributions are stored as embedding-space profiles
  versioned with the model. This fixes the POC's self-comparison flaw.

### 4. Backend: FastAPI on Python

- All the real computation is Python: the statistics, the embedding shift tests
  (PCA / k-NN / domain AUC), category-mix distance (TVD) and TotalSegmentator.
- `slicepoint/segmentation` is already FastAPI with token auth, upload limits and a
  versioned response. We extend that pattern.
- There is no Node runtime tier. Vite's dev server proxies API calls to FastAPI. In
  production, FastAPI serves the static build or runs as a separate container.
- GPU segmentation stays a separate worker service, because it is single-flight behind
  a lock.

### 5. An orchestrator runs the assessment pipeline

An assessment is a multi-step workflow, not a single request: ingest, embed, load the
reference profile, run the checks, derive the verdict, then render the report. Some steps
call services outside SlicePoint:

- **ASHER FORGE core services** (from the AI-Assess work): cohort planning, and
  probabilistic graphical models (PGMs) that synthesize samples and populations. Uses
  include sizing a validation cohort and generating a reference population when a vendor
  will not share its training distribution.
- **OpenCPU**, for statistics already validated in R.
- The **GPU segmentation worker**.

Decision:

- The pipeline is a declarative list of steps. Each step's inputs and outputs are typed
  with `slicepoint-schemas` models, so steps can be retried, cached and audited
  individually.
- Each external service sits behind a port (an interface) with an explicit
  "unavailable" result. A step that needs a missing service is reported as skipped. It
  never silently passes.
- Two runners implement the same interface:
  - A **local in-process runner**, the default for the open-source and standalone use.
    It needs one machine and no FORGE.
  - A **FORGE runner**, which dispatches steps to FORGE runners and compute. This costs
    Asher compute, but it is worth keeping for the services that only exist there.
- The API is job-based: `POST /v1/assessments` returns a job id, and progress and
  results are read per step.
- The workflow engine (in-process queue, Celery, Prefect, Temporal, or FORGE's own) is
  **not chosen here**. It gets its own ADR once the FORGE runner contract is known.

### 6. Contract package: `slicepoint-schemas`

- Pydantic v2 models only, with no numpy, torch or pandas, so FORGE and third parties
  can import it cheaply.
- It is the single source of truth. OpenAPI and JSON Schema are generated from it,
  then TypeScript types via `openapi-typescript`.
- Every payload carries a `schema_version`. Sites are identified by a stable `site_id`,
  not by matching hospital-name strings.
- **Thresholds are configuration, not constants.** A `ThresholdProfile` per model and
  per site carries the Dice markers, size tolerance, decision lines, check targets and
  minimum group size, along with their provenance. The 30 mm rule is AAA-specific.
  The checks themselves generalize to other imaging AI.
- **Checks form a registry.** Each check exposes a descriptor (id, title, definition,
  target, sub-factors) and returns a `CheckResult`. The UI renders check cards
  generically from the descriptor, so a new check needs no UI change.
- The verdict is three-state: `go`, `no_go` or `borderline`. Failing sub-factors are
  named, and every score carries its sample size so a reader can see when the evidence
  is thin.

### 7. Frontend: React (web), not React Native

- React has the larger open-source contributor pool and the stronger medical-imaging
  ecosystem (OHIF, Cornerstone3D, NiiVue). The POC's UI patterns are already React and
  shadcn.
- The users are a decision committee and clinicians or analysts working on desktop.
  React Native would add cost and serve no one.
- Summary and chart view-models are plain TypeScript, so a Vue shell (Asher house style)
  can reuse them. FORGE integrates through the API or an embedded web component, not
  by sharing UI code.

### 8. Persistence and audit (next phase, not in scope for the first cut)

Each assessment is stored with: who ran it, the model version, the dataset hash, the
embedding-space id, the threshold profile and the verdict. This is the hook into
AI-Watch for after-go-live monitoring. The planned stack is SQLAlchemy and Alembic.

### 9. Library first, with tiered deployment

A mid-sized hospital will not run a FastAPI container. It can run a notebook. Following
the pattern of Epic's Seismometer, SlicePoint is built **library first**:

- `slicepoint-schemas`: the contract (§6).
- `slicepoint-core`: importable analysis classes covering ingestion adapters, the
  embedding service, the check registry, statistics and the local runner. It depends on
  pandas, scipy and scikit-learn, and **never** on FastAPI, a database or a GPU. Steps
  that need external services (segmentation, PGM synthesis, OpenCPU) are optional and
  report themselves as skipped when the service is absent.
- Thin shells over the same code path: template notebooks, a CLI with JSON output
  (which is also how an AI assistant such as Copilot can run it), and the FastAPI service.

The React app also builds as a **static viewer** that renders a versioned result JSON,
which was the POC's own model. A hospital can therefore see the full UI without a
server, and no patient data leaves its premises. The library also writes a
self-contained HTML report.

| Tier | Audience | Runs |
|---|---|---|
| 0 | Gifted, mid-sized hospital | `pip install slicepoint`, a notebook or CLI, an HTML report, and the static viewer |
| 1 | Site with IT support | Tier 0 plus a self-hosted static viewer |
| 2 | FORGE / AI-Select | FastAPI, the orchestrator with the FORGE runner, persistence and audit |

Streamlit was not chosen: it would be a third UI to maintain, and the notebook plus the
static viewer already cover that need.

## Consequences

- **Good:** the computation is reproducible and auditable. One contract serves the UI,
  FORGE and outside contributors. New checks, modalities and ingestion sources plug in
  without touching the UI.
- **Cost:** the notebook logic has to be ported into services and tested. That is the
  bulk of the reconstruction effort.
- **Risk:** the schema is derived from one curated hackathon dataset and will change
  once real adapters exist. The mitigation is `schema_version` plus explicit
  `NotImplementedError` stubs rather than silent assumptions.

## Alternatives considered

| Option | Why not |
|---|---|
| Express or Node middle tier | It would only proxy to Python and add a second language. The Base44 integration already needed exactly this proxy. |
| Flask | No native Pydantic validation, OpenAPI or async. All of it would be bolted on. |
| Django | Its ORM and admin are useful but heavyweight. SQLAlchemy covers persistence. |
| Vue frontend | It matches Asher's house style, but the open-source audience and the imaging ecosystem are React-first. Vue reuse is preserved through the API and view-models. |
| React Native | No mobile user exists for this workflow. |

## Open questions

| # | Question | Owner | Status |
|---|---|---|---|
| 1 | **Contributor licence grant.** The repo `LICENSE` is MIT, but the copyright line is Asher Informatics PBC. Under Nucleate terms the student team owns its IP, so the team must explicitly agree in writing that its contributions are licensed MIT. A one-line written grant or a DCO sign-off both work. | Dr. Kalafut, with the team | **Blocks** code landing near FORGE |
| 2 | **Score formulas.** See below. | Dr. Kalafut to ratify | Provisional v0 proposed |
| 3 | **`<hospital>_dice.json`.** No writer exists in the repo. The segmentation notebook that produced it was never committed, so its contract is inferred. | Ask the team | Open |
| 4 | **Reference distributions.** Where they come from per model, and who signs them. This is a required step: without them every check compares a site against itself. PGM-synthesized populations (§5) are a fallback, not a substitute. | Open | Needed before any real GO |
| 5 | **First `EmbeddingSpace`.** CT uses the Merlin CT encoder (2,048-d, per `docs/data-card.md`), version unknown. For report text, the likely candidate is `embeddings-small` as used in Asher Foundry. | Confirm | Open |

**Score formulas (question 2).** No code anywhere computes the 0 to 100 check scores. The
notebook emits only a categorical status per check (`OK` / `Watch` / `Problem`), built
from TVD, Wasserstein, domain-AUC and Wilson triggers (see `data-contract-inventory.md`).
The schema therefore treats **status as primary** and makes the numeric score optional,
always tagged with a named `score_method`.

A provisional first attempt, `score_method = "provisional-v0"`:

| Check | Provisional score |
|---|---|
| Different people | 100 × distinct people ÷ scans |
| Scan settings match | 100 × (1 − worst TVD across scanner, contrast and slice thickness) |
| Patients match | 100 × (1 − worst TVD across sex, age band and aneurysm size class) |
| Labels follow 30 mm rule | 100 × (1 − share of labels that conflict with the rule) |
| AI accuracy | the lowest of: Dice × 100, share of scans within size tolerance, and sensitivity |

Each formula is reported with its n and a Wilson interval where it applies. A red trigger
always overrides a passing score. These formulas are a reasonable first cut that matches
the POC's sub-factors. They are not validated and must not be shown to a hospital until
ratified.
