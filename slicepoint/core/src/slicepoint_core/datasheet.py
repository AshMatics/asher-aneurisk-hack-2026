"""Compare a site's data with a vendor datasheet (summary statistics only, no vendor rows).

For each variable the datasheet discloses and the site has, two questions are asked:

* **Coverage**: is the site inside what the model saw? The share of the site's scans that
  fall outside the disclosed range, or in categories the datasheet does not list. This is
  the safety question, and a site that is a narrower slice of a broad datasheet passes it.
* **Equality**: is the site distributed like the datasheet? Only meaningful when the
  datasheet's population scope matches the site's. A site that is a narrower slice of a
  broad training set will "differ" by design; pass ``scope_broader=True`` to report those
  differences as expected rather than as findings.

Tests use only what is disclosed, with no invented distributions where avoidable:

* categorical: chi-square on site counts against the datasheet's counts (a contingency
  table when the datasheet's counts or n are known, goodness of fit otherwise); effect size
  is the total variation distance (TVD) between the two mixes.
* continuous, site has values: the site's values binned on the datasheet's own cut points
  (histogram edges, else the quartiles, whose bins each hold 25%), chi-square, TVD. With
  only a mean and SD, Welch's t-test from summary statistics and the standardized mean
  difference.
* age: sites carry decade ``age_band`` only, so the datasheet's age summary is turned
  into band shares (histogram, else a piecewise-linear CDF through min, quartiles and max,
  else a normal with the disclosed mean and SD) and tested by goodness of fit. Marked
  approximate, because the band shares are derived.

A finding needs both a small p-value and an effect larger than the minimum: with a few
hundred scans, trivial differences are "significant". The defaults are provisional and
uncalibrated.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Literal

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import Field
from scipy import stats as sst
from slicepoint_schemas.common import ContractModel, Sha256Hex, SiteId
from slicepoint_schemas.vendor_datasheet import (
    CategoricalSummary,
    ContinuousSummary,
    DatasheetVariable,
    ValueSource,
    VendorDatasheet,
)

from . import __version__
from .ingestion import TabularDataset

FORMAT: Literal["slicepoint.datasheet_comparison/0.1"] = "slicepoint.datasheet_comparison/0.1"


@dataclass(frozen=True)
class DatasheetCheckParams:
    """Decision lines. Provisional: not calibrated on real sites."""

    alpha: float = 0.01
    """p-value below which a difference counts (with the effect-size minimum)."""
    min_tvd: float = 0.10
    """Smallest total variation distance that counts as a difference."""
    min_smd: float = 0.25
    """Smallest |standardized mean difference| that counts (mean/SD-only variables)."""
    coverage_tolerance: float = 0.02
    """Largest share of site scans outside the disclosed range that still counts as covered."""


class Status(str, Enum):
    OUTSIDE_COVERAGE = "outside_coverage"
    """More of the site lies outside what the datasheet discloses than the tolerance allows."""
    DIFFERS = "differs"
    """Covered, but distributed differently (significant and larger than the minimum effect)."""
    DIFFERS_EXPECTED = "differs_expected"
    """Distributed differently, but the datasheet's scope is broader than the site's."""
    SIMILAR = "similar"
    NOT_TESTABLE = "not_testable"


class CoverageResult(ContractModel):
    outside_n: int = Field(ge=0)
    outside_share: float = Field(ge=0.0, le=1.0)
    detail: str


class EqualityResult(ContractModel):
    method: str
    statistic: float | None = None
    df: float | None = None
    p_value: float | None = Field(default=None, ge=0.0, le=1.0)
    effect_name: Literal["tvd", "smd"]
    effect: float | None = None
    approximate: bool = Field(description="True when the expected distribution was derived, not disclosed, "
                                          "or the datasheet's numbers were digitized or estimated.")
    site_shares: dict[str, float] | None = None
    datasheet_shares: dict[str, float] | None = None
    notes: tuple[str, ...] = ()


class VariableComparison(ContractModel):
    variable: str
    label: str | None = None
    site_column: str | None = None
    status: Status
    reason: str | None = Field(default=None, description="Why not testable, or what drove the status.")
    n_site: int = Field(ge=0, description="Site scans with a value.")
    n_site_missing: int = Field(ge=0)
    datasheet_n: int | None = None
    value_source: ValueSource
    coverage: CoverageResult | None = None
    equality: EqualityResult | None = None


class DatasheetComparison(ContractModel):
    """Result of comparing one site with one vendor datasheet."""

    format: Literal["slicepoint.datasheet_comparison/0.1"] = FORMAT
    site_id: SiteId
    n_site_scans: int = Field(ge=0)
    dataset_fingerprint: Sha256Hex
    datasheet_id: str
    datasheet_title: str
    model_name: str
    describes: str
    scope: str
    scope_broader: bool
    params: dict[str, float]
    variables: tuple[VariableComparison, ...]
    not_disclosed: tuple[str, ...] = Field(description="What the datasheet says it does not give.")
    site_columns_not_in_datasheet: tuple[str, ...]
    notes: tuple[str, ...] = ()
    produced_by: str

    def by_status(self, status: Status) -> list[VariableComparison]:
        return [v for v in self.variables if v.status is status]


# --------------------------------------------------------------------------- site columns

SITE_COLUMNS: Mapping[str, str] = {
    "sex": "sex",
    "scanner_vendor": "scanner_vendor",
    "contrast_phase": "contrast_phase",
    "slice_thickness_class": "slice_thickness_class",
    "slice_thickness_mm": "slice_thickness_mm",
    "kvp": "kvp",
    "age_years": "age_band",
    "max_aortic_diameter_mm": "max_aortic_diameter_mm",
    "aaa": "aaa",
    "aaa_size_class": "aaa_size_class",
}
"""Datasheet variable -> site column. Variables not listed here are reported as not testable."""

_TESTED_SITE_COLUMNS = ("sex", "scanner_vendor", "contrast_phase", "slice_thickness_class", "slice_thickness_mm",
                        "kvp", "age_band", "max_aortic_diameter_mm", "aaa", "aaa_size_class")

_TRUE = {"true", "yes", "y", "1", "aaa", "positive"}
_FALSE = {"false", "no", "n", "0", "none", "negative", "no aaa"}
_CATCH_ALL = {"other", "others", "unknown", "missing", "not reported"}

TIE_SHARE = 0.05
"""Share of site values exactly on a disclosed quartile above which quartile bins are not used."""

FloatArray = npt.NDArray[np.float64]
Cdf = Callable[[FloatArray], FloatArray]


def _key(value: object, *, boolean: bool = False) -> str:
    k = str(value).strip().lower()
    if boolean:
        if k in _TRUE:
            return "true"
        if k in _FALSE:
            return "false"
    return k


def _weakest(v: DatasheetVariable) -> ValueSource:
    return v.weakest_value_source


def _datasheet_n(v: DatasheetVariable, ds: VendorDatasheet) -> int | None:
    return v.n if v.n is not None else ds.n_scans


# --------------------------------------------------------------------------- tests


def _chi_square(site_counts: FloatArray, ds_counts: FloatArray | None, ds_shares: FloatArray) -> tuple[str, float, float, float, tuple[str, ...]]:
    """Contingency when datasheet counts are known, goodness of fit otherwise."""
    notes: list[str] = []
    if ds_counts is not None:
        table = np.vstack([site_counts, ds_counts])
        table = table[:, table.sum(axis=0) > 0]
        if table.shape[1] < 2:
            return "chi2_contingency", 0.0, 0.0, 1.0, ("one category only",)
        res = sst.chi2_contingency(table, correction=False)
        if (res.expected_freq < 5).any():
            notes.append("some expected counts are below 5; the p-value is rough")
        return "chi2_contingency", float(res.statistic), float(res.dof), float(res.pvalue), tuple(notes)
    keep = ds_shares > 0
    obs, exp = site_counts[keep], ds_shares[keep] / ds_shares[keep].sum() * site_counts[keep].sum()
    if len(obs) < 2:
        return "chi2_goodness_of_fit", 0.0, 0.0, 1.0, ("one category only",)
    if (exp < 5).any():
        notes.append("some expected counts are below 5; the p-value is rough")
    stat, p = sst.chisquare(obs, exp)
    return "chi2_goodness_of_fit", float(stat), float(len(obs) - 1), float(p), tuple(notes)


def _tvd(p: Mapping[str, float], q: Mapping[str, float]) -> float:
    return 0.5 * float(sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in set(p) | set(q)))


def _shares(counts: Mapping[str, float]) -> dict[str, float]:
    total = float(sum(counts.values()))
    return {k: (v / total if total else 0.0) for k, v in counts.items()}


def _compare_categorical(site: pd.Series, v: DatasheetVariable, summary: CategoricalSummary,
                         ds_n: int | None, approx: bool) -> tuple[CoverageResult, EqualityResult]:
    boolean = v.variable == "aaa"
    site_keys = site.map(lambda x: _key(x, boolean=boolean))
    site_counts: dict[str, float] = {str(k): float(c) for k, c in site_keys.value_counts().items()}
    ds_shares = {_key(k, boolean=boolean): s for k, s in summary.shares().items()}
    if summary.counts is not None:
        ds_counts: dict[str, float] | None = {_key(k, boolean=boolean): float(c) for k, c in summary.counts.items()}
    elif ds_n is not None:
        ds_counts = {k: s * ds_n for k, s in ds_shares.items()}
    else:
        ds_counts = None
    catch_all = next((k for k in ds_shares if k in _CATCH_ALL and ds_shares[k] > 0), None)
    unseen = {k: c for k, c in site_counts.items() if ds_shares.get(k, 0.0) == 0.0}
    n = float(sum(site_counts.values()))
    if unseen and catch_all is not None:
        # The datasheet lumps unlisted categories into e.g. "other": fold the site's unlisted ones in too.
        for k, c in unseen.items():
            site_counts.pop(k)
            site_counts[catch_all] = site_counts.get(catch_all, 0.0) + c
        detail = f"{', '.join(sorted(unseen))} not listed; counted under the datasheet's '{catch_all}'"
        outside = 0.0
    else:
        outside = float(sum(unseen.values()))
        detail = (f"categories the datasheet does not list: {', '.join(sorted(unseen))}" if unseen
                  else "every site category is in the datasheet")
    coverage = CoverageResult(outside_n=int(outside), outside_share=outside / n if n else 0.0, detail=detail)
    cats = sorted(set(site_counts) | set(ds_shares))
    sc = np.array([site_counts.get(k, 0.0) for k in cats])
    dsh = np.array([ds_shares.get(k, 0.0) for k in cats])
    dc = np.array([ds_counts.get(k, 0.0) for k in cats]) if ds_counts is not None else None
    method, stat, df, p, notes = _chi_square(sc, dc, dsh)
    site_sh = {k: site_counts.get(k, 0.0) / n if n else 0.0 for k in cats}
    eq = EqualityResult(method=method, statistic=stat, df=df, p_value=min(1.0, p), effect_name="tvd",
                        effect=_tvd(site_sh, ds_shares), approximate=approx, site_shares=site_sh,
                        datasheet_shares=ds_shares, notes=notes)
    return coverage, eq


def _range_coverage(values: FloatArray, low: float | None, high: float | None, what: str) -> CoverageResult:
    if low is None and high is None:
        return CoverageResult(outside_n=0, outside_share=0.0, detail=f"no {what} range disclosed; coverage unknown")
    below = int((values < low).sum()) if low is not None else 0
    above = int((values > high).sum()) if high is not None else 0
    out = below + above
    lo = "-inf" if low is None else f"{low:g}"
    hi = "inf" if high is None else f"{high:g}"
    return CoverageResult(outside_n=out, outside_share=out / len(values) if len(values) else 0.0,
                          detail=f"{below} below and {above} above the disclosed range [{lo}, {hi}]")


def _binned(values: FloatArray, edges: FloatArray, ds_shares: FloatArray, ds_counts: FloatArray | None,
            approx: bool, method_note: str) -> EqualityResult:
    inside = values[(values >= edges[0]) & (values <= edges[-1])]
    idx = np.clip(np.searchsorted(edges, inside, side="right") - 1, 0, len(edges) - 2)
    sc = np.bincount(idx, minlength=len(edges) - 1).astype(float)
    labels = [f"[{a:g}, {b:g})" for a, b in zip(edges[:-1], edges[1:])]
    method, stat, df, p, notes = _chi_square(sc, ds_counts, ds_shares)
    site_sh = dict(zip(labels, (sc / sc.sum()).tolist() if sc.sum() else [0.0] * len(labels)))
    ds_sh = dict(zip(labels, (ds_shares / ds_shares.sum()).tolist()))
    return EqualityResult(method=f"{method} on {method_note}", statistic=stat, df=df, p_value=min(1.0, p),
                          effect_name="tvd", effect=_tvd(site_sh, ds_sh), approximate=approx,
                          site_shares=site_sh, datasheet_shares=ds_sh, notes=notes)


def _welch(values: FloatArray, s: ContinuousSummary, ds_n: int | None, approx: bool) -> EqualityResult | None:
    if s.mean is None or s.sd is None or len(values) < 2:
        return None
    m, sd, n = float(values.mean()), float(values.std(ddof=1)), len(values)
    pooled = math.sqrt((sd**2 + s.sd**2) / 2)
    smd = (m - s.mean) / pooled if pooled > 0 else None
    if ds_n is None or ds_n < 2:
        return EqualityResult(method="standardized mean difference (datasheet n unknown, no test)",
                              effect_name="smd", effect=smd, approximate=approx)
    res = sst.ttest_ind_from_stats(m, sd, n, s.mean, s.sd, ds_n, equal_var=False)
    return EqualityResult(method="welch_t_from_summary_statistics", statistic=float(res.statistic),
                          p_value=float(res.pvalue), effect_name="smd", effect=smd, approximate=approx)


def _compare_continuous(values: FloatArray, s: ContinuousSummary, ds_n: int | None,
                        approx: bool) -> tuple[CoverageResult, EqualityResult | None, str | None]:
    low = s.min if s.min is not None else (s.histogram.edges[0] if s.histogram else None)
    high = s.max if s.max is not None else (s.histogram.edges[-1] if s.histogram else None)
    coverage = _range_coverage(values, low, high, "value")
    if s.histogram is not None:
        h = s.histogram
        edges = np.asarray(h.edges, dtype=float)
        counts = np.asarray(h.counts, dtype=float) if h.counts is not None else None
        if counts is None and ds_n is not None:
            counts = np.asarray(h.shares()) * ds_n
        return coverage, _binned(values, edges, np.asarray(h.shares()), counts, approx, "the datasheet's histogram bins"), None
    if s.median is not None and s.q1 is not None and s.q3 is not None:
        cuts = [s.q1, s.median, s.q3]
        on_cut = float(np.isin(values, cuts).mean()) if len(values) else 0.0
        if len(set(cuts)) == 3 and on_cut > TIE_SHARE:
            # Many values sit exactly on a quartile (a discrete variable such as slice thickness): the
            # datasheet's bins then need not hold 25% each, so binning on quartiles would mislead.
            welch = _welch(values, s, ds_n, approx)
            if welch is not None:
                return coverage, welch, (f"{on_cut:.0%} of site values sit exactly on a quartile (a discrete "
                                         "variable), so the mean and SD were used")
            eq = _binned(values, np.array([min(float(np.min(values)), s.q1), *cuts,
                                           max(float(np.max(values)), s.q3)]), np.full(4, 0.25),
                         np.full(4, 0.25) * ds_n if ds_n is not None else None, True, "the datasheet's quartiles")
            return coverage, eq, f"{on_cut:.0%} of site values sit exactly on a quartile; result is approximate"
        if len(set(cuts)) == 3:
            lo = min(float(np.min(values)), s.min if s.min is not None else math.inf) if len(values) else s.q1
            hi = max(float(np.max(values)), s.max if s.max is not None else -math.inf) if len(values) else s.q3
            edges = np.array([lo, *cuts, hi], dtype=float)
            shares = np.full(4, 0.25)
            counts = shares * ds_n if ds_n is not None else None
            return coverage, _binned(values, edges, shares, counts, approx, "the datasheet's quartiles"), None
        welch = _welch(values, s, ds_n, approx)
        if welch is not None:
            return coverage, welch, "quartiles tie (a discrete variable), so the mean and SD were used"
        return coverage, None, "quartiles tie (a discrete variable) and no mean/SD is disclosed"
    welch = _welch(values, s, ds_n, approx)
    return coverage, welch, None if welch else "not enough disclosed to test"


_BAND = re.compile(r"^(\d+)0-(\d+)9$")


def _band_bounds(band: str) -> tuple[float, float] | None:
    m = _BAND.match(band.strip())
    return (float(m.group(1)) * 10, float(m.group(1)) * 10 + 10) if m else None


def _age_cdf(s: ContinuousSummary) -> tuple[Cdf, str] | None:
    """A CDF for the datasheet's age, and how it was derived."""
    if s.histogram is not None:
        e = np.asarray(s.histogram.edges, dtype=float)
        cum = np.concatenate([[0.0], np.cumsum(s.histogram.shares())])

        def hist_cdf(x: FloatArray) -> FloatArray:
            return np.asarray(np.interp(x, e, cum, left=0.0, right=1.0), dtype=np.float64)

        return hist_cdf, "histogram, uniform within bins"
    if s.q1 is not None and s.median is not None and s.q3 is not None and s.q1 < s.median < s.q3:
        # A skew-normal matched to the three quartiles, truncated to [min, max] when disclosed. Straight lines
        # from the quartiles out to min and max overweight the tails: min and max are single patients.
        from scipy.optimize import least_squares

        q = np.array([s.q1, s.median, s.q3], dtype=float)
        p = np.array([0.25, 0.5, 0.75])

        def resid(theta: FloatArray) -> FloatArray:
            a, loc, log_scale = theta
            return np.asarray(sst.skewnorm.ppf(p, a, loc, math.exp(log_scale)) - q, dtype=np.float64)

        fit = least_squares(resid, x0=[0.0, s.median, math.log((s.q3 - s.q1) / 1.349)])
        a, loc, scale = float(fit.x[0]), float(fit.x[1]), math.exp(float(fit.x[2]))
        lo = -math.inf if s.min is None else s.min
        hi = math.inf if s.max is None else s.max
        c_lo, c_hi = float(sst.skewnorm.cdf(lo, a, loc, scale)), float(sst.skewnorm.cdf(hi, a, loc, scale))
        worst = float(np.max(np.abs(np.asarray(fit.fun, dtype=np.float64))))
        if c_hi - c_lo > 0 and worst < 0.05 * (s.q3 - s.q1):
            def cdf(x: FloatArray) -> FloatArray:
                raw = sst.skewnorm.cdf(np.clip(x, lo, hi), a, loc, scale)
                return np.asarray((raw - c_lo) / (c_hi - c_lo), dtype=np.float64)

            return cdf, "skew-normal matched to the disclosed quartiles" + (
                ", truncated to min and max" if s.min is not None or s.max is not None else "")
    if s.mean is not None and s.sd is not None and s.sd > 0:
        mean, sd = s.mean, s.sd

        def norm_cdf(x: FloatArray) -> FloatArray:
            return np.asarray(sst.norm.cdf(x, mean, sd), dtype=np.float64)

        return norm_cdf, "normal with the disclosed mean and SD (assumed shape)"
    return None


