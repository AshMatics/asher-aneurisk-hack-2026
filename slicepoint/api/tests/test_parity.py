"""PARITY: the API's result equals a direct slicepoint-core run (no forked logic).

Same normalisation as ``core/tests/test_cli.py``: the library run uses the API result's
``generated_at``, and steps are compared by (step, state) because their free-text detail
names the data source (the API records the dataset name, not a server path).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from slicepoint_schemas import HACKATHON_DEFAULT_PROFILE, AssessmentResult

from conftest import AUTH, PARITY_SITES, PRACTICE_DIR, needs_data, wait_for
from slicepoint_core import Assessment, ParquetAdapter, ReferenceProfile

pytestmark = needs_data


@pytest.fixture(scope="module")
def core_reference() -> ReferenceProfile:
    return ReferenceProfile.build(ParquetAdapter("hospital_a").load_tabular(PRACTICE_DIR / "hospital_a"),
                                  HACKATHON_DEFAULT_PROFILE)


@pytest.mark.parametrize("site", PARITY_SITES)
def test_api_result_equals_core(site: str, client: TestClient, reference_id: str,
                                core_reference: ReferenceProfile) -> None:
    r = client.post("/v1/assessments", headers=AUTH,
                    json={"dataset": site, "site_id": site, "reference_id": reference_id})
    assert r.status_code == 202, r.text
    job = wait_for(client, r.json()["job_id"])
    assert job["state"] == "succeeded", job
    raw = client.get(f"/v1/assessments/{job['job_id']}/result", headers=AUTH)
    via_api = AssessmentResult.model_validate_json(raw.content)

    data = ParquetAdapter(site).load_tabular(PRACTICE_DIR / site)
    direct = Assessment(data, core_reference, HACKATHON_DEFAULT_PROFILE, now=via_api.generated_at).run().export()

    assert via_api.model_dump(exclude={"steps"}) == direct.model_dump(exclude={"steps"})
    assert [(s.step, s.state) for s in via_api.steps] == [(s.step, s.state) for s in direct.steps]
    assert job["audit"]["verdict"] == direct.verdict.final_outcome.value
    assert job["audit"]["dataset_fingerprint"] == direct.dataset_fingerprint
    assert str(PRACTICE_DIR) not in raw.text
