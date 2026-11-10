"""Write ``slicepoint/api/openapi.json`` from the app (``slicepoint-api-openapi``).

``--check`` exits 1 if the file on disk differs from what the current code generates.
Output is deterministic: keys sorted, two-space indent, trailing newline. TypeScript
types come from this file via ``openapi-typescript`` (see the README).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "openapi.json"
"""``slicepoint/api/openapi.json`` for an editable/source checkout."""


def openapi_schema() -> dict[str, Any]:
    from .app import create_app
    from .settings import Settings

    with tempfile.TemporaryDirectory() as tmp:
        data, results = Path(tmp) / "data", Path(tmp) / "results"
        data.mkdir()
        settings = Settings.model_validate(
            {"token": "x" * 32, "data_root": data, "results_dir": results})
        app = create_app(settings)
        return app.openapi()


def render() -> str:
    return json.dumps(openapi_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="slicepoint-api-openapi", description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true", help="exit 1 if the file is stale")
    args = parser.parse_args(argv)
    text = render()
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.is_file() else ""
        if current != text:
            sys.stderr.write(f"{args.out} is stale: run `uv run slicepoint-api-openapi`\n")
            return 1
        return 0
    args.out.write_text(text, encoding="utf-8")
    sys.stdout.write(f"wrote {args.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
