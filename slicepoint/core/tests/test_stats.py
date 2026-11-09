"""The statistics: hand-computed values, then the notebook's own implementation on the
practice data (``notebook_reference``)."""

from __future__ import annotations

import math
from typing import Any, Literal

import numpy as np
import pandas as pd
import pytest
from scipy import stats as st

import notebook_reference as nb
from conftest import NOTEBOOK_DIR, PARITY_SITES, PRACTICE_DIR, needs_data
from slicepoint_core import stats as S

# --------------------------------------------------------------------------- hand-computed


def test_wilson_hand_values() -> None:
    z2 = 1.959963984540054**2
    lo, hi = S.wilson_interval(0, 10) or (None, None)
    assert lo == 0.0 and hi == pytest.approx(z2 / (10 + z2), abs=1e-12)  # 0.27753
    lo, hi = S.wilson_interval(10, 10) or (None, None)
    assert hi == 1.0 and lo == pytest.approx(10 / (10 + z2), abs=1e-12)  # 0.72247
    lo, hi = S.wilson_interval(5, 10) or (None, None)
    assert lo == pytest.approx(0.2365931, abs=1e-6) and hi == pytest.approx(0.7634069, abs=1e-6)
    assert S.wilson_interval(0, 0) is None
    with pytest.raises(ValueError):
        S.wilson_interval(3, 2)


@pytest.mark.parametrize("k,n", [(0, 1), (1, 1), (6, 7), (0, 7), (18, 20), (69, 73), (72, 72), (1, 100), (37, 41)])
def test_wilson_matches_scipy(k: int, n: int) -> None:
    lo, hi = S.wilson_interval(k, n) or (math.nan, math.nan)
    assert (lo, hi) == pytest.approx(nb.wilson(k, n), abs=1e-12)


def test_binary_metrics_missing_counts_as_wrong() -> None:
    y = [True, True, True, False, False, False]
    p = [1.0, 0.0, np.nan, 0.0, 1.0, np.nan]
    b = S.binary_metrics(y, p)
    assert (b.n, b.n_aaa, b.tp, b.fn, b.tn, b.fp, b.n_no_answer) == (6, 3, 1, 2, 1, 2, 2)
    assert b.sens == pytest.approx(1 / 3) and b.spec == pytest.approx(1 / 3)
    assert b.bal_acc == pytest.approx(1 / 3) and b.g_mean == pytest.approx(1 / 3)
    a = S.binary_metrics(y, p, missing="drop")
    assert (a.n, a.tp, a.fn, a.tn, a.fp, a.n_no_answer) == (4, 1, 1, 1, 1, 0)
    assert a.sens == 0.5 and a.spec == 0.5


def test_binary_metrics_empty_class() -> None:
    b = S.binary_metrics([False, False], [0.0, 1.0])
    assert b.sens is None and b.sens_lo is None and b.bal_acc is None and b.g_mean is None
    assert b.spec == 0.5


def test_diameter_agreement_hand_values() -> None:
    d = S.diameter_agreement([10, 12, 14, 16], [11, 11, 11, 11])
    # errors -1, 1, 3, 5: bias 2, population SD sqrt(5), MAE 2.5, RMSE 3
    assert d.n == 4 and d.bias == 2.0 and d.mae == 2.5 and d.rmse == 3.0
    assert d.sd == pytest.approx(math.sqrt(5))
    assert d.loa_low == pytest.approx(2 - 1.96 * math.sqrt(5)) and d.loa_high == pytest.approx(2 + 1.96 * math.sqrt(5))
    assert d.within == {2.0: 0.5, 3.0: 0.75}
    assert d.spearman is None  # constant reference: undefined, not NaN
    v0 = d.to_v0()
    assert v0.within_2mm == 0.5 and v0.within_3mm == 0.75


def test_diameter_agreement_population_sd_not_sample() -> None:
    d = S.diameter_agreement([1.0, 3.0, 1.0, 3.0], [0.0, 0.0, 0.0, 0.0])
    assert d.sd == pytest.approx(1.0)  # sample SD would be 1.1547


def test_diameter_agreement_too_few_pairs() -> None:
    d = S.diameter_agreement([1.0, np.nan, 3.0], [1.0, 2.0, np.nan])
    assert d.n == 1 and d.mae is None and d.within[2.0] is None


def test_tvd_hand_values() -> None:
    assert S.tvd({"a": 0.5, "b": 0.5}, {"a": 1.0}) == 0.5
    assert S.tvd({"a": 1.0}, {"b": 1.0}) == 1.0
    assert S.tvd({"a": 0.2, "b": 0.8}, {"a": 0.2, "b": 0.8}) == 0.0
    assert S.category_mix(["x", None, "x", "y"]) == {"MISSING": 0.25, "x": 0.5, "y": 0.25}


