# slicepoint-core

The importable analysis library for the SlicePoint rebuild (ADR 0001, section 9). It
covers ingestion, the statistics, reference profiles, the check registry and a local
assessment runner. It produces the contract types from `slicepoint-schemas` and never
depends on FastAPI, a database, a GPU or torch (enforced by `tests/test_package.py`).

Milestone 1 ports `test_your_hospital.ipynb` (with `monitor.py`) and reproduces its
results on the practice data. See [PARITY.md](PARITY.md).

## Install and test

```bash
cd slicepoint/core
uv venv && uv pip install -e ../schemas -e '.[test]'
.venv/bin/python -m pytest        # includes the parity suite (needs data/practice)
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
report = Assessment(site, reference, profile).run()

report.verdict.outcome                         # VerdictOutcome.NO_GO
report.checks["repeats"].status                # CheckStatus.PROBLEM
report.checks["repeats"].n_effective           # 32.0 (Kish, 80 scans of 40 people)
report.checks["repeats"].failing_sub_factors   # ('people', 'leakage')
report.performance.diameter.within_tolerance   # profile tolerances (2 mm BA, 3 mm size)
report.performance.aaa_missing_as_wrong.sens   # 0.857...
open("hospital_b.assessment.json", "w").write(report.to_json())   # versioned AssessmentResult

legacy = to_slicepoint_v0(report, hospital_name="Hospital B")     # POC viewer format
```

`ParquetAdapter(site_id).load(folder)` returns the contract `CuratedDataset`, as the
`IngestionAdapter` protocol requires. `Assessment` accepts either view.

## Layout

| Module | What it holds |
|---|---|
| `ingestion` | `ParquetAdapter` (the one real adapter; `on_inconsistency="raise"` by default, or `"drop_and_note"` to reproduce the notebook's join and record a "Files" note) and `TabularDataset` (a DataFrame plus a float32 embedding ndarray). Rows are validated through the schemas row models; embeddings are validated at the array level (see the module docstring for why and the measured cost). The DICOM, NIfTI and report-text adapters remain stubs in `slicepoint_schemas.ingestion`. |
| `stats` | Pure functions: `wilson_interval`, `binary_metrics` (missing counted as wrong, or dropped), `diameter_agreement` (bias, LoA with population SD, MAE, within-tolerance), `category_mix` / `tvd`, `wasserstein_shift`, `permutation_test`, `fisher_exact_p`, `domain_auc`, `fit_reference` / `KnnCoverage`, `group_people` (near-duplicate and person grouping), `cutoff_range`, `kish_effective_n`, `embedding_probe`, `leakage_test` |
| `reference` | `ReferenceProfile` and its pydantic `ReferenceSummary`: category mixes, deduplicated numeric distributions, label facts, reference performance, kNN coverage state, provenance (dataset fingerprint, builder, profile parameters). It is tied to one `EmbeddingSpace`; `require_space` raises `IncomparableEmbeddingSpacesError` on a mismatch. |
| `checks` | `CheckRegistry`, `CheckSpec` (descriptor + function + requirements + factor-to-sub-factor map), `CheckContext` (shared lazy analyses), and the five checks in `checks/builtin.py` |
| `params` | Typed access to a `ThresholdProfile`. Checks read every threshold through it; a missing key raises `MissingThresholdError`. |
| `assessment` | `Assessment(...).run()`: the sequential local runner. Each step records ok, skipped or failed. Returns an `AssessmentReport` wrapping `slicepoint_schemas.AssessmentResult`. |
| `ports` | `ServicePort` protocol and service names (segmentation, OpenCPU, FORGE PGM, embedding). Declared only; an absent service makes its step skipped. |
| `legacy` | `to_slicepoint_v0`: export to the POC `<hospital>_slicepoint.json` (`SlicePointFileV0`) |

## How a check works

A check is a `CheckDescriptor` (data, from the schemas registry) plus one function
`(CheckContext) -> CheckOutput`. The function returns findings: a factor id, a
severity (red, yellow, ok or info), the text and the numbers behind it. The registry
turns these into a `CheckResult`:

- **status** is the worst severity (`ok` if nothing was raised). Info items become notes.
- **failing_sub_factors** are the registry sub-factors mapped from the non-ok factors.
  Following reviewer decision 1, the default registry has sub-factors for leakage, domain
  AUC, coverage, the HU and kVp shifts, no-answers, specificity and subgroups. A non-ok
  factor with no sub-factor is listed in the evidence as
  `failing_factor_without_sub_factor`. Today those are the labelled and predicted
  diameter distribution shifts, impossible values and embedding shortcuts.
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
  continuous R² probes (cell 26, never used in a rule), figures, and the HTML report.
- **Coverage is magnitude-blind.** The notebook's coverage uses cosine kNN in PCA space,
  so scans displaced radially from the reference still count as covered
  (`test_coverage_is_blind_to_magnitude`). It stays as is for parity (reviewer decision
  2). A magnitude or reconstruction-error test is planned with the embedding-service work
  (a VAE-style data-space marker, ADR section 3).
- **A few factors have no sub-factor:** the labelled and predicted diameter distribution
  shifts (patients), impossible values and embedding shortcuts (scanning). They appear
  only in the evidence.
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
- No CLI, API, persistence or HTML report in this milestone.
