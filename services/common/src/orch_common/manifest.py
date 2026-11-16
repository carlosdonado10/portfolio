"""Project manifest (`projects/<id>/stack.toml`) model and discovery."""

import re
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, PrivateAttr, ValidationError, field_validator

_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ManifestError(Exception):
    """A manifest is invalid or the registry is inconsistent."""


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str
    port: int


class Health(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = "/healthz"
    timeout_s: int = 180
    interval_s: float = 3


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    tagline: str = ""
    repo: str | None = None
    ref: str = "main"
    compose: str
    entry: Entry
    health: Health
    expected_boot_s: int
    demo_url: str | None = None
    order: int = 100

    # Set by discovery, not read from TOML.
    _dir: Path = PrivateAttr(default=Path())
    _hidden: bool = PrivateAttr(default=False)

    @field_validator("id")
    @classmethod
    def _check_id(_cls, v: str) -> str:
        if not _ID_RE.fullmatch(v):
            raise ValueError(f"id {v!r} must be lowercase alphanumerics and hyphens")
        return v

    @property
    def dir(self) -> Path:
        return self._dir

    @property
    def hidden(self) -> bool:
        return self._hidden

    @property
    def base_path(self) -> str:
        return f"/p/{self.id}/"

    @property
    def project_name(self) -> str:
        return f"orch-{self.id}"

    @property
    def entry_alias(self) -> str:
        return f"{self.id}-entry"

    def checkout_dir(self, repos_dir: Path) -> Path:
        return repos_dir / self.id if self.repo else self._dir

    def compose_path(self, repos_dir: Path) -> Path:
        return self.checkout_dir(repos_dir) / self.compose


def _load_one(path: Path, hidden: bool) -> Manifest:
    try:
        data = tomllib.loads(path.read_text())
        m = Manifest.model_validate(data)
    except (tomllib.TOMLDecodeError, ValidationError, OSError) as e:
        raise ManifestError(f"{path}: {e}") from e
    if m.id != path.parent.name:
        raise ManifestError(f"{path}: id {m.id!r} does not match folder {path.parent.name!r}")
    m._dir = path.parent
    m._hidden = hidden
    if m.repo is None and not (path.parent / m.compose).is_file():
        raise ManifestError(f"{path}: compose file {m.compose!r} not found")
    return m


def load_manifests(projects_dir: Path, include_hidden: bool = False) -> list[Manifest]:
    if not projects_dir.is_dir():
        return []
    found: list[tuple[Path, bool]] = [
        (p, False) for p in projects_dir.glob("*/stack.toml") if not p.parent.name.startswith("_")
    ]
    if include_hidden:
        found += [(p, True) for p in projects_dir.glob("_*/**/stack.toml")]
    manifests: list[Manifest] = []
    seen: set[str] = set()
    for path, hidden in sorted(found):
        m = _load_one(path, hidden)
        if m.id in seen:
            raise ManifestError(f"{path}: duplicate id {m.id!r}")
        seen.add(m.id)
        manifests.append(m)
    return sorted(manifests, key=lambda m: (m.order, m.id))
