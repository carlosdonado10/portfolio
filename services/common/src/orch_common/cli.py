"""``orchctl``: validate manifests, render nginx config, prepare project images."""

import argparse
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from orch_common.manifest import Manifest, ManifestError, load_manifests
from orch_common.nginx import render_projects_conf

Runner = Callable[[list[str]], None]


class StepError(Exception):
    """A prepare step failed."""


def _run(argv: list[str]) -> None:
    # Explicit argv list, no shell; output streams to the inherited stdout/stderr.
    subprocess.run(argv, check=True)  # noqa: S603


def _truthy(value: str | None) -> bool:
    return (value or "").lower() in {"1", "true"}


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _step(run: Runner, argv: list[str], what: str) -> None:
    try:
        run(argv)
    except Exception as e:
        raise StepError(f"{what} failed: {e}") from e


def _checkout(m: Manifest, repo: str, repos: Path, run: Runner) -> None:
    dest = str(m.checkout_dir(repos))
    if Path(dest).exists():
        _step(run, ["git", "-C", dest, "fetch", "--tags", "--prune", "origin"], f"{m.id}: fetch")
    else:
        _step(run, ["git", "clone", repo, dest], f"{m.id}: clone")
    try:
        run(["git", "-C", dest, "checkout", "--detach", m.ref])
    except Exception:
        _step(
            run,
            ["git", "-C", dest, "checkout", "--detach", f"origin/{m.ref}"],
            f"{m.id}: checkout {m.ref}",
        )


def _prepare(manifests: list[Manifest], repos: Path, run: Runner) -> None:
    for m in manifests:
        if m.repo:
            _checkout(m, m.repo, repos, run)
    for m in manifests:
        base = ["docker", "compose", "-p", m.project_name, "-f", str(m.compose_path(repos))]
        _step(run, [*base, "build"], f"{m.id}: build")
        _step(run, [*base, "pull", "--ignore-buildable"], f"{m.id}: pull")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orchctl", description="Orchestrator operator CLI.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, helptext in (
        ("validate", "validate every manifest"),
        ("render-nginx", "render per-project nginx config"),
        ("prepare", "clone/fetch project repos, build and pull images"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument(
            "--projects",
            type=Path,
            default=Path(os.environ.get("ORCH_PROJECTS_DIR", "./projects")),
            help="projects directory (env ORCH_PROJECTS_DIR, default ./projects)",
        )
        p.add_argument(
            "--include-hidden",
            action="store_true",
            default=_truthy(os.environ.get("ORCH_INCLUDE_HIDDEN")),
            help="include _-prefixed projects (env ORCH_INCLUDE_HIDDEN=1)",
        )
        if name == "render-nginx":
            p.add_argument("--out", required=True, help="output file, or - for stdout")
        if name == "prepare":
            p.add_argument(
                "--repos",
                type=Path,
                default=Path(os.environ.get("ORCH_REPOS_DIR", "/srv/orch/repos")),
                help="repos directory (env ORCH_REPOS_DIR, default /srv/orch/repos)",
            )
    return parser


def main(argv: list[str] | None = None, run: Runner = _run) -> int:
    """Run the CLI. Returns the process exit code (0 ok, 1 failure, 2 usage)."""
    args = _parser().parse_args(argv)
    try:
        manifests = load_manifests(args.projects, args.include_hidden)
        if args.command == "validate":
            for m in manifests:
                print(f"ok {m.id} -> {m.base_path}")
        elif args.command == "render-nginx":
            text = render_projects_conf(manifests)
            if args.out == "-":
                sys.stdout.write(text)
            else:
                _atomic_write(Path(args.out), text)
        else:
            _prepare(manifests, args.repos, run)
    except (ManifestError, StepError) as e:
        print(e, file=sys.stderr)
        return 1
    return 0