def _compare_age(bands: pd.Series, s: ContinuousSummary, ds_n: int | None) -> tuple[CoverageResult | None, EqualityResult | None, str | None]:
    counts = bands.astype(str).value_counts()
    maybe = {str(b): _band_bounds(str(b)) for b in counts.index}
    bad = [b for b, v in maybe.items() if v is None]
    if bad:
        return None, None, f"age bands not in decade form: {', '.join(sorted(bad)[:3])}"
    parsed = {b: v for b, v in maybe.items() if v is not None}
    keys = sorted(parsed, key=lambda b: parsed[b][0])
    low = s.min if s.min is not None else (s.histogram.edges[0] if s.histogram else None)
    high = s.max if s.max is not None else (s.histogram.edges[-1] if s.histogram else None)
    out = 0
    for b in keys:
        a, z = parsed[b]
        if (low is not None and z <= low) or (high is not None and a > high):
            out += int(counts[b])
    n = int(counts.sum())
    lo = "-inf" if low is None else f"{low:g}"
    hi = "inf" if high is None else f"{high:g}"
    coverage = (CoverageResult(outside_n=out, outside_share=out / n if n else 0.0,
                               detail=f"{out} scans in age bands wholly outside the disclosed range [{lo}, {hi}]")
                if low is not None or high is not None
                else CoverageResult(outside_n=0, outside_share=0.0, detail="no age range disclosed; coverage unknown"))
    cdf = _age_cdf(s)
    if cdf is None:
        return coverage, None, "not enough disclosed to derive age-band shares"
    f, how = cdf
    # Every decade the site or the datasheet has: a band the datasheet covers but the site lacks
    # counts as zero (a site with nobody under 60 must not look like a full-range datasheet).
    site_starts = {int(parsed[b][0]): b for b in keys}

    def mass(a: float, z: float) -> float:
        c = f(np.array([a, z], dtype=np.float64))
        return float(c[1] - c[0])

    starts = [a for a in range(0, 130, 10) if a in site_starts or mass(a, a + 10.0) > 0.001]
    keys = [site_starts.get(a, f"{a}-{a + 9}") for a in starts]
    edges = np.array([float(starts[0])] + [a + 10.0 for a in starts], dtype=np.float64)
    probs = np.diff(f(edges))
    probs = np.clip(probs, 0.0, None)
    sc = np.array([float(counts.get(b, 0)) for b in keys])
    if float(probs.sum()) <= 0:
        return coverage, None, "the datasheet's age range does not overlap the site's bands"
    method, stat, df, p, notes = _chi_square(sc, None, probs)
    site_sh = dict(zip(keys, (sc / sc.sum()).tolist()))
    ds_sh = dict(zip(keys, (probs / probs.sum()).tolist()))
    tail = 1.0 - float(probs.sum())
    extra = (f"{tail:.1%} of the datasheet's age mass lies outside the site's bands and is left out",) if tail > 0.005 else ()
    eq = EqualityResult(method=f"{method} on age bands (datasheet shares from {how})", statistic=stat, df=df,
                        p_value=min(1.0, p), effect_name="tvd", effect=_tvd(site_sh, ds_sh), approximate=True,
                        site_shares=site_sh, datasheet_shares=ds_sh, notes=notes + extra)
    return coverage, eq, None


