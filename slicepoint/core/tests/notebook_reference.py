"""The notebook's own implementations, copied from ``test_your_hospital.ipynb`` (via the
plain-Python extraction) with type annotations added and nothing else changed. They are
the oracle the ported statistics are tested against. ``monitor.py`` is imported from the
repo as is.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd
import scipy.stats as st
from scipy.sparse.csgraph import connected_components
from scipy.stats import binomtest, spearmanr
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedGroupKFold, cross_val_score
from sklearn.preprocessing import StandardScaler

SIM_DUP = 0.95


def load_monitor(notebook_dir: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("slicepoint_monitor", notebook_dir / "monitor.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def to_float(s: pd.Series) -> pd.Series:
    return s.map(lambda v: np.nan if pd.isna(v) else float(bool(v))).astype(float)


def mix(df: pd.DataFrame, col: str) -> pd.Series:
    return df[col].fillna("MISSING").astype(str).value_counts(normalize=True).sort_index()


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return np.nan, np.nan
    ci = binomtest(int(k), int(n)).proportion_ci(method="wilson")
    return float(ci.low), float(ci.high)


def bin_metrics(g: pd.DataFrame, missing: str = "wrong") -> dict[str, Any]:
    y = g["aaa"].to_numpy(bool); p = g["pred_aaa_f"].to_numpy(float)
    if missing == "drop":
        keep = ~np.isnan(p); y, p = y[keep], p[keep]
    pos, neg = int(y.sum()), int((~y).sum())
    tp = int((y & (p == 1)).sum()); tn = int((~y & (p == 0)).sum())
    sens = tp / pos if pos else np.nan; spec = tn / neg if neg else np.nan
    (slo, shi), (plo, phi) = wilson(tp, pos), wilson(tn, neg)
    ok_ = not (np.isnan(sens) or np.isnan(spec))
    return {"n": int(len(y)), "n_aaa": pos, "n_not_aaa": neg, "tp": tp, "fn": pos - tp, "tn": tn, "fp": neg - tn,
            "n_no_answer": int(np.isnan(g["pred_aaa_f"].to_numpy(float)).sum()) if missing == "wrong" else 0,
            "sens": sens, "sens_lo": slo, "sens_hi": shi, "spec": spec, "spec_lo": plo, "spec_hi": phi,
            "bal_acc": (sens + spec) / 2 if ok_ else np.nan, "g_mean": float(np.sqrt(sens * spec)) if ok_ else np.nan}


def diam_metrics(g: pd.DataFrame) -> dict[str, Any]:
    m = g["pred_max_diameter_mm"].notna() & g["max_aortic_diameter_mm"].notna()
    e = (g.loc[m, "pred_max_diameter_mm"] - g.loc[m, "max_aortic_diameter_mm"]).to_numpy(float)
    if len(e) < 3:
        return {"n": int(len(e)), "mae": np.nan, "rmse": np.nan, "bias": np.nan, "loa_low": np.nan, "loa_high": np.nan,
                "within_2mm": np.nan, "within_3mm": np.nan, "spearman": np.nan}
    return {"n": int(len(e)), "mae": float(np.abs(e).mean()), "rmse": float(np.sqrt((e ** 2).mean())), "bias": float(e.mean()),
            "loa_low": float(e.mean() - 1.96 * e.std()), "loa_high": float(e.mean() + 1.96 * e.std()),
            "within_2mm": float((np.abs(e) <= 2).mean()), "within_3mm": float((np.abs(e) <= 3).mean()),
            "spearman": float(spearmanr(g.loc[m, "pred_max_diameter_mm"], g.loc[m, "max_aortic_diameter_mm"])[0])}


def dice_metrics(g: pd.DataFrame) -> dict[str, float]:
    x = g["pred_aorta_dice"].dropna() if "pred_aorta_dice" in g else pd.Series(dtype=float)
    if not len(x):
        return {}
    return {"median": float(x.median()), "mean": float(x.mean()), "share_below_0.90": float((x < 0.90).mean()),
            "share_below_0.85": float((x < 0.85).mean())}


def w_test(x: Any, y: Any, n_perm: int = 1000, seed: int = 0) -> dict[str, float]:
    x, y = np.asarray(x, float), np.asarray(y, float)
    x, y = x[~np.isnan(x)], y[~np.isnan(y)]
    if len(x) < 5 or len(y) < 5:
        return {"sd_units": np.nan, "p": np.nan, "median_diff": np.nan, "null95_sd_units": np.nan}
    rng = np.random.default_rng(seed)
    obs = st.wasserstein_distance(x, y); pool = np.concatenate([x, y]); n = len(x)
    null = np.empty(n_perm)
    for i in range(n_perm):
        rng.shuffle(pool); null[i] = st.wasserstein_distance(pool[:n], pool[n:])
    return {"sd_units": obs / np.std(y), "p": (1 + (null >= obs).sum()) / (n_perm + 1),
            "median_diff": np.median(x) - np.median(y), "null95_sd_units": np.percentile(null, 95) / np.std(y)}


def domain_auc(Xa: Any, Xb: Any, ga: Any, gb: Any, n_pc: int = 32) -> float:
    X = np.vstack([Xa, Xb]); y = np.r_[np.zeros(len(Xa)), np.ones(len(Xb))]; g = np.r_[ga, gb]
    Zp = StandardScaler().fit_transform(X)
    Zp = PCA(min(n_pc, len(X) - 2, Zp.shape[1]), random_state=0).fit_transform(Zp)
    cv = StratifiedGroupKFold(5, shuffle=True, random_state=0)
    return float(cross_val_score(LogisticRegression(max_iter=2000), Zp, y, groups=g, cv=cv, scoring="roc_auc").mean())


def patient_groups(df: pd.DataFrame, emb_cols: list[str], thresh: float = SIM_DUP) -> tuple[Any, Any, Any]:
    Z = StandardScaler().fit_transform(df[emb_cols].to_numpy())
    Z = Z / np.maximum(np.linalg.norm(Z, axis=1, keepdims=True), 1e-9)
    S = Z @ Z.T
    np.fill_diagonal(S, -1)
    pid = (df["patient_id"].fillna(df["case_id"]) if "patient_id" in df else df["case_id"]).astype(str).to_numpy()
    same_pid = pid[:, None] == pid[None, :]
    _, lab = connected_components((S > thresh) | same_pid, directed=False)
    return lab, S, pid


def cutoff_range(df: pd.DataFrame, grid: Any = None) -> dict[str, float] | None:
    grid = np.arange(20, 40.01, 0.5) if grid is None else grid
    m = df["pred_max_diameter_mm"].notna()
    y = df.loc[m, "aaa"].to_numpy(bool); dd = df.loc[m, "pred_max_diameter_mm"].to_numpy(float)
    if y.sum() == 0 or (~y).sum() == 0:
        return None
    sc = np.array([(((dd >= t) & y).sum() / y.sum() + ((dd < t) & ~y).sum() / (~y).sum()) / 2 for t in grid])
    okg = grid[sc >= sc.max() - 1e-9]
    return {"low": float(okg.min()), "high": float(okg.max()), "bal_acc_at_best": float(sc.max())}


def load_hospital(folder: Path) -> pd.DataFrame:
    """The notebook's ``load_hospital`` merge (without the file report)."""
    tabs = {t: pd.read_parquet(folder / f"{t}.parquet") for t in ["features", "labels", "predictions", "embeddings"]}
    df = (tabs["features"].drop_duplicates("case_id")
          .merge(tabs["labels"].drop_duplicates("case_id"), on="case_id")
          .merge(tabs["predictions"].drop_duplicates("case_id"), on="case_id", how="left")
          .merge(tabs["embeddings"].drop_duplicates("case_id"), on="case_id"))
    df["aaa"] = df["aaa"].astype(bool)
    df["pred_aaa_f"] = to_float(df["pred_aaa"])
    out: pd.DataFrame = df.reset_index(drop=True)
    return out
