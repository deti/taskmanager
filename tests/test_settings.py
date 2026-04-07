"""Unit tests for taskmanager.settings module."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from taskmanager.settings import (
    PROJECT_ROOT as SETTINGS_PROJECT_ROOT,
)
from taskmanager.settings import (
    Settings,
    get_settings,
)


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """Clear the get_settings LRU cache before and after each test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_defaults_when_no_env_vars(monkeypatch):
    """Settings should use defaults when environment variables are not set."""
    # Ensure related environment variables are unset
    for key in ["APP_NAME", "DEBUG", "LOG_LEVEL", "ENVIRONMENT"]:
        monkeypatch.delenv(key, raising=False)

    s = Settings()
    assert s.app_name == "taskmanager"
    assert s.debug is False
    assert s.log_level == "INFO"
    assert s.environment == "development"


def test_environment_overrides(monkeypatch):
    """Environment variables should override default values."""
    monkeypatch.setenv("APP_NAME", "custom-app")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    monkeypatch.setenv("ENVIRONMENT", "test")

    s = Settings()
    assert s.app_name == "custom-app"
    assert s.debug is True
    assert s.log_level == "ERROR"
    assert s.environment == "test"


def test_get_settings_is_cached():
    """get_settings should return the same instance until cache is cleared."""
    # Prime the cache and get the first instance
    a = get_settings()
    b = get_settings()
    assert a is b  # same object from cache

    # Clearing the cache should yield a new instance
    get_settings.cache_clear()
    c = get_settings()
    assert c is not a


def test_project_root_and_env_file_config():
    """PROJECT_ROOT should point to repo root; env_file should reference .env there."""
    # From the tests/ directory, repo root is the parent
    expected_repo_root = Path(__file__).resolve().parents[1]

    assert SETTINGS_PROJECT_ROOT.resolve() == expected_repo_root

    # Validate env_file configured to PROJECT_ROOT/.env
    # In pydantic v2, model_config is a dict-like object set on the class
    env_file = Settings.model_config.get("env_file")
    assert isinstance(env_file, tuple)
    assert env_file[0] == SETTINGS_PROJECT_ROOT / ".env"


def test_unknown_env_vars_are_ignored(monkeypatch):
    """Unknown environment vars should be ignored due to extra='ignore'."""
    monkeypatch.setenv("UNKNOWN_SETTING", "something")
    s = Settings()

    # Accessing an unknown attribute should raise AttributeError (not set)
    with pytest.raises(AttributeError):
        _ = s.unknown_setting


def test_invalid_log_level_raises(monkeypatch):
    """Invalid LOG_LEVEL should trigger validation error due to Literal type."""
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")  # Not in allowed list

    with pytest.raises(ValidationError):
        Settings()

# TOML configuration tests


@pytest.fixture
def mock_config_file(monkeypatch, tmp_path):
    """Mock the config file path to use a temporary directory."""
    temp_config = tmp_path / "config.toml"
    monkeypatch.setattr(
        "taskmanager.settings._get_config_file_path",
        lambda: temp_config
    )
    return temp_config


def test_toml_file_not_exist(mock_config_file):
    """Missing TOML config file should not raise error (graceful fallback)."""
    assert not mock_config_file.exists()
    s = Settings()
    assert s.app_name == "taskmanager"
    assert s.log_format == "text"


def test_toml_loads_successfully(mock_config_file):
    """Valid TOML config should be loaded and applied."""
    mock_config_file.write_text("""
app_name = "my-taskmanager"
debug = true
log_level = "DEBUG"
log_format = "json"
default_shell = "/bin/zsh"
history_retention_days = 60
api_host = "0.0.0.0"
api_port = 9000
""")
    s = Settings()
    assert s.app_name == "my-taskmanager"
    assert s.debug is True
    assert s.log_level == "DEBUG"
    assert s.log_format == "json"
    assert s.default_shell == "/bin/zsh"
    assert s.history_retention_days == 60
    assert s.api_host == "0.0.0.0"
    assert s.api_port == 9000


def test_env_overrides_toml(monkeypatch, mock_config_file):
    """Environment variables should override TOML config values."""
    mock_config_file.write_text("""
app_name = "toml-app"
log_level = "WARNING"
log_format = "json"
""")
    monkeypatch.setenv("APP_NAME", "env-app")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    s = Settings()
    assert s.app_name == "env-app"
    assert s.log_level == "ERROR"
    assert s.log_format == "json"


def test_toml_overrides_defaults(monkeypatch, mock_config_file):
    """TOML config should override defaults when env vars not set."""
    mock_config_file.write_text("""
log_format = "json"
default_shell = "/bin/fish"
""")
    for key in ["LOG_FORMAT", "DEFAULT_SHELL"]:
        monkeypatch.delenv(key, raising=False)
    s = Settings()
    assert s.log_format == "json"
    assert s.default_shell == "/bin/fish"


def test_invalid_toml_syntax_raises(mock_config_file):
    """Invalid TOML syntax should produce clear error."""
    mock_config_file.write_text("""
app_name = "test"
invalid syntax here!
""")
    # TOML syntax error is wrapped in a Pydantic ValidationError
    with pytest.raises(ValidationError, match="Invalid TOML syntax"):
        Settings()


def test_invalid_toml_field_value_raises(mock_config_file):
    """Invalid field values in TOML should raise ValidationError."""
    mock_config_file.write_text("""
log_format = "xml"
""")
    with pytest.raises(ValidationError):
        Settings()


def test_negative_port_raises(mock_config_file):
    """Negative port number should raise ValidationError."""
    mock_config_file.write_text("""
api_port = -1
""")
    with pytest.raises(ValidationError):
        Settings()
