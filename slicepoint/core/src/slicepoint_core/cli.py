"""``slicepoint``: the command-line shell over slicepoint-core (ADR 0001 section 9, tier 0).

The CLI holds no analysis logic. Every subcommand calls the same library path as the
notebook and the future API: ``ParquetAdapter`` -> ``ReferenceProfile`` ->
``Assessment.run()`` -> ``AssessmentResult`` (+ ``report.render_html``).

Exit codes (stable; documented in ``slicepoint --help``):

* 0  ran, and the verdict is GO (or: the command succeeded)
* 3  ran fine, and the verdict is BORDERLINE or NO-GO: a person needs to review it
* 1  usage or input error (bad flag, missing folder, bad file or column)
* 2  internal failure (a bug); rerun with ``--debug`` for the traceback
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal, NoReturn

from pydantic import BaseModel, ValidationError

EXIT_GO = 0
EXIT_INPUT = 1
EXIT_INTERNAL = 2
EXIT_REVIEW = 3

_EXIT_TEXT = f"""\
exit codes:
  {EXIT_GO}  ran, and the verdict is GO (other subcommands: success)
  {EXIT_REVIEW}  ran fine, and the verdict is BORDERLINE or NO-GO: needs human review
  {EXIT_INPUT}  usage or input error (bad flag, missing folder, bad file or column)
  {EXIT_INTERNAL}  internal failure (a bug); rerun with --debug for the traceback
"""

_DATA_TEXT = """\
data folder layout (one folder per site, curated parquet, joined on case_id):
  features.parquet      required  one row per scan (patient_id, age_band, sex, scanner_vendor, ...)
  predictions.parquet   required  the AI's outputs (pred_aaa, pred_max_diameter_mm, pred_aorta_dice)
  labels.parquet        optional  your labels (aaa, max_aortic_diameter_mm, aaa_size_class)
  embeddings.parquet    optional  case_id + emb_0..emb_2047 (Merlin CT space)
Raw DICOM / PACS input is not supported yet. `slicepoint schema FeatureRow` shows the columns.
"""

_MAIN_EPILOG = f"""\
typical run (hospital_b checked against reference hospital_a):
  slicepoint reference build --data data/practice/hospital_a --site-id hospital_a --out refs/hospital_a
  slicepoint assess --data data/practice/hospital_b --site-id hospital_b \\
      --reference-profile refs/hospital_a --out out/result.json --html out/report.html --json

{_DATA_TEXT}
{_EXIT_TEXT}
Everything runs on this computer. Nothing is uploaded or sent anywhere.
"""

_ASSESS_EPILOG = f"""\
examples:
  # reference saved earlier with `slicepoint reference build`
  slicepoint assess --data data/practice/hospital_b --site-id hospital_b --site-name "Hospital B" \\
      --reference-profile refs/hospital_a --out out/result.json --html out/report.html --viewer
  # build the reference on the fly from its data folder, machine-readable summary on stdout
  slicepoint assess --data data/practice/hospital_b --site-id hospital_b \\
      --reference-dir data/practice/hospital_a --reference-site-id hospital_a --out out/result.json --json

--json prints one JSON object on stdout:
  {{"ok": true, "exit_code": 3, "site_id": "...", "verdict": "no_go", "not_evaluated": [...],
   "checks": [{{"id": "repeats", "title": "...", "status": "problem", "n": 80, "n_effective": 32.0,
               "failing_sub_factors": ["people", "leakage"]}}, ...],
   "outputs": {{"result": "out/result.json", "html": "out/report.html", "legacy_json": null,
               "viewer": "out/slicepoint-viewer.html"}}}}
  A check that did not run has status "skipped" or "failed" and a "reason"; it never counts as ok.
  On an error: {{"ok": false, "exit_code": 1, "error": "<one line>"}}.