# --------------------------------------------------------------------------- driver


def _status(cov: CoverageResult | None, eq: EqualityResult | None, params: DatasheetCheckParams,
            scope_broader: bool) -> tuple[Status, str]:
    if cov is not None and cov.outside_share > params.coverage_tolerance:
        return Status.OUTSIDE_COVERAGE, f"{cov.outside_share:.1%} of site scans outside: {cov.detail}"
    if eq is None:
        return Status.NOT_TESTABLE, "no equality test possible"
    minimum = params.min_tvd if eq.effect_name == "tvd" else params.min_smd
    big = eq.effect is not None and abs(eq.effect) >= minimum
    significant = eq.p_value is None or eq.p_value < params.alpha
    if big and significant:
        why = f"{eq.effect_name.upper()} {abs(eq.effect or 0):.2f} >= {minimum:g}" + (
            f", p = {eq.p_value:.2g}" if eq.p_value is not None else ", no p-value (datasheet n unknown)")
        if scope_broader:
            return Status.DIFFERS_EXPECTED, why + "; the datasheet describes a broader population"
        return Status.DIFFERS, why
    return Status.SIMILAR, (f"{eq.effect_name.upper()} {abs(eq.effect or 0):.2f}"
                            + (f", p = {eq.p_value:.2g}" if eq.p_value is not None else ""))


