"""Embedding spaces: the data-space marker (ADR 0001, section 3).

An embedding of the input data (CT, MR or report text) is a marker of the data space a
model is being run on. Two embedding sets can be compared only when they live in the same
:class:`EmbeddingSpace`, identified by ``space_id``. This module enforces that rule; it
does not compute embeddings or distances.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from .common import CaseId, ContractModel, Modality, Sha256Hex, VersionedModel

SpaceId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")]


class IncomparableEmbeddingSpacesError(ValueError):
    """Raised when two embedding sets from different spaces are compared."""


class EmbeddingSpace(VersionedModel):
    """A versioned embedding space.

    ``encoder_version`` and ``preprocessing_hash`` are optional because the hackathon
    space does not know them; a production space should set both.
    """

    space_id: SpaceId
    encoder_name: str = Field(min_length=1)
    encoder_version: str | None = Field(
        default=None, description="Encoder release/weights version. None means unknown."
    )
    modality: Modality
    dim: int = Field(gt=0)
    preprocessing_hash: Sha256Hex | None = Field(
        default=None,
        description="sha256 of the preprocessing definition (resampling, windowing, "
        "tokenisation). None means unknown.",
    )
    description: str | None = None


HACKATHON_MERLIN_CT_SPACE = EmbeddingSpace(
    space_id="merlin-ct-2048:hackathon",
    encoder_name="Merlin CT encoder",
    encoder_version=None,
    modality=Modality.CT,
    dim=2048,
    preprocessing_hash=None,
    description=(
        "Embeddings precomputed upstream for the hackathon practice data "
        "(embeddings.parquet, emb_0..emb_2047, float32). Encoder per docs/data-card.md "
        "L73. Encoder version and preprocessing are UNKNOWN: nothing in the repo records "
        "them, so sets in this space are only comparable with each other."
    ),
)
"""The one embedding space the hackathon data claims. Version and preprocessing unknown."""


class CaseEmbedding(ContractModel):
    """One case's vector. Its length is checked against the space by :class:`EmbeddingSet`."""

    case_id: CaseId
    vector: tuple[float, ...] = Field(min_length=1)


class EmbeddingSet(VersionedModel):
    """All embeddings of a dataset, tagged with the space they claim to come from."""

    space: EmbeddingSpace
    embeddings: tuple[CaseEmbedding, ...]

    @model_validator(mode="after")
    def _check_dims_and_ids(self) -> EmbeddingSet:
        seen: set[str] = set()
        for emb in self.embeddings:
            if len(emb.vector) != self.space.dim:
                raise ValueError(
                    f"case {emb.case_id}: vector length {len(emb.vector)} != "
                    f"space {self.space.space_id} dim {self.space.dim}"
                )
            if emb.case_id in seen:
                raise ValueError(f"duplicate case_id in embedding set: {emb.case_id}")
            seen.add(emb.case_id)
        return self

    @property
    def case_ids(self) -> frozenset[str]:
        return frozenset(e.case_id for e in self.embeddings)

    def require_comparable(self, other: EmbeddingSet) -> None:
        """Raise unless ``other`` is in the same embedding space as this set."""
        assert_comparable(self, other)


def assert_comparable(a: EmbeddingSet, b: EmbeddingSet) -> None:
    """Raise :class:`IncomparableEmbeddingSpacesError` unless both sets share a space.

    Same ``space_id`` but a different definition (dim, encoder, version, preprocessing)
    is also rejected: it means two parties disagree about what the id denotes.
    """
    if a.space.space_id != b.space.space_id:
        raise IncomparableEmbeddingSpacesError(
            f"embedding spaces differ: {a.space.space_id!r} vs {b.space.space_id!r}"
        )
    if a.space != b.space:
        raise IncomparableEmbeddingSpacesError(
            f"space_id {a.space.space_id!r} is defined inconsistently by the two sets"
        )


class EmbeddingComparisonRequest(VersionedModel):
    """A request to compare a candidate site's embeddings against a reference.

    Validation fails when the two sets are not in the same space, so an API that accepts
    this model can never be handed an apples-to-oranges comparison.
    """

    reference: EmbeddingSet
    candidate: EmbeddingSet

    @model_validator(mode="after")
    def _same_space(self) -> EmbeddingComparisonRequest:
        assert_comparable(self.reference, self.candidate)
        return self


def case_embedding_from_wide_row(
    row: Mapping[str, object], *, dim: int, prefix: str = "emb_"
) -> CaseEmbedding:
    """Build a :class:`CaseEmbedding` from one wide parquet row (``case_id``, ``emb_0`` ...).

    Pure: the caller does the reading. Rejects missing or extra columns, so a 2047- or
    2049-column file cannot slip through.
    """
    expected = {"case_id", *(f"{prefix}{i}" for i in range(dim))}
    keys = set(row)
    if keys != expected:
        missing = sorted(expected - keys)[:5]
        extra = sorted(keys - expected)[:5]
        raise ValueError(f"wide embedding row columns mismatch; missing={missing} extra={extra}")
    return CaseEmbedding.model_validate(
        {"case_id": row["case_id"], "vector": [row[f"{prefix}{i}"] for i in range(dim)]}
    )
