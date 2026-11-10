# Parity with the hackathon notebook

The target is `slicepoint/python_notebooks/hospital_test_output/hospital_{b..e}_slicepoint.json`,
produced by `test_your_hospital.ipynb` with reference `hospital_a`. hospital_f and g have
no data in `data/practice`, so they are not tested. Suite: `tests/test_parity.py`
(`pytest -m parity`).

Core runs with `HACKATHON_DEFAULT_PROFILE` unchanged. No threshold was tuned to make a
result match.

## Results

| Criterion | b | c | d | e |
|---|---|---|---|---|
| (a) performance: BinMetrics (both modes), diameter, Dice, within 1e-9 | pass | pass | pass | pass |
| (b) every legacy finding's check status equals core's | pass | pass | pass | pass |
| (b') sentence identical (apart from the documented exceptions below) | pass | pass | pass | pass |
| (c) scans: all fields equal; `personGroup` partitions equal up to relabelling | pass | pass | pass | pass |
| notes: same set as legacy | pass | pass | pass | pass |

Statuses, shown as legacy / core:

| check | b | c | d | e |
|---|---|---|---|---|
| repeats | Problem / problem | OK / ok | OK / ok | OK / ok |
| scanning | Watch / watch | Problem / problem | Problem / problem | Watch / watch |
| patients | (absent) / ok | (absent) / ok | Problem / problem | Watch / watch |
| labels | OK / ok | Watch / watch | OK / ok | Problem / problem |
| accuracy | Problem / problem | Watch / watch | Watch / watch | Problem / problem |

"(absent)": the POC dropped a check that nothing mapped to. Here the patients check ran
with all its inputs and nothing reached yellow, so core reports `ok`. In the POC this
was indistinguishable from "not evaluated".

The verdict is `no_go` for all four sites (`derive_verdict`; every site has at least one
problem).

### How this was established

1. The extracted notebook code was executed unchanged, with plots stubbed, in this
   environment. Its `slicepoint.json` output was byte-identical to the committed legacy
   file for b, d and e. For c, one sentence differed (see D1). So the legacy files are
   reproducible, and the notebook is a valid oracle.
2. Core's full finding list (area, severity and exact text, including the `ok` and
   `info` findings that the POC export drops) was compared with the oracle's
   `<site>_test_results.json`. All findings match except D2's threshold text.
3. The statistics are tested one by one against the notebook's own functions,
   copied into `tests/notebook_reference.py`, and against `monitor.py` imported as is
   (`tests/test_stats.py`).

## Divergences and their causes

| # | Where | What differs | Cause | Effect on status |
|---|---|---|---|---|
| D1 | c / repeats sentence | Leakage "6.8 vs **6.0** mm" here, "6.8 vs **5.9** mm" in the POC file | The MLP (`MLPRegressor`, seeded) gives by-person MAE 5.95096 mm here; on the POC machine it rounded to 5.9. That is a floating-point difference between BLAS builds, not a seeding difference: core and the notebook agree to all digits when run on the same machine. | none (gap ratio far from 0.15) |
| D2 | c, d / accuracy sentences | Outlier threshold printed as **4.2** mm instead of **4.3** mm | Core uses the population SD of the reference error (4.2454 mm × 3), as the ADR and spec require. The notebook used pandas' sample SD (4.2668). The outlier counts are identical on b–e (4, 2, 6, 1): no error falls between the two thresholds. | none |
| D3 | d / kVp shift routing | Core files "tube voltage (kVp) is somewhat different" (yellow) under **scanning**; the notebook filed it under **patients** | The notebook routed "Patients & scanners" findings by substring. "volt**age**" contains "age". Core routes by variable. | none on d (both checks are already problem). Elsewhere, a kVp-only shift would raise scanning rather than patients. |
| D5 | d / patients | New yellow finding: "The AAA size-class mix differs from the reference (distance 0.16)" | **Intentional, new vs the POC** (reviewer decision 4): TVD alert on `aaa_size_class` with the other mixes' lines (yellow 0.15 / red 0.30), trigger `AAA size class mix` in the profile. TVDs: b 0.02, c 0.0075, d 0.16, e 0.02. | none: d patients is already problem, and its sentence (the first two red texts) is unchanged. No expected value in the parity test had to change. |
| D6 | b, e / scanning scan-content sentence (not in the export) | "cannot be told apart ... no better than chance (AUC 0.50; cross-validated 0.45, at or below chance)" instead of "hard to tell apart (AUC 0.45)" | **Intentional, new vs the POC** (owner decision 2026-11-10): the scanning check classifies and reports `max(AUC, 0.5)`; a cross-validated AUC below 0.5 is noise around chance. `stats.domain_auc` still returns the raw value (tested against the notebook to 1e-12) and the finding keeps it as evidence `scan_content_auc.auc_raw`. Raw AUCs vs hospital_a: b 0.447, c 0.847, d 0.631, e 0.457. | none: b and e scanning are watch, so the ok sentence is not their summary, and 0.5 is below the yellow line (0.65). |
| D4 | notes order | Same notes, in a different order | Core collects notes check by check; the notebook collected them in cell order. | none |

## Performance block shape

Following reviewer decision 5, `AssessmentResult.performance.diameter` is the
profile-driven `DiameterAgreement` (population SD, `within_tolerance` entries carrying
their `tolerance_mm`). Criterion (a) compares the POC-shaped export of it
(`to_slicepoint_v0`, `DiameterMetricsV0`) with the legacy file, and also checks the new
fields directly. The V0 models are now used only for legacy files and parity.

## SD convention

Following the ADR and the POC spec, SlicePoint uses the **population** SD (`ddof=0`)
everywhere: Bland-Altman limits of agreement, the Wasserstein shift in SD units, and the
measurement-outlier threshold. The notebook mixed the two (numpy `e.std()` is population;
pandas `.std()` is sample). The only place this changes anything printed is D2, and no
outcome changes on the practice data. This is also recorded in
`HACKATHON_DEFAULT_PROFILE.provenance.notes`.

## Seeding and non-determinism

| Step | Randomness | Handling |
|---|---|---|
| Wasserstein permutation test | `default_rng(seed).shuffle`, 1,000 permutations | Same seed and in-place shuffle order as `w_test`, so p-values are identical. |
| Domain AUC | PCA, `StratifiedGroupKFold(shuffle)` | `random_state=seed`. Identical to the notebook (tested to 1e-12). |
| Embedding probe | PCA, `StratifiedGroupKFold(shuffle)` | `random_state=seed`. |
| Leakage (MLP) | `KFold(shuffle)`, PCA, `MLPRegressor` | `random_state=seed`. Ported; identical to the notebook on the same machine; BLAS-sensitive across machines (D1). |
| kNN coverage | PCA | `random_state=seed`. Distances agree with `monitor.fit_reference` to 1e-5 (float32 embeddings) and the outside share is identical. |

`seed` is `parameters.random_seed` (0) in the threshold profile.

## Not ported (no effect on `slicepoint.json`)

- `monitor.evaluate` triggers as a separate list. The notebook counted them toward its
  own verdict text, but the export never used them.
- The shape analysis (off by default), the third leakage split, the continuous R² probes,
  figures and the HTML report.
