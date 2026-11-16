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
    assert "set $gate_fast http://control-plane:8000/internal/gate/fast;" in out
    assert "proxy_pass $gate_fast;" in out
    assert "proxy_pass http://control-plane" not in out  # resolved per request, not at start
    assert "error_page 500 502 503 504 = @interstitial_fast;" in out
    assert "proxy_set_header X-Real-IP $remote_addr;" in out
    assert "location @interstitial_fast { return 302 /lab/p/fast; }" in out
    # hyphenated ids: variable name uses underscores, everything else keeps the hyphen
    assert "set $up_slow_two http://slow-two-entry:9000;" in out
    assert "auth_request /_gate/slow-two;" in out
    assert "set $gate_slow_two http://control-plane:8000/internal/gate/slow-two;" in out
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
    assert out.stat().st_mode & 0o777 == 0o644
    assert [p.name for p in out.parent.iterdir()] == ["projects.conf"]  # no temp left behind


def test_render_to_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make(tmp_path, "fast")
    assert main(["render-nginx", "--projects", str(tmp_path), "--out", "-"]) == 0
    assert "location /p/fast/ {" in capsys.readouterr().out


def test_render_redirects_bare_project_path_to_trailing_slash(tmp_path: Path) -> None:
    out = render_projects_conf(manifests(tmp_path))
    assert "location = /p/fast { return 301 /p/fast/; }" in out
    assert "location = /p/slow-two { return 301 /p/slow-two/; }" in out


# -- static gateway config ---------------------------------------------------

PROXY = Path(__file__).resolve().parents[3] / "infra" / "proxy"


def _strip_maps() -> list[tuple[str, str, str, str]]:
    """(source var, target var, regex, replacement) for each cookie-stripping map."""
    import re

    conf = (PROXY / "nginx.conf").read_text()
    blocks = re.findall(
        r"map \$(\w+) \$(project_cookie\w*) \{\s*default \$\w+;\s*\"~(.+?)\"\s+\"(.+?)\";\s*\}",
        conf,
    )
    return [(src, dst, rx, rep) for src, dst, rx, rep in blocks]


def _apply_maps(cookie: str) -> str:
    import re

    values = {"http_cookie": cookie}
    for src, dst, rx, rep in _strip_maps():
        value = values[src]
        m = re.search(rx, value)
        # nginx: $1/$2 refer to the regex captures; no match falls back to default.
        values[dst] = rep.replace("$1", m.group(1)).replace("$2", m.group(2)) if m else value
    return values["project_cookie"]


@pytest.mark.parametrize(
    ("cookie", "expected"),
    [
        ("orch_sid=abc", ""),
        ("x=1; orch_sid=abc; y=2", "x=1; y=2"),
        ("orch_sid=abc; x=1", "x=1"),
        ("x=1; orch_admin=zz; orch_sid=abc", "x=1; "),
        ("orch_admin=zz; theme=dark; orch_sid=abc", "theme=dark; "),
        ("theme=dark", "theme=dark"),
        ("myorch_sid=keep", "myorch_sid=keep"),
        ("", ""),
    ],
)
def test_project_upstreams_never_see_orch_cookies(cookie: str, expected: str) -> None:
    assert len(_strip_maps()) == 2  # orch_sid and a legacy Path=/ orch_admin
    assert _apply_maps(cookie) == expected


def test_project_snippet_forwards_stripped_cookie_and_gate_keeps_full_cookie(
    tmp_path: Path,
) -> None:
    snippet = (PROXY / "snippets" / "project-proxy.conf").read_text()
    assert "proxy_set_header Cookie $project_cookie;" in snippet
    gate = render_projects_conf(manifests(tmp_path)).split("location = /_gate/fast {")[1]
    assert "proxy_set_header Cookie $http_cookie;" in gate.split("}")[0]


def test_gateway_resolver_ttl_is_short() -> None:
    conf = (PROXY / "nginx.conf").read_text()
    assert "resolver 127.0.0.11 valid=2s ipv6=off;" in conf
    assert "# set_real_ip_from" in conf
    assert "# real_ip_header" in conf
