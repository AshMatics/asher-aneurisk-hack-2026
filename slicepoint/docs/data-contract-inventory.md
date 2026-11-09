# SlicePoint data-contract inventory

Extracted 2026-11-09 from the hackathon practice data, notebooks and segmentation service; facts unless marked INFERRED.
This document is the source of truth for slicepoint-schemas v0.

Notebook references use `ipynb:LINE`, which is the raw line number inside the .ipynb JSON. "Cell N" is the cell's index in `nb["cells"]`.

---

## 1. Ingestion surface: data/practice/hospital_{a..e}/*.parquet

**Rows per hospital:** a=100; b, c, d, e=80 each. Total 420. Every hospital has the same column set in all four files. `manifest.json` has `schema_version "0.1.0"`, `release_set "dev"`, and per-file `{path, rows, bytes, sha256}` plus per-hospital row counts.

**Join key:** `case_id`. It is unique within each file, unique across all 420 rows, and is a 16-character lowercase hex string. In every hospital the case_id set is identical across all 4 files, and the row order is identical too. No parquet file has an index (RangeIndex).

**Physical types (pyarrow):** strings are `string`, floats are `double`, `aaa`/`pred_aaa` are `bool`, embeddings are `float` (float32).

### features.parquet (17 cols)

| col | arrow type | nulls (a/b/c/d/e) | observed values / range |
|---|---|---|---|
| case_id | string | 0 | 16-hex |
| patient_id | string | 0 | 16-hex. Unique per row in a, c, d, e. **In b: 80 rows, 60 IDs** (10 IDs ×2 rows, 5 IDs ×3 rows). No patient_id appears in more than one hospital. |
| age_band | string | 0 | `20-29, 30-39, 40-49, 50-59, 60-69, 70-79, 80-89, 90-99`. **Note:** `10-19` appears in the hospital_g sample JSON, so treat this as an open `^\d0-\d9$` pattern, not a closed enum. |
| sex | string | 0 | `M` (252), `F` (168) |
| scanner_vendor | string, nullable | 3/3/0/2/1 (9 total) | `siemens` (355), `philips` (40), `ge` (16) |
| contrast_phase | string | 0 | `venous`, `arterial`, `non-contrast` |
| slice_thickness_mm | double | 0 | {0.6, 0.625, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 3.75, 5.0} |
| slice_thickness_class | string | 0 | `thin` (<2 mm, observed 0.6–1.5), `standard` (2.0–3.75), `thick` (5.0). The mapping is exact in the data. |
| kvp | double, nullable | same rows as vendor nulls (verified) | {80, 90, 100, 110, 120, 130, 140, 150} |
| study_description | string | 0 | 24 distinct free-text values (e.g. "CTA Abdomen/Pelvis") |
| protocol_name | string | 0 | 42 distinct free-text values |
| aorta_hu_mean | double | 0 | 25.4 – 653.8 |
| aorta_hu_sd | double | 0 | 17.0 – 370.2 |
| organ_volumes_liver | double | 0 | 0.0 – 4187.1 mL (4 zeros) |
| organ_volumes_spleen | double | 0 | 0.0 – 2568.7 (21 zeros) |
| organ_volumes_kidney_left | double | 0 | 0.0 – 437.8 (6 zeros) |
| organ_volumes_kidney_right | double | 0 | 0.0 – 288.0 (2 zeros) |

Per-hospital distributions that stand out:
- **c:** 100% venous and 100% thick, with no vendor nulls.
- **d:** 70% arterial and 75% M.

### labels.parquet (4 cols, no nulls)
- `case_id`
- `max_aortic_diameter_mm` (double): 13.46 – 91.17
- `aaa` (bool): 50 True / 370 False
- `aaa_size_class` (string): `none` (370), `30-54mm` (38), `>=55mm` (12)

**30 mm rule in the data:** across a, b, c, d, every row satisfies `aaa == (diam >= 30)`. **Hospital e has 5 rows with aaa=True and diam < 30.** The 30-54mm class has a minimum diameter of 25.74 mm, so `aaa_size_class` follows the hospital's convention, not the diameter.

