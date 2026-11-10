"""Stored reference profiles: ``<results_dir>/references/<reference_id>/``.

Each folder holds what :meth:`ReferenceProfile.save` writes (``reference.json`` and
``reference_arrays.npz``) plus ``service.json`` (the dataset name and who asked).
"""

from __future__ import annotations

import json
import re
import shutil
import threading
from pathlib import Path

from pydantic import ValidationError
from slicepoint_core import ReferenceProfile
from slicepoint_core.reference import ARRAYS_FILE, SUMMARY_FILE, ReferenceSummary

from .models import REFERENCE_ID_PATTERN, ReferenceInfo

SERVICE_FILE = "service.json"


class ReferenceExists(Exception):
    pass


class ReferenceStore:
    def __init__(self, results_dir: Path) -> None:
        self.root = results_dir / "references"
        self._lock = threading.Lock()

    def path(self, reference_id: str) -> Path:
        if not re.fullmatch(REFERENCE_ID_PATTERN, reference_id):
            raise ValueError("invalid reference id")
        return self.root / reference_id

    def exists(self, reference_id: str) -> bool:
        d = self.path(reference_id)
        return (d / SUMMARY_FILE).is_file() and (d / ARRAYS_FILE).is_file()

    def load(self, reference_id: str) -> ReferenceProfile:
        return ReferenceProfile.load(self.path(reference_id))

    def info(self, reference_id: str) -> ReferenceInfo | None:
        if not self.exists(reference_id):
            return None
        d = self.path(reference_id)
        try:
            summary = ReferenceSummary.model_validate_json((d / SUMMARY_FILE).read_text(encoding="utf-8"))
        except (OSError, ValidationError):
            return None
        meta: dict[str, object] = {}
        if (d / SERVICE_FILE).is_file():
            try:
                loaded = json.loads((d / SERVICE_FILE).read_text(encoding="utf-8"))
                meta = loaded if isinstance(loaded, dict) else {}
            except (OSError, ValueError):
                meta = {}
        return _info(summary, dataset=_str_or_none(meta.get("dataset")),
                     requested_by=_str_or_none(meta.get("requested_by")))

    def list(self) -> list[ReferenceInfo]:
        if not self.root.is_dir():
            return []
        out = []
        for d in sorted(self.root.iterdir()):
            if re.fullmatch(REFERENCE_ID_PATTERN, d.name):
                info = self.info(d.name)
                if info is not None:
                    out.append(info)
        return out

    def save(self, reference: ReferenceProfile, *, dataset: str, requested_by: str) -> ReferenceInfo:
        """Write ``reference`` under its id. Raises :class:`ReferenceExists` if taken."""
        ref_id = reference.summary.reference_id
        final = self.path(ref_id)
        with self._lock:
            if final.exists():
                raise ReferenceExists(ref_id)
            tmp = self.root / f".{ref_id}.tmp"
            shutil.rmtree(tmp, ignore_errors=True)
            reference.save(tmp)
            (tmp / SERVICE_FILE).write_text(
                json.dumps({"dataset": dataset, "requested_by": requested_by}, indent=2) + "\n", encoding="utf-8"
            )
            tmp.rename(final)
        return _info(reference.summary, dataset=dataset, requested_by=requested_by)


def _str_or_none(v: object) -> str | None:
    return v if isinstance(v, str) else None


def _info(s: ReferenceSummary, *, dataset: str | None, requested_by: str | None) -> ReferenceInfo:
    return ReferenceInfo(
        reference_id=s.reference_id,
        site_id=s.site_id,
        dataset=dataset,
        n_cases=s.n_cases,
        n_people=s.n_people,
        has_labels=s.has_labels,
        embedding_space_id=s.embedding_space.space_id if s.embedding_space else None,
        profile_id=s.provenance.profile_id,
        dataset_fingerprint=s.provenance.dataset_fingerprint,
        built_at=s.provenance.built_at,
        built_by=s.provenance.built_by,
        requested_by=requested_by,
    )
