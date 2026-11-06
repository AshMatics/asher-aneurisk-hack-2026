"""The hook: a model that looks good only because the split was wrong.

    pip install pandas pyarrow scikit-learn
    python starter/hook.py                      # uses data/practice/hospital_a
    python starter/hook.py data/practice/hospital_a

Predicts maximum aortic diameter from the image embeddings with a small neural
network (two hidden layers). First on the hospital as released, then presented to simulate
that every patient was scanned twice - which is common in real datasets or by accident if the dataset is completely de-identified.
There is also a domain-specific "alloteric" behavior represented here too. In many screening and watchful waiting scenarios - as potentiall
with AAA imaging - the same patient is scanned at different time point.  Also, it's not uncommon for a patient's imaging styuy to be repeated. 
OR, if not careful with research data acquisition, a different 'reconstruction' of the study may appear like an independent study/series in the hosptals
imaging data archive.

The model is scored two ways:
- random split: scans are shuffled into train and test, the usual default, BUT no control on ensuring studies from same patient not in both test and train.
- by patient: all scans of a patient stay together in test or train.

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

#---------------------------
warnings.filterwarnings("ignore")   # small-data convergence chatter

# About the embeddings model and our process
#
# Each CT was run through Merlin (Stanford, open source), a 3D image model
# trained on abdominal CTs and their radiology reports. For each scan it
# outputs one vector of 2,048 numbers: emb_0 ... emb_2047.
#
# Individual numbers have no meaning but the information theoertice distances do: scans that look alike
# are closer in embedding/latent space. "Alike" includes anatomy and disease, and also acquisition
# (scanner, slice thickness, contrast phase), which is why embeddings are
# useful for auditing data, not only for prediction models.
#
# Ways to use them:
#   - nearest neighbours: find repeat or near-duplicate scans
#   - PCA or UMAP: plot hospitals and see whether they overlap
#   - two-sample tests (MMD, or train a classifier to tell hospital A
#     from B): measure how far apart two hospitals are, against chance
#   - as model inputs, as this script does
#
# Caveat: Merlin crops a fixed box (about 34 x 34 x 48 cm) from the
# centre of the scan, so the ends of long scans are not seen.

# to Merling:
#Input: the full CT volume, resampled to 1.5 × 1.5 × 3 mm. Merlin then takes a fixed 224 × 224 × 160-voxel box from the center of voxel (about 34 × 34 × 48 cm), 
#       so it sees most of the abdomen but can miss the ends of a long scan.
#Output: one 2,048-number vector for that bounding box/volume. One row per scan in embeddings.parquet.

hospital = Path(sys.argv[1] if len(sys.argv) > 1 else "data/practice/hospital_a")
df = (pd.read_parquet(hospital / "features.parquet")
      .merge(pd.read_parquet(hospital / "labels.parquet"), on="case_id")
      .merge(pd.read_parquet(hospital / "embeddings.parquet"), on="case_id"))
X = df.filter(like="emb_").to_numpy()
y = df["max_aortic_diameter_mm"].to_numpy()

patient = df["patient_id"].fillna(df["case_id"]).to_numpy()

#note - nomenclature and terms in/on medical imaging data can be crazy.
# Comparing scans: two scans of the same patient give two vectors, which is why repeat scans show up as near-neighbours.
# What a vector can’t well though is something local, like a small focal change or a single bad slice,
# because it may barely move the vector in its manifold in the lower projectino space. For that type of assessment an dconsidering, the
# teams should work with the source image data directly and not rely upon the embeddings.

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
