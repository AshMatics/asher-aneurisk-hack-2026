# Data card (draft)

> Draft schema. Column names may change before release.

## Sources

Abdominal CT drawn from public research datasets, resampled into virtual hospitals. Source attribution and licenses will be listed here at release.

## Layout

```
hospital_<id>/
  features.parquet      one row per case
  embeddings.parquet    one vector per case
  predictions.parquet   baseline model outputs per case
  labels.parquet        ground truth per case, under this hospital's labeling convention
```

Deep lane (opt-in, separate download):

```
hospital_<id>/images/<case_id>.nii.gz
dicom_sample/          a small set of studies with real DICOM headers
```

## features.parquet

| Column | Type | Notes |
| --- | --- | --- |
| `case_id` | str | Hashed, unique per release |
| `patient_id` | str or null | Hashed. May be missing at some hospitals, as in real life |
| `age_band` | str | e.g. `50-59` |
| `sex` | str | `F`, `M` |
| `scanner_vendor` | str | |
| `contrast_phase` | str | e.g. `arterial`, `venous`, `non-contrast` |
| `slice_thickness_mm` | float | |
| `slice_thickness_class` | str | `thin` (under 2 mm), `standard`, `thick` (5 mm and over) |
| `kvp` | float | Where available |
| `protocol_name` | str | Free text, as found |
| `aorta_hu_mean`, `aorta_hu_sd` | float | Within the segmented aorta |
| `organ_volumes_*` | float | Selected organs, mL |

## labels.parquet

| Column | Type | Notes |
| --- | --- | --- |
| `case_id` | str | |
| `max_aortic_diameter_mm` | float | Primary label (continuous) |
| `aaa` | bool | Derived from diameter under this hospital's convention |
| `aaa_size_class` | str | `none`, `<30mm`, `30-54mm`, `>=55mm` |

## predictions.parquet

| Column | Type | Notes |
| --- | --- | --- |
| `case_id` | str | |
| `pred_aorta_dice` | float | Baseline segmentation model vs reference mask |
| `pred_max_diameter_mm` | float | From the baseline model's mask |
| `pred_aaa` | bool | Baseline AAA call |

## embeddings.parquet

| Column | Type | Notes |
| --- | --- | --- |
| `case_id` | str | |
| `emb_0` ... `emb_{d-1}` | float | One pretrained CT encoder; name and version in file metadata |

## Subgroups

Subgroup columns provided for every case: `sex`, `age_band`, `aaa_size_class`, `scanner_vendor`, `contrast_phase`, `slice_thickness_class`.
