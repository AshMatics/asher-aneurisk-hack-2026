from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from slicepoint_schemas import CuratedDataset, EmbeddingSpace, IngestionAdapter
from slicepoint_schemas.common import Modality
from slicepoint_schemas.ingestion import NiftiAdapter

from conftest import PRACTICE_DIR, load_site, needs_data
from slicepoint_core import ParquetAdapter, TabularDataset

pytestmark = needs_data


def test_adapter_satisfies_protocol() -> None:
    adapter: IngestionAdapter = ParquetAdapter("hospital_b")
    assert isinstance(adapter, IngestionAdapter)


def test_load_returns_contract_dataset() -> None:
    ds = ParquetAdapter("hospital_b").load(PRACTICE_DIR / "hospital_b")
    assert isinstance(ds, CuratedDataset)
    assert ds.site_id == "hospital_b" and len(ds.features) == 80
    assert ds.embeddings is not None and ds.embeddings.space.dim == 2048
    assert sum(r.pred_aaa is None for r in ds.predictions) == 4


def test_tabular_view_shapes_and_dtypes() -> None:
    t = load_site("hospital_b")
    assert len(t) == 80 and t.embeddings is not None
    assert t.embeddings.shape == (80, 2048) and t.embeddings.dtype == np.float32
    assert t.has_labels and t.has_predictions
    assert int(t.frame["pred_aaa_f"].isna().sum()) == 4
    assert set(t.frame["pred_aaa_f"].dropna().unique()) <= {0.0, 1.0}
    assert t.frame["aaa"].dtype == bool


def test_round_trip_curated_tabular(tmp_path: Path) -> None:
    t = load_site("hospital_c")
    back = TabularDataset.from_curated(t.to_curated())
    assert back.fingerprint() == t.fingerprint()
    assert back.embeddings is not None and t.embeddings is not None
    assert np.array_equal(back.embeddings, t.embeddings)


def test_site_id_is_explicit_and_validated() -> None:
    with pytest.raises(ValueError, match="site_id"):
        ParquetAdapter("Hospital B").load_tabular(PRACTICE_DIR / "hospital_b")
    t = ParquetAdapter("site-42").load_tabular(PRACTICE_DIR / "hospital_b")
    assert t.site_id == "site-42"  # never derived from the folder name


def test_labels_and_embeddings_are_optional(tmp_path: Path) -> None:
    for f in ("features", "predictions"):
        shutil.copy(PRACTICE_DIR / "hospital_b" / f"{f}.parquet", tmp_path / f"{f}.parquet")
    t = ParquetAdapter("hospital_b").load_tabular(tmp_path)
    assert not t.has_labels and t.embeddings is None and t.space is None
    ds = t.to_curated()
    assert ds.labels is None and ds.embeddings is None


def test_wrong_embedding_dimension_rejected(tmp_path: Path) -> None:
    for f in ("features", "predictions", "labels", "embeddings"):
        shutil.copy(PRACTICE_DIR / "hospital_b" / f"{f}.parquet", tmp_path / f"{f}.parquet")
    small = EmbeddingSpace(space_id="tiny", encoder_name="x", modality=Modality.CT, dim=16)
    with pytest.raises(ValueError, match="do not match space tiny"):
        ParquetAdapter("hospital_b", space=small).load_tabular(tmp_path)


def test_join_integrity_and_nan_embeddings(tmp_path: Path) -> None:
    src = PRACTICE_DIR / "hospital_b"
    for f in ("features", "predictions", "labels"):
        shutil.copy(src / f"{f}.parquet", tmp_path / f"{f}.parquet")
    emb = pq.read_table(src / "embeddings.parquet")
    pq.write_table(emb.slice(0, 79), tmp_path / "embeddings.parquet")
    with pytest.raises(ValueError, match="embeddings: case_id set differs"):
        ParquetAdapter("hospital_b").load_tabular(tmp_path)
    col = emb.column("emb_0").to_numpy().copy()
    col[3] = np.nan
    pq.write_table(emb.set_column(1, "emb_0", pa.array(col)), tmp_path / "embeddings.parquet")
    with pytest.raises(ValueError, match="NaN or inf"):
        ParquetAdapter("hospital_b").load_tabular(tmp_path)


