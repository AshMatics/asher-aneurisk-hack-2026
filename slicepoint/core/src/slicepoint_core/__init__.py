"""slicepoint-core: the importable SlicePoint analysis library (ADR 0001 section 9).

Ingestion adapters, statistics, reference profiles, the check registry and the local
assessment runner. No FastAPI, database, GPU or torch.

    from slicepoint_core import Assessment, ParquetAdapter, ReferenceProfile
    from slicepoint_schemas import HACKATHON_DEFAULT_PROFILE

    ref = ReferenceProfile.build(ParquetAdapter("hospital_a").load_tabular("data/practice/hospital_a"),
                                 HACKATHON_DEFAULT_PROFILE)
    site = ParquetAdapter("hospital_b").load_tabular("data/practice/hospital_b")
    report = Assessment(site, ref, HACKATHON_DEFAULT_PROFILE).run()
    print(report.verdict.outcome, report.to_json())
"""

from __future__ import annotations

__version__ = "0.1.0"

from . import stats  # noqa: E402
from .assessment import Assessment, AssessmentReport  # noqa: E402
from .checks import CheckRegistry, CheckSpec, Requirement, default_registry  # noqa: E402
from .ingestion import ParquetAdapter, TabularDataset  # noqa: E402
from .legacy import to_slicepoint_v0  # noqa: E402
from .reference import ReferenceProfile, ReferenceSummary  # noqa: E402

__all__ = [
    "Assessment",
    "AssessmentReport",
    "CheckRegistry",
    "CheckSpec",
    "ParquetAdapter",
    "ReferenceProfile",
    "ReferenceSummary",
    "Requirement",
    "TabularDataset",
    "__version__",
    "default_registry",
    "stats",
    "to_slicepoint_v0",
]
