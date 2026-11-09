"""JSON Schema export for every top-level model.

``slicepoint-schemas-export`` writes one ``<Name>.schema.json`` per model into
``slicepoint/schemas/jsonschema/`` (or ``--out``). ``--check`` exits 1 if the files on
disk differ from what the current code would generate. Output is deterministic: keys
sorted, two-space indent, trailing newline.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import VERSION as PYDANTIC_VERSION
from pydantic import BaseModel

from .checks import CheckDescriptor, CheckRegistry, CheckResult
from .embedding import EmbeddingComparisonRequest, EmbeddingSet, EmbeddingSpace
from .ingestion import CuratedDataset, DatasetManifest, FeatureRow, LabelRow, PredictionRow
from .legacy import CompareResponseV1, DiceSummaryV0, MonthlySummaryV0, SlicePointFileV0
from .thresholds import ThresholdProfile
from .verdict import Verdict

TOP_LEVEL_MODELS: Mapping[str, type[BaseModel]] = {
    # new contract
    "CuratedDataset": CuratedDataset,
    "DatasetManifest": DatasetManifest,
    "FeatureRow": FeatureRow,
    "LabelRow": LabelRow,
    "PredictionRow": PredictionRow,
    "EmbeddingSpace": EmbeddingSpace,
    "EmbeddingSet": EmbeddingSet,
    "EmbeddingComparisonRequest": EmbeddingComparisonRequest,
    "ThresholdProfile": ThresholdProfile,
    "CheckDescriptor": CheckDescriptor,
    "CheckRegistry": CheckRegistry,
    "CheckResult": CheckResult,
    "Verdict": Verdict,
    # legacy POC payloads
    "SlicePointFileV0": SlicePointFileV0,
    "MonthlySummaryV0": MonthlySummaryV0,
    "DiceSummaryV0": DiceSummaryV0,
    "CompareResponseV1": CompareResponseV1,
}

DEFAULT_OUT_DIR = Path(__file__).resolve().parents[2] / "jsonschema"
"""``slicepoint/schemas/jsonschema`` for an editable/source checkout."""


def json_schemas() -> dict[str, dict[str, Any]]:
    """Validation-mode JSON Schema (by alias) for every top-level model."""
    return {name: model.model_json_schema(by_alias=True, mode="validation") for name, model in TOP_LEVEL_MODELS.items()}


def render(schema: Mapping[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def rendered_files() -> dict[str, str]:
    """File name -> file content, exactly as written to disk."""
    return {f"{name}.schema.json": render(schema) for name, schema in json_schemas().items()}


GENERATOR_STAMP = "GENERATED_WITH_PYDANTIC"
"""File recording the pydantic version that produced the schemas: its JSON Schema output
differs between pydantic releases, so the files are only reproducible with that version."""


def write_json_schemas(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / GENERATOR_STAMP).write_text(PYDANTIC_VERSION + "\n", encoding="utf-8")
    written = []
    for fname, text in rendered_files().items():
        path = out_dir / fname
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


def diff_json_schemas(out_dir: Path) -> list[str]:
    """Names of files that are missing, stale or unexpected in ``out_dir``."""
    expected = rendered_files()
    problems = []
    for fname, text in expected.items():
        path = out_dir / fname
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            problems.append(fname)
    if out_dir.exists():
        problems += sorted(p.name for p in out_dir.glob("*.schema.json") if p.name not in expected)
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--check", action="store_true", help="verify instead of writing")
    args = parser.parse_args(argv)
    out: Path = args.out
    if args.check:
        stale = diff_json_schemas(out)
        if stale:
            print("stale JSON Schema files: " + ", ".join(stale), file=sys.stderr)
            return 1
        print(f"JSON Schemas in {out} are up to date")
        return 0
    for path in write_json_schemas(out):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
