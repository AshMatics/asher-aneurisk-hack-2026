"""slicepoint-schemas: the Pydantic v2 contract layer for the SlicePoint rebuild.

See ``slicepoint/docs/adr/0001-slicepoint-rebuild-architecture.md`` and
``slicepoint/docs/data-contract-inventory.md``. No IO, no numpy/pandas/torch.
"""

from __future__ import annotations

from .assessment import (
    AssessmentResult,
    CasesToReview,
    CheckRun,
    CheckRunState,
    DiameterAgreement,
    PerformanceSummary,
    ReferenceRef,
    ReviewCase,
    ReviewReason,
    ScanSummary,
    StepRecord,
    StepState,
    Strata,
    StratumRow,
)
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
from .vendor_datasheet import (
    KNOWN_VARIABLES,
    CategoricalSummary,
    ContinuousSummary,
    DatasheetPartition,
    DatasheetSource,
    DatasheetVariable,
    Histogram,
    ModelIdentity,
    PopulationScope,
    SourceKind,
    SourceRef,
    ValueSource,
    VendorDatasheet,
)
from .verdict import Verdict, VerdictOutcome, VerdictOverride, derive_verdict

__version__ = "0.2.2"

__all__ = [
    "KNOWN_VARIABLES",
    "CategoricalSummary",
    "ContinuousSummary",
    "DatasheetPartition",
    "DatasheetSource",
    "DatasheetVariable",
    "Histogram",
    "ModelIdentity",
    "PopulationScope",
    "SourceKind",
    "SourceRef",
    "ValueSource",
    "VendorDatasheet",
    "AssessmentResult",
    "CasesToReview",
    "CheckRun",
    "CheckRunState",
    "DiameterAgreement",
    "PerformanceSummary",
    "ReferenceRef",
    "ReviewCase",
    "ReviewReason",
    "ScanSummary",
    "StepRecord",
    "StepState",
    "Strata",
    "StratumRow",
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
