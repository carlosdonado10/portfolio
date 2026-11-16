import asyncio

import httpx
import pytest
from agent.driver import ComposeError, DockerComposeDriver
from agent.probe import HttpHealthProbe


class FakeProc:
    def __init__(self, rc=0, out=b"", err=b""):
        self.returncode = rc
        self._out, self._err = out, err

    async def communicate(self):
        return self._out, self._err


class Spawner:
    def __init__(self, *procs, raises=None):
        self.procs = list(procs)
        self.argvs: list[tuple] = []
        self.raises = raises

    async def __call__(self, *argv, **kw):
        assert "shell" not in kw
        self.argvs.append(argv)
        if self.raises:
            raise self.raises
        return self.procs.pop(0)


async def test_up_argv(tmp_path, make_manifest):
    sp = Spawner(FakeProc())
    m = make_manifest("a")
    await DockerComposeDriver(tmp_path, sp).up(m)
    assert sp.argvs == [
        (
            "docker", "compose", "-p", "orch-a", "-f", str(m.compose_path(tmp_path)),
            "up", "-d", "--no-build", "--pull", "never", "--remove-orphans",
        )
    ]  # fmt: skip


async def test_down_argv_never_removes_volumes(tmp_path, make_manifest):
    (tmp_path / "a").mkdir()
    m = make_manifest("a", repo="x/y")
    m.compose_path(tmp_path).write_text("services: {}\n")
    sp = Spawner(FakeProc())
    await DockerComposeDriver(tmp_path, sp).down(m)
    argv = sp.argvs[0]
    assert argv[-2:] == ("down", "--remove-orphans")
    assert "-v" not in argv and "--volumes" not in argv
    assert "-f" in argv


async def test_down_without_compose_file_uses_project_name_only(tmp_path, make_manifest):
    sp = Spawner(FakeProc())
    await DockerComposeDriver(tmp_path, sp).down(make_manifest("a", repo="x/y"))
    assert sp.argvs[0] == ("docker", "compose", "-p", "orch-a", "down", "--remove-orphans")


async def test_nonzero_exit_raises_with_stderr(tmp_path, make_manifest):
    sp = Spawner(FakeProc(1, err=b"service web failed\n"))
    with pytest.raises(ComposeError, match="service web failed"):
        await DockerComposeDriver(tmp_path, sp).up(make_manifest("a"))


async def test_nonzero_exit_with_empty_stderr_still_has_message(tmp_path, make_manifest):
    sp = Spawner(FakeProc(1))
    with pytest.raises(ComposeError, match="failed"):
        await DockerComposeDriver(tmp_path, sp).up(make_manifest("a"))


@pytest.mark.parametrize(
    "stderr", [b"pull access denied for foo", b"No such image: foo:latest", b"image not found"]
)
async def test_missing_image_maps_to_prepare_hint(tmp_path, stderr, make_manifest):
    sp = Spawner(FakeProc(1, err=stderr))
    with pytest.raises(ComposeError, match="orchctl prepare") as ei:
        await DockerComposeDriver(tmp_path, sp).up(make_manifest("a"))
    assert "pull access" not in str(ei.value)


async def test_missing_checkout_compose_gives_prepare_hint_without_docker(tmp_path, make_manifest):
    sp = Spawner()
    with pytest.raises(ComposeError, match="orchctl prepare"):
        await DockerComposeDriver(tmp_path, sp).up(make_manifest("a", repo="x/y"))
    assert sp.argvs == []


async def test_missing_docker_binary_is_compose_error(tmp_path, make_manifest):
    sp = Spawner(raises=FileNotFoundError("docker"))
    with pytest.raises(ComposeError, match="cannot run docker"):
        await DockerComposeDriver(tmp_path, sp).up(make_manifest("a"))


async def test_running_filters_orch_prefix(tmp_path):
    out = b'[{"Name":"orch-a","Status":"running(2)"},{"Name":"other","Status":"running(1)"},{"Name":"orch-b-c"}]'
    sp = Spawner(FakeProc(out=out))
    assert await DockerComposeDriver(tmp_path, sp).running() == {"a", "b-c"}
    # --all: created/exited/half-started projects must be seen so they get downed.
    assert sp.argvs[0] == ("docker", "compose", "ls", "--all", "--format", "json")


@pytest.mark.parametrize("out", [b"", b"  \n", b"not json", b'{"Name":"orch-a"}', b'[1,{"x":1}]'])
async def test_running_parses_defensively(tmp_path, out):
    sp = Spawner(FakeProc(out=out))
    assert await DockerComposeDriver(tmp_path, sp).running() == set()


def probe_with(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HttpHealthProbe(client)


async def test_probe_url_and_200_is_healthy(make_manifest):
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(200)

    assert await probe_with(handler).check(make_manifest("a")) is True
    assert seen == ["http://a-entry:8080/p/a/healthz"]


async def test_probe_non_200_is_unhealthy(make_manifest):
    assert await probe_with(lambda r: httpx.Response(503)).check(make_manifest("a")) is False
    assert await probe_with(lambda r: httpx.Response(204)).check(make_manifest("a")) is False


async def test_probe_connection_error_is_unhealthy(make_manifest):
    def handler(req):
        raise httpx.ConnectError("refused")

    assert await probe_with(handler).check(make_manifest("a")) is False


async def test_probe_default_client_closes():
    p = HttpHealthProbe()
    await p.aclose()


async def test_up_argv_includes_pull_never(tmp_path, make_manifest):
    sp = Spawner(FakeProc())
    await DockerComposeDriver(tmp_path, sp).up(make_manifest("a"))
    argv = sp.argvs[0]
    assert argv[argv.index("--pull") + 1] == "never"


async def test_down_project_by_name(tmp_path):
    sp = Spawner(FakeProc())
    await DockerComposeDriver(tmp_path, sp).down_project("orch-ghost")
    assert sp.argvs[0] == ("docker", "compose", "-p", "orch-ghost", "down", "--remove-orphans")


class HangingProc:
    returncode = None

    def __init__(self):
        self.killed = False
        self.waited = False

    async def communicate(self):
        await asyncio.sleep(3600)

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        self.waited = True


async def test_cancel_during_up_kills_subprocess(tmp_path, make_manifest):
    proc = HangingProc()
    sp = Spawner(proc)
    task = asyncio.create_task(DockerComposeDriver(tmp_path, sp).up(make_manifest("a")))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert proc.killed and proc.waited


async def test_up_timeout_reports_failed(tmp_path, make_manifest):
    proc = HangingProc()
    sp = Spawner(proc)
    m = make_manifest("a", timeout_s=0)
    with pytest.raises(ComposeError, match="compose up exceeded 0 seconds"):
        await DockerComposeDriver(tmp_path, sp).up(m)
    assert proc.killed and proc.waited
