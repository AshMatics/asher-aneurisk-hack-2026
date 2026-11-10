# SlicePoint

SlicePoint checks whether an imaging AI model fits a hospital's patients and scanners
before it is switched on. It compares a sample of the site's scans with a reference (the
data the model was validated on). The output is a **GO / BORDERLINE / NO-GO** verdict,
five health checks with their evidence, AI performance by group, and a list of cases to
review. The first model is AAA (abdominal aortic aneurysm) detection on CT; the checks
are not specific to AAA.

It began as a runner-up project at the 2026 Nucleate Pittsburgh hackathon and is being
rebuilt here as open source. The architecture is in
[ADR 0001](docs/adr/0001-slicepoint-rebuild-architecture.md).

## Quick start

You need Python 3.10+ and the practice data unzipped into `data/practice/` at the repo
root (see [data/README.md](../data/README.md)). Run these from the repo root.

**1. Install and run one assessment (CLI):**

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e slicepoint/schemas -e slicepoint/core

slicepoint assess --data data/practice/hospital_b --site-id hospital_b \
    --reference-dir data/practice/hospital_a --reference-site-id hospital_a \
    --out out/result.json --html out/report.html --viewer
```

Open `out/report.html` (printable), or `out/slicepoint-viewer.html` and load
`out/result.json` (interactive, offline). Exit code 0 means GO and 3 means a person
should read the report.

**2. Notebook:** open `slicepoint/notebooks/slicepoint_quickstart.ipynb`, set the folders
in Step 2 and choose *Run All*.

**3. Service with the live web UI** (needs [uv](https://docs.astral.sh/uv/), Node 22 and pnpm 9):

```bash
cd slicepoint && uv sync --all-packages --all-extras
(cd viewer && pnpm install && pnpm build:live)
export SLICEPOINT_SERVICE_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
echo "$SLICEPOINT_SERVICE_TOKEN"                 # paste this into the sign-in page
SLICEPOINT_DATA_ROOT="$PWD/../data/practice" SLICEPOINT_RESULTS_DIR="$PWD/../.slicepoint-results" \
SLICEPOINT_UI_DIR="$PWD/viewer/dist-live" SLICEPOINT_COOKIE_SECURE=0 \
    uv run --directory api slicepoint-api        # open http://127.0.0.1:8100/
```

A hospital running it on its own data should follow
[docs/getting-started-hospital.md](docs/getting-started-hospital.md).

## What is here

| Folder | Package | What it is |
|---|---|---|
| [schemas/](schemas/README.md) | `slicepoint-schemas` | The data contract: Pydantic models, JSON Schema, threshold profiles, the check registry |
| [core/](core/README.md) | `slicepoint-core` | The analysis library, CLI, HTML report and notebook support. No server, database or GPU |
| [api/](api/README.md) | `slicepoint-api` | FastAPI service: job-based assessments, token and browser-session auth, serves the live UI |
| [viewer/](viewer/README.md) | `slicepoint-viewer` | React viewer, built two ways: an offline single file (no network access) and a live build for the API |
| [segmentation/](segmentation/README.md) | `slicepoint-model` | Separate GPU worker: 3D aorta segmentation and mask comparison |
| [docs/](docs/) | | ADR, hospital guide, data-contract inventory |

## Develop

```bash
cd slicepoint
uv sync --all-packages --all-extras                  # schemas + core + api, one lock
uv run --directory core pytest -m "not notebook"     # likewise schemas and api; add mypy
cd viewer && pnpm install && pnpm verify             # contract checks, types, lint, tests, both builds
```

## Status and limits

- Input is curated parquet files (features, predictions, optional labels and
  embeddings). Readers for DICOM, PACS exports and report text are planned, not built.
- The 0–100 check scores are provisional and hidden by default until their formulas are
  ratified.
- Results come from a test sample, not a trial. They support a decision and are not
  medical advice.
