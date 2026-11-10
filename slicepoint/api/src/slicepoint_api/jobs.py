"""Job store and job runner.

The workflow engine is not chosen (ADR 0001 section 5), so it sits behind
:class:`JobRunner`. :class:`ThreadPoolJobRunner` is the local in-process
implementation, with bounded concurrency. A Celery, Prefect, Temporal or FORGE runner
would implement the same two methods.

:class:`JobStore` keeps job records in memory and writes each one to
``<results_dir>/<job_id>/job.json`` on every change, so finished jobs survive a
restart. Jobs that were queued or running when the process stopped are not resumed:
on startup they are marked ``failed`` with an "interrupted" error.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from .models import JOB_ID_PATTERN, JobRecord, JobState, StepStatus

_log = logging.getLogger(__name__)

JOB_FILE = "job.json"
RESULT_FILE = "result.json"
REPORT_FILE = "report.html"
INTERRUPTED = ("interrupted: the service stopped before this job finished; it was not resumed. "
               "Submit it again.")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class JobRunner(Protocol):
    """Runs submitted work somewhere. ``submit`` must not block on the work itself."""

    def submit(self, work: Callable[[], None]) -> None: ...

    def shutdown(self) -> None: ...


class ThreadPoolJobRunner:
    """In-process runner: at most ``max_workers`` jobs at once; the rest wait in order."""

    def __init__(self, max_workers: int) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="slicepoint-job")

    def submit(self, work: Callable[[], None]) -> None:
        self._pool.submit(work)

    def shutdown(self) -> None:
        # Queued jobs are dropped; they stay "queued" on disk and are reported as
        # interrupted on the next start.
        self._pool.shutdown(wait=False, cancel_futures=True)


class JobStore:
    def __init__(self, results_dir: Path) -> None:
        self.results_dir = results_dir
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ disk

    def job_dir(self, job_id: str) -> Path:
        if not re.fullmatch(JOB_ID_PATTERN, job_id):
            raise ValueError("invalid job id")
        return self.results_dir / job_id

    def _persist(self, record: JobRecord) -> None:
        atomic_write_text(self.job_dir(record.job_id) / JOB_FILE, record.model_dump_json(indent=2) + "\n")

    def load_from_disk(self) -> None:
        """Read every ``<job_id>/job.json``; mark unfinished ones as interrupted."""
        if not self.results_dir.is_dir():
            return
        for d in sorted(self.results_dir.iterdir()):
            if not (re.fullmatch(JOB_ID_PATTERN, d.name) and (d / JOB_FILE).is_file()):
                continue
            try:
                record = JobRecord.model_validate_json((d / JOB_FILE).read_text(encoding="utf-8"))
            except (OSError, ValidationError, ValueError):
                _log.warning("ignoring unreadable job record in %s", d.name)
                continue
            if record.job_id != d.name:
                _log.warning("ignoring job record whose id does not match its folder: %s", d.name)
                continue
            if record.state in (JobState.QUEUED, JobState.RUNNING):
                now = utcnow()
                for step in record.steps:
                    if step.status is StepStatus.RUNNING:
                        step.status = StepStatus.FAILED
                        step.finished_at = now
                        step.message = "interrupted"
                record.state = JobState.FAILED
                record.finished_at = now
                record.error = INTERRUPTED
                self._persist(record)
            with self._lock:
                self._jobs[record.job_id] = record

    # ------------------------------------------------------------------ access

    def add(self, record: JobRecord) -> None:
        with self._lock:
            self._persist(record)
            self._jobs[record.job_id] = record

    @contextmanager
    def edit(self, job_id: str) -> Iterator[JobRecord]:
        """Change a record in place; it is written to disk when the block exits."""
        with self._lock:
            record = self._jobs[job_id]
            yield record
            self._persist(record)

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            r = self._jobs.get(job_id)
            return None if r is None else r.model_copy(deep=True)

    def all(self) -> list[JobRecord]:
        with self._lock:
            records = [r.model_copy(deep=True) for r in self._jobs.values()]
        return sorted(records, key=lambda r: r.created_at, reverse=True)

    def active_count(self) -> int:
        with self._lock:
            return sum(r.state in (JobState.QUEUED, JobState.RUNNING) for r in self._jobs.values())
