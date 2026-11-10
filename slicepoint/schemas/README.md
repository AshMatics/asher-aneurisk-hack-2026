# slicepoint-schemas

The contract layer for the SlicePoint rebuild: Pydantic v2 models only, with no IO and no numpy, pandas or torch. SlicePoint answers one question for a hospital: *is this imaging AI a fit for our patients and scanners before we turn it on?* It answers with a GO / NO-GO / BORDERLINE verdict backed by five data-health checks.

Sources of truth: `slicepoint/docs/adr/0001-slicepoint-rebuild-architecture.md` and `slicepoint/docs/data-contract-inventory.md`.

## Layers

```text
ingestion surface  ──►  analysis core  ──►  API (FastAPI /v1)  ──►  UI (React)
 CuratedDataset         checks, stats,       CheckResult, Verdict,
 EmbeddingSet           embeddings           ThresholdProfile, ...
```

| Module | What it holds |
|---|---|
| `common` | `ContractModel` (frozen, `extra=forbid`, no NaN/inf), `VersionedModel` (`schema_version`), `SiteId`, opaque `CaseId` / `PatientId`, legacy `ShortCaseId`, `AgeBand`, closed enums for legacy and open `OpenSex` / `OpenScannerVendor` for new data |
| `ingestion` | Row models that mirror the practice parquet exactly, `DatasetManifest`, `CuratedDataset` (join integrity), the `IngestionAdapter` protocol and declared stub adapters |
| `embedding` | `EmbeddingSpace`, `EmbeddingSet`, `CaseEmbedding`. Dimension is checked. Comparing across spaces is rejected (`assert_comparable`, `EmbeddingComparisonRequest`). `HACKATHON_MERLIN_CT_SPACE` |
| `thresholds` | `TriggerThreshold` (ordering checked against `worse`), `ThresholdProfile` with per-value provenance, and `HACKATHON_DEFAULT_PROFILE` |
| `checks` | `CheckStatus`, `CheckDescriptor`, `CheckRegistry` (the 5 POC checks), and `CheckResult` (status first; `score` needs a `score_method`; per-check `n` is required; optional `n_effective` needs an `n_effective_method`; optional `subjects`) |
| `verdict` | `Verdict` (consistency validated on the derived outcome), `VerdictOverride` (attributed, justified human decision) with `final_outcome`, and `derive_verdict(results, profile)` |
| `legacy` | `SlicePointFileV0`, `MonthlySummaryV0`, `DiceSummaryV0`, `CompareResponseV1`, plus converters to the new models |
| `export` | JSON Schema for every top-level model, written to `jsonschema/` |

## Decisions worth knowing

- **New data is open; legacy is strict.** In ingestion and the new contract:
  - `case_id` and `patient_id` are opaque: non-empty, at most 128 characters, no surrounding whitespace.
  - `sex` and `scanner_vendor` accept unknown strings. Known values are normalised (`m` becomes `M`, `Canon` becomes `canon`).

  The legacy V0 models keep the closed POC enums and the hex id patterns. The practice data still uses 16-hex ids, but new sources are not held to that.
- **A check missing from a legacy file is "not evaluated", not "ok".** The POC dropped a check when nothing mapped to it, and silence is not evidence. Such a verdict cannot be `go` without an override.
- **Overrides are explicit.** `Verdict.outcome` is always the *derived* outcome and stays consistent with the results. A human decision goes in `override`:
  - It records `outcome`, `by`, `at` (timezone-aware) and a required `note` of at least 20 characters after trimming.
  - Its outcome must differ from the derived one.
  - `final_outcome` is the outcome to act on.
  - Overriding to `go` past a `problem` or an unevaluated check is allowed, but only through this record.
- **Sample size is per check.** `n` is the number of cases the check actually used. The legacy converter's `n` (the file's scan count) is a legacy-only stand-in.
- **Effective sample size.** `n_effective` (with `n_effective_method`, `0 < n_effective <= n`) and `subjects` (`<= n`) are optional. Repeat scans of one person and clustering within a site carry less information than `n` independent cases, and that matters for Wilson intervals and the "too few to judge" suppression.

To add a check, add a `CheckDescriptor` to a `CheckRegistry` and pass that registry in the validation context (`context={"check_registry": registry}`). Only data changes.

## Fact vs INFERRED

**Facts** (verified against the repo data):

- parquet columns, types and nullability
- the `slicepoint.json` shape, including the exact scan key order. All 6 samples validate and round-trip byte-for-byte after JSON parsing.
- BinMetrics count arithmetic, the Wilson bound ordering and the rate definitions
- the null-iff rule for `pred_aaa` / `pred_max_diameter_mm`
- the monitor trigger thresholds
- the `/v1/compare` status rules
- the monthly-summary verdict text rule

**INFERRED** (in docstrings, and not hardened into validators beyond what is stated):

- the GO rule in `derive_verdict`. It is status-based: problem → `no_go`; watch → `borderline`; an expected check that did not run → `borderline`; otherwise `go`.
- the whole `DiceSummaryV0` contract (no writer exists)
- the `labels` sub-factor ids
- the `Audience` values
- the UI constants in `HACKATHON_DEFAULT_PROFILE` that come only from the POC spec PDF: Dice markers 0.81/0.90, nearby window 5 mm, size tolerance 3 mm, BA tolerance 2 mm, and the check targets.

Each value's source is in `HACKATHON_DEFAULT_PROFILE.value_sources`, and the known conflicts are in `provenance.notes`. Min group size is 15 (notebook) rather than 12–14 (spec).

Deliberately **not** enforced at ingestion, because detecting these is what the checks are for:

- impossible values
- the 30 mm label rule (hospital e breaks it)
- size class vs diameter
- thickness class vs mm
- kVp null iff vendor null

## Running

```bash
cd slicepoint/schemas
uv venv && uv pip install -e '.[test]'
.venv/bin/python -m pytest          # parquet test skips if pyarrow or data/practice is missing
.venv/bin/mypy                      # --strict with the pydantic.mypy plugin, src + tests
.venv/bin/slicepoint-schemas-export # regenerate jsonschema/  (--check to verify only)
```

`jsonschema/GENERATED_WITH_PYDANTIC` records the pydantic version that produced the committed schemas. Pydantic's JSON Schema output changes between releases, so the "committed == regenerated" test skips under a different pydantic version. The package itself is tested on Python 3.10 with pydantic 2.7.4, and on Python 3.12 with pydantic 2.14.

## Known gaps

- **No score formulas.** The 0–100 check scores have no formula anywhere in the repo. `score` stays optional and must name its `score_method`; the legacy converters leave it `None`.
- **No `<hospital>_dice.json` writer.** `DiceSummaryV0` is inferred from the POC spec.
- **Ingestion adapters are TBD.** Every input today is hand-curated hackathon parquet. `ParquetAdapter` belongs in the analysis core; the oxidicom DICOM, NIfTI and report-text adapters are declarations that raise `NotImplementedError`.
- **Persistence and audit are not modeled yet.** That covers the assessment record (who, model version, dataset hash, space id, profile, verdict) and the orchestrator step/job models (ADR section 5).
- `<hospital>_test_results.json` (the notebook's richer output) and `history.csv` are not modeled. No sample of either exists.
- The legacy closed enums (`ScannerVendor`, `Sex`) hold only the observed POC values by design. New data uses the open types.
- No formula yet produces `n_effective`. The field and its method name are the contract; the computation belongs in the analysis core.
- `final_outcome` is a Python property, not a serialized field. API clients compute it as `override?.outcome ?? outcome`.