### predictions.parquet (4 cols)
- `pred_aorta_dice` (double): 0.796 – 0.995, no nulls.
- `pred_max_diameter_mm` (double, nullable): 6 nulls (b=4, c=1, e=1). Range 13.34 – 91.11.
- `pred_aaa` (arrow bool, nullable): same 6 rows null. Pandas reads it as `object` when nulls are present. True=39, False=375.
- `pred_aaa == (pred_max_diameter_mm >= 30)` holds exactly on all non-null rows.

### embeddings.parquet
- Columns: `case_id` + `emb_0` … `emb_2047`, i.e. 2048 float32 values.
- No nulls. Value range is −0.038 to 2.88.

### hospital_c extras
- `images/` and `masks/` directories exist but are **empty**.
- The data card documents the expected names: `images/<case_id>.nii.gz` (HU) and `masks/<case_id>_aorta.nii.gz` (same grid).

### tutorial_keys/hospital_{a,c}.json
- Shape: `{hospital, findings:[{kind, severity, description, evidence_expected}]}`.
- Observed values: kind `none`/`acquisition`; severity `none`/`strong`.

### Documented semantics (docs/data-card.md)
- L36: case_id is "Hashed, unique within the release. Joins all tables."
- L37: patient_id: "Scans of the same patient share it, when the hospital records it reliably."
- L40: scanner_vendor "str or null … Missing for a few cases"
- L43: slice_thickness_class "`thin` (under 2 mm), `standard`, `thick` (5 mm and over)"
- L44: kvp "Tube voltage. Missing where the scanner vendor is missing."
- L47: aorta_hu_* "Within the segmented aorta"
- L48: organ volumes are in **mL**
- L55: max_aortic_diameter_mm is the "Primary label (continuous)"
- L56: aaa is "derived from the diameter under this hospital's convention"
- L64: pred_aorta_dice is the "Overlap of the baseline segmentation model's aorta with the reference mask (0 to 1)"
- L73: embeddings are a "Merlin CT encoder, one 2,048-number vector per case"
- L77: subgroup columns are sex, age_band, aaa_size_class, scanner_vendor, contrast_phase, slice_thickness_class
- L81: 80–100 cases per hospital

The data card says pred_max_diameter_mm and pred_aaa are float/bool but does not mention that they can be null; the data has 6 nulls.

docs/technical-reference.md has no column, unit, or 30 mm definitions; it is methodology only. The 30 mm rule is defined in code:
- `AAA_CUTOFF_MM = 30` (test_your_hospital.ipynb:80)
- monitor.py:147-148: `(max_aortic_diameter_mm >= 30) != aaa`
- size-class expectation (ipynb cell 15): `<30 → none`, `<55 → 30-54mm`, else `>=55mm`

---

## 2. Analysis output payloads

### 2a. `<hospital>_slicepoint.json`
Written by test_your_hospital.ipynb cell 34 (`sp = {` at ipynb:1572), using `json.dumps(sp, allow_nan=False)` after `clean()`, which turns NaN/inf into null and numpy types into Python types (cell 5). All 6 samples (hospital_b–g) have the identical key set.

