"""Pure statistical building blocks, ported from ``test_your_hospital.ipynb`` and
``monitor.py``.

Each function is deterministic given its inputs (random procedures take an explicit
``seed``) and has no IO. Line references are to the notebook as extracted in
``slicepoint/docs/data-contract-inventory.md``.

Standard deviation: SlicePoint uses the **population** SD (``ddof=0``) throughout, as the
ADR and the POC spec say. The notebook mixed the two: numpy ``e.std()`` (population) for
limits of agreement and the Wasserstein shift, but pandas ``.std()`` (sample) for the
measurement-outlier threshold. On the practice data the choice changes no outcome; see
``PARITY.md``.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy import stats as st
from scipy.sparse.csgraph import connected_components
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold, KFold, StratifiedGroupKFold, cross_val_predict, cross_val_score
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from slicepoint_schemas.assessment import DiameterAgreement as DiameterAgreementModel
from slicepoint_schemas.assessment import ToleranceRole, WithinTolerance
from slicepoint_schemas.legacy import BinMetricsV0, DiameterMetricsV0, DiceMetricsV0

FloatArray = npt.NDArray[np.floating]
BoolArray = npt.NDArray[np.bool_]
IntArray = npt.NDArray[np.intp]

MISSING = "MISSING"
"""Category used for nulls in category mixes (``fillna("MISSING")`` in the notebook)."""

_Z95 = 1.959963984540054  # scipy.stats.norm.ppf(0.975)


def _f(x: float) -> float | None:
    """NaN/inf -> None, else a plain float."""
    return None if not math.isfinite(x) else float(x)


# --------------------------------------------------------------------------- Wilson


def wilson_interval(k: int, n: int, z: float = _Z95) -> tuple[float, float] | None:
    """95% Wilson score interval for ``k`` successes out of ``n`` (no continuity correction).

    Same as ``scipy.stats.binomtest(k, n).proportion_ci(method="wilson")`` used by the
    notebook (ipynb ``wilson``). Returns ``None`` when ``n == 0`` (the notebook's NaN).
    """
    if n < 0 or k < 0 or k > n:
        raise ValueError(f"need 0 <= k <= n, got k={k}, n={n}")
    if n == 0:
        return None
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    lo, hi = center - half, center + half
    # The bounds are exactly 0 / 1 at k = 0 / k = n; remove rounding residue.
    if k == 0:
        lo = 0.0
    if k == n:
        hi = 1.0
    return max(0.0, lo), min(1.0, hi)


# --------------------------------------------------------------------------- binary metrics


def binary_metrics(
    y_true: npt.ArrayLike, y_pred: npt.ArrayLike, *, missing: Literal["wrong", "drop"] = "wrong"
) -> BinMetricsV0:
    """Sensitivity / specificity of a yes/no call (ipynb ``bin_metrics``).

    ``y_pred`` is 1.0 / 0.0, with NaN for "no answer". With ``missing="wrong"`` a missing
    answer counts as wrong for both classes (a missed aneurysm or a false alarm); with
    ``"drop"`` the no-answer cases are removed first (the "when answered" variant).
    """
    y = np.asarray(y_true, dtype=bool)
    p = np.asarray(y_pred, dtype=float)
    if y.shape != p.shape:
        raise ValueError("y_true and y_pred must have the same shape")
    n_no_answer = int(np.isnan(p).sum())
    if missing == "drop":
        keep = ~np.isnan(p)
        y, p = y[keep], p[keep]
        n_no_answer = 0
    pos, neg = int(y.sum()), int((~y).sum())
    tp = int((y & (p == 1)).sum())
    tn = int((~y & (p == 0)).sum())
    sens = tp / pos if pos else None
    spec = tn / neg if neg else None
    s_ci, p_ci = wilson_interval(tp, pos), wilson_interval(tn, neg)
    return BinMetricsV0(
        n=len(y),
        n_aaa=pos,
        n_not_aaa=neg,
        tp=tp,
        fn=pos - tp,
        tn=tn,
        fp=neg - tn,
        n_no_answer=n_no_answer,
        sens=sens,
        sens_lo=s_ci[0] if s_ci else None,
        sens_hi=s_ci[1] if s_ci else None,
        spec=spec,
        spec_lo=p_ci[0] if p_ci else None,
        spec_hi=p_ci[1] if p_ci else None,
        bal_acc=(sens + spec) / 2 if sens is not None and spec is not None else None,
        g_mean=float(np.sqrt(sens * spec)) if sens is not None and spec is not None else None,
    )


# --------------------------------------------------------------------------- diameter agreement


@dataclass(frozen=True)
class DiameterAgreement:
    """Bland-Altman style agreement between a predicted and a reference measurement.

    ``error = predicted - reference``. ``sd`` is the population SD of the error, and the
    95% limits of agreement are ``bias +/- 1.96 sd``. ``within`` maps each tolerance (mm)
    to the share of cases with ``|error| <= tolerance``. All floats are ``None`` when
    fewer than ``min_n`` pairs exist (the notebook's NaN block).
    """

    n: int
    mae: float | None
    rmse: float | None
    bias: float | None
    sd: float | None
    loa_low: float | None
    loa_high: float | None
    within: Mapping[float, float | None]
    spearman: float | None
    min_n: int = 3

    def to_model(self, ba_tolerance_mm: float, size_tolerance_mm: float) -> DiameterAgreementModel:
        """The profile-driven contract block used in ``AssessmentResult``."""
        return DiameterAgreementModel(
            n=self.n,
            min_n=self.min_n,
            mae=self.mae,
            rmse=self.rmse,
            bias=self.bias,
            sd=self.sd,
            loa_low=self.loa_low,
            loa_high=self.loa_high,
            within_tolerance=(
                WithinTolerance(role=ToleranceRole.BLAND_ALTMAN, tolerance_mm=ba_tolerance_mm,
                                share=self.within.get(ba_tolerance_mm)),
                WithinTolerance(role=ToleranceRole.SIZE, tolerance_mm=size_tolerance_mm,
                                share=self.within.get(size_tolerance_mm)),
            ),
            spearman=self.spearman,
        )

    def to_v0(self, ba_tolerance_mm: float = 2.0, size_tolerance_mm: float = 3.0) -> DiameterMetricsV0:
        """The POC ``performance.diameter`` block (``within_2mm`` / ``within_3mm``); legacy only."""
        return DiameterMetricsV0(
            n=self.n,
            mae=self.mae,
            rmse=self.rmse,
            bias=self.bias,
            loa_low=self.loa_low,
            loa_high=self.loa_high,
            within_2mm=self.within.get(ba_tolerance_mm),
            within_3mm=self.within.get(size_tolerance_mm),
            spearman=self.spearman,
        )


def diameter_agreement(
    predicted: npt.ArrayLike,
    reference: npt.ArrayLike,
    *,
    tolerances_mm: Sequence[float] = (2.0, 3.0),
    min_n: int = 3,
) -> DiameterAgreement:
    """Agreement on the pairs where both values are present (ipynb ``diam_metrics``)."""
    pred = np.asarray(predicted, dtype=float)
    ref = np.asarray(reference, dtype=float)
    m = ~np.isnan(pred) & ~np.isnan(ref)
    e = pred[m] - ref[m]
    n = len(e)
    if n < min_n:
        return DiameterAgreement(n, None, None, None, None, None, None, {t: None for t in tolerances_mm}, None, min_n)
    bias = float(e.mean())
    sd = float(e.std(ddof=0))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", st.ConstantInputWarning)  # undefined rho -> None
        rho = _f(float(st.spearmanr(pred[m], ref[m])[0]))
    return DiameterAgreement(
        n=n,
        mae=float(np.abs(e).mean()),
        rmse=float(np.sqrt((e**2).mean())),
        bias=bias,
        sd=sd,
        loa_low=bias - 1.96 * sd,
        loa_high=bias + 1.96 * sd,
        within={t: float((np.abs(e) <= t).mean()) for t in tolerances_mm},
        spearman=rho,
        min_n=min_n,
    )


def dice_summary(dice: npt.ArrayLike, *, line: float = 0.90, secondary_line: float = 0.85) -> DiceMetricsV0 | None:
    """Median, mean and share below the Dice lines (ipynb ``dice_metrics``). ``None`` if empty."""
    x = np.asarray(dice, dtype=float)
    x = x[~np.isnan(x)]
    if not len(x):
        return None
    return DiceMetricsV0.model_validate(
        {
            "median": float(np.median(x)),
            "mean": float(x.mean()),
            "share_below_0.90": float((x < line).mean()),
            "share_below_0.85": float((x < secondary_line).mean()),
        }
    )


# --------------------------------------------------------------------------- category mix


def category_mix(values: pd.Series | Sequence[object]) -> dict[str, float]:
    """Share of each category, with nulls counted as ``"MISSING"`` (notebook ``mix``).

    Keys are sorted, matching ``value_counts(normalize=True).sort_index()``.
    """
    s = pd.Series(values, dtype=object)
    s = s.where(s.notna(), MISSING).astype(str)
    vc = s.value_counts(normalize=True).sort_index()
    return {str(k): float(v) for k, v in vc.items()}


def tvd(p: Mapping[str, float], q: Mapping[str, float]) -> float:
    """Total variation distance ``0.5 * sum |p - q|`` over the union of categories
    (monitor ``tvd``). 0 = identical mixes, 1 = nothing in common."""
    keys = set(p) | set(q)
    return 0.5 * float(sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys))


# --------------------------------------------------------------------------- distribution shift


def _finite(x: npt.ArrayLike) -> FloatArray:
    a = np.asarray(x, dtype=float)
    return a[~np.isnan(a)]


def wasserstein_shift(x: npt.ArrayLike, reference: npt.ArrayLike) -> float | None:
    """1-D Wasserstein distance between ``x`` and ``reference``, in units of the
    reference's population SD (monitor triggers; ``sd_units`` in ``w_test``).

    ``None`` if either side is empty or the reference SD is 0.
    """
    a, r = _finite(x), _finite(reference)
    if not len(a) or not len(r):
        return None
    sd = float(np.std(r))
    if sd == 0:
        return None
    return float(st.wasserstein_distance(a, r)) / sd


@dataclass(frozen=True)
class PermutationTest:
    """Result of :func:`permutation_test` (notebook ``w_test``)."""

    sd_units: float | None
    p: float | None
    median_diff: float | None
    null95_sd_units: float | None
    n: int
    n_reference: int


def permutation_test(
    x: npt.ArrayLike, reference: npt.ArrayLike, *, n_perm: int = 1000, seed: int = 0, min_n: int = 5
) -> PermutationTest:
    """Permutation test of the Wasserstein distance between ``x`` and ``reference``.

    Ported exactly from the notebook's ``w_test``: the pooled values are shuffled in
    place ``n_perm`` times with ``numpy.random.default_rng(seed)``, and
    ``p = (1 + #{null >= observed}) / (n_perm + 1)``. Shift and null 95th percentile
    are in reference-SD units (population SD). All ``None`` below ``min_n`` per side.
    """
    a, r = _finite(x), _finite(reference)
    if len(a) < min_n or len(r) < min_n:
        return PermutationTest(None, None, None, None, len(a), len(r))
    rng = np.random.default_rng(seed)
    obs = float(st.wasserstein_distance(a, r))
    pool = np.concatenate([a, r])
    n = len(a)
    null = np.empty(n_perm)
    for i in range(n_perm):
        rng.shuffle(pool)
        null[i] = st.wasserstein_distance(pool[:n], pool[n:])
    sd = float(np.std(r))
    return PermutationTest(
        sd_units=_f(obs / sd) if sd else None,
        p=float((1 + (null >= obs).sum()) / (n_perm + 1)),
        median_diff=float(np.median(a) - np.median(r)),
        null95_sd_units=_f(float(np.percentile(null, 95)) / sd) if sd else None,
        n=len(a),
        n_reference=len(r),
    )


def fisher_exact_p(k1: int, n1: int, k2: int, n2: int) -> float:
    """Two-sided Fisher exact p for ``k1/n1`` vs ``k2/n2`` (AAA prevalence, cell 19)."""
    _, p = st.fisher_exact([[k1, n1 - k1], [k2, n2 - k2]])
    return float(p)


# --------------------------------------------------------------------------- embeddings


def domain_auc(
    reference: FloatArray,
    candidate: FloatArray,
    reference_groups: Sequence[Hashable] | npt.NDArray[np.object_],
    candidate_groups: Sequence[Hashable] | npt.NDArray[np.object_],
    *,
    n_pc: int = 32,
    n_splits: int = 5,
    seed: int = 0,
) -> float:
    """Cross-validated ROC AUC of a classifier telling candidate scans from reference
    scans (notebook ``domain_auc``). 0.5 = indistinguishable.

    Standardise the pooled embeddings, PCA to ``min(n_pc, n - 2, dim)`` components,
    then logistic regression under ``StratifiedGroupKFold`` so scans of one person never
    straddle train and test. Groups must already be distinct between the two sets.
    """
    X = np.vstack([reference, candidate])
    y = np.r_[np.zeros(len(reference)), np.ones(len(candidate))]
    g = np.r_[np.asarray(reference_groups, dtype=object), np.asarray(candidate_groups, dtype=object)]
    Z = StandardScaler().fit_transform(X)
    Z = PCA(min(n_pc, len(X) - 2, Z.shape[1]), random_state=seed).fit_transform(Z)
    cv = StratifiedGroupKFold(n_splits, shuffle=True, random_state=seed)
    scores = cross_val_score(LogisticRegression(max_iter=2000), Z, y, groups=g, cv=cv, scoring="roc_auc")
    return float(np.mean(scores))


@dataclass(frozen=True)
class KnnCoverage:
    """What "normal" looks like in embedding space (monitor ``fit_reference``).

    Note: cosine distance ignores magnitude, so scans displaced radially from the
    reference centre (in standardised PCA space) still count as covered. Ported as is.

    Reference embeddings are standardised, projected to PCA space, and each candidate
    scan's mean cosine distance to its ``k`` nearest reference scans is compared with
    ``dist_thr``, the ``percentile``-th percentile of the same statistic within the
    reference (leave-self-out). By construction about 5% of reference scans fall outside.

    Only arrays are stored, so the state serialises to ``npz`` and the transform is
    plain numpy (identical maths to the sklearn objects that fitted it).
    """

    scaler_mean: FloatArray
    scaler_scale: FloatArray
    pca_mean: FloatArray
    pca_components: FloatArray
    reference_points: FloatArray
    k: int
    dist_thr: float
    percentile: float

    def project(self, embeddings: FloatArray) -> FloatArray:
        Z = (np.asarray(embeddings) - self.scaler_mean) / self.scaler_scale
        out: FloatArray = (Z - self.pca_mean) @ self.pca_components.T
        return out

    def mean_knn_distance(self, embeddings: FloatArray) -> FloatArray:
        """Mean cosine distance to the ``k`` nearest reference points (self included if
        ``embeddings`` is the reference itself)."""
        d = _cosine_distances(self.project(embeddings), self.reference_points)
        d.sort(axis=1)
        out: FloatArray = d[:, : self.k].mean(axis=1)
        return out

    def share_outside(self, embeddings: FloatArray) -> float:
        """Share of scans whose mean kNN distance exceeds ``dist_thr``."""
        return float((self.mean_knn_distance(embeddings) > self.dist_thr).mean())


def _cosine_distances(a: FloatArray, b: FloatArray) -> FloatArray:
    an = a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), np.finfo(float).tiny)
    bn = b / np.maximum(np.linalg.norm(b, axis=1, keepdims=True), np.finfo(float).tiny)
    d: FloatArray = 1.0 - an @ bn.T
    np.clip(d, 0.0, 2.0, out=d)
    return d


def fit_reference(
    embeddings: FloatArray, *, n_pc: int = 32, k: int = 5, percentile: float = 95.0, seed: int = 0
) -> KnnCoverage:
    """Fit :class:`KnnCoverage` on reference embeddings (monitor ``fit_reference``)."""
    E = np.asarray(embeddings)
    scaler = StandardScaler().fit(E)
    pca = PCA(min(n_pc, len(E) - 1, E.shape[1]), random_state=seed).fit(scaler.transform(E))
    Xr = pca.transform(scaler.transform(E))
    d = _cosine_distances(Xr, Xr)
    d.sort(axis=1)
    within = d[:, 1 : k + 1].mean(axis=1)  # leave self (distance 0) out
    return KnnCoverage(
        scaler_mean=np.asarray(scaler.mean_),
        scaler_scale=np.asarray(scaler.scale_),
        pca_mean=np.asarray(pca.mean_),
        pca_components=np.asarray(pca.components_),
        reference_points=np.asarray(Xr),
        k=k,
        dist_thr=float(np.percentile(within, percentile)),
        percentile=percentile,
    )


# --------------------------------------------------------------------------- people


@dataclass(frozen=True)
class PersonGrouping:
    """Real-person grouping of scans (notebook ``patient_groups``, cell 11).

    * ``labels``: connected-component label per scan, over "same patient id OR cosine
      similarity of standardised embeddings > threshold". Label numbers are arbitrary.
    * ``twin`` / ``twin_similarity``: each scan's most similar other scan.
    * ``is_duplicate``: ``twin_similarity > threshold``.
    * ``id_mismatch``: duplicates whose twin carries a different patient id.
    """

    labels: IntArray
    twin: IntArray
    twin_similarity: FloatArray
    is_duplicate: BoolArray
    id_mismatch: BoolArray
    threshold: float

    @property
    def n_people(self) -> int:
        return len(set(self.labels.tolist()))

    @property
    def share_with_near_duplicate(self) -> float:
        return float(self.is_duplicate.mean()) if len(self.is_duplicate) else 0.0

    def first_of_each(self) -> BoolArray:
        """Mask keeping the first scan of each person, in row order (the notebook's
        ``keep_D``: "one scan per real patient")."""
        keep: BoolArray = ~pd.Series(self.labels).duplicated().to_numpy()
        return keep


def group_people(
    embeddings: FloatArray | None,
    patient_ids: Sequence[object] | npt.NDArray[np.object_],
    case_ids: Sequence[str] | npt.NDArray[np.object_],
    *,
    threshold: float = 0.95,
) -> PersonGrouping:
    """Group scans of the same real person. A null patient id falls back to the case id.

    Without embeddings only patient ids are used, and no scan is a near-duplicate.
    """
    cid = np.asarray(case_ids, dtype=object)
    raw = pd.Series(np.asarray(patient_ids, dtype=object))
    pid = raw.where(raw.notna(), pd.Series(cid)).astype(str).to_numpy()
    n = len(pid)
    same_pid = pid[:, None] == pid[None, :]
    if embeddings is None or n < 2:
        _, lab = connected_components(same_pid, directed=False)
        zeros = np.zeros(n, dtype=bool)
        return PersonGrouping(
            np.asarray(lab, dtype=np.intp), np.arange(n, dtype=np.intp), np.full(n, np.nan), zeros, zeros.copy(), threshold
        )
    Z = StandardScaler().fit_transform(np.asarray(embeddings))
    Z = Z / np.maximum(np.linalg.norm(Z, axis=1, keepdims=True), 1e-9)
    S = Z @ Z.T
    np.fill_diagonal(S, -1)
    _, lab = connected_components((S > threshold) | same_pid, directed=False)
    twin = S.argmax(axis=1)
    twin_sim = S.max(axis=1)
    is_dup = twin_sim > threshold
    return PersonGrouping(
        labels=np.asarray(lab, dtype=np.intp),
        twin=np.asarray(twin, dtype=np.intp),
        twin_similarity=np.asarray(twin_sim, dtype=float),
        is_duplicate=np.asarray(is_dup, dtype=bool),
        id_mismatch=np.asarray(is_dup & (pid != pid[twin]), dtype=bool),
        threshold=threshold,
    )


def kish_effective_n(group_labels: Sequence[Hashable] | npt.NDArray[np.generic], *, icc: float = 1.0) -> float:
    """Effective sample size of ``n`` scans clustered by person (Kish design effect).

    ``deff = 1 + (m_w - 1) * icc`` with ``m_w = sum(m_g^2) / sum(m_g)``, Kish's
    size-weighted mean cluster size for unequal clusters, and ``n_eff = n / deff``.

    With ``icc = 1`` (repeat scans of one person carry no extra information, the
    conservative default) this is ``(sum m_g)^2 / sum m_g^2``, which equals the number
    of people when every person has the same number of scans and is below it otherwise.
    With ``icc = 0`` it is ``n``. Raises on an empty input.
    """
    if not 0.0 <= icc <= 1.0:
        raise ValueError("icc must be in [0, 1]")
    sizes = np.asarray(pd.Series(np.asarray(group_labels, dtype=object)).value_counts().to_numpy(), dtype=float)
    n = float(sizes.sum())
    if n == 0:
        raise ValueError("no cases")
    m_w = float((sizes**2).sum()) / n
    return n / (1.0 + (m_w - 1.0) * icc)


# --------------------------------------------------------------------------- cutoff


@dataclass(frozen=True)
class CutoffRange:
    """Thresholds on the model's diameter that best reproduce the labels (cell 24)."""

    low: float
    high: float
    bal_acc_at_best: float

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2


def cutoff_grid(low: float = 20.0, high: float = 40.0, step: float = 0.5) -> FloatArray:
    """``np.arange(low, high + 0.01, step)``, the notebook's grid (20-40 mm, 0.5 mm)."""
    out: FloatArray = np.arange(low, high + 0.01, step)
    return out


def cutoff_range(
    predicted_mm: npt.ArrayLike, labels: npt.ArrayLike, grid: FloatArray | None = None
) -> CutoffRange | None:
    """Range of grid thresholds maximising balanced accuracy of ``predicted >= t`` vs
    the labels, over cases with a prediction. ``None`` if a class is empty."""
    g = cutoff_grid() if grid is None else np.asarray(grid, dtype=float)
    pred = np.asarray(predicted_mm, dtype=float)
    y_all = np.asarray(labels, dtype=bool)
    m = ~np.isnan(pred)
    y, d = y_all[m], pred[m]
    if y.sum() == 0 or (~y).sum() == 0:
        return None
    sc = np.array([(((d >= t) & y).sum() / y.sum() + ((d < t) & ~y).sum() / (~y).sum()) / 2 for t in g])
    best = g[sc >= sc.max() - 1e-9]
    return CutoffRange(low=float(best.min()), high=float(best.max()), bal_acc_at_best=float(sc.max()))


# --------------------------------------------------------------------------- probes


@dataclass(frozen=True)
class ProbeScore:
    balanced_accuracy: float
    chance: float

    @property
    def above_chance(self) -> float:
        return self.balanced_accuracy - self.chance


def embedding_probe(
    embeddings: FloatArray,
    target: Sequence[object] | pd.Series,
    groups: npt.NDArray[np.generic],
    *,
    n_pc: int = 32,
    n_splits: int = 5,
    seed: int = 0,
    min_class_n: int = 10,
    min_rows: int = 25,
) -> ProbeScore | None:
    """How well a variable can be read back from the embeddings (cell 26 ``predictability``).

    PCA to ``max(2, min(n_pc, n - 3))`` components on the site's own embeddings, then a
    grouped, stratified cross-validated logistic regression. Classes with fewer than
    ``min_class_n`` scans are dropped. ``None`` if too few rows or classes remain, or if
    the cross-validation cannot be built.
    """
    E = np.asarray(embeddings)
    Zs = StandardScaler().fit_transform(E)
    nc = int(max(2, min(n_pc, len(E) - 3)))
    P = PCA(nc, random_state=seed).fit_transform(Zs)
    y = pd.Series(target, dtype=object).reset_index(drop=True)
    y = y.where(y.notna(), MISSING).astype(str)
    y = y.where(y.map(y.value_counts()) >= min_class_n)
    m = y.notna().to_numpy()
    if m.sum() < min_rows or y[m].nunique() < 2:
        return None
    cv = StratifiedGroupKFold(n_splits, shuffle=True, random_state=seed)
    try:
        acc = cross_val_score(
            LogisticRegression(max_iter=2000), P[m], y[m], groups=np.asarray(groups)[m], cv=cv, scoring="balanced_accuracy"
        ).mean()
    except Exception:  # noqa: BLE001 - the notebook skips a probe whose CV cannot be built
        return None
    return ProbeScore(balanced_accuracy=float(acc), chance=float(1 / y[m].nunique()))


@dataclass(frozen=True)
class LeakageResult:
    random_split_mae: float
    by_person_mae: float
    random_split_r2: float
    by_person_r2: float

    @property
    def gap(self) -> float:
        return self.by_person_mae - self.random_split_mae

    @property
    def gap_ratio(self) -> float:
        """``gap / by_person_mae``; the notebook flags red when this exceeds 0.15."""
        return self.gap / self.by_person_mae if self.by_person_mae else float("nan")


def leakage_test(
    embeddings: FloatArray,
    target: npt.ArrayLike,
    person_labels: npt.NDArray[np.generic],
    *,
    n_splits: int = 5,
    seed: int = 0,
    n_pc: int = 32,
    max_iter: int = 3000,
) -> LeakageResult | None:
    """Random-split vs by-person cross-validated MAE of a small MLP predicting ``target``
    from embeddings (cell 13). If the random split is much better, scans of the same
    person leak between folds.

    Seeded exactly like the notebook (``KFold(shuffle, random_state=seed)``, PCA and MLP
    ``random_state=seed``). The MLP is still sensitive to the BLAS build, so MAE values
    can differ in the second decimal across machines (see ``PARITY.md``). ``None`` when
    there are fewer than ``n_splits`` people. The notebook's third split ("by listed
    patient_id") is not used by any rule and is not computed.
    """
    X = np.asarray(embeddings)
    y = np.asarray(target, dtype=float)
    ok = ~np.isnan(y)
    g = np.asarray(person_labels)[ok]
    if len(set(g.tolist())) < n_splits:
        return None
    n = len(X)
    nc = int(max(2, min(n_pc, n * 0.8 - 2)))

    def model() -> object:
        return make_pipeline(
            StandardScaler(),
            PCA(nc, random_state=seed),
            MLPRegressor(hidden_layer_sizes=(64, 32), alpha=1e-3, max_iter=max_iter, random_state=seed),
        )

    yy = y[ok]
    pr_rand = cross_val_predict(model(), X[ok], yy, cv=KFold(n_splits, shuffle=True, random_state=seed))
    pr_grp = cross_val_predict(model(), X[ok], yy, cv=GroupKFold(n_splits), groups=g)
    sst = float(np.sum((yy - yy.mean()) ** 2))

    def r2(pr: FloatArray) -> float:
        return 1 - float(np.sum((pr - yy) ** 2)) / sst if sst else float("nan")

    return LeakageResult(
        random_split_mae=float(np.mean(np.abs(pr_rand - yy))),
        by_person_mae=float(np.mean(np.abs(pr_grp - yy))),
        random_split_r2=r2(pr_rand),
        by_person_r2=r2(pr_grp),
    )