def compare_to_datasheet(data: TabularDataset, datasheet: VendorDatasheet, *,
                         params: DatasheetCheckParams | None = None,
                         scope_broader: bool = False) -> DatasheetComparison:
    """Compare one site's data with a vendor datasheet, variable by variable."""
    params = params or DatasheetCheckParams()
    frame = data.frame
    rows: list[VariableComparison] = []
    for v in datasheet.variables:
        source = _weakest(v)
        approx = source in (ValueSource.DIGITIZED, ValueSource.ESTIMATED)
        ds_n = _datasheet_n(v, datasheet)
        column = SITE_COLUMNS.get(v.variable)

        def row(status: Status, reason: str | None, n_site: int, n_missing: int,
                coverage: CoverageResult | None = None, equality: EqualityResult | None = None,
                *, _v: DatasheetVariable = v, _n: int | None = ds_n, _src: ValueSource = source,
                _col: str | None = column) -> VariableComparison:
            return VariableComparison(variable=_v.variable, label=_v.label, site_column=_col, status=status,
                                      reason=reason, n_site=n_site, n_site_missing=n_missing, datasheet_n=_n,
                                      value_source=_src, coverage=coverage, equality=equality)

        if column is None or column not in frame.columns:
            why = ("SlicePoint data has no column for this variable" if column is None
                   else f"the site data has no `{column}` column (labels missing?)")
            rows.append(row(Status.NOT_TESTABLE, why, 0, len(frame)))
            continue
        col = frame[column]
        present = col[col.notna()]
        n_missing = int(len(col) - len(present))
        cov: CoverageResult | None
        eq: EqualityResult | None
        why_nt: str | None = None
        summary = v.summary
        if len(present) == 0:
            rows.append(row(Status.NOT_TESTABLE, "no site values", 0, n_missing))
            continue
        if isinstance(summary, CategoricalSummary):
            cov, eq = _compare_categorical(present, v, summary, ds_n, approx)
        elif column == "age_band":
            cov, eq, why_nt = _compare_age(present, summary, ds_n)
        else:
            values = pd.to_numeric(present, errors="coerce").dropna().to_numpy(dtype=float)
            cov, eq, why_nt = _compare_continuous(values, summary, ds_n, approx)
        status, why = _status(cov, eq, params, scope_broader)
        if status is Status.NOT_TESTABLE and why_nt:
            why = why_nt
        elif why_nt:
            why = f"{why}; {why_nt}"
        rows.append(row(status, why, len(present), n_missing, cov, eq))
    disclosed_cols = {SITE_COLUMNS[v.variable] for v in datasheet.variables if v.variable in SITE_COLUMNS}
    extra = tuple(c for c in _TESTED_SITE_COLUMNS if c in frame.columns and c not in disclosed_cols)
    notes = [
        "Equality tests are meaningful only if the datasheet's population matches your site's. "
        f"Datasheet scope: {datasheet.scope.description}",
        "Marginals only: each variable is compared on its own; combinations (e.g. older women on one scanner) "
        "cannot be checked against a datasheet.",
        "Decision lines are provisional and uncalibrated.",
    ]
    if datasheet.describes.value != "training":
        notes.append(f"The datasheet describes the vendor's {datasheet.describes.value} data, not its training data.")
    if "patient_id" in frame.columns and frame["patient_id"].nunique() < len(frame):
        notes.append(f"{len(frame)} scans from {frame['patient_id'].nunique()} patient ids; scans are counted, "
                     "not people, so repeat scans weigh more.")
    return DatasheetComparison(
        site_id=data.site_id, n_site_scans=len(frame), dataset_fingerprint=data.fingerprint(),
        datasheet_id=datasheet.datasheet_id, datasheet_title=datasheet.title, model_name=datasheet.model.name,
        describes=datasheet.describes.value, scope=datasheet.scope.description, scope_broader=scope_broader,
        params={k: float(x) for k, x in asdict(params).items()}, variables=tuple(rows),
        not_disclosed=datasheet.not_disclosed, site_columns_not_in_datasheet=extra, notes=tuple(notes),
        produced_by=f"slicepoint-core {__version__}",
    )