```
fileType: "hospital_data"                       (literal; validated)
hospitalName: str      = HOSPITAL_NAME.replace("_"," ").title()  e.g. "Hospital B"
scans: list[Scan]      (len == n merged rows; 80 in every sample)
  Scan (keys in this exact order; the validator checks list(s)==SCAN_KEYS, ipynb:1594):
    id: str                      first 8 chars of case_id (uniqueness checked, not enforced)
    personGroup: str             "p{int}" = connected-component label from patient_id OR embedding cosine>0.95
    sex: str|null                observed M/F
    age_band: str|null           observed 10-19 … 90-99
    scanner_vendor: str|null     siemens/philips/ge/null (nulls observed)
    contrast_phase: str|null     arterial/venous/non-contrast
    slice_thickness_class: str|null  thin/standard/thick
    aaa_size_class: str|null     none/30-54mm/>=55mm
    aaa: bool|null               (never null in samples)
    referenceDiameterMm: float|null  rounded 2dp (never null in samples)
    aiDiameterMm: float|null     rounded 2dp; null observed
    aiAaa: bool|null             null = "AI gave no answer" (observed)
findings: list[{check, status, sentence}]   0..5 items, one per check present
  check: "repeats"|"scanning"|"labels"|"accuracy"|"patients"
  status: "Problem"|"Watch"|"OK"
  sentence: str  (up to 2 texts at the worst status, joined with a space)
notes: list[str]   texts from area "Files", severity "info", or unmapped areas
performance:
  aaa_missing_as_wrong: BinMetrics
  aaa_when_answered:    BinMetrics
  diameter: {n:int, mae, rmse, bias, loa_low, loa_high, within_2mm, within_3mm, spearman: float|null}
  dice: {median, mean, "share_below_0.90", "share_below_0.85": float}  OR {} if no pred_aorta_dice
dice (OPTIONAL; present in all 6 samples): {average: float (3dp), note: "Baseline model Dice."|"Our team's segmentation."}
```

`BinMetrics` (ipynb:835) has these fields:
- int: `n, n_aaa, n_not_aaa, tp, fn, tn, fp, n_no_answer`
- float|null: `sens, sens_lo, sens_hi, spec, spec_lo, spec_hi, bal_acc, g_mean`. These are NaN→null when the denominator is 0. `*_lo/_hi` are 95% Wilson bounds.
- In `aaa_when_answered`, `n_no_answer` is always 0.

Other notes:
- Key names `"share_below_0.90"` contain a dot, so they need a Pydantic alias.
- If the diameter `n < 3`, every diameter float is null.

**Findings seen per sample:**
- b: repeats/Problem, labels/OK, scanning/Watch, accuracy/Problem
- c: repeats OK, labels Watch, scanning Problem, accuracy Watch
- d: + patients/Problem
- e: labels Problem, accuracy Problem, patients Watch
- f and g: no `patients` entry

`patients` is therefore optional; a check is absent when nothing mapped to it.

**Area → check mapping** (ipynb:1539-1552):
- Repeat patients, Leakage → `repeats`
- Scan content, Impossible values, Embeddings → `scanning`
- Labelling, Labelling vs model → `labels`
- AAA model, Subgroups, Silent failures, Measurement outliers, Segmentation shape → `accuracy`
- "Patients & scanners" → `patients` if the lowercased text contains any of `["sex","age","prevalence","aorta diameter"]`, otherwise `scanning`. This is a substring heuristic.
- Severity → status: red→Problem, yellow→Watch, ok→OK. `info` goes to notes.

There is also a richer sibling file, `<hospital>_test_results.json` (cell 32, ipynb:1450). Top-level keys:
- `meta{hospital, reference, generated_at ISO, n_scans, cutoff_mm, near_duplicate_similarity, shape_analysis_used}`
- `verdict{text, n_red, n_yellow}`
- `files{new,reference: {rows, duplicate_case_ids, case_ids_missing_from_file, merged_rows, missing_expected_feature_columns}}`
- `dataset_description`, `integrity_checks{repeat_patients, leakage_test, labelling, implausible_values, model_outputs}`
- `shift_vs_reference{categorical_distance, numeric, aaa_prevalence, scan_content}`
- `model_performance{new, reference, subgroups[rows], evidence_gaps, effective_cutoff{new,reference:{low,high,bal_acc_at_best}|null}}`
- `embedding_analysis`, `segmentation_shape`, `triggers[monitor rows minus "worse"]`
- `findings[{area, severity: red|yellow|ok|info, text, evidence:{...}}]`
- `figures[str]`

No sample of this file is in the repo.

