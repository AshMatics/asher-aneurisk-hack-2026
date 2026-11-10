"""Reference profiles: what "the population the model was validated on" looks like.

A :class:`ReferenceProfile` is built once from a reference dataset (hospital_a in the
hackathon) and then compared against any number of candidate sites. It holds:

* a pydantic :class:`ReferenceSummary` (category mixes, numeric summaries, label facts,
  reference model performance, the fitted coverage threshold, provenance), and
* fitted arrays (deduplicated numeric values for the permutation tests, the raw
  embeddings and person groups for the domain classifier, and the kNN coverage state),
  saved as ``npz``.

The profile is tied to the reference dataset's :class:`EmbeddingSpace`. Comparing it
with embeddings from a different space raises
:class:`~slicepoint_schemas.embedding.IncomparableEmbeddingSpacesError`.

The POC compared each site with hospital_a, a sibling site, not with the model's real
training distribution. ADR open question 4 (where reference distributions come from and
who signs them) is still open; this class is the container, not the answer.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Literal

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import AwareDatetime, Field
from slicepoint_schemas.common import ContractModel, Sha256Hex, SiteId
from slicepoint_schemas.embedding import EmbeddingSpace, IncomparableEmbeddingSpacesError
from slicepoint_schemas.assessment import DiameterAgreement
from slicepoint_schemas.legacy import BinMetricsV0, DiceMetricsV0
from slicepoint_schemas.thresholds import ThresholdProfile

from . import __version__
from . import stats as S
from .ingestion import TabularDataset
from .params import Params

CATEGORY_COLUMNS: tuple[str, ...] = ("scanner_vendor", "contrast_phase", "slice_thickness_class", "sex", "age_band")
"""monitor.CAT_COLS, in the notebook's order."""

CATEGORY_LABELS: dict[str, str] = {
    "scanner_vendor": "Scanner brand mix",
    "contrast_phase": "Contrast phase mix",
    "slice_thickness_class": "Slice thickness mix",
    "sex": "Sex mix",
    "age_band": "Age mix",
}
"""monitor.CAT_LABEL: also the trigger names in the threshold profile."""

NUMERIC_SHIFT_COLUMNS: tuple[str, ...] = (
    "aorta_hu_mean",
    "max_aortic_diameter_mm",
    "pred_max_diameter_mm",
    "kvp",
    "slice_thickness_mm",
)
"""Columns tested by the Wasserstein permutation test (notebook ``NICE``), in order."""

SUMMARY_FILE = "reference.json"
ARRAYS_FILE = "reference_arrays.npz"


class NumericSummary(ContractModel):
    n: int = Field(ge=0)
    mean: float | None = None
    sd: float | None = Field(default=None, description="Population SD.")
    median: float | None = None
    min: float | None = None
    max: float | None = None


class CoverageSummary(ContractModel):
    k: int = Field(gt=0)
    n_components: int = Field(gt=0)
    percentile: float
    dist_thr: float


class CutoffSummary(ContractModel):
    low: float
    high: float
    bal_acc_at_best: float


class ReferenceProvenance(ContractModel):
    source: str | None = Field(default=None, description="Where the reference data was read from.")
    dataset_fingerprint: Sha256Hex
    built_at: AwareDatetime
    built_by: str = Field(min_length=1, description="Producer and version.")
    profile_id: str = Field(min_length=1, description="ThresholdProfile whose parameters fitted it.")
    parameters: dict[str, float] = Field(description="The parameters used to fit the arrays.")


class ReferenceSummary(ContractModel):
    """Everything about the reference except the large arrays."""

    format: Literal["slicepoint.reference_profile/0.1"] = "slicepoint.reference_profile/0.1"
    reference_id: str = Field(min_length=1)
    site_id: SiteId
    n_cases: int = Field(ge=0)
    n_people: int = Field(ge=0)
    has_labels: bool
    embedding_space: EmbeddingSpace | None
    category_mixes: dict[str, dict[str, float]] = Field(
        description="Full-data category mixes (nulls as MISSING); includes aaa_size_class if labelled."
    )
    numeric_deduplicated: dict[str, NumericSummary] = Field(
        description="One scan per person; the arrays behind these are in the npz."
    )
    aaa_positive_deduplicated: int | None = None
    n_deduplicated: int = Field(ge=0)
    smallest_aaa_mm: float | None = None
    largest_not_aaa_mm: float | None = None
    performance_missing_as_wrong: BinMetricsV0 | None = None
    diameter: DiameterAgreement | None = None
    dice: DiceMetricsV0 | None = None
    error_sd_mm: float | None = Field(default=None, description="Population SD of predicted - label diameter.")
    cutoff: CutoffSummary | None = None
    coverage: CoverageSummary | None = None
    provenance: ReferenceProvenance


