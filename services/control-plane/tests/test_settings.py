import pytest
from control_plane.settings import Settings
from pydantic import ValidationError


def test_settings_reads_nested_lease_env(monkeypatch):
    monkeypatch.setenv("ORCH_COOKIE_SECRET", "c" * 16)
    monkeypatch.setenv("ORCH_OWNER_SECRET", "o" * 16)
    monkeypatch.setenv("ORCH_LEASE__WINDOW_S", "5")
    settings = Settings()
    assert settings.lease.to_config().window_s == 5
    assert settings.lease.to_config().grace_s == 180
    assert settings.cookie_secure is True
    assert settings.include_hidden is False
    assert settings.public_base_url == ""


def test_rejects_short_secrets(monkeypatch):
    monkeypatch.setenv("ORCH_COOKIE_SECRET", "c" * 16)
    monkeypatch.setenv("ORCH_OWNER_SECRET", "short")
    with pytest.raises(ValidationError):
        Settings()
    monkeypatch.setenv("ORCH_OWNER_SECRET", "o" * 16)
    monkeypatch.setenv("ORCH_COOKIE_SECRET", "")
    with pytest.raises(ValidationError):
        Settings()
