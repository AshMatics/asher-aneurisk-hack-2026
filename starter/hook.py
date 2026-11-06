"""The hook: a model that looks good only because the split was wrong.

    pip install pandas pyarrow scikit-learn
    python starter/hook.py                      # uses data/practice/hospital_a
    python starter/hook.py data/practice/hospital_a

Predicts maximum aortic diameter from the image embeddings with a small neural
network (two hidden layers). First on the hospital as released, then after
pretending every patient was scanned twice, which is common in real data
(follow-up scans, repeat studies, re-reconstructions).

The model is scored two ways:
- random split: scans are shuffled into train and test, the usual default
- by patient: all scans of a patient stay on the same side

When patients have more than one scan, a random split puts near-copies of the same
person on both sides, and the score measures memory, not skill.
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold, KFold, cross_val_predict
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")   # small-data convergence chatter

hospital = Path(sys.argv[1] if len(sys.argv) > 1 else "data/practice/hospital_a")
df = (pd.read_parquet(hospital / "features.parquet")
      .merge(pd.read_parquet(hospital / "labels.parquet"), on="case_id")
      .merge(pd.read_parquet(hospital / "embeddings.parquet"), on="case_id"))
X = df.filter(like="emb_").to_numpy()
y = df["max_aortic_diameter_mm"].to_numpy()
patient = df["patient_id"].fillna(df["case_id"]).to_numpy()


def model():
    return make_pipeline(StandardScaler(), PCA(32, random_state=0),
                         MLPRegressor(hidden_layer_sizes=(64, 32), alpha=1e-3, max_iter=3000, random_state=0))


def score(X, y, groups, title):
    print(f"\n{title}: {len(y)} scans, {len(set(groups))} patients")
    for name, cv, g in [("random split", KFold(5, shuffle=True, random_state=0), None),
                        ("by patient  ", GroupKFold(5), groups)]:
        pred = cross_val_predict(model(), X, y, cv=cv, groups=g)
        print(f"  {name}  error {mean_absolute_error(y, pred):4.1f} mm   R2 {r2_score(y, pred):5.2f}")


score(X, y, patient, f"{hospital.name} as released")

# Every patient scanned a second time: a slightly different embedding and a
# diameter re-measured to within about 1 mm. Nothing else changes.
rng = np.random.default_rng(0)
X2 = np.vstack([X, X + rng.normal(0, 1, X.shape) * X.std(axis=0) * 0.1])
y2 = np.concatenate([y, y + rng.normal(0, 1, len(y))])
score(X2, y2, np.concatenate([patient, patient]), f"{hospital.name} with one repeat scan per patient")

print("""
R2 near 1 means the model explains the diameter; 0 means no better than the average;
below 0 means worse than the average. Same data, same model: only the split changed.
Which practice hospitals have patients with more than one scan, and do you always know?""")