def test_wasserstein_shift_hand_value() -> None:
    # W1 between {1,2,3} and {0,0,2,2} is 0.5 + 1/6 + 1/3 = 1.0; reference population SD is 1.
    assert S.wasserstein_shift([1, 2, 3], [0, 0, 2, 2]) == pytest.approx(1.0)
    assert S.wasserstein_shift([1, 2], [3, 3]) is None  # reference SD 0
    assert S.wasserstein_shift([], [1, 2]) is None


def test_permutation_test_deterministic_and_null() -> None:
    rng = np.random.default_rng(1)
    x, y = rng.normal(size=40), rng.normal(size=50)
    a = S.permutation_test(x, y, n_perm=200, seed=3)
    b = S.permutation_test(x, y, n_perm=200, seed=3)
    assert a == b and a.p is not None and a.p > 0.05
    far = S.permutation_test(x + 3, y, n_perm=200, seed=3)
    assert far.p == pytest.approx(1 / 201) and far.sd_units is not None and far.sd_units > 2
    assert S.permutation_test([1, 2, 3], y).p is None  # below min_n


def test_cutoff_range_hand_values() -> None:
    c = S.cutoff_range([25.0, 28.0, 31.0, 35.0, np.nan], [False, False, True, True, True])
    assert c is not None and (c.low, c.high, c.bal_acc_at_best) == (28.5, 31.0, 1.0)
    assert c.midpoint == 29.75
    assert S.cutoff_range([25.0, 28.0], [False, False]) is None


def test_kish_effective_n() -> None:
    assert S.kish_effective_n([0, 0, 1, 1]) == pytest.approx(2.0)  # 2 people x 2 scans
    assert S.kish_effective_n([0, 1, 2, 3]) == pytest.approx(4.0)
    assert S.kish_effective_n(["a", "a", "a", "b"]) == pytest.approx(16 / 10)  # (3+1)^2 / (9+1)
    assert S.kish_effective_n([0, 0, 1, 1], icc=0.0) == pytest.approx(4.0)
    assert S.kish_effective_n([0, 0, 1, 1], icc=0.5) == pytest.approx(4 / 1.5)
    with pytest.raises(ValueError):
        S.kish_effective_n([], icc=1.0)


def test_group_people_by_id_and_embedding() -> None:
    rng = np.random.default_rng(0)
    base = rng.normal(size=(6, 20))
    emb = np.vstack([base, base[0] + 1e-4 * rng.normal(size=20)])  # scan 6 is a twin of scan 0
    pids = ["p0", "p1", "p1", "p3", "p4", "p5", "other"]
    g = S.group_people(emb, pids, [f"c{i}" for i in range(7)])
    assert g.labels[1] == g.labels[2]  # same patient id
    assert g.labels[0] == g.labels[6]  # near-identical embedding, different id
    assert g.n_people == 5
    assert bool(g.is_duplicate[0]) and bool(g.is_duplicate[6]) and bool(g.id_mismatch[6])
    assert g.first_of_each().tolist() == [True, True, False, True, True, True, False]
    no_emb = S.group_people(None, [None, "x", "x"], ["a", "b", "c"])
    assert no_emb.n_people == 2 and not no_emb.is_duplicate.any()


def test_domain_auc_separable() -> None:
    rng = np.random.default_rng(0)
    a, b = rng.normal(size=(40, 10)), rng.normal(size=(40, 10)) + 4
    auc = S.domain_auc(a, b, [f"a{i}" for i in range(40)], [f"b{i}" for i in range(40)], n_pc=5)
    assert auc > 0.95


def test_coverage_reference_share_is_about_five_percent() -> None:
    rng = np.random.default_rng(0)
    ref = rng.normal(size=(100, 16))
    cov = S.fit_reference(ref, n_pc=8)
    # Each reference scan finds itself at distance 0, so its own share is at most 5%.
    assert cov.share_outside(ref) <= 0.05
    assert cov.share_outside(rng.normal(size=(200, 16))) < 0.25


def test_coverage_is_blind_to_magnitude() -> None:
    """Documented property of the notebook's method (cosine kNN in PCA space): moving
    scans radially away from the reference centre does not take them outside coverage.
    Raised as an open question in PARITY.md / README."""
    rng = np.random.default_rng(0)
    ref = rng.normal(size=(100, 16))
    cov = S.fit_reference(ref, n_pc=16)
    far = (ref - ref.mean(axis=0)) * 5 + ref.mean(axis=0)
    assert cov.share_outside(far) <= 0.05


# --------------------------------------------------------------------------- vs the notebook


@pytest.fixture(scope="module")
def nb_frames() -> dict[str, pd.DataFrame]:
    return {s: nb.load_hospital(PRACTICE_DIR / s) for s in ("hospital_a", *PARITY_SITES)}


def _same(core: Any, ref: Any) -> bool:
    if ref is None or (isinstance(ref, float) and math.isnan(ref)):
        return core is None
    return bool(core == pytest.approx(ref, abs=1e-12))


