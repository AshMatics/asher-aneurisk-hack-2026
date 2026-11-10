"""The ingestion surface (ADR 0001, section 2).

Honest status: **every input today is a hand-curated parquet set made for the hackathon**
(``data/practice/hospital_{a..e}/{features,labels,predictions,embeddings}.parquet``,
joined on ``case_id``, with precomputed embeddings). No production ingestion path exists.
Input datasets must be curated and adapters built; that work is TBD.

What this module commits to:

* :class:`CuratedDataset` is the contract analysis code depends on. It never depends on a
  file format or a source system.
* Per-row models mirror the practice parquet columns exactly, with the nullability the
  data actually has.
* :class:`IngestionAdapter` is the protocol adapters implement. This package does **no
  IO**: the adapter classes below are named declarations that raise
  ``NotImplementedError``. The working parquet reader belongs in the analysis core.

Deliberately *not* enforced here, because detecting them is what the checks are for:
value ranges ("impossible values"), the 30 mm label rule, size-class vs diameter,
thickness class vs mm, and kvp-null-iff-vendor-null (true in the practice data and
documented in the data card, but a data-quality signal, not a parse rule).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from os import PathLike
from typing import Protocol, runtime_checkable

from pydantic import Field, StrictBool, model_validator

from .common import (
    AaaSizeClass,
    AgeBand,
    CaseId,
    ContractModel,
    ContrastPhase,
    PatientId,
    OpenScannerVendor,
    OpenSex,
    Sha256Hex,
    SiteId,
    SliceThicknessClass,
    UnitInterval,
    VersionedModel,
)
from .embedding import EmbeddingSet

# --------------------------------------------------------------------------- per-row models


class FeatureRow(ContractModel):
    """One row of ``features.parquet`` (17 columns).

    ``case_id``, ``patient_id``, ``sex`` and ``scanner_vendor`` are open for new sources:
    opaque ids, and value lists that accept unknown strings (known ones normalised). The
    legacy V0 models keep the closed POC enums and the hex id patterns.
    """

    case_id: CaseId
    patient_id: PatientId
    age_band: AgeBand
    sex: OpenSex
    scanner_vendor: OpenScannerVendor | None = Field(
        description="Missing for a few cases (9 of 420)."
    )
    contrast_phase: ContrastPhase
    slice_thickness_mm: float
    slice_thickness_class: SliceThicknessClass
    kvp: float | None = Field(description="Tube voltage. Null exactly where vendor is null.")
    study_description: str
    protocol_name: str
    aorta_hu_mean: float = Field(description="Mean HU within the segmented aorta.")
    aorta_hu_sd: float
    organ_volumes_liver: float = Field(description="mL. Zeros occur.")
    organ_volumes_spleen: float = Field(description="mL. Zeros occur.")
    organ_volumes_kidney_left: float = Field(description="mL. Zeros occur.")
    organ_volumes_kidney_right: float = Field(description="mL. Zeros occur.")


class LabelRow(ContractModel):
    """One row of ``labels.parquet``. ``aaa`` follows the hospital's convention, which is
    not always ``diameter >= 30`` (hospital e has 5 counter-examples)."""

    case_id: CaseId
    max_aortic_diameter_mm: float = Field(description="Primary label (continuous).")
    aaa: StrictBool
    aaa_size_class: AaaSizeClass


class PredictionRow(ContractModel):
    """One row of ``predictions.parquet``.

    ``pred_max_diameter_mm`` and ``pred_aaa`` are null together (6 rows: b=4, c=1, e=1):
    null means "the model gave no answer", never "normal". On non-null rows the data has
    ``pred_aaa == (pred_max_diameter_mm >= 30)``; that is the model's convention and is
    not enforced here.
    """

    case_id: CaseId
    pred_aorta_dice: UnitInterval
    pred_max_diameter_mm: float | None
    pred_aaa: StrictBool | None

    @model_validator(mode="after")
    def _null_together(self) -> PredictionRow:
        if (self.pred_aaa is None) != (self.pred_max_diameter_mm is None):
            raise ValueError("pred_aaa must be null if and only if pred_max_diameter_mm is null")
        return self


# --------------------------------------------------------------------------- manifest


class TableName(str, Enum):
    FEATURES = "features"
    LABELS = "labels"
    PREDICTIONS = "predictions"
    EMBEDDINGS = "embeddings"


class ManifestFile(ContractModel):
    path: str = Field(min_length=1, description="Relative to the release root.")
    rows: int | None = Field(
        default=None,
        ge=0,
        description="Row count for tabular files. Absent for non-tabular entries "
        "(the practice manifest lists tutorial_keys/*.json without rows).",
    )
    bytes: int = Field(ge=0)
    sha256: Sha256Hex


class DatasetManifest(ContractModel):
    """Mirror of ``data/practice/manifest.json``.

    ``schema_version`` here is the *data release's* version string, not this package's.
    """

    schema_version: str
    release_set: str
    release_key_fingerprint: str | None = None
    files: tuple[ManifestFile, ...]
    hospitals: dict[SiteId, dict[TableName, int]]

    @model_validator(mode="after")
    def _counts_agree(self) -> DatasetManifest:
        by_path = {f.path: f.rows for f in self.files}
        if len(by_path) != len(self.files):
            raise ValueError("duplicate path in manifest files")
        for site, tables in self.hospitals.items():
            for table, rows in tables.items():
                path = f"{site}/{table.value}.parquet"
                if path in by_path and by_path[path] != rows:
                    raise ValueError(
                        f"manifest disagrees with itself for {path}: {by_path[path]} vs {rows}"
                    )
        return self

    def rows_for(self, site_id: str) -> Mapping[TableName, int] | None:
        return self.hospitals.get(site_id)


# --------------------------------------------------------------------------- dataset


class CuratedDataset(VersionedModel):
    """The ingestion surface: everything the analysis core may read for one site.

    ``labels`` is optional (a go-live month can arrive without confirmed answers).
    ``embeddings`` is optional because producing embeddings is an analysis-core service
    in the rebuild; precomputed sets are accepted when tagged with their space.
    """

    site_id: SiteId
    manifest: DatasetManifest | None = None
    features: tuple[FeatureRow, ...]
    labels: tuple[LabelRow, ...] | None = None
    predictions: tuple[PredictionRow, ...]
    embeddings: EmbeddingSet | None = None

    @model_validator(mode="after")
    def _join_integrity(self) -> CuratedDataset:
        tables: dict[TableName, list[str]] = {
            TableName.FEATURES: [r.case_id for r in self.features],
            TableName.PREDICTIONS: [r.case_id for r in self.predictions],
        }
        if self.labels is not None:
            tables[TableName.LABELS] = [r.case_id for r in self.labels]
        if self.embeddings is not None:
            tables[TableName.EMBEDDINGS] = [e.case_id for e in self.embeddings.embeddings]
        reference = set(tables[TableName.FEATURES])
        for name, ids in tables.items():
            if len(set(ids)) != len(ids):
                raise ValueError(f"{name.value}: case_id is not unique")
            if set(ids) != reference:
                raise ValueError(f"{name.value}: case_id set differs from features")
        if self.manifest is not None:
            counts = self.manifest.rows_for(self.site_id)
            if counts is not None:
                for name, ids in tables.items():
                    if name in counts and counts[name] != len(ids):
                        raise ValueError(
                            f"{name.value}: {len(ids)} rows but manifest says {counts[name]}"
                        )
        return self


# --------------------------------------------------------------------------- adapters

Source = str | PathLike[str]


@runtime_checkable
class IngestionAdapter(Protocol):
    """Turns one source into a :class:`CuratedDataset`. Implementations live outside
    this package (it does no IO)."""

    name: str

    def load(self, source: Source) -> CuratedDataset: ...


class _DeclaredAdapter:
    name: str = "declared"
    status: str = "TBD"

    def load(self, source: Source) -> CuratedDataset:
        raise NotImplementedError(
            f"{type(self).__name__} is a declaration in slicepoint-schemas ({self.status}); "
            "no IO is implemented in the contract package."
        )


class ParquetAdapter(_DeclaredAdapter):
    """Hand-curated hackathon parquet (features/labels/predictions/embeddings).

    The only source that exists today. Its working implementation belongs in the analysis
    core, built from the row models above plus
    :func:`slicepoint_schemas.embedding.case_embedding_from_wide_row`.
    """

    name = "parquet"
    status = "implemented in the analysis core, not here"


class OxidicomDicomAdapter(_DeclaredAdapter):
    """DICOM receipt via the oxidicom listener (FNNDSC / ChRIS). Placeholder; needs its own
    ADR when adopted. Features would come from DICOM headers plus segmentation."""

    name = "oxidicom_dicom"
    status = "TBD"


class NiftiAdapter(_DeclaredAdapter):
    """NIfTI volumes plus masks, named ``images/<case_id>.nii.gz`` and
    ``masks/<case_id>_aorta.nii.gz`` per the data card. The practice hospital_c folders
    exist but are empty. Placeholder."""

    name = "nifti"
    status = "TBD"


class ReportTextAdapter(_DeclaredAdapter):
    """Radiology report text, embedded in a ``report_text`` space. Encoder TBD
    (ADR open question 5). Placeholder."""

    name = "report_text"
    status = "TBD"


DECLARED_ADAPTERS: Mapping[str, type[_DeclaredAdapter]] = {
    a.name: a for a in (ParquetAdapter, OxidicomDicomAdapter, NiftiAdapter, ReportTextAdapter)
}
