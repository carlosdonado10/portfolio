from pathlib import Path

import pytest
from orch_common.cli import main

BODY = """
id = "{id}"
name = "Demo"
compose = "docker-compose.yml"
expected_boot_s = 30
{extra}
entry = {{ service = "web", port = 8000 }}
health = {{ path = "/healthz" }}
"""


def make(root: Path, id_: str, extra: str = "") -> Path:
    d = root / id_
    d.mkdir(parents=True)
    (d / "stack.toml").write_text(BODY.format(id=id_, extra=extra))
    (d / "docker-compose.yml").write_text("services: {}\n")
    return d


class Recorder:
    def __init__(self, fail_on: int | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, argv: list[str]) -> None:
        self.calls.append(argv)
        if self.fail_on is not None and len(self.calls) == self.fail_on:
            raise RuntimeError("boom")


def test_validate_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make(tmp_path, "good")
    assert main(["validate", "--projects", str(tmp_path)]) == 0
    assert "ok good -> /p/good/" in capsys.readouterr().out

    bad = tmp_path / "bad"
    make(bad, "Bad_ID")
    assert main(["validate", "--projects", str(bad)]) == 1
    err = capsys.readouterr().err
    assert "Bad_ID" in err and "stack.toml" in err


def test_prepare_clones_then_builds_and_pulls(tmp_path: Path) -> None:
    projects, repos = tmp_path / "p", tmp_path / "r"
    make(projects, "fast", 'repo = "https://example.com/fast.git"\nref = "v1"')
    make(projects, "local")
    rec = Recorder()
    code = main(
        ["prepare", "--projects", str(projects), "--repos", str(repos)],
        run=rec,
        probe=lambda _: False,
    )
    assert code == 0
    co = str(repos / "fast")
    fc = str(repos / "fast" / "docker-compose.yml")
    lc = str(projects / "local" / "docker-compose.yml")
    assert rec.calls == [
        ["git", "clone", "--", "https://example.com/fast.git", co],
        ["git", "-C", co, "checkout", "--detach", "v1"],
        ["docker", "compose", "-p", "orch-fast", "-f", fc, "build"],
        ["docker", "compose", "-p", "orch-fast", "-f", fc, "pull", "--ignore-buildable"],
        ["docker", "compose", "-p", "orch-local", "-f", lc, "build"],
        ["docker", "compose", "-p", "orch-local", "-f", lc, "pull", "--ignore-buildable"],
    ]


def test_prepare_fetches_existing_checkout(tmp_path: Path) -> None:
    projects, repos = tmp_path / "p", tmp_path / "r"
    make(projects, "fast", 'repo = "https://example.com/fast.git"')
    (repos / "fast").mkdir(parents=True)
    rec = Recorder()
    assert (
        main(
            ["prepare", "--projects", str(projects), "--repos", str(repos)],
            run=rec,
            probe=lambda _: False,
        )
        == 0
    )
    co = str(repos / "fast")
    assert rec.calls[0] == ["git", "-C", co, "fetch", "--tags", "--prune", "origin"]
    assert rec.calls[1][-1] == "main"


def _checkout_calls(tmp_path: Path, on_remote: bool) -> tuple[list[list[str]], list[list[str]]]:
    projects, repos = tmp_path / "p", tmp_path / "r"
    make(projects, "fast", 'repo = "https://example.com/fast.git"')
    (repos / "fast").mkdir(parents=True)
    rec, probes = Recorder(), list[list[str]]()

    def probe(argv: list[str]) -> bool:
        probes.append(argv)
        return on_remote

    argv = ["prepare", "--projects", str(projects), "--repos", str(repos)]
    assert main(argv, run=rec, probe=probe) == 0
    return rec.calls, probes


def test_prepare_prefers_remote_branch(tmp_path: Path) -> None:
    calls, probes = _checkout_calls(tmp_path, on_remote=True)
    co = str(tmp_path / "r" / "fast")
    assert probes == [["git", "-C", co, "rev-parse", "--verify", "--quiet", "origin/main"]]
    assert calls[1] == ["git", "-C", co, "checkout", "--detach", "origin/main"]


def test_prepare_falls_back_to_tag_or_sha(tmp_path: Path) -> None:
    calls, _ = _checkout_calls(tmp_path, on_remote=False)
    co = str(tmp_path / "r" / "fast")
    assert calls[1] == ["git", "-C", co, "checkout", "--detach", "main"]


def test_prepare_stops_on_first_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    projects, repos = tmp_path / "p", tmp_path / "r"
    make(projects, "aaa")
    make(projects, "bbb")
    rec = Recorder(fail_on=1)
    assert main(["prepare", "--projects", str(projects), "--repos", str(repos)], run=rec) == 1
    assert len(rec.calls) == 1
    err = capsys.readouterr().err
    assert "aaa" in err and "build" in err


def test_prepare_fails_when_both_checkouts_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    projects, repos = tmp_path / "p", tmp_path / "r"
    make(projects, "fast", 'repo = "https://example.com/fast.git"')
    (repos / "fast").mkdir(parents=True)

    def run(argv: list[str]) -> None:
        if "checkout" in argv:
            raise RuntimeError("nope")

    assert (
        main(
            ["prepare", "--projects", str(projects), "--repos", str(repos)],
            run=run,
            probe=lambda _: False,
        )
        == 1
    )
    assert "fast" in capsys.readouterr().err


def test_prepare_surfaces_called_process_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import subprocess

    make(tmp_path / "p", "aaa")

    def run(argv: list[str]) -> None:
        raise subprocess.CalledProcessError(3, argv)

    assert (
        main(["prepare", "--projects", str(tmp_path / "p"), "--repos", str(tmp_path)], run=run) == 1
    )
    assert "aaa" in capsys.readouterr().err


def test_cli_defaults_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make(tmp_path / "projects", "shown")
    make(tmp_path / "projects" / "_hidden", "secret")
    monkeypatch.setenv("ORCH_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.delenv("ORCH_INCLUDE_HIDDEN", raising=False)
    assert main(["validate"]) == 0
    out = capsys.readouterr().out
    assert "ok shown" in out and "secret" not in out

    monkeypatch.setenv("ORCH_INCLUDE_HIDDEN", "1")
    assert main(["validate"]) == 0
    assert "ok secret" in capsys.readouterr().out

    monkeypatch.setenv("ORCH_INCLUDE_HIDDEN", "0")
    assert main(["validate"]) == 0
    assert "secret" not in capsys.readouterr().out

    monkeypatch.setenv("ORCH_REPOS_DIR", str(tmp_path / "repos"))
    rec = Recorder()
    assert main(["prepare"], run=rec) == 0
    assert str(tmp_path / "projects" / "shown" / "docker-compose.yml") in rec.calls[0]


def test_include_hidden_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make(tmp_path / "_h", "secret")
    assert main(["validate", "--projects", str(tmp_path), "--include-hidden"]) == 0
    assert "ok secret" in capsys.readouterr().out


def test_usage_errors() -> None:
    with pytest.raises(SystemExit) as e:
        main(["bogus"])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e2:
        main([])
    assert e2.value.code == 2
