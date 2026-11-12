# SlicePoint

[![CI](https://github.com/AshMatics/slicepoint/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/AshMatics/slicepoint/actions/workflows/ci.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Dependabot](https://img.shields.io/badge/dependabot-enabled-025E8C?logo=dependabot)](.github/dependabot.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](CHANGELOG.md#known-issues)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Dataset: SlicePoint AAA CT](https://img.shields.io/badge/%F0%9F%A4%97%20dataset-slicepoint--aaa--ct-yellow)](https://huggingface.co/datasets/slicepoint/slicepoint-aaa-ct)
[![Dataset: SlicePoint Hospitals](https://img.shields.io/badge/%F0%9F%A4%97%20dataset-slicepoint--hospitals-yellow)](https://huggingface.co/datasets/slicepoint/slicepoint-hospitals)

SlicePoint checks whether an imaging AI model fits a hospital's patients and scanners
before it is switched on. It compares a sample of the site's scans with a reference (the
data the model was validated on) and returns a **GO / BORDERLINE / NO-GO** verdict, five
health checks with their evidence, AI performance by group, cases to review and, when the
vendor publishes one, a comparison with the vendor's training-data datasheet. The first
model is abdominal aortic aneurysm (AAA) detection on CT; the checks are not specific to AAA.

SlicePoint began as the runner-up project at the 2026 Nucleate Pittsburgh hackathon and is
being rebuilt here as open source by Asher Informatics PBC with the student team.

**Start here:** [slicepoint/README.md](slicepoint/README.md) has the quick start (install,
run one assessment, open the report), the package map and how to run the service with
its web UI. Changes are in [CHANGELOG.md](CHANGELOG.md).

## What is in this repository

| Path | What |
|---|---|
| [`slicepoint/schemas/`](slicepoint/schemas) | `slicepoint-schemas`: the data contract (Pydantic models, JSON Schemas) |
| [`slicepoint/core/`](slicepoint/core) | `slicepoint-core`: the analysis library, the `slicepoint` command line, the HTML report |
| [`slicepoint/api/`](slicepoint/api) | `slicepoint-api`: the FastAPI service, with the web UI bundled |
| [`slicepoint/viewer/`](slicepoint/viewer) | The React result viewer (a single offline file, and the live UI for the API) |
| [`slicepoint/segmentation/`](slicepoint/segmentation) | `slicepoint-model`: the aorta segmentation worker (GPU, TotalSegmentator) |
| [`slicepoint/docs/`](slicepoint/docs) | Architecture decisions, the data contract, a hospital guide, references |
| [`slicepoint/datasets/`](slicepoint/datasets) | The source of the Hugging Face dataset cards |
| [`slicepoint/notebooks/`](slicepoint/notebooks) | The quick-start notebook |
| [`slicepoint/python_notebooks/`](slicepoint/python_notebooks) | The student team's original proof of concept, kept as written |
| [`data/`](data) | Where sample data goes (not in git); [data/README.md](data/README.md) says how to download it |
| [`nucleate-hack-2026/`](nucleate-hack-2026) | The hackathon material: brief, documents, starter and federated harness |

## Datasets

Two public datasets on Hugging Face, both CC BY 4.0 and derived from the TotalSegmentator
dataset (University Hospital Basel). [DATASETS.md](DATASETS.md) describes them in full.

| Dataset | What | Size |
|---|---|---|
| [slicepoint/slicepoint-aaa-ct](https://huggingface.co/datasets/slicepoint/slicepoint-aaa-ct) | 567 abdominal CT scans with ground-truth masks, aortic measurements, AAA labels, a baseline model's predictions and embeddings; cohorts for a vendor/site demo; vendor datasheets | ~17 GB (tables ~20 MB) |
| [slicepoint/slicepoint-hospitals](https://huggingface.co/datasets/slicepoint/slicepoint-hospitals) | The seven simulated hospitals from the hackathon, with planted problems and the answer keys; used by the tests | ~14 GB (tables ~10 MB) |

## License and contributors

The code is released under the [MIT License](LICENSE). The datasets keep their own
license (CC BY 4.0, from TotalSegmentator); see [DATASETS.md](DATASETS.md).

SlicePoint started as a student project. Under the hackathon terms each contributor owns
their work, so each is asked to confirm in writing that their contributions are licensed
under MIT (ADR 0001, open question 1). Until every row below reads "affirmed", the license
of the work listed in that row is pending.

| Contributor | Contributed | MIT affirmed |
|---|---|---|
| Yajushi Khurana (PhD student, Carnegie Mellon University and University of Pittsburgh) | The original proof of concept: notebooks and monitoring scripts in `slicepoint/python_notebooks/` | Pending |
| Umang Pandey (graduate student, Bioengineering, Carnegie Mellon University) | The aorta segmentation and comparison service in `slicepoint/segmentation/` | Pending |
| Manya Natakala (University of Pittsburgh) | The hackathon design and presentation | Pending |
| Evangeline Gulea (University of Pittsburgh) | The hackathon design and presentation | Pending |
| Asher Informatics PBC (John Kalafut, with AI assistance) | The rebuild: schemas, core, API, viewer, datasets, documentation | Yes (copyright holder) |

To affirm, a contributor sends Asher Informatics (or posts on the repository's license issue) this sentence:
*"I agree that my contributions to SlicePoint (github.com/AshMatics/slicepoint) are licensed
under the MIT License."*

**Not for clinical use.** SlicePoint supports a decision; it is not a medical device and
its outputs are not medical advice.
