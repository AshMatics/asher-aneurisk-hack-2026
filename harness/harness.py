"""Federated audit harness.

Runs a team's ``audit(node_path)`` function inside each virtual hospital and
enforces one rule: only summary statistics leave a node.

Usage:
    python harness/harness.py --data path/to/release --audit my_audit:audit --out summaries.json

The data directory holds one folder per hospital (``hospital_*``). The audit
function receives the path to one hospital folder and returns a JSON-able
dict of summaries. The harness rejects outputs that look like row-level data.

What is rejected:
- pandas objects (DataFrame, Series, Index)
- any list or array whose length equals the hospital's case count
- any case_id or patient_id value appearing anywhere in the output
- outputs larger than ``--max-elements`` numbers in total

What is warned about (not rejected):
- integer counts between 1 and ``--min-cell - 1``. Small cells can identify
  people in real data; decide whether your summary needs them.

This is a teaching harness, not a privacy guarantee. A determined team can
smuggle rows past any heuristic check. The point is to design an audit that
works within the rule, the way it would have to on a real federated platform.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

DEFAULT_MAX_ELEMENTS = 1_000_000
DEFAULT_MIN_CELL = 5


class LeakError(ValueError):
    """Raised when an audit output looks like row-level data."""


def _load_audit(spec: str) -> Callable[[Path], dict]:
    module_name, _, func_name = spec.partition(":")
    if not func_name:
        func_name = "audit"
    sys.path.insert(0, str(Path.cwd()))
    module = importlib.import_module(module_name)
    return getattr(module, func_name)


def _node_identifiers(node: Path) -> tuple[int, set[str]]:
    features = pd.read_parquet(node / "features.parquet")
    ids: set[str] = set(features["case_id"].astype(str))
    if "patient_id" in features.columns:
        ids |= set(features["patient_id"].dropna().astype(str))
    return len(features), ids


def _to_jsonable(obj: Any) -> Any:
    if isinstance(obj, (pd.DataFrame, pd.Series, pd.Index)):
        raise LeakError("pandas objects are not allowed; return summaries, not tables")
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _to_jsonable(obj.tolist())
    if isinstance(obj, np.generic):
        return obj.item()
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    raise LeakError(f"unsupported type in audit output: {type(obj).__name__}")


def _walk(obj: Any, path: str = "$"):
    yield path, obj
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")


def check_output(out: Any, n_rows: int, identifiers: set[str],
                 max_elements: int = DEFAULT_MAX_ELEMENTS,
                 min_cell: int = DEFAULT_MIN_CELL) -> tuple[Any, list[str]]:
    """Validate one node's audit output. Returns (jsonable_output, warnings)."""
    clean = _to_jsonable(out)
    if not isinstance(clean, dict):
        raise LeakError("audit must return a dict")

    warnings: list[str] = []
    n_numbers = 0
    for path, value in _walk(clean):
        if isinstance(value, list) and n_rows > 1 and len(value) == n_rows:
            raise LeakError(f"{path}: list length equals case count ({n_rows}); looks row-level")
        if isinstance(value, str) and value in identifiers:
            raise LeakError(f"{path}: contains a case or patient identifier")
        if isinstance(value, dict):
            leaked = [k for k in value if k in identifiers]
            if leaked:
                raise LeakError(f"{path}: keyed by case or patient identifiers")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            n_numbers += 1
            if isinstance(value, int) and 0 < value < min_cell:
                warnings.append(f"{path}: small count ({value} < {min_cell})")
    if n_numbers > max_elements:
        raise LeakError(f"output has {n_numbers} numbers, over the {max_elements} limit")
    return clean, warnings


def run(data_dir: Path, audit: Callable[[Path], dict],
        max_elements: int = DEFAULT_MAX_ELEMENTS,
        min_cell: int = DEFAULT_MIN_CELL) -> dict:
    nodes = sorted(p for p in data_dir.iterdir() if p.is_dir() and p.name.startswith("hospital_"))
    if not nodes:
        raise SystemExit(f"no hospital_* folders found in {data_dir}")

    results: dict[str, Any] = {}
    for node in nodes:
        n_rows, identifiers = _node_identifiers(node)
        try:
            out = audit(node)
            clean, warnings = check_output(out, n_rows, identifiers, max_elements, min_cell)
            results[node.name] = {"status": "ok", "summary": clean, "warnings": warnings}
            note = f" ({len(warnings)} warnings)" if warnings else ""
            print(f"[ok]       {node.name}{note}")
        except LeakError as exc:
            results[node.name] = {"status": "rejected", "reason": str(exc)}
            print(f"[rejected] {node.name}: {exc}")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data", type=Path, required=True, help="release folder with hospital_* subfolders")
    parser.add_argument("--audit", required=True, help="module:function, e.g. my_audit:audit")
    parser.add_argument("--out", type=Path, default=Path("summaries.json"))
    parser.add_argument("--max-elements", type=int, default=DEFAULT_MAX_ELEMENTS)
    parser.add_argument("--min-cell", type=int, default=DEFAULT_MIN_CELL)
    args = parser.parse_args(argv)

    results = run(args.data, _load_audit(args.audit), args.max_elements, args.min_cell)
    args.out.write_text(json.dumps(results, indent=2))
    rejected = [k for k, v in results.items() if v["status"] == "rejected"]
    print(f"wrote {args.out}; {len(results) - len(rejected)} ok, {len(rejected)} rejected")
    return 1 if rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
