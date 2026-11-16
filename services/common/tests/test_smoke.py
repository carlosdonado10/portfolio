"""The three Python packages of the uv workspace are importable together."""

import pytest


def test_workspace_packages_import() -> None:
    import agent
    import control_plane
    import orch_common

    assert orch_common and control_plane and agent


def test_orchctl_entrypoint_runs() -> None:
    from orch_common.cli import main

    with pytest.raises(SystemExit) as e:
        main(["bogus"])
    assert e.value.code == 2