class ReferenceProfile:
    """A fitted reference. Build with :meth:`build`, persist with :meth:`save` / :meth:`load`."""

    def __init__(
        self,
        summary: ReferenceSummary,
        *,
        numeric: dict[str, npt.NDArray[np.floating]],
        embeddings: npt.NDArray[np.floating] | None,
        person_labels: npt.NDArray[np.intp],
        coverage: S.KnnCoverage | None,
    ) -> None:
        self.summary = summary
        self.numeric = numeric
        self.embeddings = embeddings
        self.person_labels = person_labels
        self.coverage = coverage

    # ------------------------------------------------------------------ building

    @classmethod
    def build(
        cls,
        dataset: TabularDataset,
        profile: ThresholdProfile,
        *,
        reference_id: str | None = None,
        built_at: dt.datetime | None = None,
    ) -> ReferenceProfile:
        p = Params(profile)
        df = dataset.frame
        groups = S.group_people(
            dataset.embeddings, df["patient_id"].to_numpy(dtype=object), dataset.case_ids,
            threshold=p.num("near_duplicate_similarity"),
        )
        keep = groups.first_of_each()
        dedup = df[keep].reset_index(drop=True)

        mixes = {c: S.category_mix(df[c]) for c in CATEGORY_COLUMNS if c in df}
        if dataset.has_labels:
            mixes["aaa_size_class"] = S.category_mix(df["aaa_size_class"])
        numeric = {c: _finite(dedup[c]) for c in NUMERIC_SHIFT_COLUMNS if c in dedup}

        perf = diam = dice = None
        err_sd = None
        cutoff = None
        smallest = largest = None
        n_pos_dedup = None
        if dataset.has_labels:
            y = df["aaa"].to_numpy(bool)
            d = df["max_aortic_diameter_mm"].to_numpy(float)
            smallest = float(d[y].min()) if y.any() else None
            largest = float(d[~y].max()) if (~y).any() else None
            n_pos_dedup = int(dedup["aaa"].sum())
            if dataset.has_predictions:
                perf = S.binary_metrics(y, df["pred_aaa_f"].to_numpy(float))
                agreement = S.diameter_agreement(
                    df["pred_max_diameter_mm"], df["max_aortic_diameter_mm"], tolerances_mm=p.tolerances()
                )
                diam = agreement.to_model(*p.tolerances())
                err_sd = agreement.sd
                c = S.cutoff_range(df["pred_max_diameter_mm"], y, p.cutoff_grid())
                cutoff = CutoffSummary(low=c.low, high=c.high, bal_acc_at_best=c.bal_acc_at_best) if c else None
        if "pred_aorta_dice" in df:
            dice = S.dice_summary(df["pred_aorta_dice"], line=p.num("dice_poor_outline_line"),
                                  secondary_line=p.num("dice_secondary_line"))

        coverage = None
        if dataset.embeddings is not None:
            coverage = S.fit_reference(
                dataset.embeddings,
                n_pc=p.int("embedding_max_pcs"),
                k=p.int("coverage_knn_k"),
                percentile=p.num("coverage_percentile"),
                seed=p.int("random_seed"),
            )

        summary = ReferenceSummary(
            reference_id=reference_id or f"ref-{dataset.site_id}",
            site_id=dataset.site_id,
            n_cases=len(df),
            n_people=groups.n_people,
            has_labels=dataset.has_labels,
            embedding_space=dataset.space,
            category_mixes=mixes,
            numeric_deduplicated={c: _numeric_summary(v) for c, v in numeric.items()},
            aaa_positive_deduplicated=n_pos_dedup,
            n_deduplicated=len(dedup),
            smallest_aaa_mm=smallest,
            largest_not_aaa_mm=largest,
            performance_missing_as_wrong=perf,
            diameter=diam,
            dice=dice,
            error_sd_mm=err_sd,
            cutoff=cutoff,
            coverage=None
            if coverage is None
            else CoverageSummary(
                k=coverage.k,
                n_components=int(coverage.pca_components.shape[0]),
                percentile=coverage.percentile,
                dist_thr=coverage.dist_thr,
            ),
            provenance=ReferenceProvenance(
                source=dataset.source,
                dataset_fingerprint=dataset.fingerprint(),
                built_at=built_at or dt.datetime.now(dt.timezone.utc),
                built_by=f"slicepoint-core {__version__}",
                profile_id=profile.profile_id,
                parameters={
                    k: profile.parameters[k]
                    for k in (
                        "near_duplicate_similarity", "embedding_max_pcs", "coverage_knn_k",
                        "coverage_percentile", "random_seed",
                    )
                    if k in profile.parameters
                },
            ),
        )
        return cls(
            summary,
            numeric=numeric,
            embeddings=None if dataset.embeddings is None else np.asarray(dataset.embeddings),
            person_labels=groups.labels,
            coverage=coverage,
        )

    # ------------------------------------------------------------------ space guard

    @property
    def space(self) -> EmbeddingSpace | None:
        return self.summary.embedding_space

    def require_space(self, space: EmbeddingSpace | None) -> None:
        """Raise unless ``space`` is this reference's embedding space.

        ``None`` (a candidate without embeddings) is accepted: embedding-based parts are
        then skipped, not compared.
        """
        if space is None:
            return
        mine = self.space
        if mine is None:
            raise IncomparableEmbeddingSpacesError(
                f"reference {self.summary.reference_id} has no embeddings; cannot compare space {space.space_id!r}"
            )
        if mine.space_id != space.space_id:
            raise IncomparableEmbeddingSpacesError(
                f"embedding spaces differ: reference {mine.space_id!r} vs candidate {space.space_id!r}"
            )
        if mine != space:
            raise IncomparableEmbeddingSpacesError(f"space_id {space.space_id!r} is defined inconsistently")

    # ------------------------------------------------------------------ persistence

    def save(self, directory: str | Path) -> Path:
        """Write ``reference.json`` (the summary) and ``reference_arrays.npz``."""
        out = Path(directory)
        out.mkdir(parents=True, exist_ok=True)
        (out / SUMMARY_FILE).write_text(self.summary.model_dump_json(indent=2) + "\n", encoding="utf-8")
        arrays: dict[str, npt.ArrayLike] = {f"numeric__{k}": v for k, v in self.numeric.items()}
        arrays["person_labels"] = self.person_labels
        if self.embeddings is not None:
            arrays["embeddings"] = self.embeddings
        if self.coverage is not None:
            c = self.coverage
            arrays.update(
                coverage_scaler_mean=c.scaler_mean,
                coverage_scaler_scale=c.scaler_scale,
                coverage_pca_mean=c.pca_mean,
                coverage_pca_components=c.pca_components,
                coverage_reference_points=c.reference_points,
            )
        # numpy stubs: a **dict unpack is checked against the allow_pickle: bool keyword.
        np.savez_compressed(out / ARRAYS_FILE, **arrays)  # type: ignore[arg-type]
        return out

    @classmethod
    def load(cls, directory: str | Path) -> ReferenceProfile:
        d = Path(directory)
        summary = ReferenceSummary.model_validate(json.loads((d / SUMMARY_FILE).read_text(encoding="utf-8")))
        with np.load(d / ARRAYS_FILE, allow_pickle=False) as z:
            arrays = {k: z[k] for k in z.files}
        numeric = {k.removeprefix("numeric__"): v for k, v in arrays.items() if k.startswith("numeric__")}
        coverage = None
        if summary.coverage is not None:
            coverage = S.KnnCoverage(
                scaler_mean=arrays["coverage_scaler_mean"],
                scaler_scale=arrays["coverage_scaler_scale"],
                pca_mean=arrays["coverage_pca_mean"],
                pca_components=arrays["coverage_pca_components"],
                reference_points=arrays["coverage_reference_points"],
                k=summary.coverage.k,
                dist_thr=summary.coverage.dist_thr,
                percentile=summary.coverage.percentile,
            )
        return cls(
            summary,
            numeric=numeric,
            embeddings=arrays.get("embeddings"),
            person_labels=arrays["person_labels"].astype(np.intp),
            coverage=coverage,
        )


def _finite(s: pd.Series) -> npt.NDArray[np.floating]:
    a = pd.to_numeric(s, errors="coerce").to_numpy(dtype=float)
    out: npt.NDArray[np.floating] = a[~np.isnan(a)]
    return out


def _numeric_summary(v: npt.NDArray[np.floating]) -> NumericSummary:
    if not len(v):
        return NumericSummary(n=0)
    return NumericSummary(
        n=len(v),
        mean=float(np.mean(v)),
        sd=float(np.std(v)),
        median=float(np.median(v)),
        min=float(np.min(v)),
        max=float(np.max(v)),
    )
