---
license: cc-by-4.0
pretty_name: SlicePoint AAA CT
language: [en]
tags: [medical, ct, abdominal-aortic-aneurysm, segmentation, nifti, distribution-shift, totalsegmentator]
size_categories: [n<1K]
task_categories: [image-segmentation, image-classification]
configs:
  - config_name: cases
    data_files: tables/cases.parquet
  - config_name: features
    data_files:
      - {split: all, path: cohorts/all/features.parquet}
      - {split: vendor_train, path: cohorts/vendor_train/features.parquet}
      - {split: site_retrospective, path: cohorts/site_retrospective/features.parquet}
  - config_name: labels
    data_files:
      - {split: all, path: cohorts/all/labels.parquet}
      - {split: vendor_train, path: cohorts/vendor_train/labels.parquet}
      - {split: site_retrospective, path: cohorts/site_retrospective/labels.parquet}
  - config_name: predictions
    data_files:
      - {split: all, path: cohorts/all/predictions.parquet}
      - {split: vendor_train, path: cohorts/vendor_train/predictions.parquet}
      - {split: site_retrospective, path: cohorts/site_retrospective/predictions.parquet}
  - config_name: embeddings
    data_files:
      - {split: all, path: cohorts/all/embeddings.parquet}
      - {split: vendor_train, path: cohorts/vendor_train/embeddings.parquet}
      - {split: site_retrospective, path: cohorts/site_retrospective/embeddings.parquet}
---

# SlicePoint AAA CT