{_EXIT_TEXT}"""


class _UsageError(Exception):
    """Bad input the user can fix (exit 1)."""


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on usage errors; SlicePoint reserves 2 for internal failures."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(EXIT_INPUT, f"{self.prog}: error: {message}\n")


# --------------------------------------------------------------------------- loading inputs


def _load_profile(path: str | None) -> Any:
    from slicepoint_schemas.thresholds import HACKATHON_DEFAULT_PROFILE, ThresholdProfile

    if path is None:
        return HACKATHON_DEFAULT_PROFILE
    p = Path(path)
    if not p.is_file():
        raise _UsageError(f"{p}: threshold profile file not found")
    try:
        return ThresholdProfile.model_validate_json(p.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise _UsageError(f"{p}: not a valid ThresholdProfile: {_first_error(exc)}") from exc


def _first_error(exc: ValidationError) -> str:
    errs = exc.errors()
    if not errs:
        return str(exc).splitlines()[0]
    e = errs[0]
    loc = ".".join(str(x) for x in e["loc"]) or "(top level)"
    more = f" (+{len(errs) - 1} more)" if len(errs) > 1 else ""
    return f"{loc}: {e['msg']}{more}"


def _load_site(folder: str, site_id: str, on_inconsistency: str) -> Any:
    from .ingestion import ParquetAdapter

    _check_site_id(site_id, "--site-id")
    mode: Literal["raise", "drop_and_note"] = "drop_and_note" if on_inconsistency == "drop_and_note" else "raise"
    return ParquetAdapter(site_id, on_inconsistency=mode).load_tabular(folder)


def _check_site_id(site_id: str, flag: str) -> None:
    import re

    from slicepoint_schemas.common import SITE_ID_PATTERN

    if not re.fullmatch(SITE_ID_PATTERN, site_id):
        raise _UsageError(
            f"{flag} {site_id!r} is not a valid site id: use lowercase letters, digits, '_' or '-' "
            "(for example hospital_b)"
        )


def _load_reference(directory: str) -> Any:
    from .reference import ARRAYS_FILE, SUMMARY_FILE, ReferenceProfile

    d = Path(directory)
    if not d.is_dir():
        raise _UsageError(f"{d}: reference profile folder not found (make one with `slicepoint reference build`)")
    for f in (SUMMARY_FILE, ARRAYS_FILE):
        if not (d / f).is_file():
            raise _UsageError(f"{d / f}: missing; {d} is not a saved reference profile")
    try:
        return ReferenceProfile.load(d)
    except ValidationError as exc:
        raise _UsageError(f"{d / SUMMARY_FILE}: not a valid reference profile: {_first_error(exc)}") from exc


def _input_guard(fn: Callable[[], Any]) -> Any:
    """Run a loading step; turn the errors a user can fix into a one-line _UsageError."""
    from slicepoint_schemas.embedding import IncomparableEmbeddingSpacesError

    from .errors import InputError

    try:
        return fn()
    except (_UsageError, InputError, FileNotFoundError, IncomparableEmbeddingSpacesError) as exc:
        raise _UsageError(str(exc)) from exc
    except ValidationError as exc:
        raise _UsageError(_first_error(exc)) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise _UsageError(f"{type(exc).__name__}: {exc}") from exc


# --------------------------------------------------------------------------- output helpers


def _emit(args: argparse.Namespace, payload: dict[str, Any], text: str) -> None:
    if getattr(args, "json", False):
        sys.stdout.write(json.dumps(payload, indent=2, default=str) + "\n")
    else:
        sys.stdout.write(text.rstrip("\n") + "\n")


def _summary(result: Any, *, show_scores: bool, outputs: dict[str, str | None], exit_code: int) -> dict[str, Any]:
    from .report import summarize

    return {"ok": True, "exit_code": exit_code, **summarize(result, show_provisional_scores=show_scores),
            "outputs": outputs}


def _summary_text(s: dict[str, Any]) -> str:
    from .report import format_n_effective

    label = {"go": "GO", "no_go": "NO-GO", "borderline": "BORDERLINE"}[s["verdict"]]
    lines = [
        f"SlicePoint: site {s['site_id']} vs reference {s['reference_id']} (profile {s['profile_id']})",
        f"Verdict: {label}",
        "",
    ]
    for c in s["checks"]:
        status = str(c["status"]).upper()
        if c["n"] is None:
            detail = f"not evaluated: {c.get('reason') or ''}"
        else:
            detail = f"n={c['n']}" + (f" (effective {format_n_effective(c['n_effective'])})"
                                      if c["n_effective"] is not None else "")
            if c["failing_sub_factors"]:
                detail += "  failing: " + ", ".join(c["failing_sub_factors"])
            if "provisional_score" in c and c["provisional_score"] is not None:
                detail += f"  provisional score {c['provisional_score']:.0f} (not validated)"
        lines.append(f"  {c['title']:<26} {status:<9} {detail}")
    if s["not_evaluated"]:
        lines.append(f"\nNot evaluated (never counts as passed): {', '.join(s['not_evaluated'])}")
    if s["skipped_steps"] or s["failed_steps"]:
        lines.append(f"Skipped steps: {', '.join(s['skipped_steps']) or 'none'}; "
                     f"failed steps: {', '.join(s['failed_steps']) or 'none'}")
    outs = [f"{k}: {v}" for k, v in s["outputs"].items() if v]
    if outs:
        lines.append("\nWrote " + "; ".join(outs))
    lines.append(
        "\nExit 0: verdict GO." if s["exit_code"] == EXIT_GO
        else f"\nExit {EXIT_REVIEW}: the run worked; the verdict needs a person to review the report."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------- subcommands


def _cmd_reference_build(args: argparse.Namespace) -> int:
    from .reference import ReferenceProfile

    profile = _input_guard(lambda: _load_profile(args.profile))
    data = _input_guard(lambda: _load_site(args.data, args.site_id, args.on_inconsistency))
    ref = ReferenceProfile.build(data, profile, reference_id=args.reference_id)
    out = ref.save(args.out)
    s = ref.summary
    payload = {
        "ok": True, "exit_code": EXIT_GO, "reference_id": s.reference_id, "site_id": s.site_id,
        "n_cases": s.n_cases, "n_people": s.n_people, "has_labels": s.has_labels,
        "embedding_space_id": s.embedding_space.space_id if s.embedding_space else None,
        "profile_id": profile.profile_id, "outputs": {"reference_profile": str(out)},
    }
    _emit(args, payload, f"Built reference {s.reference_id} from site {s.site_id}: {s.n_cases} scans, "
                         f"{s.n_people} people, labels {'yes' if s.has_labels else 'no'}, embeddings "
                         f"{'yes' if s.embedding_space else 'no'}.\nSaved to {out}")
    return EXIT_GO


def _cmd_assess(args: argparse.Namespace) -> int:
    from slicepoint_schemas.verdict import VerdictOutcome

    from .assessment import Assessment
    from .legacy import to_slicepoint_v0
    from .reference import ReferenceProfile
    from .report import write_html

    profile = _input_guard(lambda: _load_profile(args.profile))
    if args.reference_profile:
        reference = _input_guard(lambda: _load_reference(args.reference_profile))
    else:
        if not args.reference_site_id:
            raise _UsageError("--reference-dir needs --reference-site-id (the reference site's stable id, "
                              "for example hospital_a); it is never guessed")
        _input_guard(lambda: _check_site_id(args.reference_site_id, "--reference-site-id"))
        ref_data = _input_guard(lambda: _load_site(args.reference_dir, args.reference_site_id, args.on_inconsistency))
        reference = ReferenceProfile.build(ref_data, profile)
    site = _input_guard(lambda: _load_site(args.data, args.site_id, args.on_inconsistency))
    assessment = _input_guard(lambda: Assessment(site, reference, profile, site_name=args.site_name))

    report = assessment.run()
    result = report.result
    outputs: dict[str, str | None] = {"result": None, "html": None, "legacy_json": None, "viewer": None}
    outputs["result"] = str(_input_guard(
        lambda: report.write_json(args.out, show_provisional_scores=args.show_provisional_scores)))
    if args.html:
        outputs["html"] = str(_input_guard(lambda: write_html(
            result, args.html, show_provisional_scores=args.show_provisional_scores)))
    if args.legacy_json:
        try:
            legacy = to_slicepoint_v0(report, hospital_name=args.hospital_name or args.site_name or args.site_id)
        except ValueError as exc:
            raise _UsageError(f"--legacy-json: {exc}") from exc
        path = Path(args.legacy_json)

        def write_legacy() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(legacy.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8")

        _input_guard(write_legacy)
        outputs["legacy_json"] = str(path)
    if args.viewer:
        from .viewer import copy_viewer

        outputs["viewer"] = str(_input_guard(lambda: copy_viewer(Path(args.out).parent)))

    code = EXIT_GO if result.verdict.final_outcome is VerdictOutcome.GO else EXIT_REVIEW
    s = _summary(result, show_scores=args.show_provisional_scores, outputs=outputs, exit_code=code)
    _emit(args, s, _summary_text(s))
    return code


def _detect_model(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    if data.get("result_type") == "slicepoint.assessment_result":
        return "AssessmentResult"
    if data.get("fileType") == "hospital_data":
        return "SlicePointFileV0"
    if data.get("comparison_type") == "model_vs_vendor_mask_agreement":
        return "CompareResponseV1"
    if "months" in data and "scenario" in data:
        return "MonthlySummaryV0"
    if str(data.get("format", "")).startswith("slicepoint.reference_profile/"):
        return "ReferenceSummary"
    if "profile_id" in data and "check_targets" in data:
        return "ThresholdProfile"
    if "average" in data and "note" in data:
        return "DiceSummaryV0"
    return None


def _models() -> dict[str, type[BaseModel]]:
    from slicepoint_schemas.export import TOP_LEVEL_MODELS

    from .reference import ReferenceSummary

    return {**TOP_LEVEL_MODELS, "ReferenceSummary": ReferenceSummary}


def _cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.is_file():
        raise _UsageError(f"{path}: file not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _UsageError(f"{path}: not valid JSON ({exc})") from exc
    models = _models()
    name = args.type or _detect_model(data)
    if name is None:
        raise _UsageError(f"{path}: cannot tell the file type; pass --type (one of {', '.join(sorted(models))})")
    if name not in models:
        raise _UsageError(f"--type {name!r} is unknown; choose one of {', '.join(sorted(models))}")
    try:
        models[name].model_validate(data)
    except ValidationError as exc:
        raise _UsageError(f"{path}: invalid {name}: {_first_error(exc)}") from exc
    payload = {"ok": True, "exit_code": EXIT_GO, "file": str(path), "type": name, "valid": True}
    _emit(args, payload, f"{path}: valid {name}")
    return EXIT_GO


def _cmd_schema(args: argparse.Namespace) -> int:
    models = _models()
    if args.list:
        names = sorted(models)
        _emit(args, {"ok": True, "exit_code": EXIT_GO, "models": names}, "\n".join(names))
        return EXIT_GO
    name = args.model or "AssessmentResult"
    if name not in models:
        raise _UsageError(f"unknown model {name!r}; choose one of {', '.join(sorted(models))}")
    schema = models[name].model_json_schema(by_alias=True, mode="validation")
    sys.stdout.write(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    return EXIT_GO


# --------------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    from . import __version__

    fmt = argparse.RawDescriptionHelpFormatter
    common = _Parser(add_help=False)
    common.add_argument("--json", action="store_true",
                        help="print one machine-readable JSON object on stdout instead of text")
    common.add_argument("--debug", action="store_true", help="show tracebacks and debug logging on errors")

    p = _Parser(
        prog="slicepoint",
        description="SlicePoint: check whether an imaging AI fits your patients and scanners before you turn it on. "
                    "Compares your site's curated data with a reference and writes a GO / BORDERLINE / NO-GO "
                    "verdict, a result JSON and a self-contained HTML report.",
        epilog=_MAIN_EPILOG,
        formatter_class=fmt,
    )
    p.add_argument("--version", action="version", version=f"slicepoint-core {__version__}")
    sub = p.add_subparsers(dest="command", metavar="COMMAND", parser_class=_Parser)
    sub.required = True

    ref = sub.add_parser("reference", help="build a reference profile", description="Reference profiles.",
                         formatter_class=fmt)
    ref_sub = ref.add_subparsers(dest="ref_command", metavar="ACTION", parser_class=_Parser)
    ref_sub.required = True
    build = ref_sub.add_parser(
        "build", parents=[common], formatter_class=fmt,
        help="fit a reference profile from a data folder and save it",
        description="Fit a reference profile (category mixes, distributions, embedding coverage, reference "
                    "performance) from one site's data folder and save it as reference.json + "
                    "reference_arrays.npz. Build it once from the validated population, then reuse it.",
        epilog="example:\n  slicepoint reference build --data data/practice/hospital_a --site-id hospital_a "
               "--out refs/hospital_a\n\n" + _DATA_TEXT + "\n" + _EXIT_TEXT,
    )
    build.add_argument("--data", required=True, metavar="DIR", help="the reference site's data folder")
    build.add_argument("--site-id", "--reference-site-id", dest="site_id", required=True, metavar="ID",
                       help="stable id of the reference site, e.g. hospital_a (required; never guessed from the "
                            "folder)")
    build.add_argument("--out", required=True, metavar="PROFILE_DIR", help="folder to write the profile into")
    build.add_argument("--reference-id", metavar="ID", default=None, help="id to record (default ref-<site-id>)")
    build.add_argument("--profile", metavar="FILE", default=None,
                       help="threshold profile JSON (default: the built-in hackathon-default-v0)")
    build.add_argument("--on-inconsistency", choices=("raise", "drop_and_note"), default="raise",
                       help="if the parquet files disagree on case_ids: stop (raise, default) or drop those "
                            "cases and record a note (drop_and_note)")
    build.set_defaults(func=_cmd_reference_build)

    a = sub.add_parser(
        "assess", parents=[common], formatter_class=fmt,
        help="assess a site against a reference and write the verdict and report",
        description="Assess one site's data folder against a reference. Writes the versioned AssessmentResult "
                    "JSON (--out) and optionally the HTML report (--html) and the POC viewer JSON (--legacy-json).",
        epilog=_ASSESS_EPILOG,
    )
    a.add_argument("--data", required=True, metavar="DIR", help="your site's data folder")
    a.add_argument("--site-id", required=True, metavar="ID", help="stable id for your site, e.g. hospital_b")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--reference-profile", metavar="PROFILE_DIR",
                   help="a saved reference profile (from `slicepoint reference build`)")
    g.add_argument("--reference-dir", metavar="DIR", help="a reference data folder; the profile is built on the fly")
    a.add_argument("--reference-site-id", metavar="ID", default=None,
                   help="stable id of the reference site; required with --reference-dir (never guessed)")
    a.add_argument("--site-name", metavar="NAME", default=None,
                   help="readable name for your site, shown in the report title and stored in the result "
                        "(default: the site id made readable, e.g. hospital_b -> Hospital B)")
    a.add_argument("--profile", metavar="FILE", default=None,
                   help="threshold profile JSON (default: the built-in hackathon-default-v0)")
    a.add_argument("--on-inconsistency", choices=("raise", "drop_and_note"), default="raise",
                   help="if the parquet files disagree on case_ids: stop (default) or drop and note")
    a.add_argument("--out", required=True, metavar="RESULT_JSON", help="where to write the AssessmentResult JSON")
    a.add_argument("--html", metavar="REPORT_HTML", default=None, help="also write the self-contained HTML report")
    a.add_argument("--legacy-json", metavar="POC_JSON", default=None,
                   help="also write the POC viewer's <hospital>_slicepoint.json")
    a.add_argument("--hospital-name", metavar="NAME", default=None,
                   help="display name for --legacy-json (default: --site-name, else the site id)")
    a.add_argument("--viewer", action="store_true",
                   help="also write the interactive viewer (slicepoint-viewer.html) next to --out; open it "
                        "in a browser and drop result.json onto it (it makes no network requests)")
    a.add_argument("--show-provisional-scores", action="store_true",
                   help="keep the unvalidated 0-100 scores in result.json and show them in the report and summary "
                        "(left out by default; ADR 0001: not for hospitals until ratified)")
    a.set_defaults(func=_cmd_assess)

    v = sub.add_parser(
        "validate", parents=[common], formatter_class=fmt,
        help="validate a result, profile or legacy POC JSON file",
        description="Validate a JSON file against its SlicePoint contract. The type is detected from the file "
                    "(AssessmentResult, ThresholdProfile, reference.json, or a legacy POC file: "
                    "SlicePointFileV0, MonthlySummaryV0, DiceSummaryV0, CompareResponseV1); --type forces one.",
        epilog="examples:\n  slicepoint validate out/result.json\n"
               "  slicepoint validate hospital_b_slicepoint.json --json\n\n" + _EXIT_TEXT,
    )
    v.add_argument("file", metavar="FILE")
    v.add_argument("--type", metavar="MODEL", default=None, help="model name to validate against")
    v.set_defaults(func=_cmd_validate)

    sc = sub.add_parser(
        "schema", parents=[common], formatter_class=fmt,
        help="print the JSON Schema of a contract model",
        description="Print the JSON Schema of a SlicePoint contract model (default AssessmentResult).",
        epilog="examples:\n  slicepoint schema\n  slicepoint schema FeatureRow\n  slicepoint schema --list\n\n"
               + _EXIT_TEXT,
    )
    sc.add_argument("model", nargs="?", metavar="MODEL", default=None)
    sc.add_argument("--list", action="store_true", help="list the model names")
    sc.set_defaults(func=_cmd_schema)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    debug = bool(getattr(args, "debug", False))
    logging.basicConfig(level=logging.DEBUG if debug else logging.WARNING, format="slicepoint: %(message)s",
                        stream=sys.stderr)
    func: Callable[[argparse.Namespace], int] = args.func
    try:
        return func(args)
    except _UsageError as exc:
        return _fail(args, EXIT_INPUT, str(exc), debug)
    except KeyboardInterrupt:
        return _fail(args, EXIT_INPUT, "interrupted", debug)
    except Exception as exc:  # noqa: BLE001 - every unexpected error becomes exit 2 with one line
        msg = f"internal error: {type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}"
        if not debug:
            msg += " (rerun with --debug for the traceback)"
        return _fail(args, EXIT_INTERNAL, msg, debug)


def _fail(args: argparse.Namespace, code: int, message: str, debug: bool) -> int:
    if debug:
        traceback.print_exc()
    one_line = " ".join(message.split())
    sys.stderr.write(f"slicepoint: error: {one_line}\n")
    if getattr(args, "json", False):
        sys.stdout.write(json.dumps({"ok": False, "exit_code": code, "error": one_line}) + "\n")
    return code


def entry_point() -> NoReturn:
    sys.exit(main())


if __name__ == "__main__":  # pragma: no cover
    entry_point()
