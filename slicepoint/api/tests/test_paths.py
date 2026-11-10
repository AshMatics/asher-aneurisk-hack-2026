"""Dataset names: relative to the data root only, no traversal, no symlink escape, no path disclosure."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import AUTH, make_client
from slicepoint_api.datasets import DatasetPathError, list_datasets, resolve_dataset


@pytest.fixture()
def tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "data_root_secret"
    (root / "site_a").mkdir(parents=True)
    (root / "site_a" / "features.parquet").write_bytes(b"")
    (root / "group" / "site_b").mkdir(parents=True)
    (root / "group" / "site_b" / "features.parquet").write_bytes(b"")
    outside = tmp_path / "outside_secret"
    outside.mkdir()
    (outside / "features.parquet").write_bytes(b"")
    (root / "escape").symlink_to(outside, target_is_directory=True)
    (root / "inside_link").symlink_to(root / "site_a", target_is_directory=True)
    return root.resolve(), outside, tmp_path / "results"


BAD_NAMES = ["/etc", "/etc/passwd", "../outside_secret", "site_a/../../outside_secret", "..", ".", "",
             "site_a/", "~/x", "a\\b", "a//b", " site_a"]


@pytest.mark.parametrize("name", BAD_NAMES)
def test_resolve_rejects_unsafe_names(tree: tuple[Path, Path, Path], name: str) -> None:
    root, _, _ = tree
    with pytest.raises(DatasetPathError) as info:
        resolve_dataset(root, name)
    assert str(root) not in str(info.value)


def test_resolve_rejects_symlink_escape(tree: tuple[Path, Path, Path]) -> None:
    root, outside, _ = tree
    with pytest.raises(DatasetPathError) as info:
        resolve_dataset(root, "escape")
    assert str(outside) not in str(info.value) and str(root) not in str(info.value)


def test_resolve_accepts_folders_under_the_root(tree: tuple[Path, Path, Path]) -> None:
    root, _, _ = tree
    assert resolve_dataset(root, "site_a") == root / "site_a"
    assert resolve_dataset(root, "group/site_b") == root / "group" / "site_b"
    assert resolve_dataset(root, "inside_link") == root / "site_a"  # a symlink that stays inside is fine


def test_listing_never_follows_symlinks_out(tree: tuple[Path, Path, Path]) -> None:
    root, _, _ = tree
    assert list_datasets(root) == ["group/site_b", "site_a"]


@pytest.mark.parametrize("name", [*BAD_NAMES, "escape", "missing"])
def test_api_rejects_unsafe_names_without_disclosing_paths(tree: tuple[Path, Path, Path], name: str) -> None:
    root, outside, results = tree
    with make_client(root, results) as c:
        for body in ({"dataset": name, "site_id": "hospital_b", "reference_id": "ref-hospital_a"},
                     {"dataset": "site_a", "site_id": "hospital_b", "reference_dataset": name,
                      "reference_site_id": "hospital_a"}):
            r = c.post("/v1/assessments", headers=AUTH, json=body)
            assert r.status_code in (400, 422), (name, r.status_code)
            assert str(root) not in r.text and str(outside) not in r.text
            assert "secret" not in r.text
        r = c.post("/v1/references", headers=AUTH, json={"dataset": name, "site_id": "hospital_a"})
        assert r.status_code in (400, 422) and "secret" not in r.text


def test_api_lists_dataset_names_only(tree: tuple[Path, Path, Path]) -> None:
    root, _, results = tree
    with make_client(root, results) as c:
        r = c.get("/v1/datasets", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"datasets": ["group/site_b", "site_a"]}
    assert "secret" not in r.text


def test_bad_ids_in_the_url_are_422(tree: tuple[Path, Path, Path]) -> None:
    root, _, results = tree
    with make_client(root, results) as c:
        assert c.get("/v1/assessments/..%2F..%2Fetc", headers=AUTH).status_code in (404, 422)
        assert c.get("/v1/assessments/not-a-job", headers=AUTH).status_code == 422
        assert c.get("/v1/references/UPPER", headers=AUTH).status_code == 422
        assert c.get("/v1/assessments/" + "0" * 32, headers=AUTH).status_code == 404
        assert c.get("/v1/references/ref-none", headers=AUTH).status_code == 404


def test_default_reference_id_fits_a_max_length_site_id(tmp_path: Path) -> None:
    """``ref-<site_id>`` for a 64-character site id is a valid stored reference id (not a 500)."""
    from slicepoint_api.references import ReferenceStore

    site_id = "s" * 64
    store = ReferenceStore(tmp_path)
    assert store.path(f"ref-{site_id}").name == f"ref-{site_id}"
    assert not store.exists(f"ref-{site_id}")
