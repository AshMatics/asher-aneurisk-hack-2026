"""Execute the tier-0 quickstart notebook headlessly against the practice data.

Needs the ``notebook`` extra (nbclient, nbformat, ipykernel); skips cleanly without it or
without ``data/practice``. Paths reach the notebook through the ``SLICEPOINT_*``
environment variables its parameters cell reads (the cell is also tagged ``parameters``
for papermill).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import PRACTICE_DIR, REPO_ROOT

NOTEBOOK = REPO_ROOT / "slicepoint" / "notebooks" / "slicepoint_quickstart.ipynb"

pytestmark = pytest.mark.notebook


def test_committed_notebook_has_no_outputs() -> None:
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            assert cell["outputs"] == [] and cell["execution_count"] is None
    params = [c for c in nb["cells"] if "parameters" in c.get("metadata", {}).get("tags", [])]
    assert len(params) == 1


def test_notebook_has_no_analysis_logic() -> None:
    """Code cells only call the library: no pandas maths, numpy or stats in the notebook."""
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    code = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    for banned in ("import numpy", "from slicepoint_core import stats", ".mean(", ".groupby(", "scipy", "sklearn"):
        assert banned not in code
    assert max(len("".join(c["source"]).splitlines()) for c in nb["cells"] if c["cell_type"] == "code") <= 8


def test_notebook_executes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    nbformat = pytest.importorskip("nbformat")
    nbclient = pytest.importorskip("nbclient")
    pytest.importorskip("ipykernel")
    if not (PRACTICE_DIR / "hospital_b").exists():
        pytest.skip("practice data not present")
    out = tmp_path / "out"
    env = {
        "SLICEPOINT_DATA_DIR": str(PRACTICE_DIR / "hospital_b"),
        "SLICEPOINT_SITE_ID": "hospital_b",
        "SLICEPOINT_REFERENCE": str(PRACTICE_DIR / "hospital_a"),
        "SLICEPOINT_REFERENCE_SITE_ID": "hospital_a",
        "SLICEPOINT_OUT_DIR": str(out),
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    nb = nbformat.read(NOTEBOOK, as_version=4)
    client = nbclient.NotebookClient(nb, timeout=600, kernel_name="python3",
                                     resources={"metadata": {"path": str(tmp_path)}})
    client.execute()

    texts = []
    for cell in nb.cells:
        for o in cell.get("outputs", []):
            assert o.get("output_type") != "error", o
            texts.append(o.get("text", ""))
            texts.extend(str(v) for v in o.get("data", {}).values())
    joined = "\n".join(texts)
    assert "Verdict: NO-GO" in joined
    assert "repeats" in joined and "failing_sub_factors" in joined  # the check table
    assert "<iframe" in joined
    result = out / "hospital_b_result.json"
    report = out / "hospital_b_report.html"
    assert result.is_file() and report.is_file()
    assert json.loads(result.read_text(encoding="utf-8"))["verdict"]["outcome"] == "no_go"
    assert "https://" not in report.read_text(encoding="utf-8")
    assert (out / "reference_hospital_a" / "reference.json").is_file()