def test_row_validation_errors_name_the_table(tmp_path: Path) -> None:
    src = PRACTICE_DIR / "hospital_b"
    for f in ("features", "labels", "embeddings"):
        shutil.copy(src / f"{f}.parquet", tmp_path / f"{f}.parquet")
    preds = pq.read_table(src / "predictions.parquet")
    dice = preds.column("pred_aorta_dice").to_numpy().copy()
    dice[0] = 1.5
    pq.write_table(preds.set_column(1, "pred_aorta_dice", pa.array(dice)), tmp_path / "predictions.parquet")
    with pytest.raises(ValueError, match="predictions.parquet row 0"):
        ParquetAdapter("hospital_b").load_tabular(tmp_path)


def test_other_adapters_remain_stubs() -> None:
    with pytest.raises(NotImplementedError):
        NiftiAdapter().load("x")


def _broken_copy(tmp_path: Path) -> Path:
    """hospital_b with: case 0 duplicated in labels, case 1 missing from embeddings,
    case 2 missing from predictions."""
    src = PRACTICE_DIR / "hospital_b"
    shutil.copy(src / "features.parquet", tmp_path / "features.parquet")
    labels = pq.read_table(src / "labels.parquet")
    pq.write_table(pa.concat_tables([labels, labels.slice(0, 1)]), tmp_path / "labels.parquet")
    emb = pq.read_table(src / "embeddings.parquet")
    pq.write_table(pa.concat_tables([emb.slice(0, 1), emb.slice(2)]), tmp_path / "embeddings.parquet")
    preds = pq.read_table(src / "predictions.parquet")
    pq.write_table(pa.concat_tables([preds.slice(0, 2), preds.slice(3)]), tmp_path / "predictions.parquet")
    return tmp_path


def test_inconsistent_tables_raise_by_default(tmp_path: Path) -> None:
    folder = _broken_copy(tmp_path)
    with pytest.raises(ValueError, match="not unique|differs from features"):
        ParquetAdapter("hospital_b").load_tabular(folder)
    with pytest.raises(ValueError, match="on_inconsistency"):
        ParquetAdapter("hospital_b", on_inconsistency="ignore")  # type: ignore[arg-type]


def test_drop_and_note_reproduces_the_notebook_join(tmp_path: Path) -> None:
    folder = _broken_copy(tmp_path)
    full = load_site("hospital_b")
    ids = full.frame["case_id"].tolist()
    t = ParquetAdapter("hospital_b", on_inconsistency="drop_and_note").load_tabular(folder)
    assert len(t) == 79 and ids[1] not in set(t.frame["case_id"])  # missing embedding: dropped
    assert t.frame["case_id"].tolist() == [c for c in ids if c != ids[1]]  # order kept, duplicate collapsed
    row2 = t.frame[t.frame["case_id"] == ids[2]].iloc[0]  # missing prediction: kept, counts as no answer
    assert np.isnan(row2["pred_aaa_f"]) and np.isnan(row2["pred_max_diameter_mm"])
    assert t.embeddings is not None and full.embeddings is not None
    assert np.array_equal(t.embeddings[1:], full.embeddings[2:])
    text = " ".join(t.notes)
    assert "do not appear in all the files" in text and "more than once" in text and "1 case(s) were dropped" in text
    with pytest.raises(ValueError, match="no prediction row"):
        t.to_curated()


def test_drop_and_note_notes_reach_the_assessment(tmp_path: Path) -> None:
    from slicepoint_schemas import HACKATHON_DEFAULT_PROFILE

    from conftest import FIXED_NOW
    from slicepoint_core import Assessment, ReferenceProfile

    ref = ReferenceProfile.build(load_site("hospital_a"), HACKATHON_DEFAULT_PROFILE, built_at=FIXED_NOW)
    t = ParquetAdapter("hospital_b", on_inconsistency="drop_and_note").load_tabular(_broken_copy(tmp_path))
    rep = Assessment(t, ref, now=FIXED_NOW).run()
    assert rep.result.notes[: len(t.notes)] == t.notes
    assert rep.performance.aaa_missing_as_wrong is not None
    assert rep.performance.aaa_missing_as_wrong.n_no_answer == 5  # 4 original + the case with no prediction row


def test_drop_and_note_on_clean_data_changes_nothing() -> None:
    t = ParquetAdapter("hospital_c", on_inconsistency="drop_and_note").load_tabular(PRACTICE_DIR / "hospital_c")
    assert t.notes == () and t.fingerprint() == load_site("hospital_c").fingerprint()
