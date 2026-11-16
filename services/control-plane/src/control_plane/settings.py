"""Service configuration (env prefix ORCH_, nested delimiter __)."""

from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from control_plane.lease import LeaseConfig


class LeaseSettings(BaseModel):
    window_s: float = 900
    grace_s: float = 180
    idle_s: float = 180
    presence_s: float = 120

    def to_config(self) -> LeaseConfig:
        return LeaseConfig(**self.model_dump())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ORCH_", env_nested_delimiter="__")

    db_path: Path = Path("/data/orch.sqlite")
    projects_dir: Path = Path("/srv/orch/projects")
    repos_dir: Path = Path("/srv/orch/repos")
    include_hidden: bool = False
    cookie_secret: str
    cookie_secure: bool = True
    owner_secret: str
    resend_api_key: str | None = None
    email_from: str | None = None
    public_base_url: str = ""
    lease: LeaseSettings = LeaseSettings()
