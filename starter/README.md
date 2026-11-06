# Starter notes

Download the practice tables first (see [../docs/getting-started.md](../docs/getting-started.md)), install the basics (`pip install pandas pyarrow numpy`), then:

```python
import pandas as pd
from pathlib import Path

root = Path("data/practice")
h = "hospital_a"
features = pd.read_parquet(root / h / "features.parquet")
labels = pd.read_parquet(root / h / "labels.parquet")
preds = pd.read_parquet(root / h / "predictions.parquet")
emb = pd.read_parquet(root / h / "embeddings.parquet")

df = features.merge(labels, on="case_id").merge(preds, on="case_id")
print(df.shape, emb.shape)
print(df.groupby("contrast_phase")["aaa"].mean())
```

Every table joins on `case_id`. Patients with more than one scan share a `patient_id` (when the hospital records it reliably).

A quick first check is to run the example audit across every practice hospital, inside the harness:

```bash
python harness/harness.py --data data/practice --audit harness.example_audit:audit --out summaries.json
```

See [../harness/README.md](../harness/README.md) for what the harness allows out of a hospital.

For the images, any NIfTI reader works (`nibabel`, `SimpleITK`). CT values are Hounsfield units. Masks share the image grid.

## The hook

`hook.py` trains a small neural network to predict aortic diameter from the embeddings, then shows how a random train/test split can make it look far better than it is once patients have more than one scan. It runs on a laptop in under a minute:

```bash
pip install pandas pyarrow scikit-learn
python starter/hook.py
```
