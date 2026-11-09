"""slicepoint-schemas: the Pydantic v2 contract layer for the SlicePoint rebuild.

See ``slicepoint/docs/adr/0001-slicepoint-rebuild-architecture.md`` and
``slicepoint/docs/data-contract-inventory.md``. No IO, no numpy/pandas/torch.
"""

from __future__ import annotations

from .checks import (
    CHECK_REGISTRY,
    CHECK_REGISTRY_CONTEXT_KEY,
    DEFAULT_CHECK_REGISTRY,
    CheckDescriptor,
    CheckRegistry,
    CheckResult,
    CheckStatus,
    Evidence,
)
from .common import SCHEMA_VERSION
from .embedding import (
    HACKATHON_MERLIN_CT_SPACE,
    CaseEmbedding,
    EmbeddingComparisonRequest,
    EmbeddingSet,
    EmbeddingSpace,
    IncomparableEmbeddingSpacesError,
    assert_comparable,
)
from .ingestion import (
    CuratedDataset,
    DatasetManifest,
    FeatureRow,
    IngestionAdapter,
    LabelRow,
    PredictionRow,
)
from .legacy import CompareResponseV1, DiceSummaryV0, MonthlySummaryV0, SlicePointFileV0
from .thresholds import HACKATHON_DEFAULT_PROFILE, ThresholdProfile, TriggerThreshold
from .verdict import Verdict, VerdictOutcome, VerdictOverride, derive_verdict

__version__ = "0.1.0"

__all__ = [
    "CHECK_REGISTRY",
    "CHECK_REGISTRY_CONTEXT_KEY",
    "DEFAULT_CHECK_REGISTRY",
    "HACKATHON_DEFAULT_PROFILE",
    "HACKATHON_MERLIN_CT_SPACE",
    "SCHEMA_VERSION",
    "CaseEmbedding",
    "CheckDescriptor",
    "CheckRegistry",
    "CheckResult",
    "CheckStatus",
    "CompareResponseV1",
    "CuratedDataset",
    "DatasetManifest",
    "DiceSummaryV0",
    "EmbeddingComparisonRequest",
    "EmbeddingSet",
    "EmbeddingSpace",
    "Evidence",
    "FeatureRow",
    "IncomparableEmbeddingSpacesError",
    "IngestionAdapter",
    "LabelRow",
    "MonthlySummaryV0",
    "PredictionRow",
    "SlicePointFileV0",
    "ThresholdProfile",
    "TriggerThreshold",
    "Verdict",
    "VerdictOutcome",
    "VerdictOverride",
    "__version__",
    "assert_comparable",
    "derive_verdict",
]