### 2b. `<hospital>_dice.json`: **no writer exists in the repo.**
- grep finds no `_dice.json` anywhere.
- The PDF spec (docs/Slicepoint POC Reconstruction Spec.pdf, p.24) says a "segmentation notebook" emits it with "mean Dice; median and share below 0.90 are optional and missing in the demo". That notebook is not in the repo.
- The closest existing producers:
  1. `slicepoint.json.dice{average, note}` together with `performance.dice{median, mean, share_below_0.90, share_below_0.85}`.
  2. `cohort.evaluate` in slicepoint/segmentation/slicepoint_model/cohort.py writes **`summary.json`** (L68-87):
     - `{hospital, attempted:int, succeeded:int, failed:int, paired_cases:int, mean_dice: float|null, mean_delta_vs_vendor_reported: float|null, paired_delta_patient_bootstrap_95ci: [lo,hi]|null, comparison_note, annotation_note, pretraining_overlap: str, subgroups: {sex|age_band|scanner_vendor|contrast_phase|slice_thickness_class: [{group:str, n:int, mean_dice:float}]}}`
     - Per-case output goes to `cases.csv`, with columns: case_id, patient_id, sex, age_band, scanner_vendor, contrast_phase, slice_thickness_class, the compare_masks keys, vendor_reported_dice, delta_dice, vendor_recomputed_dice, model_vendor_agreement_dice, status (`ok`|`failed`), error.
- INFERRED: the `_dice.json` contract would be modeled as `{average: float, median?: float, share_below_0_90?: float}`.

### 2c. `<hospital>_monthly_summary.json`
Written by monthly_golive_reports.ipynb cell 14 (ipynb:547; extracted mgr.py:190-196):
```
hospital: str; reference: str; scenario: "stable"|"drift"|"no_answer"|"real data"
first_month_with_a_red_alert: str("YYYY-MM")|null
history_file: str (path to history.csv)
months: [{month:"YYYY-MM", n_scans:int, labels:bool, red:int, yellow:int, green:int,
          verdict:"Review needed"|"Proceed with care"|"Comparable to validation",
          red_triggers:[str], yellow_triggers:[str]}]   # trigger names = monitor.py trigger strings
```
- The file is written with `json.dumps` and no `allow_nan=False`.
- `history.csv` (monitor.py:221-231) has columns: hospital, month, n_scans, group, trigger, value, yellow, red, kind (`pct|pp|sd|mm|num2`), worse (`high|low`), status (`GREEN|YELLOW|RED|n/a`), meaning, action.
- monitor.py and run_monthly.py write no JSON (only CSV and HTML). run_monthly exits with code 2 if any trigger is RED.

### 2d. Segmentation API: `POST /v1/compare` (api.py:103-161)
**Request:** multipart with `ct` and `vendor_mask` (both .nii.gz), `response_format` ∈ `json|zip|image` (default json), and `include_mask: bool`. Requires a bearer token.

**JSON response:**
```
schema_version: "1.0"; comparison_type: "model_vs_vendor_mask_agreement"
metrics (core.compare_masks, core.py:35-70):
  dice: float; iou: float; prediction_volume_ml: float; reference_volume_ml: float
  hd95_mm: float|null; empty_prediction: bool; empty_reference: bool
  hd95_status: "ok"|"both_empty"|"empty_mask"|"sheared_grid"
assessment (presentation.py:10-34):
  status: "empty_mask_review"|"high_agreement"|"review_with_caution"|"low_agreement"
  review_priority: "high"|"low"|"medium"; message: str; dice_percent: float (2dp)
  clinical_correctness_established: false; interpretation: str
  thresholds: {high_agreement:"> 0.9", review_with_caution:"0.7 through 0.9", low_agreement:"< 0.7"}
model (core.predict provenance): {model:"TotalSegmentator", version, task:"total", roi:"aorta", fast:bool, device:str, elapsed_seconds:float, input_sha256, mask_sha256}
display (render_comparison): {plane:"axial", canonical_slice_index:int, selection:str, ct_window_hu:[-150,300], score_dimension:"3D"}
limitation: str
image: {media_type:"image/png", data_url:"data:image/png;base64,..."}       (json format only)
predicted_mask?: {media_type:"application/gzip", filename:"aorta.nii.gz", base64:str}  (if include_mask)
```
- In `image` mode the response is a PNG with headers `X-Dice-Score` and `X-Agreement-Status`. In `zip` mode it is aorta.nii.gz + comparison.png + result.json.
- Dice when both masks are empty is 1.0. The assessment raises an error if dice is non-finite or outside [0,1].
- Errors: 401, 413, 422, 503 (busy, `Retry-After: 30`), 500.

