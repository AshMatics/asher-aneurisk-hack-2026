# Data card

What you receive, file by file. Where to download it: [getting-started.md](getting-started.md).

## Sources

Abdominal CT from public research datasets, resampled into virtual hospitals. Sources, citations and licenses are in `CREDITS.md` inside each download. Do not try to match cases back to the source datasets.

## Layout

```
practice/
  manifest.json          every file with its row count and checksum
  CREDITS.md             sources and licenses
  hospital_<x>/
    features.parquet     one row per case
    labels.parquet       ground truth per case, under this hospital's labeling convention
    predictions.parquet  baseline model outputs per case
    embeddings.parquet   one image embedding per case
  tutorial_keys/         answer keys released early (Friday)
```

The Sunday download has the same layout. Hospital letters are assigned at random and say nothing about the hospital.

Deep lane (optional, separate download, one zip per hospital):

```
hospital_<x>/images/<case_id>.nii.gz       CT volume, Hounsfield units
hospital_<x>/masks/<case_id>_aorta.nii.gz  reference aorta mask, same grid
```

## features.parquet

| Column | Type | Notes |
| --- | --- | --- |
| `case_id` | str | Hashed, unique within the release. Joins all tables. |
| `patient_id` | str | Hashed. Scans of the same patient share it, when the hospital records it reliably. |
| `age_band` | str | 10-year bands, e.g. `50-59` |
| `sex` | str | `F`, `M` |
| `scanner_vendor` | str or null | e.g. `siemens`, `philips`, `ge`. Missing for a few cases. |
| `contrast_phase` | str | `arterial`, `venous`, `non-contrast` |
| `slice_thickness_mm` | float | Acquisition slice thickness |
| `slice_thickness_class` | str | `thin` (under 2 mm), `standard`, `thick` (5 mm and over) |
| `kvp` | float or null | Tube voltage. Missing where the scanner vendor is missing. |
| `study_description` | str | The exam as ordered (EHR/RIS wording), free text as found |
| `protocol_name` | str | The scanner protocol, free text as found |
| `aorta_hu_mean`, `aorta_hu_sd` | float | Within the segmented aorta |
| `organ_volumes_liver`, `organ_volumes_spleen`, `organ_volumes_kidney_left`, `organ_volumes_kidney_right` | float | mL |

## labels.parquet

| Column | Type | Notes |
| --- | --- | --- |
| `case_id` | str | |
| `max_aortic_diameter_mm` | float | Primary label (continuous) |
| `aaa` | bool | Abdominal aortic aneurysm, derived from the diameter under this hospital's convention |
| `aaa_size_class` | str | `none`, `30-54mm`, `>=55mm` |

## predictions.parquet

| Column | Type | Notes |
| --- | --- | --- |
| `case_id` | str | |
| `pred_aorta_dice` | float | Overlap of the baseline segmentation model's aorta with the reference mask (0 to 1) |
| `pred_max_diameter_mm` | float | Diameter from the baseline model's mask |
| `pred_aaa` | bool | Baseline AAA call |

## embeddings.parquet

| Column | Type | Notes |
| --- | --- | --- |
| `case_id` | str | |
| `emb_0` ... `emb_2047` | float | Merlin CT encoder, one 2,048-number vector per case |

## Subgroups

Subgroup columns for every case: `sex`, `age_band`, `aaa_size_class`, `scanner_vendor`, `contrast_phase`, `slice_thickness_class`.

## Size

80 to 100 cases per hospital. Tables and embeddings together are under 10 MB.
