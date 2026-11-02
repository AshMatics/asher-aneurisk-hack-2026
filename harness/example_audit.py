"""A deliberately simple example audit that passes the harness.

It returns only summaries: counts, histograms on fixed bins, low-dimensional
embedding moments, and the pieces needed to estimate intracluster correlation
centrally. It finds some problems and misses others. Beating it is the job.

    python harness/harness.py --data path/to/release --audit harness.example_audit:audit
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# Fixed bins and a shared random projection, so every node's summaries line up.
DIAMETER_BINS_MM = list(range(10, 81, 5))
PROJ_DIM = 16
PROJ_SEED = 2026


def _projection(d: int) -> np.ndarray:
    rng = np.random.default_rng(PROJ_SEED)
    return rng.standard_normal((d, PROJ_DIM)) / np.sqrt(PROJ_DIM)


def audit(node: Path) -> dict:
    features = pd.read_parquet(node / "features.parquet")
    labels = pd.read_parquet(node / "labels.parquet")
    emb = pd.read_parquet(node / "embeddings.parquet")
    df = features.merge(labels, on="case_id")

    out: dict = {"n_cases": int(len(df))}

    # Label prior
    out["aaa_counts"] = {str(k): int(v) for k, v in df["aaa"].value_counts().items()}
    hist, _ = np.histogram(df["max_aortic_diameter_mm"].dropna(), bins=DIAMETER_BINS_MM)
    out["diameter_hist"] = {"bins_mm": DIAMETER_BINS_MM, "counts": hist.tolist()}

    # Metadata marginals
    for col in ["sex", "age_band", "scanner_vendor", "contrast_phase", "slice_thickness_class"]:
        if col in df.columns:
            out[f"{col}_counts"] = {str(k): int(v) for k, v in df[col].value_counts().items()}

    # Embedding moments in a shared low-dimensional projection
    emb_cols = [c for c in emb.columns if c.startswith("emb_")]
    z = emb[emb_cols].to_numpy() @ _projection(len(emb_cols))
    out["emb_proj_mean"] = z.mean(axis=0).tolist()
    out["emb_proj_cov"] = np.cov(z, rowvar=False).tolist()

    # Clustering: one-way ANOVA pieces on diameter, grouped by patient
    if "patient_id" in df.columns and df["patient_id"].notna().any():
        g = df.dropna(subset=["patient_id", "max_aortic_diameter_mm"]).groupby("patient_id")["max_aortic_diameter_mm"]
        sizes = g.size()
        grand = df["max_aortic_diameter_mm"].mean()
        ss_between = float((sizes * (g.mean() - grand) ** 2).sum())
        ss_within = float(((df["max_aortic_diameter_mm"] - g.transform("mean")) ** 2).sum())
        out["clusters"] = {
            "n_patients": int(len(sizes)),
            "cluster_size_counts": {str(k): int(v) for k, v in sizes.value_counts().sort_index().items()},
            "ss_between": ss_between,
            "ss_within": ss_within,
        }
    else:
        out["clusters"] = {"patient_id_available": False}

    return out
