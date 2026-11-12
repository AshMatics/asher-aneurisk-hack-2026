# Changelog

All notable changes to SlicePoint are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

**Versioning.** A repository tag `vX.Y.Z` is a SlicePoint release. SlicePoint is several
packages in one repository, each with its own version; every release below lists the
package versions it contains. Packages are not tagged on their own.

## [Unreleased]

### Changed
- CI tests Python 3.12 on pushes and pull requests; Python 3.10 runs only on a manual run
  until the known 3.10 discrepancy is fixed (it showed as a failed check on every PR).

### Security
- Dependabot alerts 11-13 (tornado): core's `notebook` extra now installs only on Python
  3.11 and newer, because the fixed tornado (6.6) dropped Python 3.10; the lock now holds only
  tornado 6.6.1. On 3.10 the notebook test skips.
- Dependabot alert 14 (minimatch, a development-only ESLint dependency): pinned to 11.x with a
  pnpm override; lint, typecheck and tests pass.
- Dependabot no longer proposes major `@types/node` updates, Python base-image moves or
  `pytorch/pytorch` image updates (the segmentation torch stack is upgraded deliberately).

## [0.2.0] - 2026-11-12

The rebuild: SlicePoint as a library, command line, API and web viewer, with public
datasets and vendor-datasheet checks; the repository becomes SlicePoint's home.

Packages: `slicepoint-schemas` 0.2.3 (data contract 0.1.0), `slicepoint-core` 0.2.2,
`slicepoint-api` 0.2.0, viewer 0.2.2, `slicepoint-model` (segmentation) 0.3.1.

### 2026-11-12: the repository

#### Changed
- The repository is now SlicePoint's home: the hackathon material (brief, documents, starter,
  federated harness) moved to `nucleate-hack-2026/`. `data/` stays at the root as the
  sample-data folder; the practice data now downloads from Hugging Face
  (`slicepoint/slicepoint-hospitals`) instead of the hackathon's storage.
- Reference PDFs (the TotalSegmentator paper, the POC reconstruction spec) moved to
  `slicepoint/docs/references/`.

#### Added
- Root `README.md` with a repository map, the datasets and the license and contributor
  status; `DATASETS.md`; this changelog.
- Continuous integration (`.github/workflows/ci.yml`): Ruff, mypy and pytest for schemas,
  core and api on Python 3.10 and 3.12 (mypy on 3.12); viewer lint, typecheck and tests; checks that the
  JSON Schemas, `openapi.json` and the TypeScript contract and client are current.
- Ruff configuration (`slicepoint/pyproject.toml`) and Dependabot version updates
  (`.github/dependabot.yml`).

#### Known issues
- On Python 3.10 the lock resolves older numpy (2.2), scipy (1.15) and scikit-learn (1.7),
  and four core tests differ from the reference results (a domain-classifier gap of +0.21
  instead of +0.17, one sub-factor for `hospital_d`, and the CLI and library results
  disagreeing within one run, which points to non-determinism). CI runs 3.10 without
  blocking; Python 3.12 is the verified version until this is resolved.

#### Fixed
- Unused imports flagged by Ruff in `slicepoint_core.datasheet` and the segmentation
  service script.

### 2026-11-12: SlicePoint

#### Added
- **Vendor datasheets.** `VendorDatasheet` in `slicepoint-schemas` (0.2.2): what a vendor
  discloses about its training data, as marginal summaries, with the population it
  describes and where every number came from (reported, computed, digitized, estimated).
  Race and ethnicity are known variables.
- `slicepoint datasheet check` (`slicepoint-core` 0.2.2): tests a site against a datasheet,
  variable by variable, for coverage (is the site inside what the model saw?) and equality
  (is it distributed the same way?), from summary statistics only. `--scope-broader` reports
  differences as expected when the datasheet covers a wider population.
- `assess --datasheet` (schemas 0.2.3, viewer 0.2.2): the comparison is stored as
  `AssessmentResult.datasheet` and shown as its own section of the HTML report and a
  Datasheet tab in the viewer. It never changes the verdict.
- Example datasheets, including two computed from TotalSegmentator's own metadata.
- Public datasets on Hugging Face: `slicepoint/slicepoint-aaa-ct` and
  `slicepoint/slicepoint-hospitals` (CC BY 4.0), with their cards in `slicepoint/datasets/`.
- The live web UI ships inside `slicepoint-api` (0.2.0, PR #14); `slicepoint/Dockerfile` and
  `docker-compose.yml` run SlicePoint as one container, with segmentation as an optional
  second service.

#### Changed
- Segmentation worker (`slicepoint-model` 0.3.1, PR #15): torch 2.13.0, torchvision 0.28.0
  and nnunetv2 2.8.1, for the Dependabot torch alerts; nnunetv2 2.5.1 cannot load
  checkpoints under torch 2.6 or later.

#### Fixed
- Datasheet age tests use a skew-normal fitted to the quartiles (straight-line tails to the
  minimum and maximum raised a false alarm), count age bands the site lacks, and avoid
  quartile bins when many values sit exactly on a quartile.

### 2026-11-10

#### Added
- `slicepoint-api` (PR #11): a job-based FastAPI service over `slicepoint-core`, with bearer
  and browser-session authentication.
- Viewer live mode (PR #12): runs assessments through the API.
- Check descriptors stored in results, a floor on the domain-classifier AUC, and a flag for
  comparing a site with its own reference (PR #13).

### 2026-11-09

#### Added
- The rebuild, in six steps (PRs #5 to #10): ADR 0001 and the `slicepoint-schemas` contract;
  `slicepoint-core` with parity to the original notebook; the `slicepoint` command line, the
  HTML report and a tier-0 notebook; the static result viewer, shipped by `assess --viewer`;
  a uv workspace for the Python packages.

## [0.1.0] - 2026-11-08

The 2026 Nucleate Pittsburgh hackathon: the "IID Is a Lie" repository and the student
team's SlicePoint proof of concept (tagged retroactively at `35ae40a`).

### 2026-11-08

#### Added
- The hackathon proof of concept by the student team: notebooks, monitoring scripts and
  sample outputs (PR #4), and the pretrained aorta segmentation and comparison service.

### 2026-11-01 to 2026-11-07

#### Added
- The public hackathon repository for "IID Is a Lie" (Nucleate Pittsburgh 2026): brief,
  documents, starter notes, federated audit harness, MIT license (PRs #1 to #3).

[Unreleased]: https://github.com/AshMatics/slicepoint/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/AshMatics/slicepoint/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/AshMatics/slicepoint/releases/tag/v0.1.0
