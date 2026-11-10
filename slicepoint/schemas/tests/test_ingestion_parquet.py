"""(b) Every practice parquet row validates into the ingestion models, and the manifest row
counts hold. Skipped when pyarrow or the practice data is missing.

The reading here is test scaffolding, not an adapter: the package itself does no IO.
"""

from __future__ import annotations

from typing import Any

import pytest

from conftest import PRACTICE_DIR, load_json
from slicepoint_schemas.embedding import HACKATHON_MERLIN_CT_SPACE, EmbeddingSet, case_embedding_from_wide_row
from slicepoint_schemas.ingestion import (
    CuratedDataset,
    DatasetManifest,
    FeatureRow,
    LabelRow,
    PredictionRow,
    TableName,
)

pq = pytest.importorskip("pyarrow.parquet")

MANIFEST_PATH = PRACTICE_DIR / "manifest.json"
pytestmark = pytest.mark.skipif(not MANIFEST_PATH.exists(), reason="practice data not present")

SITES = ["hospital_a", "hospital_b", "hospital_c", "hospital_d", "hospital_e"]


def _rows(site: str, table: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = pq.read_table(PRACTICE_DIR / site / f"{table}.parquet").to_pylist()
    return rows


@pytest.fixture(scope="module")
def manifest() -> DatasetManifest:
    return DatasetManifest.model_validate(load_json(MANIFEST_PATH))


def test_manifest_counts(manifest: DatasetManifest) -> None:
    assert set(manifest.hospitals) == set(SITES)
    total = 0
    for site in SITES:
        counts = manifest.hospitals[site]
        for table in TableName:
            n = pq.ParquetFile(PRACTICE_DIR / site / f"{table.value}.parquet").metadata.num_rows
            assert counts[table] == n
        total += counts[TableName.FEATURES]
    assert total == 420


@pytest.mark.parametrize("site", SITES)
def test_every_row_validates(site: str, manifest: DatasetManifest) -> None:
    features = tuple(FeatureRow.model_validate(r) for r in _rows(site, "features"))
    labels = tuple(LabelRow.model_validate(r) for r in _rows(site, "labels"))
    predictions = tuple(PredictionRow.model_validate(r) for r in _rows(site, "predictions"))
    embeddings = EmbeddingSet(
        space=HACKATHON_MERLIN_CT_SPACE,
        embeddings=tuple(
            case_embedding_from_wide_row(r, dim=HACKATHON_MERLIN_CT_SPACE.dim) for r in _rows(site, "embeddings")
        ),
    )
    dataset = CuratedDataset(
        site_id=site,
        manifest=manifest,
        features=features,
        labels=labels,
        predictions=predictions,
        embeddings=embeddings,
    )
    assert len(dataset.features) == manifest.hospitals[site][TableName.FEATURES]


def test_observed_nullability_matches_inventory() -> None:
    """Facts from the inventory that the models must not contradict."""
    vendor_nulls = pred_nulls = 0
    for site in SITES:
        feats = _rows(site, "features")
        vendor_nulls += sum(r["scanner_vendor"] is None for r in feats)
        assert all((r["kvp"] is None) == (r["scanner_vendor"] is None) for r in feats)
        pred_nulls += sum(r["pred_aaa"] is None for r in _rows(site, "predictions"))
    assert vendor_nulls == 9
    assert pred_nulls == 6


def test_manifest_disagreeing_count_rejected(manifest: DatasetManifest) -> None:
    site = "hospital_b"
    features = tuple(FeatureRow.model_validate(r) for r in _rows(site, "features"))
    predictions = tuple(PredictionRow.model_validate(r) for r in _rows(site, "predictions"))
    with pytest.raises(ValueError, match="manifest says"):
        CuratedDataset(site_id=site, manifest=manifest, features=features[:-1], predictions=predictions[:-1])
