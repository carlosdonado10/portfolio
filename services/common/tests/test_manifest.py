from pathlib import Path

import pytest
from orch_common.manifest import ManifestError, load_manifests

BODY = """
id = "{id}"
name = "Demo"
compose = "docker-compose.yml"
expected_boot_s = 30
{extra}
entry = {{ service = "web", port = 8000 }}
health = {{ path = "/healthz" }}
"""


def write(root: Path, folder: str, id_: str, extra: str = "", compose: bool = True) -> Path:
    d = root / folder
    d.mkdir(parents=True)
    (d / "stack.toml").write_text(BODY.format(id=id_, extra=extra))
    if compose:
        (d / "docker-compose.yml").write_text("services: {}\n")
    return d


def test_loads_valid_manifest(tmp_path: Path) -> None:
    write(tmp_path, "demo", "demo")
    (m,) = load_manifests(tmp_path)
    assert m.id == "demo"
    assert m.base_path == "/p/demo/"
    assert m.project_name == "orch-demo"
    assert m.entry_alias == "demo-entry"
    assert m.health.timeout_s == 180
    assert m.dir == tmp_path / "demo"
    assert "dir" not in m.model_dump()
    assert "hidden" not in m.model_dump()
    assert m.compose_path(Path("/srv/r")) == tmp_path / "demo" / "docker-compose.yml"


def test_missing_projects_dir_is_empty(tmp_path: Path) -> None:
    assert load_manifests(tmp_path / "nope") == []


def test_rejects_bad_id(tmp_path: Path) -> None:
    write(tmp_path, "Bad_ID", "Bad_ID")
    with pytest.raises(ManifestError):
        load_manifests(tmp_path)


def test_rejects_folder_id_mismatch(tmp_path: Path) -> None:
    write(tmp_path, "foo", "bar")
    with pytest.raises(ManifestError):
        load_manifests(tmp_path)


def test_rejects_missing_compose_file(tmp_path: Path) -> None:
    write(tmp_path, "demo", "demo", compose=False)
    with pytest.raises(ManifestError):
        load_manifests(tmp_path)


def test_rejects_unknown_key(tmp_path: Path) -> None:
    write(tmp_path, "demo", "demo", extra="bogus = 1")
    with pytest.raises(ManifestError, match=r"stack\.toml"):
        load_manifests(tmp_path)


def test_rejects_invalid_toml(tmp_path: Path) -> None:
    d = tmp_path / "demo"
    d.mkdir()
    (d / "stack.toml").write_text("id = = broken")
    with pytest.raises(ManifestError, match=r"stack\.toml"):
        load_manifests(tmp_path)


def test_repo_manifest_paths(tmp_path: Path) -> None:
    write(tmp_path, "demo", "demo", extra='repo = "https://x/y.git"', compose=False)
    (m,) = load_manifests(tmp_path)
    assert m.compose_path(Path("/srv/r")) == Path("/srv/r/demo/docker-compose.yml")
    assert m.checkout_dir(Path("/srv/r")) == Path("/srv/r/demo")


def test_rejects_duplicate_ids(tmp_path: Path) -> None:
    write(tmp_path, "demo", "demo")
    write(tmp_path, "_examples/demo", "demo")
    with pytest.raises(ManifestError, match="duplicate"):
        load_manifests(tmp_path, include_hidden=True)


def test_hidden_excluded_by_default(tmp_path: Path) -> None:
    write(tmp_path, "_examples/fast", "fast")
    assert load_manifests(tmp_path) == []
    (m,) = load_manifests(tmp_path, include_hidden=True)
    assert m.id == "fast"
    assert m.hidden is True


def test_sorted_by_order_then_id(tmp_path: Path) -> None:
    write(tmp_path, "b", "b", extra="order = 1")
    write(tmp_path, "a", "a", extra="order = 5")
    write(tmp_path, "c", "c", extra="order = 1")
    assert [m.id for m in load_manifests(tmp_path)] == ["b", "c", "a"]


def test_id_length_cap(tmp_path: Path) -> None:
    ok = "a" * 40
    write(tmp_path, ok, ok)
    assert [m.id for m in load_manifests(tmp_path)] == [ok]
    bad = "b" * 41
    write(tmp_path, bad, bad)
    with pytest.raises(ManifestError):
        load_manifests(tmp_path)