@needs_data
@pytest.mark.parametrize("site", ("hospital_a", *PARITY_SITES))
def test_metrics_match_notebook(site: str, nb_frames: dict[str, pd.DataFrame]) -> None:
    df = nb_frames[site]
    modes: tuple[Literal["wrong", "drop"], ...] = ("wrong", "drop")
    for missing in modes:
        ref = nb.bin_metrics(df, missing)
        core = S.binary_metrics(df["aaa"].to_numpy(bool), df["pred_aaa_f"].to_numpy(float), missing=missing)
        assert all(_same(getattr(core, k), v) for k, v in ref.items()), (missing, core, ref)
    dref = nb.diam_metrics(df)
    dcore = S.diameter_agreement(df["pred_max_diameter_mm"], df["max_aortic_diameter_mm"]).to_v0().model_dump()
    assert all(_same(dcore[k], v) for k, v in dref.items())
    dice = S.dice_summary(df["pred_aorta_dice"])
    assert dice is not None and dice.model_dump(by_alias=True) == pytest.approx(nb.dice_metrics(df), abs=1e-12)
    c_ref, c_core = nb.cutoff_range(df), S.cutoff_range(df["pred_max_diameter_mm"], df["aaa"].to_numpy(bool))
    assert c_ref is not None and c_core is not None
    assert (c_core.low, c_core.high, c_core.bal_acc_at_best) == (c_ref["low"], c_ref["high"], c_ref["bal_acc_at_best"])


@needs_data
@pytest.mark.parametrize("site", PARITY_SITES)
def test_tvd_and_permutation_match_notebook(site: str, nb_frames: dict[str, pd.DataFrame]) -> None:
    monitor = nb.load_monitor(NOTEBOOK_DIR)
    d, r = nb_frames[site], nb_frames["hospital_a"]
    for c in monitor.CAT_COLS:
        assert S.tvd(S.category_mix(d[c]), S.category_mix(r[c])) == pytest.approx(
            float(monitor.tvd(nb.mix(d, c), nb.mix(r, c))), abs=1e-12
        )
    for c in ("aorta_hu_mean", "max_aortic_diameter_mm"):
        ref = nb.w_test(d[c], r[c], n_perm=300)
        core = S.permutation_test(d[c], r[c], n_perm=300)
        assert core.sd_units == pytest.approx(ref["sd_units"], abs=1e-12)
        assert core.p == ref["p"]
        assert core.null95_sd_units == pytest.approx(ref["null95_sd_units"], abs=1e-12)
        assert S.wasserstein_shift(d[c], r[c]) == pytest.approx(ref["sd_units"], abs=1e-12)


@needs_data
@pytest.mark.parametrize("site", PARITY_SITES)
def test_people_domain_auc_and_coverage_match_notebook(site: str, nb_frames: dict[str, pd.DataFrame]) -> None:
    monitor = nb.load_monitor(NOTEBOOK_DIR)
    d, r = nb_frames[site], nb_frames["hospital_a"]
    emb = [str(c) for c in d if str(c).startswith("emb_")]
    lab_d, _, _ = nb.patient_groups(d, emb)
    lab_r, _, _ = nb.patient_groups(r, emb)
    g_d = S.group_people(d[emb].to_numpy(), d["patient_id"].to_numpy(object), d["case_id"].to_numpy(object))
    assert _partition(g_d.labels) == _partition(lab_d)

    ga, gb = np.array([f"ref_{i}" for i in lab_r]), np.array([f"new_{i}" for i in lab_d])
    assert S.domain_auc(r[emb].to_numpy(), d[emb].to_numpy(), ga, gb) == pytest.approx(
        nb.domain_auc(r[emb].to_numpy(), d[emb].to_numpy(), ga, gb), abs=1e-12
    )

    prof = monitor.fit_reference(r)
    Xn = prof["pca"].transform(prof["scaler"].transform(d[emb].to_numpy()))
    dist, _ = prof["nn"].kneighbors(Xn, n_neighbors=prof["k"])
    cov = S.fit_reference(r[emb].to_numpy())
    assert cov.dist_thr == pytest.approx(float(prof["dist_thr"]), rel=1e-5)
    assert cov.mean_knn_distance(d[emb].to_numpy()) == pytest.approx(dist.mean(axis=1), abs=1e-5)
    assert cov.share_outside(d[emb].to_numpy()) == float((dist.mean(axis=1) > prof["dist_thr"]).mean())


def _partition(labels: Any) -> set[frozenset[int]]:
    groups: dict[Any, set[int]] = {}
    for i, lab in enumerate(np.asarray(labels).tolist()):
        groups.setdefault(lab, set()).add(i)
    return {frozenset(v) for v in groups.values()}


def test_fisher_exact() -> None:
    assert S.fisher_exact_p(20, 80, 9, 100) == pytest.approx(float(st.fisher_exact([[20, 60], [9, 91]])[1]))
