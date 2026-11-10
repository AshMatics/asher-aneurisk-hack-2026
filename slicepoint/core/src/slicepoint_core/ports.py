"""Ports for services outside the library (ADR 0001 section 5).

Milestone 1 only declares them. A step that needs a service the caller did not supply,
or one that reports itself unavailable, is recorded as **skipped**, never passed.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

SEGMENTATION = "segmentation"
"""GPU segmentation worker (``slicepoint/segmentation``, ``POST /v1/compare``)."""
OPENCPU = "opencpu"
"""OpenCPU, for statistics already validated in R."""
FORGE_PGM = "forge_pgm"
"""FORGE core services: cohort planning and PGM population synthesis."""
EMBEDDING = "embedding"
"""Embedding encoder service (ADR section 3). Precomputed embeddings bypass it."""

KNOWN_SERVICES = (SEGMENTATION, OPENCPU, FORGE_PGM, EMBEDDING)


@runtime_checkable
class ServicePort(Protocol):
    name: str

    def available(self) -> bool:
        """True if the service can be called now."""
        ...
