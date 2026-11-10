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
    report.write_html("report.html")      # self-contained; provisional scores hidden

Command line: ``slicepoint --help`` (see :mod:`slicepoint_core.cli`).
"""

from __future__ import annotations

__version__ = "0.2.0"

from . import report, stats  # noqa: E402
from .assessment import Assessment, AssessmentReport, strip_provisional_scores  # noqa: E402
from .errors import InputError  # noqa: E402
from .checks import CheckRegistry, CheckSpec, Requirement, default_registry  # noqa: E402
from .ingestion import ParquetAdapter, TabularDataset  # noqa: E402
from .legacy import to_slicepoint_v0  # noqa: E402
from .reference import ReferenceProfile, ReferenceSummary  # noqa: E402
from .report import render_html, write_html  # noqa: E402
from .viewer import copy_viewer, viewer_info, viewer_path  # noqa: E402

__all__ = [
    "Assessment",
    "AssessmentReport",
    "CheckRegistry",
    "CheckSpec",
    "InputError",
    "ParquetAdapter",
    "ReferenceProfile",
    "ReferenceSummary",
    "Requirement",
    "TabularDataset",
    "copy_viewer",
    "__version__",
    "default_registry",
    "render_html",
    "report",
    "stats",
    "strip_provisional_scores",
    "to_slicepoint_v0",
    "viewer_info",
    "viewer_path",
    "write_html",
]
