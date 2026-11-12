# Data

Sample data for SlicePoint lives here, outside git (everything in this folder except this
README is ignored, so it cannot be committed by accident).

## The practice hospitals (`data/practice/`)

The SlicePoint tests, notebooks and examples use the hackathon's practice hospitals. They are
published on Hugging Face as
[slicepoint/slicepoint-hospitals](https://huggingface.co/datasets/slicepoint/slicepoint-hospitals).
Download the tables (about 10 MB) into `data/practice/`:

```bash
pip install -U "huggingface_hub[cli]"
hf download slicepoint/slicepoint-hospitals --repo-type dataset --local-dir data/practice \
    --include "hospital_*/*.parquet" --include "manifest.json"
```

You get one folder per hospital (`hospital_a` to `hospital_g`), each with
`features.parquet`, `labels.parquet`, `predictions.parquet` and `embeddings.parquet`, joined
on `case_id`, plus `manifest.json` (row counts and sha256 of the `hospital_a` to `hospital_e`
tables as first released). Add `--include "hospital_c/images/*" --include "hospital_c/masks/*"`
for one site's CT volumes and aorta masks, or leave out `--include` for everything (about 14 GB).

Columns and what each hospital hides: the
[dataset card](https://huggingface.co/datasets/slicepoint/slicepoint-hospitals) and
[DATASETS.md](../DATASETS.md).
