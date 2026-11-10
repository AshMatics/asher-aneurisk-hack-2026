"""The ``slicepoint`` command line (milestone 2). Most tests run it as a subprocess."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest
from slicepoint_schemas import HACKATHON_DEFAULT_PROFILE, AssessmentResult

from conftest import LEGACY_DIR, PRACTICE_DIR, needs_data
from slicepoint_core import Assessment, ParquetAdapter, ReferenceProfile, cli, strip_provisional_scores

CLI = [sys.executable, "-m", "slicepoint_core.cli"]


def run(*args: str | Path, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([*CLI, *map(str, args)], capture_output=True, text=True, cwd=cwd, timeout=300)


def _one_line_error(proc: subprocess.CompletedProcess[str]) -> str:
    assert "Traceback" not in proc.stderr
    lines = [ln for ln in proc.stderr.splitlines() if ln.startswith("slicepoint: error:")]
    assert len(lines) == 1, proc.stderr
    return lines[0]


@pytest.fixture(scope="module")
def ref_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not (PRACTICE_DIR / "hospital_a").exists():
        pytest.skip("practice data not present")
    out = tmp_path_factory.mktemp("refs") / "hospital_a"
    proc = run("reference", "build", "--data", PRACTICE_DIR / "hospital_a", "--site-id", "hospital_a", "--out", out)
    assert proc.returncode == 0, proc.stderr
    assert (out / "reference.json").is_file() and (out / "reference_arrays.npz").is_file()
    return out


def test_console_script_is_declared() -> None:
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert 'slicepoint = "slicepoint_core.cli:entry_point"' in text


def test_help_documents_exit_codes_and_layout() -> None:
    proc = run("--help")
    assert proc.returncode == 0
    for text in ("exit codes:", "0  ran, and the verdict is GO", "3  ran fine", "1  usage or input error",
                 "2  internal failure", "features.parquet", "slicepoint assess"):
        assert text in proc.stdout
    sub = run("assess", "--help")
    assert sub.returncode == 0 and "--reference-profile" in sub.stdout and '"failing_sub_factors"' in sub.stdout


def test_usage_error_is_exit_1_not_2() -> None:
    proc = run("assess", "--data", "x", "--out", "y.json")
    assert proc.returncode == cli.EXIT_INPUT
    assert "required" in proc.stderr and "Traceback" not in proc.stderr


@needs_data
def test_assess_json_summary_and_outputs(ref_dir: Path, tmp_path: Path) -> None:
    out, html, legacy = tmp_path / "out" / "result.json", tmp_path / "out" / "report.html", tmp_path / "poc.json"
    proc = run("assess", "--data", PRACTICE_DIR / "hospital_b", "--site-id", "hospital_b",
               "--reference-profile", ref_dir, "--out", out, "--html", html, "--legacy-json", legacy, "--json")
    assert proc.returncode == cli.EXIT_REVIEW, proc.stderr
    s: dict[str, Any] = json.loads(proc.stdout)
    assert s["ok"] is True and s["exit_code"] == 3 and s["verdict"] == "no_go" and s["site_id"] == "hospital_b"
    assert [c["id"] for c in s["checks"]] == ["repeats", "scanning", "patients", "labels", "accuracy"]
    for c in s["checks"]:
        assert {"id", "status", "n", "n_effective", "failing_sub_factors"} <= set(c)
        assert "provisional_score" not in c
    repeats = s["checks"][0]
    assert repeats == {"id": "repeats", "title": "Different people", "status": "problem", "n": 80,
                       "n_effective": 32.0, "failing_sub_factors": ["people", "leakage"]}
    assert s["outputs"] == {"result": str(out), "html": str(html), "legacy_json": str(legacy)}
    assert s["skipped_steps"] == ["segmentation"] and s["failed_steps"] == []
    result = AssessmentResult.model_validate_json(out.read_text(encoding="utf-8"))
    assert result.verdict.outcome.value == "no_go"
    raw = json.loads(out.read_text(encoding="utf-8"))
    assert all("score" not in r and "score_method" not in r for r in raw["verdict"]["results"])
    assert "provisional-v0" not in out.read_text(encoding="utf-8")
    assert result.thresholds is not None and result.thresholds.profile_id == result.profile_id
    assert result.strata is not None and result.cases_to_review is not None
    doc = html.read_text(encoding="utf-8")
    assert "https://" not in doc and "http://" not in doc and "provisional-v0" not in doc
    assert "<h1>SlicePoint fit check: Hospital B</h1>" in doc
    assert run("validate", legacy).returncode == 0
    # The POC export never carries provisional scores (its findings are check/status/sentence).
    assert "score" not in legacy.read_text(encoding="utf-8").lower()
    # The written file must satisfy the published JSON Schema, not only Pydantic (which also
    # accepts field names where the schema requires aliases).
    import jsonschema

    schema_path = Path(__file__).resolve().parents[2] / "schemas" / "jsonschema" / "AssessmentResult.schema.json"
    jsonschema.validate(raw, json.loads(schema_path.read_text(encoding="utf-8")))


@needs_data
def test_cli_and_library_give_the_same_result(ref_dir: Path, tmp_path: Path) -> None:
    """No forked logic: the CLI result equals a direct library run, apart from the timestamp."""
    out = tmp_path / "r.json"
    proc = run("assess", "--data", PRACTICE_DIR / "hospital_c", "--site-id", "hospital_c",
               "--reference-profile", ref_dir, "--out", out)
    assert proc.returncode == cli.EXIT_REVIEW, proc.stderr
    assert "Verdict: NO-GO" in proc.stdout and "Exit 3" in proc.stdout
    via_cli = AssessmentResult.model_validate_json(out.read_text(encoding="utf-8"))
    site = ParquetAdapter("hospital_c").load_tabular(PRACTICE_DIR / "hospital_c")
    direct = strip_provisional_scores(Assessment(site, ReferenceProfile.load(ref_dir), HACKATHON_DEFAULT_PROFILE,
                                                 now=via_cli.generated_at).run().result)
    assert via_cli.model_dump(exclude={"steps"}) == direct.model_dump(exclude={"steps"})
    assert [(s.step, s.state) for s in via_cli.steps] == [(s.step, s.state) for s in direct.steps]


@needs_data
def test_go_verdict_exits_0(tmp_path: Path) -> None:
    """hospital_a against itself is only borderline (2 measurement outliers); relaxing the
    outlier rule in a profile file makes every check ok, so the CLI exits 0."""
    params = dict(HACKATHON_DEFAULT_PROFILE.parameters, outlier_sd_multiple=10.0)
    relaxed = HACKATHON_DEFAULT_PROFILE.model_copy(update={"profile_id": "test-relaxed", "parameters": params})
    prof = tmp_path / "profile.json"
    prof.write_text(relaxed.model_dump_json(), encoding="utf-8")
    proc = run("assess", "--data", PRACTICE_DIR / "hospital_a", "--site-id", "hospital_a",
               "--reference-dir", PRACTICE_DIR / "hospital_a", "--reference-site-id", "hospital_a",
               "--site-name", "Reference General", "--html", tmp_path / "r.html",
               "--profile", prof, "--out", tmp_path / "r.json", "--json", "--show-provisional-scores")
    assert proc.returncode == cli.EXIT_GO, proc.stdout + proc.stderr
    s = json.loads(proc.stdout)
    assert s["verdict"] == "go" and s["profile_id"] == "test-relaxed"
    assert all(c["status"] == "ok" and "provisional_score" in c for c in s["checks"])
    # --show-provisional-scores keeps the scores in result.json too
    result = AssessmentResult.model_validate_json((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert all(r.score is not None and r.score_method == "provisional-v0" for r in result.verdict.results)
    # the result records the custom profile, and the report reads it from there
    assert result.thresholds == relaxed and result.site_name == "Reference General"
    doc = (tmp_path / "r.html").read_text(encoding="utf-8")
    assert "<h1>SlicePoint fit check: Reference General</h1>" in doc and "test-relaxed" in doc


@needs_data
def test_reference_dir_without_reference_site_id_is_exit_1(tmp_path: Path) -> None:
    for extra in ([], ["--json"]):
        proc = run("assess", "--data", PRACTICE_DIR / "hospital_b", "--site-id", "hospital_b",
                   "--reference-dir", PRACTICE_DIR / "hospital_a", "--out", tmp_path / "r.json", *extra)
        assert proc.returncode == cli.EXIT_INPUT
        assert "--reference-dir needs --reference-site-id" in _one_line_error(proc)
        assert not (tmp_path / "r.json").exists()
    # reference build: the site id is required (--reference-site-id is an alias of --site-id)
    proc = run("reference", "build", "--data", PRACTICE_DIR / "hospital_a", "--out", tmp_path / "ref")
    assert proc.returncode == cli.EXIT_INPUT and "Traceback" not in proc.stderr
    assert "--site-id/--reference-site-id" in proc.stderr and "required" in proc.stderr
    assert not (tmp_path / "ref").exists()


@needs_data
def test_reference_build_accepts_reference_site_id(tmp_path: Path) -> None:
    proc = run("reference", "build", "--data", PRACTICE_DIR / "hospital_a", "--reference-site-id", "hospital_a",
               "--out", tmp_path / "ref", "--json")
    assert proc.returncode == cli.EXIT_GO, proc.stderr
    assert json.loads(proc.stdout)["site_id"] == "hospital_a"


def test_help_says_reference_site_id_is_required() -> None:
    out = " ".join(run("assess", "--help").stdout.split())
    assert "required with --reference-dir" in out and "default: reference" not in out
    assert "--site-name" in out


@needs_data
def test_missing_folder_is_a_clear_one_liner(ref_dir: Path, tmp_path: Path) -> None:
    missing = tmp_path / "no_such_site"
    proc = run("assess", "--data", missing, "--site-id", "hospital_b", "--reference-profile", ref_dir,
               "--out", tmp_path / "r.json")
    assert proc.returncode == cli.EXIT_INPUT
    line = _one_line_error(proc)
    assert str(missing) in line and "folder not found" in line
    assert not (tmp_path / "r.json").exists()


@needs_data
def test_missing_reference_profile_is_exit_1(tmp_path: Path) -> None:
    proc = run("assess", "--data", PRACTICE_DIR / "hospital_b", "--site-id", "hospital_b",
               "--reference-profile", tmp_path / "nope", "--out", tmp_path / "r.json", "--json")
    assert proc.returncode == cli.EXIT_INPUT
    assert "reference profile folder not found" in _one_line_error(proc)
    err = json.loads(proc.stdout)
    assert err["ok"] is False and err["exit_code"] == 1 and "nope" in err["error"]


def _copy_site(tmp_path: Path, site: str = "hospital_b") -> Path:
    dst = tmp_path / site
    shutil.copytree(PRACTICE_DIR / site, dst)
    return dst


@needs_data
def test_missing_column_names_file_and_column(ref_dir: Path, tmp_path: Path) -> None:
    site = _copy_site(tmp_path)
    feats = pq.read_table(site / "features.parquet")
    pq.write_table(feats.drop_columns(["age_band"]), site / "features.parquet")
    proc = run("assess", "--data", site, "--site-id", "hospital_b", "--reference-profile", ref_dir,
               "--out", tmp_path / "r.json")
    assert proc.returncode == cli.EXIT_INPUT
    line = _one_line_error(proc)
    assert str(site / "features.parquet") in line and "missing required column 'age_band'" in line


@needs_data
def test_bad_value_names_row_and_column(ref_dir: Path, tmp_path: Path) -> None:
    site = _copy_site(tmp_path)
    preds = pq.read_table(site / "predictions.parquet")
    renamed = preds.rename_columns(["pred_dice" if c == "pred_aorta_dice" else c for c in preds.column_names])
    pq.write_table(renamed, site / "predictions.parquet")
    proc = run("assess", "--data", site, "--site-id", "hospital_b", "--reference-profile", ref_dir,
               "--out", tmp_path / "r.json")
    assert proc.returncode == cli.EXIT_INPUT
    line = _one_line_error(proc)
    assert "predictions.parquet" in line and "'pred_aorta_dice'" in line


@needs_data
def test_inconsistent_case_ids_suggest_drop_and_note(ref_dir: Path, tmp_path: Path) -> None:
    site = _copy_site(tmp_path)
    labels = pq.read_table(site / "labels.parquet")
    pq.write_table(labels.slice(1), site / "labels.parquet")
    base: list[str | Path] = ["assess", "--data", site, "--site-id", "hospital_b", "--reference-profile", ref_dir,
            "--out", tmp_path / "r.json"]
    proc = run(*base)
    assert proc.returncode == cli.EXIT_INPUT
    assert "labels.parquet" in _one_line_error(proc) and "drop_and_note" in proc.stderr
    assert run(*base, "--on-inconsistency", "drop_and_note").returncode == cli.EXIT_REVIEW


def test_validate_detects_types(tmp_path: Path) -> None:
    legacy = sorted(LEGACY_DIR.glob("*_slicepoint.json"))
    if not legacy:
        pytest.skip("legacy POC outputs not present")
    proc = run("validate", legacy[0], "--json")
    assert proc.returncode == 0 and json.loads(proc.stdout)["type"] == "SlicePointFileV0"
    prof = tmp_path / "p.json"
    prof.write_text(HACKATHON_DEFAULT_PROFILE.model_dump_json(), encoding="utf-8")
    assert "valid ThresholdProfile" in run("validate", prof).stdout
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"result_type": "slicepoint.assessment_result", "site_id": "x"}), encoding="utf-8")
    proc = run("validate", bad)
    assert proc.returncode == cli.EXIT_INPUT and "invalid AssessmentResult" in _one_line_error(proc)
    unknown = tmp_path / "u.json"
    unknown.write_text("{}", encoding="utf-8")
    assert "--type" in _one_line_error(run("validate", unknown))
    notjson = tmp_path / "n.json"
    notjson.write_text("{", encoding="utf-8")
    assert run("validate", notjson).returncode == cli.EXIT_INPUT


def test_schema_prints_json_schema() -> None:
    proc = run("schema")
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["title"] == "AssessmentResult"
    assert "FeatureRow" in run("schema", "--list").stdout
    assert json.loads(run("schema", "ThresholdProfile").stdout)["title"] == "ThresholdProfile"
    assert run("schema", "Nope").returncode == cli.EXIT_INPUT


@needs_data
def test_internal_failure_is_exit_2_without_traceback(
    ref_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(self: Assessment) -> None:
        raise RuntimeError("simulated bug")

    monkeypatch.setattr(Assessment, "run", boom)
    args = ["assess", "--data", str(PRACTICE_DIR / "hospital_b"), "--site-id", "hospital_b",
            "--reference-profile", str(ref_dir), "--out", str(tmp_path / "r.json")]
    assert cli.main(args) == cli.EXIT_INTERNAL
    err = capsys.readouterr().err
    assert "internal error: RuntimeError: simulated bug" in err and "--debug" in err and "Traceback" not in err
    assert cli.main([*args, "--debug"]) == cli.EXIT_INTERNAL
    assert "Traceback" in capsys.readouterr().err
