"""slicepoint-api: the FastAPI service over slicepoint-core (ADR 0001 sections 4 and 5).

A thin, job-based shell. ``POST /v1/assessments`` returns a job id; the job runs a
declarative list of steps in-process and writes ``result.json`` and ``report.html``
under the results folder. All analysis is done by slicepoint-core; nothing here
computes a statistic.

    from slicepoint_api import Settings, create_app
    app = create_app(Settings.from_env())
"""

from __future__ import annotations

__version__ = "0.1.0"

from .app import create_app  # noqa: E402
from .settings import Settings  # noqa: E402

__all__ = ["Settings", "__version__", "create_app"]
