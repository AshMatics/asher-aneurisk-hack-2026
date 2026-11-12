---
license: cc-by-4.0
pretty_name: SlicePoint Hospitals
language: [en]
tags: [medical, ct, abdominal-aortic-aneurysm, federated-learning, non-iid, distribution-shift, dataset-shift, nifti]
size_categories: [n<1K]
configs:
  - config_name: features
    data_files:
      - {split: hospital_a, path: hospital_a/features.parquet}
      - {split: hospital_b, path: hospital_b/features.parquet}
      - {split: hospital_c, path: hospital_c/features.parquet}
      - {split: hospital_d, path: hospital_d/features.parquet}
      - {split: hospital_e, path: hospital_e/features.parquet}
      - {split: hospital_f, path: hospital_f/features.parquet}
      - {split: hospital_g, path: hospital_g/features.parquet}
  - config_name: labels
    data_files:
      - {split: hospital_a, path: hospital_a/labels.parquet}
      - {split: hospital_b, path: hospital_b/labels.parquet}
      - {split: hospital_c, path: hospital_c/labels.parquet}
      - {split: hospital_d, path: hospital_d/labels.parquet}
      - {split: hospital_e, path: hospital_e/labels.parquet}
      - {split: hospital_f, path: hospital_f/labels.parquet}
      - {split: hospital_g, path: hospital_g/labels.parquet}
  - config_name: predictions
    data_files:
      - {split: hospital_a, path: hospital_a/predictions.parquet}
      - {split: hospital_b, path: hospital_b/predictions.parquet}
      - {split: hospital_c, path: hospital_c/predictions.parquet}
      - {split: hospital_d, path: hospital_d/predictions.parquet}
      - {split: hospital_e, path: hospital_e/predictions.parquet}
      - {split: hospital_f, path: hospital_f/predictions.parquet}
      - {split: hospital_g, path: hospital_g/predictions.parquet}
  - config_name: embeddings
    data_files:
      - {split: hospital_a, path: hospital_a/embeddings.parquet}
      - {split: hospital_b, path: hospital_b/embeddings.parquet}
      - {split: hospital_c, path: hospital_c/embeddings.parquet}
      - {split: hospital_d, path: hospital_d/embeddings.parquet}
      - {split: hospital_e, path: hospital_e/embeddings.parquet}
      - {split: hospital_f, path: hospital_f/embeddings.parquet}
      - {split: hospital_g, path: hospital_g/embeddings.parquet}
  - config_name: crosswalk
    data_files: crosswalk.parquet
---

# SlicePoint Hospitals

Seven simulated hospitals for studying dataset shift and non-IID federated learning on
abdominal CT, with the answer keys. Each hospital is a sample of the
[SlicePoint AAA CT](https://huggingface.co/datasets/slicepoint/slicepoint-aaa-ct) scans,
and all but two have a problem planted on purpose: the kind of difference that makes an
AI model behave differently at a new site. They were built for the 2026 Nucleate
Pittsburgh hackathon, where teams had to find the problems. The game is over, so the keys
are published.

**Not for clinical use.** AAA labels come from a 30 mm diameter rule on the ground-truth
aorta masks that ship with TotalSegmentator (at `hospital_e`, a 25 mm lumen rule), not
from radiologist reads. Predictions apply the same rule to the public TotalSegmentator
model's masks.

## The hospitals

| Hospital | Scans (patients) | AAA | What is different | How clearly it shows |
|---|---|---|---|---|
| `hospital_a` | 100 (100) | 9 | Nothing. A clean random sample; the reference the others are compared with | none |
| `hospital_b` | 80 (40 people under 60 IDs) | 7 | Patients scanned again and again, some under new IDs; 2 patients reappear at `hospital_e` | strong (repeats), weak (cross-site) |
| `hospital_c` | 80 (80) | 7 | Every scan thick-slice (5 mm) and venous phase: same patients, scanned differently | strong on acquisition, weak on Dice |
| `hospital_d` | 80 (80) | 20 | Far more aneurysms, and older, more male, more arterial phase, all moving together | strong; the factors are confounded |
| `hospital_e` | 80 (80) | 7 by its own rule | Labels measure the inside of the vessel and call AAA at 25 mm: same images, different truth | strong |
| `hospital_f` | 80 (80) | 7 | Nothing. Tests for false alarms | none |
| `hospital_g` | 80 (80) | 7 | The exam name gives away the answer (a shortcut), plus 2 `hospital_b` patients under new IDs | weak |

`keys/<hospital>.json` holds the full recipe of each hospital: the planted findings
(`waldos`: kind, severity, description, the evidence a correct finding cites), the
targets, what was realised, and one row per case (source scan, repeat or cross-site copy,
new patient id or not). `keys/practice/` has the reference measures given to teams for
`hospital_a` to `hospital_e`, with the chance levels two clean samples would show.

`crosswalk.parquet` maps every case to its scan in SlicePoint AAA CT
(`canonical_image_id`), its true patient, and whether its image was changed:
`hospital_c` ships 5 mm re-makes, and the repeat scans at `hospital_b` and `hospital_g`
have added noise and a few slices dropped, so no file is a byte copy of another.

## Layout

| Path | What |
|---|---|
| `hospital_<x>/images/<case_id>.nii.gz` | CT volume (1.5 mm; `hospital_c` 1.5 x 1.5 x 5 mm) |
| `hospital_<x>/masks/<case_id>_aorta.nii.gz` | Ground-truth aorta mask on the same grid |
| `hospital_<x>/{features,labels,predictions,embeddings}.parquet` | The SlicePoint input contract, joined on `case_id` |
| `keys/`, `crosswalk.parquet` | Answer keys, as above |

Column meanings are the same as in SlicePoint AAA CT. `study_description` and
`protocol_name` are synthetic; at `hospital_g` they carry the shortcut.

## Download and use

```bash
hf download slicepoint/slicepoint-hospitals --repo-type dataset --exclude "*/images/*" "*/masks/*"   # tables + keys, ~10 MB
hf download slicepoint/slicepoint-hospitals --repo-type dataset --include "hospital_c/*"             # one site with images
```

```bash
slicepoint assess --data hospital_b --site-id hospital_b \
    --reference-dir hospital_a --reference-site-id hospital_a --html report.html
```

For federated-learning experiments, treat each `hospital_<x>` folder as one client;
`crosswalk.parquet` tells you where clients share patients.

## Source, license and citation

Derived from the **TotalSegmentator dataset v2.0.1** (Wasserthal J. et al., University
Hospital Basel, [doi:10.5281/zenodo.10047292](https://doi.org/10.5281/zenodo.10047292);
acquisition details from v3.0.0,
[doi:10.5281/zenodo.22688904](https://doi.org/10.5281/zenodo.22688904)), licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Modified by Asher Informatics
PBC (sampled, perturbed as described above, re-identified, derived tables added) and
released under CC BY 4.0. Segmentations by the TotalSegmentator `total` model
(Apache-2.0). Embeddings by [Merlin](https://huggingface.co/stanfordmimi/Merlin) (MIT).
Please cite TotalSegmentator (Radiology: AI 2023,
[doi:10.1148/ryai.230024](https://doi.org/10.1148/ryai.230024)).
