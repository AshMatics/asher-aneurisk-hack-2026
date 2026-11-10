"""Ingestion: the working :class:`ParquetAdapter` and the tabular view analysis code uses.

Every input today is a hand-curated hackathon parquet set (ADR 0001 section 2). The other
adapters (DICOM via oxidicom, NIfTI, report text) stay declared stubs in
``slicepoint_schemas.ingestion`` and raise ``NotImplementedError``.

Two views of one dataset
------------------------
* :class:`~slicepoint_schemas.ingestion.CuratedDataset` is the contract: one pydantic model
  per row, embeddings as ``tuple[float, ...]`` per case. :meth:`ParquetAdapter.load`
  returns it, as the ``IngestionAdapter`` protocol requires.
* :class:`TabularDataset` is what the statistics run on: one DataFrame row per case and
  the embeddings as one ``(n, dim)`` ndarray.

Validation boundary
-------------------
:meth:`ParquetAdapter.load_tabular` validates every features / labels / predictions row
through the schemas row models (about 25 small fields per case, so this is cheap) and
builds the DataFrame from the validated values, so normalisation such as ``m`` -> ``M``
applies. The **embeddings are validated at the array level instead**: exact column set
``emb_0 .. emb_{dim-1}`` for the declared space, a floating dtype, finite values, unique
case ids and the same case set as features. Join integrity (same case set and no
duplicates in every table) is enforced as in ``CuratedDataset``.

Why not route embeddings through pydantic? Not speed: measured on hospital_a (100 x 2048,
pydantic 2.14), :meth:`TabularDataset.to_curated` takes about 11 ms and the whole tabular
load about 30 ms warm. The reason is that the analysis needs the ndarray, and the
array-level checks cover everything ``EmbeddingSet`` validates (dimension, ids). The
contract view stays one call away (:meth:`ParquetAdapter.load`, ``to_curated``) and the
two views round-trip losslessly (tested).

Embeddings keep the parquet dtype (float32), as the notebook did; the statistics are
computed on that array, which is what makes parity with the notebook exact.

``site_id`` is always passed explicitly. It is never derived from a folder or display name.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from typing import Any, Literal

import numpy as np
import numpy.typing as npt
import pandas as pd
import pyarrow.parquet as pq
from pydantic import BaseModel, ValidationError
from slicepoint_schemas.common import SITE_ID_PATTERN
from slicepoint_schemas.embedding import HACKATHON_MERLIN_CT_SPACE, CaseEmbedding, EmbeddingSet, EmbeddingSpace
from slicepoint_schemas.ingestion import (
    CuratedDataset,
    DatasetManifest,
    FeatureRow,
    LabelRow,
    NiftiAdapter,
    OxidicomDicomAdapter,
    PredictionRow,
    ReportTextAdapter,
)

Source = str | PathLike[str]

FEATURE_COLUMNS: tuple[str, ...] = tuple(FeatureRow.model_fields)
LABEL_COLUMNS: tuple[str, ...] = tuple(LabelRow.model_fields)
PREDICTION_COLUMNS: tuple[str, ...] = tuple(PredictionRow.model_fields)

__all__ = [
    "FEATURE_COLUMNS",
    "LABEL_COLUMNS",
    "PREDICTION_COLUMNS",
    "NiftiAdapter",
    "OxidicomDicomAdapter",
    "ParquetAdapter",
    "ReportTextAdapter",
    "TabularDataset",
]


@dataclass(frozen=True, eq=False)
class TabularDataset:
    """One site's data in analysis-friendly form.

    ``frame`` has one row per case, in features order, with the features, labels (if
    any) and predictions columns, plus ``pred_aaa_f``: the model's call as 1.0 / 0.0, and
    NaN for "no answer". ``embeddings`` is aligned row-for-row with ``frame``.
    """

    site_id: str
    frame: pd.DataFrame
    embeddings: npt.NDArray[np.floating] | None
    space: EmbeddingSpace | None
    has_labels: bool
    manifest: DatasetManifest | None = None
    source: str | None = None
    notes: tuple[str, ...] = ()
    """Ingestion notes (the notebook's "Files" area), e.g. rows dropped as inconsistent."""
    _fingerprint: list[str] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        import re

        if not re.fullmatch(SITE_ID_PATTERN, self.site_id):
            raise ValueError(f"invalid site_id {self.site_id!r}")
        if (self.embeddings is None) != (self.space is None):
            raise ValueError("embeddings and their space are given together")
        if self.embeddings is not None and self.space is not None:
            if self.embeddings.shape != (len(self.frame), self.space.dim):
                raise ValueError(
                    f"embeddings shape {self.embeddings.shape} != ({len(self.frame)}, {self.space.dim})"
                )

    def __len__(self) -> int:
        return len(self.frame)

    @property
    def case_ids(self) -> npt.NDArray[np.object_]:
        return self.frame["case_id"].to_numpy(dtype=object)

    @property
    def has_embeddings(self) -> bool:
        return self.embeddings is not None

    @property
    def has_predictions(self) -> bool:
        return "pred_aaa" in self.frame.columns

    def fingerprint(self) -> str:
        """sha256 over the validated table content, the embedding bytes and the space id.

        Independent of file layout; stable across reloads of the same data.
        """
        if self._fingerprint:
            return self._fingerprint[0]
        h = hashlib.sha256()
        cols = [c for c in (*FEATURE_COLUMNS, *LABEL_COLUMNS[1:], *PREDICTION_COLUMNS[1:]) if c in self.frame]
        records = self.frame[cols].astype(object).where(self.frame[cols].notna(), None).to_dict("records")
        h.update(json.dumps(records, sort_keys=True, default=str).encode())
        if self.embeddings is not None and self.space is not None:
            h.update(self.space.space_id.encode())
            h.update(np.ascontiguousarray(self.embeddings).tobytes())
        self._fingerprint.append(h.hexdigest())
        return self._fingerprint[0]

    # ------------------------------------------------------------------ conversions

    @classmethod
    def from_curated(cls, dataset: CuratedDataset) -> TabularDataset:
        """Tabular view of a contract dataset (embeddings become a float32 ndarray)."""
        feats = pd.DataFrame([r.model_dump(mode="json") for r in dataset.features], columns=list(FEATURE_COLUMNS))
        preds = pd.DataFrame(
            [r.model_dump(mode="json") for r in dataset.predictions], columns=list(PREDICTION_COLUMNS)
        )
        frame = feats.merge(preds, on="case_id", how="left", validate="one_to_one")
        if dataset.labels is not None:
            labels = pd.DataFrame([r.model_dump(mode="json") for r in dataset.labels], columns=list(LABEL_COLUMNS))
            frame = frame.merge(labels, on="case_id", how="left", validate="one_to_one")
        frame = _finish_frame(frame)
        emb: npt.NDArray[np.floating] | None = None
        space = None
        if dataset.embeddings is not None:
            by_id = {e.case_id: e.vector for e in dataset.embeddings.embeddings}
            emb = np.asarray([by_id[c] for c in frame["case_id"]], dtype=np.float32)
            space = dataset.embeddings.space
        return cls(
            site_id=dataset.site_id,
            frame=frame,
            embeddings=emb,
            space=space,
            has_labels=dataset.labels is not None,
            manifest=dataset.manifest,
        )

    def to_curated(self) -> CuratedDataset:
        """The contract view (every value validated through pydantic)."""
        if self.has_predictions and bool(self.frame["pred_aorta_dice"].isna().any()):
            raise ValueError(
                "some cases have no prediction row (loaded with on_inconsistency='drop_and_note'); "
                "CuratedDataset requires every table to cover every case"
            )
        rows = self.frame.astype(object).where(self.frame.notna(), None).to_dict("records")
        features = tuple(FeatureRow.model_validate({c: r[c] for c in FEATURE_COLUMNS}) for r in rows)
        predictions = tuple(PredictionRow.model_validate({c: r[c] for c in PREDICTION_COLUMNS}) for r in rows)
        labels = (
            tuple(LabelRow.model_validate({c: r[c] for c in LABEL_COLUMNS}) for r in rows) if self.has_labels else None
        )
        emb_set = None
        if self.embeddings is not None and self.space is not None:
            emb_set = EmbeddingSet(
                space=self.space,
                embeddings=tuple(
                    CaseEmbedding(case_id=str(c), vector=tuple(float(x) for x in v))
                    for c, v in zip(self.frame["case_id"], self.embeddings)
                ),
            )
        return CuratedDataset(
            site_id=self.site_id,
            manifest=self.manifest,
            features=features,
            labels=labels,
            predictions=predictions,
            embeddings=emb_set,
        )


def _finish_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Add derived columns: ``pred_aaa_f`` (1.0 / 0.0 / NaN) and a bool ``aaa``."""
    out = frame.copy()
    if "pred_aaa" in out:
        out["pred_aaa_f"] = [np.nan if v is None or v is pd.NA or (isinstance(v, float) and np.isnan(v)) else float(bool(v)) for v in out["pred_aaa"]]
        out["pred_aaa_f"] = out["pred_aaa_f"].astype(float)
    if "aaa" in out:
        out["aaa"] = out["aaa"].astype(bool)
    result: pd.DataFrame = out.reset_index(drop=True)
    return result


def _validated_records(rows: list[dict[str, Any]], model: type[BaseModel], table: str) -> list[dict[str, Any]]:
    out = []
    for i, row in enumerate(rows):
        try:
            out.append(model.model_validate(row).model_dump(mode="json"))
        except ValidationError as exc:
            raise ValueError(f"{table}.parquet row {i} failed validation: {exc}") from exc
    return out


class ParquetAdapter:
    """Loads a curated hackathon parquet folder: ``features``, ``labels`` (optional),
    ``predictions`` and ``embeddings`` (optional) ``.parquet``, joined on ``case_id``.

    Implements the ``slicepoint_schemas.ingestion.IngestionAdapter`` protocol.

    ``on_inconsistency`` decides what happens when the tables disagree (a case missing
    from a table, or a case id repeated inside one):

    * ``"raise"`` (default): fail. Analysis on silently repaired data is not allowed.
    * ``"drop_and_note"``: the notebook's ``load_hospital`` behaviour. Duplicates keep
      their first row. Cases missing from features, labels or embeddings are dropped
      (inner join). Cases missing only from predictions are **kept with no prediction**,
      so they count as "no answer", never as normal. A "Files" note describing what
      happened is attached to the dataset and carried into the assessment notes. Such a
      dataset has no contract view (:meth:`TabularDataset.to_curated` raises), because
      ``CuratedDataset`` requires every table to cover every case.
    """

    name = "parquet"

    def __init__(
        self,
        site_id: str,
        *,
        space: EmbeddingSpace = HACKATHON_MERLIN_CT_SPACE,
        manifest: DatasetManifest | None = None,
        embedding_prefix: str = "emb_",
        on_inconsistency: Literal["raise", "drop_and_note"] = "raise",
    ) -> None:
        if on_inconsistency not in ("raise", "drop_and_note"):
            raise ValueError(f"on_inconsistency must be 'raise' or 'drop_and_note', got {on_inconsistency!r}")
        self.on_inconsistency = on_inconsistency
        self.site_id = site_id
        self.space = space
        self.manifest = manifest
        self.embedding_prefix = embedding_prefix

    def load(self, source: Source) -> CuratedDataset:
        """The contract view (``IngestionAdapter.load``)."""
        return self.load_tabular(source).to_curated()

    def load_tabular(self, source: Source) -> TabularDataset:
        """The analysis view, validated as described in the module docstring."""
        folder = Path(source)
        if not folder.is_dir():
            raise FileNotFoundError(f"{folder} is not a directory")

        def read(table: str, required: bool) -> list[dict[str, Any]] | None:
            path = folder / f"{table}.parquet"
            if not path.exists():
                if required:
                    raise FileNotFoundError(f"{self.site_id}: missing {path}")
                return None
            rows: list[dict[str, Any]] = pq.read_table(path).to_pylist()
            return rows

        feats_raw = read("features", True)
        preds_raw = read("predictions", True)
        labels_raw = read("labels", False)
        assert feats_raw is not None and preds_raw is not None

        tables: dict[str, list[dict[str, Any]]] = {
            "features": _validated_records(feats_raw, FeatureRow, "features"),
            "predictions": _validated_records(preds_raw, PredictionRow, "predictions"),
        }
        if labels_raw is not None:
            tables["labels"] = _validated_records(labels_raw, LabelRow, "labels")

        emb_path = folder / "embeddings.parquet"
        emb_ids: list[str] | None = None
        emb_matrix: npt.NDArray[np.floating] | None = None
        if emb_path.exists():
            emb_ids, emb_matrix = self._read_embeddings(emb_path)

        raw_ids = {k: [r["case_id"] for r in v] for k, v in tables.items()}
        if emb_ids is not None:
            raw_ids["embeddings"] = emb_ids
        if self.manifest is not None:
            counts: Mapping[Any, int] | None = self.manifest.rows_for(self.site_id)
            if counts is not None:
                for t, n in counts.items():
                    have = raw_ids.get(t.value)
                    if have is not None and n != len(have):
                        raise ValueError(f"{self.site_id}/{t.value}: {len(have)} rows but manifest says {n}")

        notes: list[str] = []
        if self.on_inconsistency == "raise":
            _check_join(raw_ids, raw_ids["features"])
            order = raw_ids["features"]
        else:
            order, notes = _drop_inconsistent(raw_ids)
            keep = set(order)
            for k, rows in tables.items():
                seen: set[str] = set()
                kept = []
                for r in rows:  # first occurrence wins, as drop_duplicates("case_id")
                    if r["case_id"] in keep and r["case_id"] not in seen:
                        seen.add(r["case_id"])
                        kept.append(r)
                tables[k] = kept

        kept_ids = set(order)
        frame = pd.DataFrame([r for r in tables["features"] if r["case_id"] in kept_ids], columns=list(FEATURE_COLUMNS))
        frame = frame.merge(pd.DataFrame(tables["predictions"], columns=list(PREDICTION_COLUMNS)), on="case_id", how="left")
        if "labels" in tables:
            frame = frame.merge(pd.DataFrame(tables["labels"], columns=list(LABEL_COLUMNS)), on="case_id", how="left")
        frame = _finish_frame(frame)

        if emb_matrix is not None and emb_ids is not None:
            pos: dict[str, int] = {}
            for i, c in enumerate(emb_ids):
                pos.setdefault(c, i)
            emb_matrix = emb_matrix[[pos[c] for c in order]]
        return TabularDataset(
            site_id=self.site_id,
            frame=frame,
            embeddings=emb_matrix,
            space=self.space if emb_matrix is not None else None,
            has_labels="labels" in tables,
            manifest=self.manifest,
            source=str(folder),
            notes=tuple(notes),
        )

    def _read_embeddings(self, path: Path) -> tuple[list[str], npt.NDArray[np.floating]]:
        table = pq.read_table(path)
        expected = ["case_id", *(f"{self.embedding_prefix}{i}" for i in range(self.space.dim))]
        names = list(table.column_names)
        if set(names) != set(expected) or len(names) != len(expected):
            missing = sorted(set(expected) - set(names))[:5]
            extra = sorted(set(names) - set(expected))[:5]
            raise ValueError(
                f"{path}: columns do not match space {self.space.space_id} (dim {self.space.dim}); "
                f"missing={missing} extra={extra}"
            )
        ids = [str(x) for x in table.column("case_id").to_pylist()]
        cols = [table.column(c).to_numpy() for c in expected[1:]]
        matrix = np.column_stack(cols) if cols else np.empty((len(ids), 0))
        if not np.issubdtype(matrix.dtype, np.floating):
            raise ValueError(f"{path}: embedding values must be floating point, got {matrix.dtype}")
        if not np.isfinite(matrix).all():
            raise ValueError(f"{path}: embeddings contain NaN or inf")
        return ids, matrix


def _check_join(tables: Mapping[str, list[str] | None], order: list[str]) -> None:
    reference = set(order)
    for name, ids in tables.items():
        if ids is None:
            continue
        if len(set(ids)) != len(ids):
            raise ValueError(f"{name}: case_id is not unique")
        if set(ids) != reference:
            raise ValueError(f"{name}: case_id set differs from features")


def _drop_inconsistent(raw_ids: Mapping[str, list[str]]) -> tuple[list[str], list[str]]:
    """The notebook's ``load_hospital`` join: returns the kept case order and the notes."""
    notes: list[str] = []
    dups = {t: len(ids) - len(set(ids)) for t, ids in raw_ids.items()}
    all_ids = set().union(*(set(ids) for ids in raw_ids.values()))
    missing = {t: len(all_ids - set(ids)) for t, ids in raw_ids.items()}
    if any(missing.values()):
        notes.append(
            "Some case_ids do not appear in all the files; scans missing from features, labels or embeddings "
            f"were dropped and scans missing from predictions were kept with no answer. Missing per file: {missing}."
        )
    if any(dups.values()):
        notes.append(f"Some case_ids appear more than once inside a file; the first row was kept. Duplicates: {dups}.")
    inner = [t for t in raw_ids if t != "predictions"]
    keep = set.intersection(*(set(raw_ids[t]) for t in inner))
    order: list[str] = []
    seen: set[str] = set()
    for c in raw_ids["features"]:
        if c in keep and c not in seen:
            seen.add(c)
            order.append(c)
    dropped = len(all_ids) - len(order)
    if dropped:
        notes.append(f"{dropped} case(s) were dropped because they were missing from a required file.")
    return order, notes
