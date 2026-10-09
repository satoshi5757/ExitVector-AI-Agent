from pathlib import Path

import pytest

from exitvector_agent.config import Settings, load_settings


def test_load_settings_uses_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EXITVECTOR_ENV", "test")
    monkeypatch.setenv("EXITVECTOR_DATABASE_URL", "sqlite:///tmp/test.db")
    monkeypatch.setenv("EXITVECTOR_SCAN_INTERVAL_SECONDS", "900")
    monkeypatch.setenv("EXITVECTOR_NOTIFY_THRESHOLD", "75")

    settings = load_settings(env_file=tmp_path / ".env")

    assert settings.environment == "test"
    assert settings.database_url == "sqlite:///tmp/test.db"
    assert settings.scan_interval_seconds == 900
    assert settings.notify_threshold == 75


def test_settings_reject_invalid_threshold() -> None:
    with pytest.raises(ValueError):
        Settings(notify_threshold=101)


def test_settings_reject_invalid_scan_interval() -> None:
    with pytest.raises(ValueError):
        Settings(scan_interval_seconds=0)
