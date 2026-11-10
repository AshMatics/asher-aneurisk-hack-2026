from __future__ import annotations

import shutil
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from slicepoint_api import Settings, create_app

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
PRACTICE_DIR = REPO_ROOT / "data" / "practice"
PARITY_SITES = ("hospital_b", "hospital_c", "hospital_d", "hospital_e")
SITES = ("hospital_a", *PARITY_SITES)

TOKEN = "t" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}

needs_data = pytest.mark.skipif(not (PRACTICE_DIR / "hospital_a").exists(), reason="practice data not present")


class ManualRunner:
    """A JobRunner that holds work until the test releases it."""

    def __init__(self) -> None:
        self.pending: list[Callable[[], None]] = []

    def submit(self, work: Callable[[], None]) -> None:
        self.pending.append(work)

    def run_all(self) -> None:
        while self.pending:
            self.pending.pop(0)()

    def shutdown(self) -> None:
        self.pending.clear()


def make_settings(data_root: Path, results_dir: Path, **kw: Any) -> Settings:
    return Settings.model_validate({"token": TOKEN, "data_root": data_root, "results_dir": results_dir, **kw})


def make_client(data_root: Path, results_dir: Path, *, runner: Any = None, **kw: Any) -> TestClient:
    app: FastAPI = create_app(make_settings(data_root, results_dir, **kw), runner=runner)
    return TestClient(app)


def wait_for(client: TestClient, job_id: str, timeout: float = 180.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        r = client.get(f"/v1/assessments/{job_id}", headers=AUTH)
        assert r.status_code == 200, r.text
        body: dict[str, Any] = r.json()
        if body["state"] in ("succeeded", "failed"):
            return body
        if time.monotonic() > deadline:
            raise AssertionError(f"job {job_id} still {body['state']} after {timeout}s")
        time.sleep(0.1)


@pytest.fixture(scope="session")
def data_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A copy of the practice data (tests add broken datasets next to it, never in the repo)."""
    root = tmp_path_factory.mktemp("data")
    if (PRACTICE_DIR / "hospital_a").exists():
        for site in SITES:
            (root / site).mkdir()
            for f in (PRACTICE_DIR / site).glob("*.parquet"):  # images/masks are dangling links; not needed
                shutil.copy(f, root / site / f.name)
    broken = root / "broken" / "no_predictions"
    broken.mkdir(parents=True)
    if (PRACTICE_DIR / "hospital_b").exists():
        shutil.copy(PRACTICE_DIR / "hospital_b" / "features.parquet", broken / "features.parquet")
    return root


@pytest.fixture(scope="session")
def results_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("results")


@pytest.fixture(scope="session")
def client(data_root: Path, results_dir: Path) -> Iterator[TestClient]:
    with make_client(data_root, results_dir, max_concurrent_jobs=2) as c:
        yield c


@pytest.fixture(scope="session")
def reference_id(client: TestClient) -> str:
    if not (PRACTICE_DIR / "hospital_a").exists():
        pytest.skip("practice data not present")
    r = client.post("/v1/references", headers=AUTH, json={"dataset": "hospital_a", "site_id": "hospital_a"})
    assert r.status_code == 201, r.text
    ref_id: str = r.json()["reference_id"]
    return ref_id
