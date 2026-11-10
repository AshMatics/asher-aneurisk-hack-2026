# slicepoint-core

The importable analysis library for the SlicePoint rebuild (ADR 0001, section 9). It
covers ingestion, the statistics, reference profiles, the check registry and a local
assessment runner. It produces the contract types from `slicepoint-schemas` and never
depends on FastAPI, a database, a GPU or torch (enforced by `tests/test_package.py`).

Milestone 1 ports `test_your_hospital.ipynb` (with `monitor.py`) and reproduces its
results on the practice data. See [PARITY.md](PARITY.md).

Milestone 2 adds the tier-0 shells (ADR 0001 §9) over the same code path
(`ParquetAdapter` -> `ReferenceProfile` -> `Assessment.run()`): the `slicepoint` command
line, a self-contained HTML report, and the quickstart notebook
`slicepoint/notebooks/slicepoint_quickstart.ipynb`. The hospital-facing guide is
[docs/getting-started-hospital.md](../docs/getting-started-hospital.md). A sample report on
the practice data is [examples/hospital_b_report.html](examples/hospital_b_report.html).

## Install and test

```bash
cd slicepoint/core
uv venv && uv pip install -e ../schemas -e '.[test,notebook]'
.venv/bin/python -m pytest        # parity, CLI, report and notebook suites (need data/practice)
.venv/bin/mypy                    # --strict with the pydantic plugin, src + tests
```

Tested on Python 3.12 (pandas 3.1, numpy 2.5, scikit-learn 1.9, scipy 1.18) and on
Python 3.11 (pandas 2.3, numpy 2.4, scipy 1.17). On this Mac, the scipy wheel for
Python 3.10 fails to load (a dyld error in the wheel), so 3.10 is declared but not
exercised here.

## Usage

```python
from slicepoint_core import Assessment, ParquetAdapter, ReferenceProfile, to_slicepoint_v0
from slicepoint_schemas import HACKATHON_DEFAULT_PROFILE

profile = HACKATHON_DEFAULT_PROFILE

# Reference: built once from the validated population, then saved and reused.
ref_data = ParquetAdapter("hospital_a").load_tabular("data/practice/hospital_a")
reference = ReferenceProfile.build(ref_data, profile)
reference.save("refs/hospital_a")              # reference.json + reference_arrays.npz
reference = ReferenceProfile.load("refs/hospital_a")

# Candidate site: site_id is always explicit, never taken from a folder or display name.
site = ParquetAdapter("hospital_b").load_tabular("data/practice/hospital_b")
report = Assessment(site, reference, profile, site_name="Hospital B").run()   # site_name: display only

report.verdict.outcome                         # VerdictOutcome.NO_GO
report.checks["repeats"].status                # CheckStatus.PROBLEM
report.checks["repeats"].n_effective           # 32.0 (Kish, 80 scans of 40 people)
report.checks["repeats"].failing_sub_factors   # ('people', 'leakage')
report.performance.diameter.within_tolerance   # profile tolerances (2 mm BA, 3 mm size)
report.performance.aaa_missing_as_wrong.sens   # 0.857...
report.write_json("hospital_b.assessment.json")  # versioned AssessmentResult, provisional scores left out
report.to_json(show_provisional_scores=True)     # internal review only: keeps score / score_method
report.result.strata                           # by-group table (contract model), computed during run()
report.result.cases_to_review                  # flagged scans, most urgent first
report.result.thresholds                       # the resolved ThresholdProfile the run used

legacy = to_slicepoint_v0(report, hospital_name="Hospital B")     # POC viewer format

report.write_html("hospital_b_report.html")    # self-contained; provisional scores hidden
report.summary()                               # {verdict, checks: [{id, status, n, n_effective, ...}], ...}
```

## Command line

```bash
slicepoint reference build --data DIR --site-id ID --out PROFILE_DIR [--profile threshold_profile.json]
                           # --reference-site-id is accepted as an alias of --site-id here
slicepoint assess --data DIR --site-id ID [--site-name NAME]
                  (--reference-profile PROFILE_DIR | --reference-dir DIR --reference-site-id ID)
                  --out result.json [--html report.html] [--legacy-json poc.json] [--profile threshold_profile.json]
                  [--on-inconsistency raise|drop_and_note] [--show-provisional-scores] [--json] [--debug]
slicepoint validate FILE [--type MODEL]     # AssessmentResult, ThresholdProfile, reference.json or a legacy POC file
slicepoint schema [MODEL] [--list]          # JSON Schema (default AssessmentResult)
```