---

## 3. Check and score logic

### monitor.evaluate (monitor.py:46-155)
Each trigger row has `{group, trigger, value, yellow, red, kind, worse, status, meaning, action}`.

Status rule:
- `worse="high"`: RED if value > red, YELLOW if value > yellow, otherwise GREEN.
- `worse="low"`: the same comparisons reversed (value < red, value < yellow).
- NaN → `n/a`.

Reference profile (`fit_reference`, L19-36): StandardScaler, then PCA with `n_pc = min(32, n−1, dims)`, then cosine kNN with `k=5`. `dist_thr` is the 95th percentile of the reference's mean kNN distance.

| trigger | value | yellow / red |
|---|---|---|
| No-answer rate | share of null pred_aaa | 0.02 / 0.04 |
| Change in share called AAA | \|pred rate − ref\| | 0.05 / 0.10 |
| Shift in predicted aorta size | Wasserstein / ref SD | 0.25 / 0.50 |
| Scanner/Contrast/Slice/Sex/Age mix (CAT_COLS L13) | **TVD** = 0.5·Σ\|p−q\| (L39-42), nulls → "MISSING" | 0.15 / 0.30 |
| Shift in aorta brightness (HU) | Wasserstein / ref SD | 0.25 / 0.50 |
| Rise in missing details | Δ share of rows with any CAT null | 0.05 / 0.10 |
| Scans unlike reference | share with mean kNN dist > dist_thr | 0.10 / 0.20 |
| Near-duplicate scans (n≥10) | share with max cosine (std-scaled) > 0.95 | 0.01 / 0.03 |
| Duplicates under different patient IDs | dup & pid≠twin pid | 0.005 / 0.02 |
| Broken aorta 3D shapes (if k_chi) | share \|χ−2\|>0.1 | 0.05 / 0.15 |
| Aneurysms caught (pos≥3) | sens. RED if **Wilson high < 0.70**, YELLOW if sens < 0.80 | 0.80 / 0.70 (low) |
| Average diameter error | MAE mm | 2.0 / 3.0 |
| Labels disagreeing with 30 mm rule | share `(diam>=30)!=aaa` | 0.02 / 0.05 |
| Outline quality (Dice) | mean pred_aorta_dice | 0.90 / 0.85 (low) |

### Notebook findings (test_your_hospital.ipynb)
Constants: `AAA_CUTOFF_MM=30`, `SIM_DUP=0.95` (ipynb:80-81).

- **Repeats** (cell 11, ipynb:423):
  - `patient_groups` = connected components of (cosine > 0.95 OR same patient_id). Null patient_id falls back to case_id.
  - red if share_with_near_duplicate > 0.01, else ok.
  - yellow if any patient_id is null.
- **Leakage** (cell 13): MLP MAE under random KFold(5) vs GroupKFold(5) by dedupe group. red if the gap is more than 0.15 × honest MAE.
- **Labelling** (cell 15, ipynb:550):
  - red if conflict share > 0.05 OR smallest AAA diameter < 27 (cutoff − 3).
  - yellow if share > 0.02.
  - yellow if any size class disagrees with its diameter.
- **Impossible values:** diam/pred 8–120, HU −150–1000, kVp 70–150, slice 0.1–10, organ volumes < 0 → red.
- **Silent failures:** no-answer > 0.04 red, > 0.02 yellow. Measurement outliers: |err| > 3·SD(ref err) → yellow.
- **Patients & scanners:**
  - TVD > 0.30 red, > 0.15 yellow (ipynb:700).
  - Numeric Wasserstein permutation test (1000 permutations, on deduped data): red if p < 0.01 and shift > 0.5 SD; yellow if p < 0.05 and shift > 0.25.
  - AAA prevalence: Fisher p < 0.05 and |Δ| > 0.05 → yellow.
