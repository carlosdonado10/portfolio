from collections.abc import Callable

import pytest
from orch_common.manifest import Entry, Health, Manifest


def _make(id_: str = "a", *, repo: str | None = None, timeout_s: int = 10) -> Manifest:
    return Manifest(
        id=id_,
        name=id_.upper(),
        repo=repo,
        compose="docker-compose.yml",
        entry=Entry(service="web", port=8080),
        health=Health(path="/healthz", timeout_s=timeout_s, interval_s=2),
        expected_boot_s=5,
    )


@pytest.fixture
def make_manifest() -> Callable[..., Manifest]:
    return _make


@pytest.fixture
def manifests() -> dict[str, Manifest]:
    return {"a": _make("a"), "b": _make("b")}