| Exit code | Meaning |
|---|---|
| 0 | ran, and the verdict is GO (other subcommands: success) |
| 3 | ran fine, and the verdict is BORDERLINE or NO-GO: needs human review |
| 1 | usage or input error (argparse errors included; it would otherwise use 2) |
| 2 | internal failure; `--debug` shows the traceback |

Errors are one line on stderr naming the file and column (`.../features.parquet: missing
required column 'age_band'`). With `--json`, stdout carries one JSON object: the
`report.summarize` payload plus `ok`, `exit_code` and `outputs`, or
`{"ok": false, "exit_code": 1, "error": "..."}`. `slicepoint --help` documents the data
layout, the JSON shape and the exit codes so that an AI assistant can drive it.

`--reference-site-id` is required with `--reference-dir` (missing: exit 1 with a one-line
message); the reference site id is never guessed. `result.json` leaves out the provisional
0-100 scores (`score`, `score_method` and the `score_basis` / `score_part.*` evidence)
unless `--show-provisional-scores` is given.

## HTML report

`report.render_html(result, *, show_provisional_scores=False, registry=None)` returns one
HTML document (also `AssessmentReport.to_html` / `write_html`, and `render_iframe` /
`to_notebook_html` for notebooks). It uses only the standard library, inline CSS and
inline SVG, and a Content-Security-Policy of `default-src 'none'`: no network request of
any kind. Sections: verdict and one-sentence rationale; one card per check (status as a
text label, n and effective n, failing sub-factors, findings, "What this means", "Show
the numbers"); performance two ways with Wilson intervals, diameter agreement against the
profile tolerances and Dice against the profile markers; results by group with "Too few"
suppression; cases to review; notes; methods and limits; provenance with every step's
state; the disclaimer. It honours `prefers-color-scheme` and prints the verdict and the
five cards on page one. The renderer computes no statistics: the by-group table
(`result.strata`), the case list (`result.cases_to_review`) and every threshold it prints
(`result.thresholds`, the resolved `ThresholdProfile`) come from the result, so a saved
`result.json` renders the same report. A result written before 0.2.0 lacks them and the
report says "not recorded" instead of assuming defaults. The title shows `site_name`
(`--site-name`) or, failing that, the site id made readable (`hospital_b` -> "Hospital B");
subgroup names in findings read "Contrast phase: arterial (16 cases)", not
`contrast_phase=arterial (n=16)`.

Provisional scores are hidden by default (ADR open question 2), in the HTML and in
`result.json` (`AssessmentReport.to_json` / `write_json`, `strip_provisional_scores`).
`show_provisional_scores=True` (CLI `--show-provisional-scores`) keeps them in the JSON
and shows them in the report with a "provisional, not validated" banner.

`ParquetAdapter(site_id).load(folder)` returns the contract `CuratedDataset`, as the
`IngestionAdapter` protocol requires. `Assessment` accepts either view.

## Static viewer

`slicepoint/viewer` (milestone 3) builds `slicepoint-viewer.html`: one offline HTML file
that opens any `result.json` this package writes and renders it interactively. You can
drill into a check's evidence and sort and filter the cases to review. It validates the
file against `AssessmentResult.schema.json` and refuses other `schema_version`s. It
computes no statistics and makes no network requests. See
[../viewer/README.md](../viewer/README.md).

## Layout

| Module | What it holds |
|---|---|
| `ingestion` | `ParquetAdapter` (the one real adapter; `on_inconsistency="raise"` by default, or `"drop_and_note"` to reproduce the notebook's join and record a "Files" note) and `TabularDataset` (a DataFrame plus a float32 embedding ndarray). Rows are validated through the schemas row models; embeddings are validated at the array level (see the module docstring for why and the measured cost). The DICOM, NIfTI and report-text adapters remain stubs in `slicepoint_schemas.ingestion`. |
| `stats` | Pure functions: `wilson_interval`, `binary_metrics` (missing counted as wrong, or dropped), `diameter_agreement` (bias, LoA with population SD, MAE, within-tolerance), `category_mix` / `tvd`, `wasserstein_shift`, `permutation_test`, `fisher_exact_p`, `domain_auc`, `fit_reference` / `KnnCoverage`, `group_people` (near-duplicate and person grouping), `cutoff_range`, `kish_effective_n`, `embedding_probe`, `leakage_test` |
| `reference` | `ReferenceProfile` and its pydantic `ReferenceSummary`: category mixes, deduplicated numeric distributions, label facts, reference performance, kNN coverage state, provenance (dataset fingerprint, builder, profile parameters). It is tied to one `EmbeddingSpace`; `require_space` raises `IncomparableEmbeddingSpacesError` on a mismatch. |
| `checks` | `CheckRegistry`, `CheckSpec` (descriptor + function + requirements + factor-to-sub-factor map), `CheckContext` (shared lazy analyses), and the five checks in `checks/builtin.py` |
| `params` | Typed access to a `ThresholdProfile`. Checks read every threshold through it; a missing key raises `MissingThresholdError`. |
| `assessment` | `Assessment(...).run()`: the sequential local runner. Each step records ok, skipped or failed. Returns an `AssessmentReport` wrapping `slicepoint_schemas.AssessmentResult` (`to_json` / `write_json`, provisional scores stripped by default; `to_html` / `write_html`, `summary`). Also `strip_provisional_scores`. |
| `strata` | `stratified_table` and `cases_to_review`: build the contract `Strata` and `CasesToReview` models from the per-scan table during `run()` |
| `ports` | `ServicePort` protocol and service names (segmentation, OpenCPU, FORGE PGM, embedding). Declared only; an absent service makes its step skipped. |
| `legacy` | `to_slicepoint_v0`: export to the POC `<hospital>_slicepoint.json` (`SlicePointFileV0`) |
| `report` | `render_html`, `write_html`, `render_iframe`, `summarize`, display helpers (`display_site_name`, `format_n_effective`, `humanize_column`). Display only; no statistics. |
| `cli` | The `slicepoint` console script (argparse). No analysis logic. |
| `errors` | `InputError` (a `ValueError` that names the bad file and column) |

## How a check works

A check is a `CheckDescriptor` (data, from the schemas registry) plus one function
`(CheckContext) -> CheckOutput`. The function returns findings: a factor id, a
severity (red, yellow, ok or info), the text and the numbers behind it. The registry
turns these into a `CheckResult`:

- **status** is the worst severity (`ok` if nothing was raised). Info items become notes.
- **failing_sub_factors** are the registry sub-factors mapped from the non-ok factors.
  Following reviewer decision 1, the default registry has sub-factors for leakage, domain
  AUC, coverage, the HU and kVp shifts, no-answers, specificity and subgroups. Milestone 2
  added the last four (`labelled_diameter_shift` and `predicted_diameter_shift` under
  patients; `impossible_values` and `embedding_shortcuts` under scanning), so every
  notebook rule now names a sub-factor. A non-ok factor with no sub-factor would still be
  listed in the evidence as `failing_factor_without_sub_factor`; none remains. One visible
  effect: hospital_e's patients card was "watch" with nothing named and now names both
  diameter shifts.
- **evidence** has one entry per finding plus its numbers. Optional parts that could not
  run are listed as `not_evaluated` (for example scan content when there are no
  embeddings).
- **n** is the cases used, **subjects** the distinct real people among them, and
  **n_effective** is Kish's design-effect sample size over people
  (`kish_design_effect_per_person`, ICC from `parameters.repeat_scan_icc`, default 1.0).
  Both n and n_effective are reported. The "too few to judge" rules (for example
  n_aaa >= 3 for sensitivity, n >= 15 for subgroups) still use raw counts, as in the
  notebook. Moving them to n_effective waits for the reviewer's score/ESS decision.
- **score** uses the ADR "provisional-v0" formulas, with `score_method="provisional-v0"`.
  These formulas are not validated and must not be shown to a hospital.

A check whose required inputs are missing (`Requirement.LABELS`, `EMBEDDINGS`, and so
on) is recorded as **skipped** with a reason. It never reports ok, and it appears in
`verdict.not_evaluated`. A check that raises is recorded as **failed**, and the other
checks still run. `tests/test_checks.py::test_a_sixth_check_is_one_function_plus_data`
shows a new check added with one function and one descriptor.

| Check | Required | Notebook areas (cells) | Provisional score |
|---|---|---|---|
| repeats | embeddings | Repeat patients (11), Leakage (13) | 100 × people ÷ scans |
| scanning | none | Impossible values (15); scanner, contrast and slice TVD and HU, kVp and slice-mm shifts (19); Scan content (20); Embeddings (26) | 100 × (1 − worst TVD of scanner, contrast, slice class) |
| patients | none | sex and age TVD, labelled and predicted diameter shifts, prevalence (19); AAA size-class TVD (new, reviewer decision 4) | 100 × (1 − worst TVD of sex, age band, AAA size class) |
| labels | labels | Labelling (15), Labelling vs model (24) | 100 × (1 − rule-conflict share) |
| accuracy | labels, predictions | Silent failures and outliers (17), AAA model (22), Subgroups (23), Segmentation shape / Dice (29) | lowest of Dice mean × 100, % within size tolerance, sensitivity × 100 |

Every threshold is read from the `ThresholdProfile`. The notebook-only rules were added to
`HACKATHON_DEFAULT_PROFILE` as snake_case triggers (`repeats_near_duplicate_share`,
`scanning_domain_auc`, ...) and `parameters` (`near_duplicate_similarity`,
`permutation_count`, ...), each with a cited source.

## Determinism

Every random procedure is seeded from `parameters.random_seed` (0, the notebook's seed):
the KFold and StratifiedGroupKFold shuffles, PCA, the MLP and the permutation RNG. Each
uses the same seed and call order as the notebook. The run is deterministic on one
machine. The MLP leakage test is the only step sensitive to the BLAS build. It is
**ported**, not deferred: core reproduces the notebook MAEs to full precision in this
environment, and the POC's own output for hospital_c differed in the second decimal
(see PARITY.md).

## Known gaps

- **Reference data is a sibling site.** The reference is hospital_a, not the model's
  training distribution (ADR open question 4). `ReferenceProfile` is the container, not
  the answer.
- **Score formulas are provisional** (ADR open question 2). Status is primary.
- **monitor.py triggers are deferred to the AI-Watch milestone** (reviewer decision 6).
  Examples are "change in share called AAA" and "rise in missing details". The POC
  counted them only in the notebook's own verdict text, never in `slicepoint.json`, so
  they do not affect the five checks.
- **"Too few to judge" uses raw n.** n_effective is reported but does not yet drive any
  suppression rule. This is pending the reviewer's score/ESS decision.
- **Not ported:** the shape analysis (pykarambola; off by default in the notebook), the
  notebook's third leakage split ("by listed patient_id", which no rule uses), the
  continuous R² probes (cell 26, never used in a rule), figures, and the notebook's own HTML report (replaced by
  `slicepoint_core.report`, milestone 2).
- **Coverage is magnitude-blind.** The notebook's coverage uses cosine kNN in PCA space,
  so scans displaced radially from the reference still count as covered
  (`test_coverage_is_blind_to_magnitude`). It stays as is for parity (reviewer decision
  2). A magnitude or reconstruction-error test is planned with the embedding-service work
  (a VAE-style data-space marker, ADR section 3).
- **Ingestion is strict by default.** A case missing from one table, or a duplicate case
  id, raises. `on_inconsistency="drop_and_note"` reproduces the notebook instead:
  duplicates keep their first row; cases missing from features, labels or embeddings are
  dropped; cases missing only from predictions are kept as "no answer"; and a "Files"
  note goes into the result notes. A dataset loaded that way with a missing prediction
  row has no `CuratedDataset` view.
- **Performance blocks.** The diameter block in `AssessmentResult` is the
  profile-driven `DiameterAgreement`. The binary-call and Dice blocks still use the POC
  shapes. `to_slicepoint_v0` refuses profiles whose tolerances are not 2 mm and 3 mm,
  rather than mislabel them.
- **Ports are declarations.** Segmentation, OpenCPU, FORGE PGM and the embedding encoder
  have no client yet; their steps report skipped.
- No API, persistence or static viewer yet. The CLI, HTML report and notebook are tier 0.
- **Strata and cases are report-side.** The stratified table and the cases-to-review list
  are computed when rendering, from `result.scans`; they are not fields of
  `AssessmentResult`, so the future static viewer would have to recompute them.
- **Ingestion errors name the file and column.** `ParquetAdapter` checks the column set
  before validating rows and raises `InputError` (a `ValueError`).
- **A failing check logs one warning line**; the traceback is logged at DEBUG (the CLI's
  `--debug`) instead of being printed.