- **Scan content** (ipynb:750-766): domain AUC is logistic regression on PCA(≤32) of the embeddings, StratifiedGroupKFold(5) by dedupe group. ≥0.80 red, ≥0.65 yellow. Share outside coverage > 0.20 red, > 0.10 yellow (reference baseline 0.05).
- **AAA model:**
  - Wilson via `binomtest(...).proportion_ci("wilson")`.
  - Sensitivity: red if sens_hi < 0.70, yellow if sens < 0.80. Needs n_aaa ≥ 3, otherwise info.
  - spec < 0.90 → yellow.
  - Diameter MAE > 3 red, > 2 yellow.
- **Subgroups** (`flag_row`, ipynb:944):
  - "measurement error high" if n ≥ 15 and mae > max(2.0, 2 × ref_mae).
  - "misses aneurysms" if n_aaa ≥ 3 and sens_hi < 0.70.
  - "many no-answers" if n ≥ 15 and no-answer > 0.04.
  - Each is yellow; "hospital-wide" if hits ≥ 80% of eligible groups.
  - Evidence gaps (n ≥ 10, n_aaa = 0) → info.
- **cutoff_range** (ipynb:1002): grid 20–40 mm in 0.5 steps on pred diameter. Takes the range of thresholds that maximise balanced accuracy vs labels. Shift of the midpoint vs reference: ≥3 mm red, ≥2 yellow, else ok.
- **Dice** (cell 29): median < 0.85 red; median < 0.90 or share < 0.90 above 0.10 → yellow.
- **Verdict** (ipynb:1394): counts reds and yellows from triggers plus findings. Any red → "REVIEW NEEDED", else any yellow → "PROCEED WITH CARE", else "LOOKS COMPARABLE".

### The five UI checks: the 0–100 scores are NOT computed anywhere in this repo
The notebook only emits a categorical status per check (OK/Watch/Problem). The PDF spec (p.24-25) lists the UI scores and targets and itself marks the formulas as an "Open question":

| UI check (target) | JSON `check` | Spec says score means | Feeding notebook logic |
|---|---|---|---|
| Different people (90) | `repeats` | scans per distinct person (leakage guard); sub-factors scans, people | near-dup / patient_groups, leakage test |
| Scan settings match (70) | `scanning` | similarity of acquisition mix; card shows lowest of scanner, contrast, slice thickness | TVD on those cols, HU/kVp/slice Wasserstein, domain AUC, coverage, impossible values, embeddings |
| Patients match (70) | `patients` | similarity of patient mix; lowest of sex, age, aaa size class | TVD sex/age, prevalence Fisher, diameter Wasserstein (keyword-routed) |
| Labels follow 30 mm rule (90) | `labels` | share of labels consistent with 30 mm | conflict share, cutoff_range |
| AI accuracy (88) | `accuracy` | composite of Dice, size within tolerance, aneurysms caught | bin/diam/dice metrics, subgroups, silent failures |

INFERRED: a natural score formula is (1 − TVD)·100 for the mix checks and (1 − conflict share)·100 for labels, but nothing in the code confirms it.

UI constants from the spec, with nothing in code backing them:
- Dice markers 0.81 and 0.90
- size tolerance 3 mm (Bland-Altman uses 2 mm)
- decision lines at 30 and 55 mm; "nearby" means ±5 mm
- subgroup minimum size somewhere between 12 and 14
- population SD

These conflict with the notebook, which uses sample SD (`e.std()` in numpy is population SD; pandas `.std()` is sample SD; the notebook mixes both) and a subgroup minimum of n ≥ 15.

GO rule (spec): all 5 checks meet target. The spec marks this rule as inferred.

### Gotchas for the schema
- The scan `id` is truncated to 8 chars of case_id, while parquet case_id is 16 chars.
- `personGroup` is derived from patient_id and embeddings, not from patient_id alone. In hospital_b there are 60 patient_ids but 40 groups.
- `findings` is a sparse list, not a fixed 5-key object.
- The `dice` top-level block is optional. `performance.dice` can be `{}`.
- Hospital name matching is by the string `"Hospital B"` (title-cased), while monthly_summary uses the raw `HOSPITAL_NAME` (e.g. `demo_hospital`). The join between them is by name only.
