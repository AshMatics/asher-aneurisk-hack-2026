"""The committed openapi.json must match the code (like core's stale-viewer test)."""

from __future__ import annotations

import json

from slicepoint_api.openapi_export import DEFAULT_OUT, main, render

REGENERATE = "slicepoint/api/openapi.json is stale: run `uv run --directory api slicepoint-api-openapi`"


def test_committed_openapi_is_current() -> None:
    assert DEFAULT_OUT.is_file(), REGENERATE
    assert DEFAULT_OUT.read_text(encoding="utf-8") == render(), REGENERATE
    assert main(["--check"]) == 0


def test_openapi_documents_the_contract_and_auth() -> None:
    spec = json.loads(DEFAULT_OUT.read_text(encoding="utf-8"))
    schemas = spec["components"]["schemas"]
    for name in ("AssessmentResult", "ThresholdProfile", "CheckDescriptor", "JobRecord", "AssessmentRequest"):
        assert name in schemas, name
    assert spec["components"]["securitySchemes"]["bearer"]["scheme"] == "bearer"
    assert spec["paths"]["/healthz"]["get"]["security"] == []
    assert "202" in spec["paths"]["/v1/assessments"]["post"]["responses"]
