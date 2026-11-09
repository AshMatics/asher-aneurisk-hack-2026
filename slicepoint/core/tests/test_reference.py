from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from slicepoint_schemas import HACKATHON_DEFAULT_PROFILE, EmbeddingSpace, IncomparableEmbeddingSpacesError
from slicepoint_schemas.common import Modality

from conftest import FIXED_NOW, load_site, needs_data
from slicepoint_core import Assessment, ReferenceProfile, TabularDataset

pytestmark = needs_data


def test_summary_contents(reference: ReferenceProfile) -> None:
    s = reference.summary
    assert s.site_id == "hospital_a" and s.n_cases == 100 and s.has_labels
    assert s.embedding_space is not None and s.embedding_space.space_id == "merlin-ct-2048:hackathon"
    assert set(s.category_mixes) >= {"scanner_vendor", "contrast_phase", "sex", "age_band", "aaa_size_class"}
    assert abs(sum(s.category_mixes["sex"].values()) - 1) < 1e-12
    assert s.coverage is not None and s.coverage.k == 5
    assert s.provenance.profile_id == HACKATHON_DEFAULT_PROFILE.profile_id
    assert s.provenance.built_at == FIXED_NOW
    assert len(s.provenance.dataset_fingerprint) == 64
    assert s.cutoff is not None and (s.cutoff.low, s.cutoff.high) == (27.0, 29.0)


def test_save_load_round_trip_gives_identical_assessment(reference: ReferenceProfile, tmp_path: Path) -> None:
    reference.save(tmp_path / "ref")
    loaded = ReferenceProfile.load(tmp_path / "ref")
    assert loaded.summary == reference.summary
    assert loaded.embeddings is not None and reference.embeddings is not None
    assert np.array_equal(loaded.embeddings, reference.embeddings)
    site = load_site("hospital_c")
    a = Assessment(site, reference, now=FIXED_NOW).run().result
    b = Assessment(site, loaded, now=FIXED_NOW).run().result
    assert a == b


def test_different_embedding_space_raises(reference: ReferenceProfile) -> None:
    site = load_site("hospital_b")
    other = EmbeddingSpace(space_id="merlin-ct-2048:v2", encoder_name="Merlin CT encoder", modality=Modality.CT, dim=2048)
    moved = TabularDataset(site_id=site.site_id, frame=site.frame, embeddings=site.embeddings, space=other,
                           has_labels=True)
    with pytest.raises(IncomparableEmbeddingSpacesError):
        reference.require_space(other)
    with pytest.raises(IncomparableEmbeddingSpacesError):
        Assessment(moved, reference)


def test_same_id_but_different_definition_raises(reference: ReferenceProfile) -> None:
    assert reference.space is not None
    twisted = reference.space.model_copy(update={"encoder_version": "2.0"})
    with pytest.raises(IncomparableEmbeddingSpacesError, match="inconsistently"):
        reference.require_space(twisted)