567 abdominal CT scans from the TotalSegmentator dataset, with ground-truth masks, aortic
measurements, abdominal aortic aneurysm (AAA) labels, a baseline model's predictions and
image embeddings. The AAA labels are not radiologist reads: they come from a 30 mm
threshold on the aortic diameter measured on the ground-truth aorta masks that ship with
the TotalSegmentator dataset. The baseline predictions apply the same rule to masks from
the public TotalSegmentator model. The scans were collected through University Hospital Basel but come from
10 coded imaging institutes and 15 scanner models (Siemens, Philips, GE); the `institute`
column in `tables/cases.parquet` says which. It is the canonical dataset of
[SlicePoint](https://github.com/AshMatics/slicepoint),
an open-source tool that checks whether an imaging AI model fits a hospital's patients
and scanners before it is switched on.

**Not for clinical use.** The AAA labels come from a diameter rule applied to segmentation
masks, not from radiology reports or clinical diagnoses.

## What is in it

| Path | What |
|---|---|
| `images/<id>.nii.gz` | CT volume, 1.5 mm isotropic, int16 HU (567 files) |
| `masks/<structure>/<id>.nii.gz` | Ground-truth binary masks: `aorta`, `kidney_left`, `kidney_right`, `liver`, `spleen`, `iliac_artery_left`, `iliac_artery_right` |
| `tables/cases.parquet` | Every scan: age, sex, institute (coded `a` to `j`), scanner, kVp, study type, pathology, voxel spacing, `eligible` and `exclusion_reason` |
| `tables/pipeline/` | All computed measurements: four aortic diameter methods (outer wall / lumen, axial / centerline-orthogonal) on the ground-truth (`_ref`) and model (`_pred`) masks, organ volumes, Dice per structure, Merlin embeddings |
| `cohorts/<name>/` | The SlicePoint input contract (`features`, `labels`, `predictions`, `embeddings` parquet, joined on `case_id`) for three cohorts below |
| `vendor_datasheet/` | Vendor datasheets (summary statistics only, in the SlicePoint `VendorDatasheet` format): `aaa-baseline-v0.json` summarises `vendor_train`, as a vendor might disclose it; `totalsegmentator-v2-train-all.json` and `totalsegmentator-v2-train-abdominal.json` describe the TotalSegmentator model's real training data (all 1,082 training scans, every body region, and the 481 of them in this dataset), computed from the source metadata |
| `manifest.json` | Counts and sha256 of every table |

`case_id` is TotalSegmentator's own image id (`s0001`...), so every row traces back to
the source dataset. The source has no patient id; each scan is treated as one patient.

**Not recorded: race and ethnicity.** The source has no race, ethnicity, ancestry or
residence fields (Swiss hospital records generally do not hold them), so this dataset
cannot show shifts or subgroup differences along those lines. The population is that of
a Swiss university hospital system.

### Cohorts

| Cohort | Scans | AAA | Use |
|---|---|---|---|
| `all` | 555 | 60 | Every eligible, labelled scan |
| `vendor_train` | 333 | 36 | Stands in for the data a vendor trained on |
| `site_retrospective` | 222 | 24 | Stands in for a hospital's retrospective pull ("the last 6 to 9 months of abdominal CTs") |

The two halves are a random split stratified on AAA and sex (not on institute), so they
come from the same population: a fair check should not find a meaningful difference. In practice a hospital
never sees the vendor's rows, only something like `vendor_datasheet/`. For sites that do
differ (other scanners, thick slices, different labelling rules, repeat patients), see
[slicepoint-hospitals](https://huggingface.co/datasets/slicepoint/slicepoint-hospitals).

12 scans are not in the cohorts; `tables/cases.parquet` gives each reason (5 fail the
eligibility rule, 6 have no measurable infrarenal diameter, 1 is a thorax CT). Scans the
baseline model fails on (for example Dice 0) are kept: a real cohort contains them.

## Intended use

A test harness for checking how an imaging AI model behaves at a new site, not a
leaderboard. The ground-truth masks are independent of any one model, so you can train
your own classifiers or segmenters (AAA, enlarged kidneys, organ volumes) on one part of the
data, apply them to another, and see how shifts in scanners, slice thickness, phase, age or
case mix, or hidden subgroups, change their results. The aim is to show the difference
between a model's results on clean development data and on a site's own data, not to
build the best model.

## How the values were made

- **Ground-truth masks:** the segmentations distributed with TotalSegmentator v2.0.1,
  unchanged. The dataset authors made them with model help and expert review and
  correction; they are not output of the SlicePoint pipeline.
- **Labels:** `max_aortic_diameter_mm` is the maximum infrarenal outer-wall diameter,
  measured perpendicular to the centerline of the ground-truth aorta mask. `aaa` is
  diameter >= 30 mm; `aaa_size_class` is `none`, `30-54mm` or `>=55mm`. These are
  measurement-derived labels, not radiologist reads.
- **Predictions (baseline model):** the output of an AI model, not a second ground truth.
  We ran the public TotalSegmentator model (v2.18.0, `total` task) on each CT and applied
  the same measurement and 30 mm rule to its aorta mask. It stands in for the kind of
  nnU-Net-based segmentation found in commercial imaging AI products. Null means the
  model gave no answer. `_ref` columns use the ground-truth masks,
  `_pred` columns the model's.
- **The baseline model has seen most of these scans.** TotalSegmentator was trained on
  this dataset: of the 567 scans, its own split (`totalsegmentator_split` in
  `tables/cases.parquet`) marks 491 as training, 21 as validation and 55 as test. So
  `_pred` results are not an independent test of the model. Here it scores about the same
  on its test scans as on its training scans (aorta Dice 0.968 vs 0.967; AAA agreement 98%
  vs 99%), but the test scans include only 4 AAA cases, too few to rule out a difference.
  For a fair baseline, use the `test` scans; if you train your own model on part of this
  data, compare it with TotalSegmentator on scans neither model was trained on.
- **Features:** scanner and acquisition fields come from the TotalSegmentator metadata
  (v3.0.0 adds slice thickness). Contrast phase is predicted. `study_description` and
  `protocol_name` are **synthetic**: the source has none, so they are drawn from a
  vocabulary of realistic orderables. HU and organ volumes come from the masks.
- **Embeddings:** 2048-dimensional image embeddings from the Merlin CT encoder.
- **Images:** unchanged voxels and affines; four free-text NIfTI header fields emptied.

## Download

```bash
hf download slicepoint/slicepoint-aaa-ct --repo-type dataset --include "cohorts/*" "vendor_datasheet/*"   # tables only, ~20 MB
hf download slicepoint/slicepoint-aaa-ct --repo-type dataset --include "masks/aorta/*"                    # one structure
hf download slicepoint/slicepoint-aaa-ct --repo-type dataset                                              # everything, ~17 GB
```

```python
from datasets import load_dataset
labels = load_dataset("slicepoint/slicepoint-aaa-ct", "labels", split="site_retrospective")
```

Test a site against a vendor datasheet (summary statistics only, no vendor rows). The two
TotalSegmentator datasheets show why a datasheet's population matters: the abdominal
`site_retrospective` cohort is covered by the all-regions datasheet but distributed
differently (thinner slices there), and matches the abdominal one:

```bash
slicepoint datasheet check --data cohorts/site_retrospective --site-id site \
    --datasheet vendor_datasheet/totalsegmentator-v2-train-all.json --scope-broader
slicepoint datasheet check --data cohorts/site_retrospective --site-id site \
    --datasheet vendor_datasheet/totalsegmentator-v2-train-abdominal.json
```

Run SlicePoint on the demo pair:

```bash
slicepoint assess --data cohorts/site_retrospective --site-id site \
    --reference-dir cohorts/vendor_train --reference-site-id vendor --html report.html
```

## Source, license and citation

Built from the **TotalSegmentator dataset v2.0.1** (Wasserthal J. et al., University
Hospital Basel, [doi:10.5281/zenodo.10047292](https://doi.org/10.5281/zenodo.10047292)),
with acquisition details from v3.0.0
([doi:10.5281/zenodo.22688904](https://doi.org/10.5281/zenodo.22688904)), licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). This dataset is a modified
version (subset, header fields emptied, derived tables added) by Asher Informatics PBC
and is released under CC BY 4.0. Segmentations by the TotalSegmentator `total` model
(Apache-2.0). Embeddings by [Merlin](https://huggingface.co/stanfordmimi/Merlin) (MIT).

Please cite TotalSegmentator:

```bibtex
@article{wasserthal2023totalsegmentator,
  title   = {TotalSegmentator: Robust Segmentation of 104 Anatomic Structures in CT Images},
  author  = {Wasserthal, Jakob and Breit, Hanns-Christian and Meyer, Manfred T. and others},
  journal = {Radiology: Artificial Intelligence},
  volume  = {5}, number = {5}, year = {2023},
  doi     = {10.1148/ryai.230024}
}
```

The scans came out of the 2026 Nucleate Pittsburgh hackathon, where SlicePoint started.