def format_text(result: DatasheetComparison) -> str:
    """Plain-text table for the CLI."""
    lines = [
        f"Site {result.site_id} ({result.n_site_scans} scans) vs datasheet {result.datasheet_id}: {result.datasheet_title}",
        f"Model: {result.model_name}. Describes: {result.describes}. Scope: {result.scope}",
        "",
        f"{'variable':<24} {'status':<18} {'site n':>6}  detail",
    ]
    order = list(Status)
    for v in sorted(result.variables, key=lambda r: order.index(r.status)):
        src = "" if v.value_source is ValueSource.REPORTED or v.value_source is ValueSource.COMPUTED else f" [{v.value_source.value}]"
        lines.append(f"{v.variable:<24} {v.status.value:<18} {v.n_site:>6}  {v.reason or ''}{src}")
    if result.site_columns_not_in_datasheet:
        lines += ["", "Your data has, but the datasheet does not disclose: " + ", ".join(result.site_columns_not_in_datasheet)]
    if result.not_disclosed:
        lines.append("The datasheet says it does not disclose: " + "; ".join(result.not_disclosed))
    lines += [""] + [f"Note: {n}" for n in result.notes]
    return "\n".join(lines)


__all__: Sequence[str] = (
    "DatasheetCheckParams", "DatasheetComparison", "VariableComparison", "CoverageResult", "EqualityResult",
    "Status", "SITE_COLUMNS", "compare_to_datasheet", "format_text",
)
