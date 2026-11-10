"""ADR 0001 section 9: the library never depends on FastAPI, a database, a GPU or torch."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from conftest import CORE_ROOT

FORBIDDEN = ("fastapi", "starlette", "torch", "sqlalchemy", "alembic", "cupy", "tensorflow", "jax", "matplotlib")


def test_declared_dependencies() -> None:
    text = (CORE_ROOT / "pyproject.toml").read_text()
    block = text.split("dependencies = [", 1)[1].split("]", 1)[0].lower()
    assert "slicepoint-schemas" in block
    assert not [f for f in FORBIDDEN if f in block]


def test_import_pulls_in_no_forbidden_module() -> None:
    code = (
        "import sys, slicepoint_core, slicepoint_core.assessment;"
        f"bad=[m for m in sys.modules if m.split('.')[0] in {FORBIDDEN!r}];"
        "print(','.join(bad))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=Path("/"))
    assert out.stdout.strip() == ""


def test_public_api() -> None:
    import slicepoint_core

    for name in ("Assessment", "ParquetAdapter", "ReferenceProfile", "TabularDataset", "default_registry", "stats"):
        assert hasattr(slicepoint_core, name)
