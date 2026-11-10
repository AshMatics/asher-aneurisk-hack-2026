"""Job lifecycle, steps, persistence across restarts, provisional scores and references."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from conftest import AUTH, ManualRunner, make_client, needs_data, wait_for
from slicepoint_api.jobs import INTERRUPTED

pytestmark = needs_data

PORT_STEPS = ("segmentation", "forge_pgm", "opencpu")


def _submit(client: TestClient, body: dict[str, Any], headers: dict[str, str] | None = None) -> str:
    r = client.post("/v1/assessments", headers={**AUTH, **(headers or {})}, json=body)
    assert r.status_code == 202, r.text
    assert r.headers["location"] == f"/v1/assessments/{r.json()['job_id']}"
    job_id: str = r.json()["job_id"]
    return job_id


def _steps(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in job["steps"]}


def test_lifecycle_202_then_409_then_result(data_root: Path, tmp_path: Path) -> None:
    runner = ManualRunner()
    with make_client(data_root, tmp_path / "results", runner=runner) as c:
        job_id = _submit(c, {"dataset": "hospital_b", "site_id": "hospital_b", "reference_dataset": "hospital_a",
                             "reference_site_id": "hospital_a", "site_name": "Hospital B"},
                         headers={"X-SlicePoint-User": "dr.test"})
        job = c.get(f"/v1/assessments/{job_id}", headers=AUTH).json()
        assert job["state"] == "queued" and {s["status"] for s in job["steps"]} == {"pending"}
        for suffix in ("result", "report.html"):
            r = c.get(f"/v1/assessments/{job_id}/{suffix}", headers=AUTH)
            assert r.status_code == 409 and "queued" in r.json()["detail"]
        runner.run_all()
        job = wait_for(c, job_id)
        assert job["state"] == "succeeded", job
        steps = _steps(job)
        assert [s["id"] for s in job["steps"]] == ["ingest_site", "load_reference", "embedding", *PORT_STEPS,
                                                   "run_checks", "render_report"]
        for sid in ("ingest_site", "load_reference", "embedding", "run_checks", "render_report"):
            assert steps[sid]["status"] == "succeeded", steps[sid]
            assert steps[sid]["duration_ms"] is not None and steps[sid]["finished_at"] is not None
        assert "built from hospital_a" in steps["load_reference"]["message"]
        audit = job["audit"]
        assert audit["requested_by"] == "dr.test" and audit["verdict"] == "no_go"
        assert audit["reference_id"] == "ref-hospital_a" and len(audit["dataset_fingerprint"]) == 64
        assert audit["profile_id"] == "hackathon-default-v0" and audit["embedding_space_id"]
        assert audit["core_version"] and audit["schemas_version"] and audit["api_version"] == "0.1.0"
        result = c.get(f"/v1/assessments/{job_id}/result", headers=AUTH)
        assert result.status_code == 200 and result.headers["content-type"] == "application/json"
        assert result.json()["site_name"] == "Hospital B"
        html = c.get(f"/v1/assessments/{job_id}/report.html", headers=AUTH)
        assert html.status_code == 200 and html.headers["content-type"].startswith("text/html")
        assert "Hospital B" in html.text
        csp = html.headers["content-security-policy"]
        assert csp.startswith("default-src 'none'") and "script-src" not in csp and "frame-ancestors 'none'" in csp


def test_skipped_port_steps_are_never_a_pass(client: TestClient, reference_id: str) -> None:
    job = wait_for(client, _submit(client, {"dataset": "hospital_c", "site_id": "hospital_c",
                                            "reference_id": reference_id}))
    assert job["state"] == "succeeded"
    steps = _steps(job)
    for sid in PORT_STEPS:
        assert steps[sid]["status"] == "skipped"
        assert steps[sid]["message"].startswith("service not configured")
    assert steps["embedding"]["status"] == "succeeded"  # practice data has precomputed embeddings
    result = client.get(f"/v1/assessments/{job['job_id']}/result", headers=AUTH).json()
    core_steps = {s["step"]: s["state"] for s in result["steps"]}
    assert core_steps["segmentation"] == "skipped"
    assert result["verdict"]["outcome"] != "go"


def test_bad_input_fails_the_job_cleanly(client: TestClient, reference_id: str, data_root: Path) -> None:
    job = wait_for(client, _submit(client, {"dataset": "broken/no_predictions", "site_id": "hospital_b",
                                            "reference_id": reference_id}))
    assert job["state"] == "failed"
    steps = _steps(job)
    assert steps["ingest_site"]["status"] == "failed"
    assert "predictions.parquet" in steps["ingest_site"]["message"]
    assert all(s["status"] == "pending" for s in job["steps"][1:])
    assert job["error"].startswith("ingest_site: ")
    text = json.dumps(job)
    assert str(data_root) not in text and "/private/" not in text and "Traceback" not in text
    r = client.get(f"/v1/assessments/{job['job_id']}/result", headers=AUTH)
    assert r.status_code == 409 and "failed" in r.json()["detail"]


def test_unexpected_errors_are_generic(data_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from slicepoint_api import pipeline

    def boom(*_: object, **__: object) -> object:
        raise RuntimeError(f"secret detail at {data_root}/x")

    monkeypatch.setattr(pipeline, "load_dataset", boom)
    with make_client(data_root, tmp_path / "results") as c:
        job = wait_for(c, _submit(c, {"dataset": "hospital_b", "site_id": "hospital_b",
                                      "reference_dataset": "hospital_a", "reference_site_id": "hospital_a"}))
    assert job["state"] == "failed"
    assert job["error"] == "ingest_site: internal error; details are in the server log"
    assert "secret" not in json.dumps(job)


def test_provisional_scores_stripped_by_default(client: TestClient, reference_id: str) -> None:
    base = {"dataset": "hospital_d", "site_id": "hospital_d", "reference_id": reference_id}
    hidden = wait_for(client, _submit(client, base))
    shown = wait_for(client, _submit(client, {**base, "show_provisional_scores": True}))
    r_hidden = client.get(f"/v1/assessments/{hidden['job_id']}/result", headers=AUTH).json()
    r_shown = client.get(f"/v1/assessments/{shown['job_id']}/result", headers=AUTH).json()
    assert all("score" not in c for c in r_hidden["verdict"]["results"])
    assert all(not e["key"].startswith(("score_part.", "score.")) and e["key"] != "score_basis"
               for c in r_hidden["verdict"]["results"] for e in c["evidence"])
    assert any(c.get("score") is not None for c in r_shown["verdict"]["results"])
    assert all(c.get("score_method") in (None, "provisional-v0") for c in r_shown["verdict"]["results"])
    assert hidden["request"]["show_provisional_scores"] is False
    assert shown["request"]["show_provisional_scores"] is True


def test_restart_keeps_finished_jobs_and_reports_lost_ones(data_root: Path, tmp_path: Path) -> None:
    results = tmp_path / "results"
    with make_client(data_root, results) as c:
        done = wait_for(c, _submit(c, {"dataset": "hospital_e", "site_id": "hospital_e",
                                       "reference_dataset": "hospital_a", "reference_site_id": "hospital_a"}))
        first = c.get(f"/v1/assessments/{done['job_id']}/result", headers=AUTH).json()
    assert done["state"] == "succeeded"
    # A job that was running when the process died.
    lost = dict(done, job_id="f" * 32, state="running", finished_at=None)
    lost["steps"] = [dict(s, status="running") if s["id"] == "run_checks" else s for s in done["steps"]]
    (results / lost["job_id"]).mkdir()
    (results / lost["job_id"] / "job.json").write_text(json.dumps(lost), encoding="utf-8")

    with make_client(data_root, results) as c2:
        listed = {j["job_id"]: j for j in c2.get("/v1/assessments", headers=AUTH).json()["jobs"]}
        assert listed[done["job_id"]]["state"] == "succeeded" and listed[done["job_id"]]["verdict"] is not None
        again = c2.get(f"/v1/assessments/{done['job_id']}/result", headers=AUTH)
        assert again.status_code == 200 and again.json() == first
        assert c2.get(f"/v1/assessments/{done['job_id']}/report.html", headers=AUTH).status_code == 200
        gone = c2.get(f"/v1/assessments/{'f' * 32}", headers=AUTH).json()
        assert gone["state"] == "failed" and gone["error"] == INTERRUPTED
        assert _steps(gone)["run_checks"]["status"] == "failed"
        assert c2.get(f"/v1/assessments/{'f' * 32}/result", headers=AUTH).status_code == 409


def test_request_rules(client: TestClient, reference_id: str) -> None:
    def post(body: dict[str, Any]) -> int:
        code: int = client.post("/v1/assessments", headers=AUTH, json=body).status_code
        return code

    site = {"dataset": "hospital_b", "site_id": "hospital_b"}
    assert post({**site, "reference_dataset": "hospital_a"}) == 422  # reference_site_id never guessed
    assert post({**site, "reference_id": reference_id, "reference_dataset": "hospital_a",
                 "reference_site_id": "hospital_a"}) == 422
    assert post(site) == 422
    assert post({"dataset": "hospital_b", "reference_id": reference_id}) == 422  # site_id required
    assert post({**site, "site_id": "Hospital B", "reference_id": reference_id}) == 422
    assert post({**site, "reference_id": "ref-unknown"}) == 404
    assert post({**site, "reference_id": reference_id, "on_inconsistency": "ignore"}) == 422
    assert post({**site, "reference_id": reference_id, "profile": {"profile_id": "x"}}) == 422
    assert post({**site, "reference_id": reference_id, "extra": 1}) == 422


def test_inline_profile_is_used(client: TestClient, reference_id: str) -> None:
    from slicepoint_schemas import HACKATHON_DEFAULT_PROFILE

    profile = HACKATHON_DEFAULT_PROFILE.model_copy(update={"profile_id": "custom-test-v1"})
    job = wait_for(client, _submit(client, {"dataset": "hospital_b", "site_id": "hospital_b",
                                            "reference_id": reference_id,
                                            "profile": json.loads(profile.model_dump_json())}))
    assert job["state"] == "succeeded" and job["request"]["profile_id"] == "custom-test-v1"
    result = client.get(f"/v1/assessments/{job['job_id']}/result", headers=AUTH).json()
    assert result["profile_id"] == "custom-test-v1"


def test_references(client: TestClient, reference_id: str) -> None:
    listed = client.get("/v1/references", headers=AUTH).json()["references"]
    assert reference_id in [r["reference_id"] for r in listed]
    info = client.get(f"/v1/references/{reference_id}", headers=AUTH).json()
    assert info["site_id"] == "hospital_a" and info["dataset"] == "hospital_a" and info["n_cases"] > 0
    assert info["requested_by"] == "unknown"
    dup = client.post("/v1/references", headers=AUTH, json={"dataset": "hospital_a", "site_id": "hospital_a"})
    assert dup.status_code == 409
    assert client.post("/v1/references", headers=AUTH, json={"dataset": "hospital_a"}).status_code == 422
    bad = client.post("/v1/references", headers=AUTH,
                      json={"dataset": "broken/no_predictions", "site_id": "hospital_b", "reference_id": "ref-bad"})
    assert bad.status_code == 422 and "predictions.parquet" in bad.json()["detail"]
    assert "/private/" not in bad.text


def test_datasets_listing(client: TestClient) -> None:
    names = client.get("/v1/datasets", headers=AUTH).json()["datasets"]
    assert {"hospital_a", "hospital_b", "broken/no_predictions"} <= set(names)
