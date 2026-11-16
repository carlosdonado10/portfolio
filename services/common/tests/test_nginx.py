from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from orch_common.cli import main
from orch_common.manifest import Manifest, load_manifests
from orch_common.nginx import render_projects_conf

BODY = """
id = "{id}"
name = "Demo"
compose = "docker-compose.yml"
expected_boot_s = 30
entry = {{ service = "web", port = {port} }}
health = {{ path = "/healthz" }}
"""


def make(root: Path, id_: str, port: int = 8000) -> None:
    d = root / id_
    d.mkdir(parents=True)
    (d / "stack.toml").write_text(BODY.format(id=id_, port=port))
    (d / "docker-compose.yml").write_text("services: {}\n")


def manifests(tmp_path: Path) -> list[Manifest]:
    make(tmp_path, "fast", 8000)
    make(tmp_path, "slow-two", 9000)
    return load_manifests(tmp_path)


def test_render_contains_location_gate_and_interstitial_per_manifest(tmp_path: Path) -> None:
    out = render_projects_conf(manifests(tmp_path))
    assert "location /p/fast/ {" in out
    assert "auth_request /_gate/fast;" in out
    assert "error_page 401 = @interstitial_fast;" in out
    assert "set $up_fast http://fast-entry:8000;" in out
    assert "proxy_pass $up_fast;" in out
    assert "proxy_set_header X-Forwarded-Prefix /p/fast;" in out
    assert "include /etc/nginx/snippets/project-proxy.conf;" in out
    assert "location = /_gate/fast {" in out
    assert "proxy_pass http://control-plane:8000/internal/gate/fast;" in out
    assert "location @interstitial_fast { return 302 /lab/p/fast; }" in out
    # hyphenated ids: variable name uses underscores, everything else keeps the hyphen
    assert "set $up_slow_two http://slow-two-entry:9000;" in out
    assert "auth_request /_gate/slow-two;" in out
    assert "location @interstitial_slow_two { return 302 /lab/p/slow-two; }" in out


def test_render_is_deterministic(tmp_path: Path) -> None:
    ms = manifests(tmp_path)
    assert render_projects_conf(ms) == render_projects_conf(list(ms))


@pytest.mark.parametrize(
    ("id_", "port"),
    [("a; evil", 1), ("A", 1), ("-x", 1), ("a" * 41, 1), ("ok", "80; x"), ("ok", True), ("ok", 0)],
)
def test_render_rejects_unsafe_values(id_: str, port: Any) -> None:
    fake = SimpleNamespace(id=id_, entry=SimpleNamespace(port=port))
    with pytest.raises(ValueError):
        render_projects_conf([cast(Manifest, fake)])


def test_render_writes_atomically_and_header(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    make(projects, "fast")
    out = tmp_path / "nested" / "generated" / "projects.conf"
    assert main(["render-nginx", "--projects", str(projects), "--out", str(out)]) == 0
    text = out.read_text()
    assert text.startswith("# ")
    assert "orchctl render-nginx" in text.splitlines()[0]
    assert "do not edit" in text.splitlines()[0].lower()
    assert "location /p/fast/ {" in text
    assert [p.name for p in out.parent.iterdir()] == ["projects.conf"]  # no temp left behind


def test_render_to_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make(tmp_path, "fast")
    assert main(["render-nginx", "--projects", str(tmp_path), "--out", "-"]) == 0
    assert "location /p/fast/ {" in capsys.readouterr().out
