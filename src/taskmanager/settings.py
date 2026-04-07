"""Application settings loaded via pydantic-settings.

This module defines a Settings class and a cached accessor that
loads configuration from environment variables, TOML file, and a .env file.

Precedence order: env vars > TOML config file > .env file > defaults
"""

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Compute the project root (repo root), e.g. .../autonomous-contributor
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# TOML configuration file location
CONFIG_FILE_PATH = Path.home() / ".taskmanager" / "config.toml"


def _get_config_file_path() -> Path:
    """Get the configuration file path.

    This function allows tests to monkeypatch the path more effectively.
    """
    return CONFIG_FILE_PATH


class TOMLSyntaxError(ValueError):
    """Raised when TOML configuration file contains invalid syntax."""



def _load_toml_config() -> dict[str, Any]:
    """Load configuration from TOML file if it exists.

    Returns:
        Dictionary of configuration values from TOML file, or empty dict if file
        doesn't exist or can't be parsed.

    Raises:
        TOMLSyntaxError: If TOML file exists but contains invalid syntax.
    """
    config_path = _get_config_file_path()
    if not config_path.exists():
        return {}

    try:
        with config_path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        msg = f"Invalid TOML syntax in {config_path}: {e}"
        raise TOMLSyntaxError(msg) from e


class Settings(BaseSettings):
    """App configuration.

    Values are sourced from (in order of precedence):
    1) Environment variables
    2) TOML config file (~/.taskmanager/config.toml)
    3) .env file(s) — see model_config.env_file
    4) Defaults defined on the fields
    """

    app_name: str = Field(
        default="taskmanager",
        description="Simplistic task management, for Vibe playground",
    )
    debug: bool = Field(
        default=False,
        description="Enable debug mode (more verbose logs, etc.)",
    )
    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = Field(
        default="INFO",
        description="Logging level.",
    )
    log_format: Literal["text", "json"] = Field(
        default="text",
        description="Log output format (text or json).",
    )
    environment: Literal["development", "production", "test"] = Field(
        default="development",
        description="Runtime environment name.",
    )
    default_shell: str = Field(
        default="/bin/bash",
        description="Default shell for task execution.",
    )
    history_retention_days: int = Field(
        default=30,
        description="Number of days to retain task execution history.",
        gt=0,
    )
    api_host: str = Field(
        default="127.0.0.1",
        description="API server host address.",
    )
    api_port: int = Field(
        default=8000,
        description="API server port number.",
        gt=0,
        lt=65536,
    )
    # Legacy aliases for backward compatibility
    host: str = Field(
        default="127.0.0.1",
        description="API server host address (deprecated, use api_host).",
        exclude=True,
    )
    port: int = Field(
        default=8000,
        description="API server port number (deprecated, use api_port).",
        exclude=True,
    )
    db_url: str = Field(
        default="sqlite:///~/.taskmanager/taskmanager.db",
        description="Database URL for SQLAlchemy engine.",
    )
    subprocess_timeout: int = Field(
        default=300,
        description="Default timeout in seconds for subprocess execution.",
        gt=0,
    )

    # Pydantic v2 settings config
    model_config = SettingsConfigDict(
        # Read .env from the project root
        env_file=(PROJECT_ROOT / ".env",),
        env_file_encoding="utf-8",
        # No prefix; environment variables may be written as APP_NAME, DEBUG, etc.
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="before")
    @classmethod
    def load_toml_config(cls, data: Any) -> Any:
        """Load TOML config and merge with other sources.

        This validator runs before field validation and merges TOML config
        with environment variables and .env values. Environment variables
        take precedence over TOML values.
        """
        if not isinstance(data, dict):
            data = {}

        # Load TOML config (raises ValidationError if invalid syntax)
        toml_config = _load_toml_config()

        # Merge: env vars (already in data) override TOML
        # Only add TOML values that aren't already set from env/dotenv
        for key, value in toml_config.items():
            if key not in data:
                data[key] = value

        # Handle legacy field aliases: if api_host/api_port not set, use host/port
        if "api_host" not in data and "host" in data:
            data["api_host"] = data["host"]
        if "api_port" not in data and "port" in data:
            data["api_port"] = data["port"]

        return data

    @model_validator(mode="after")
    def sync_legacy_fields(self) -> "Settings":
        """Synchronize legacy host/port fields with api_host/api_port.

        This ensures backward compatibility for code that still accesses
        the old field names.
        """
        # Sync api_host/api_port to host/port for backward compatibility
        object.__setattr__(self, "host", self.api_host)
        object.__setattr__(self, "port", self.api_port)
        return self


def get_version() -> str:
    """Extract version string from pyproject.toml.

    Used by the /api/info endpoint to report application version.
    Returns "unknown" if pyproject.toml is missing or doesn't contain
    a valid project.version field.

    Returns:
        Version string (e.g., "0.1.0") or "unknown" if unavailable.
    """
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    try:
        with pyproject_path.open("rb") as f:
            data = tomllib.load(f)
            project = data.get("project", {})
            version = project.get("version", "unknown")
            return str(version) if version is not None else "unknown"
    except (FileNotFoundError, tomllib.TOMLDecodeError, KeyError):
        return "unknown"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()


# Convenient module-level instance
settings: Settings = get_settings()
