# SlicePoint datasets

SlicePoint publishes two datasets on Hugging Face under the
[`slicepoint`](https://huggingface.co/slicepoint) organization. Both are built from the
**TotalSegmentator dataset v2.0.1** (Wasserthal et al., University Hospital Basel) and are
released under **CC BY 4.0**. The dataset cards on Hugging Face are the reference; their
source is in [`slicepoint/datasets/`](slicepoint/datasets). This page is the overview.

| | [SlicePoint AAA CT](https://huggingface.co/datasets/slicepoint/slicepoint-aaa-ct) | [SlicePoint Hospitals](https://huggingface.co/datasets/slicepoint/slicepoint-hospitals) |
|---|---|---|
| What it is | The canonical set: every usable abdominal scan, once | Seven simulated hospitals sampled from it, most with a planted problem |
| Scans | 567 (555 labelled and eligible) | 580 cases (some are repeats or re-made scans) |
| Images | CT volumes plus 7 ground-truth masks each | CT volumes plus the aorta mask |
| Tables | All measurements; cohorts in the SlicePoint input format | The SlicePoint input format, one folder per hospital |
| Extras | Vendor datasheets; TotalSegmentator split | Answer keys, crosswalk to the canonical scans, practice manifest |
| Use it for | Training and testing models; vendor-vs-site demos; datasheet checks | Testing shift detection; federated learning (one client per hospital) |

## Where the numbers come from

- **Scans.** Abdominal CT from the TotalSegmentator dataset showing the infrarenal aorta,
  iliac arteries and kidneys. The scans come from 10 coded imaging institutes and 15
  scanner models (Siemens, Philips, GE). Voxels are unchanged; four free-text NIfTI header
  fields are emptied.
- **Ground-truth masks** (`_ref` columns) are the segmentations distributed with
  TotalSegmentator: drafted by a model, then reviewed and corrected by people under two
  physicians' supervision. The aorta is one label covering the whole visible aorta.
- **AAA labels** are measurements, not radiologist reads: the maximum infrarenal
  outer-wall diameter perpendicular to the centerline of the ground-truth aorta mask, with
  AAA at 30 mm or more.
- **Baseline predictions** (`_pred` columns) are the output of an AI model: the public
  TotalSegmentator model (v2.18.0, `total` task) run on each CT, then the same measurement
  and rule. It stands in for a commercial segmentation product. **It was trained on most of
  these scans** (491 of 567 are in its training split), so its results here are not an
  independent test; use the `test` split, or scans no model has seen, for a fair baseline.
- **Embeddings** are 2048-dimensional, from the Merlin CT encoder.
- **Study description and protocol name** are synthetic: the source has none.
- **Not recorded:** race and ethnicity (Swiss hospital records generally do not hold them),
  so neither dataset can show differences along those lines.

**Not for clinical use.**

## SlicePoint AAA CT

```
images/<id>.nii.gz                    CT volume, 1.5 mm isotropic
masks/<structure>/<id>.nii.gz         aorta, kidney_left, kidney_right, liver, spleen,
                                      iliac_artery_left, iliac_artery_right
tables/cases.parquet                  every scan: demographics, institute, scanner, eligibility
tables/pipeline/                      all measurements (four diameter methods, volumes, Dice), embeddings
cohorts/{all,vendor_train,site_retrospective}/   features, labels, predictions, embeddings
vendor_datasheet/                     summary statistics a vendor might disclose
manifest.json                         counts and sha256 of every table
```

`<id>` is TotalSegmentator's own image id (`s0001`...). The cohorts: `all` (555 scans, 60
AAA), `vendor_train` (333, 36 AAA) standing in for a vendor's training data, and
`site_retrospective` (222, 24 AAA) standing in for a hospital's retrospective pull. The two
halves are a random split stratified on AAA and sex, so a fair check should find no real
difference between them.

The vendor datasheets use SlicePoint's `VendorDatasheet` format:
`aaa-baseline-v0.json` summarizes `vendor_train`; `totalsegmentator-v2-train-all.json` and
`totalsegmentator-v2-train-abdominal.json` describe the TotalSegmentator model's real
training data (all 1,082 training scans, and the 481 of them in this dataset). Testing one
site against both shows why a datasheet's population matters.

## SlicePoint Hospitals

| Hospital | Scans | What is different |
|---|---|---|
| `hospital_a` | 100 | Nothing: the clean reference |
| `hospital_b` | 80 (40 people) | Repeat scans, some under new patient ids |
| `hospital_c` | 80 | Thick slices (5 mm) and venous phase |
| `hospital_d` | 80 | More aneurysms; older, more male, more arterial phase |
| `hospital_e` | 80 | Labels measure the lumen and call AAA at 25 mm |
| `hospital_f` | 80 | Nothing: a false-alarm test |
| `hospital_g` | 80 | The exam name gives the answer away, plus 2 people from `hospital_b` |

`hospital_a` to `hospital_e` were the hackathon's practice hospitals; `f` and `g` were
released on the Sunday. `keys/` holds each hospital's full recipe and answers,
`crosswalk.parquet` maps every case to its scan in SlicePoint AAA CT, and `manifest.json` is
the practice release manifest. The SlicePoint tests use these tables as `data/practice/`
(see [data/README.md](data/README.md)).

## Download

```bash
pip install -U "huggingface_hub[cli]"
# tables only
hf download slicepoint/slicepoint-aaa-ct --repo-type dataset --include "cohorts/*" --include "vendor_datasheet/*"
hf download slicepoint/slicepoint-hospitals --repo-type dataset --exclude "*/images/*" --exclude "*/masks/*"
```

## How they were made, and how to make more

The tables, cohorts and datasheets are produced by the Asher Informatics data pipeline
(`pipeline/stages/canonical.py` and `pipeline/stages/ts_datasheets.py`; the images are
published from Modal by `pipeline/publish_hf.py`). The hospitals come from the same
pipeline's recipe-driven generators. These live in an internal repository for now; making
the generators public, so others can build new cohorts or other modalities, is planned.

## License and citation

CC BY 4.0. Modified from the TotalSegmentator dataset by Asher Informatics PBC (subset,
header fields emptied, derived tables added; for the hospitals also sampled, perturbed and
re-identified). Segmentations by the TotalSegmentator model (Apache-2.0); embeddings by
[Merlin](https://huggingface.co/stanfordmimi/Merlin) (MIT). Please cite TotalSegmentator:
Wasserthal J. et al., *Radiology: Artificial Intelligence* 2023;5(5),
[doi:10.1148/ryai.230024](https://doi.org/10.1148/ryai.230024); dataset
[doi:10.5281/zenodo.10047292](https://doi.org/10.5281/zenodo.10047292).
