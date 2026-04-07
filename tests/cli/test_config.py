"""Tests for the config CLI commands."""

import tomllib

import pytest
from typer.testing import CliRunner

from taskmanager.cli.config import app
from taskmanager.settings import get_settings


runner = CliRunner()


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """Clear settings cache before each test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def temp_config_path(tmp_path, monkeypatch):
    """Provide a temporary config file path for tests."""
    config_dir = tmp_path / ".taskmanager"
    config_file = config_dir / "config.toml"

    # Monkeypatch the CONFIG_FILE_PATH
    monkeypatch.setattr("taskmanager.cli.config.CONFIG_FILE_PATH", config_file)
    monkeypatch.setattr("taskmanager.settings.CONFIG_FILE_PATH", config_file)

    # Also patch the function that returns the path
    def mock_get_config_file_path():
        return config_file

    monkeypatch.setattr(
        "taskmanager.settings._get_config_file_path",
        mock_get_config_file_path,
    )

    return config_file


class TestConfigInit:
    """Test suite for 'config init' command."""

    def test_init_creates_config_file(self, temp_config_path):
        """Test that init creates a valid TOML config file."""
        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0
        assert temp_config_path.exists()
        # File didn't exist before, so should say "Created"
        output = result.stdout + result.stderr
        assert ("Created config file" in output or "config file" in output)

        # Verify it's valid TOML
        with temp_config_path.open("rb") as f:
            config_data = tomllib.load(f)
            # Should be empty or have comments (comments are not parsed)
            assert isinstance(config_data, dict)

    def test_init_creates_directory(self, temp_config_path):
        """Test that init creates the config directory if it doesn't exist."""
        config_dir = temp_config_path.parent
        assert not config_dir.exists()

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0
        assert config_dir.exists()
        assert "Created config directory" in result.stdout

    def test_init_fails_if_file_exists(self, temp_config_path):
        """Test that init fails if config file already exists without --force."""
        # Create initial config
        temp_config_path.parent.mkdir(parents=True)
        temp_config_path.write_text("# existing config", encoding="utf-8")

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 1
        # Error messages go to stderr with rich console
        output = result.stdout + result.stderr
        assert "already exists" in output
        assert "Use --force to overwrite" in output

    def test_init_with_force_overwrites_existing(self, temp_config_path):
        """Test that init --force overwrites existing config file."""
        # Create initial config
        temp_config_path.parent.mkdir(parents=True)
        temp_config_path.write_text("# existing config", encoding="utf-8")

        result = runner.invoke(app, ["init", "--force"])

        assert result.exit_code == 0
        assert "Overwritten config file" in result.stdout
        # Verify content was replaced
        content = temp_config_path.read_text()
        assert "TaskManager Configuration File" in content
        assert "# existing config" not in content

    def test_init_creates_valid_template(self, temp_config_path):
        """Test that init creates a config file with helpful comments."""
        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0
        content = temp_config_path.read_text()

        # Check for key documentation elements
        assert "TaskManager Configuration File" in content
        assert "Precedence order" in content
        assert "# app_name" in content
        assert "# log_level" in content
        assert "# api_host" in content


class TestConfigShow:
    """Test suite for 'config show' command."""

    def test_show_displays_all_settings(self, temp_config_path):
        """Test that show displays all configuration settings."""
        result = runner.invoke(app, ["show"])

        assert result.exit_code == 0
        assert "Current Configuration" in result.stdout
        assert "app_name" in result.stdout
        assert "log_level" in result.stdout
        assert "api_host" in result.stdout
        assert "api_port" in result.stdout

    def test_show_displays_default_source(self, temp_config_path):
        """Test that show correctly identifies default values."""
        result = runner.invoke(app, ["show"])

        assert result.exit_code == 0
        assert "default" in result.stdout

    def test_show_displays_config_source(self, temp_config_path):
        """Test that show correctly identifies config file values."""
        # Create config with custom value
        temp_config_path.parent.mkdir(parents=True)
        temp_config_path.write_text('log_level = "DEBUG"\n', encoding="utf-8")

        # Clear cache to pick up new config
        get_settings.cache_clear()

        result = runner.invoke(app, ["show"])

        assert result.exit_code == 0
        assert "config" in result.stdout
        assert "DEBUG" in result.stdout

    def test_show_displays_env_source(self, temp_config_path, monkeypatch):
        """Test that show correctly identifies environment variable values."""
        monkeypatch.setenv("LOG_LEVEL", "ERROR")
        get_settings.cache_clear()

        result = runner.invoke(app, ["show"])

        assert result.exit_code == 0
        assert "env:LOG_LEVEL" in result.stdout
        assert "ERROR" in result.stdout

    def test_show_displays_config_path(self, temp_config_path):
        """Test that show displays the config file path."""
        result = runner.invoke(app, ["show"])

        assert result.exit_code == 0
        # Path might be wrapped across lines by Rich console
        output = result.stdout.replace("\n", "")
        assert str(temp_config_path) in output

    def test_show_warns_if_config_not_found(self, temp_config_path):
        """Test that show warns if config file doesn't exist."""
        result = runner.invoke(app, ["show"])

        assert result.exit_code == 0
        assert "not found" in result.stdout or "Run 'config init'" in result.stdout

    def test_show_handles_invalid_toml(self, temp_config_path):
        """Test that show handles invalid TOML syntax gracefully."""
        temp_config_path.parent.mkdir(parents=True)
        temp_config_path.write_text("invalid toml {{{", encoding="utf-8")

        get_settings.cache_clear()

        result = runner.invoke(app, ["show"])

        assert result.exit_code == 1
        # Error messages go to stderr
        output = result.stdout + result.stderr
        assert "Error" in output or "error" in output.lower()


class TestConfigPath:
    """Test suite for 'config path' command."""

    def test_path_shows_config_location(self, temp_config_path):
        """Test that path displays the config file location."""
        result = runner.invoke(app, ["path"])

        assert result.exit_code == 0
        # Path might be wrapped by Rich console
        output = result.stdout.replace("\n", "")
        assert str(temp_config_path) in output

    def test_path_indicates_when_file_missing(self, temp_config_path):
        """Test that path indicates when config file doesn't exist."""
        result = runner.invoke(app, ["path"])

        assert result.exit_code == 0
        # Path might be wrapped by Rich console
        output = result.stdout.replace("\n", "")
        assert str(temp_config_path) in output
        assert "(not found)" in result.stdout

    def test_path_without_warning_when_file_exists(self, temp_config_path):
        """Test that path doesn't show warning when file exists."""
        temp_config_path.parent.mkdir(parents=True)
        temp_config_path.write_text("# config", encoding="utf-8")

        result = runner.invoke(app, ["path"])

        assert result.exit_code == 0
        # Path might be wrapped by Rich console
        output = result.stdout.replace("\n", "")
        assert str(temp_config_path) in output
        assert "(not found)" not in result.stdout


class TestConfigSet:
    """Test suite for 'config set' command."""

    def test_set_creates_new_value(self, temp_config_path):
        """Test that set creates a new configuration value."""
        result = runner.invoke(app, ["set", "log_level", "DEBUG"])

        assert result.exit_code == 0
        assert "Set log_level = DEBUG" in result.stdout
        assert temp_config_path.exists()

        # Verify value was written
        with temp_config_path.open("rb") as f:
            config_data = tomllib.load(f)
            assert config_data["log_level"] == "DEBUG"

    def test_set_updates_existing_value(self, temp_config_path):
        """Test that set updates an existing configuration value."""
        # Create initial config
        temp_config_path.parent.mkdir(parents=True)
        temp_config_path.write_text('log_level = "INFO"\n', encoding="utf-8")

        result = runner.invoke(app, ["set", "log_level", "ERROR"])

        assert result.exit_code == 0
        assert "Updated log_level" in result.stdout
        assert "INFO → ERROR" in result.stdout

        # Verify value was updated
        with temp_config_path.open("rb") as f:
            config_data = tomllib.load(f)
            assert config_data["log_level"] == "ERROR"

    def test_set_preserves_other_values(self, temp_config_path):
        """Test that set preserves other configuration values."""
        # Create initial config with multiple values
        temp_config_path.parent.mkdir(parents=True)
        temp_config_path.write_text(
            'log_level = "INFO"\napp_name = "my-app"\n',
            encoding="utf-8",
        )

        result = runner.invoke(app, ["set", "log_level", "DEBUG"])

        assert result.exit_code == 0

        # Verify both values exist
        with temp_config_path.open("rb") as f:
            config_data = tomllib.load(f)
            assert config_data["log_level"] == "DEBUG"
            assert config_data["app_name"] == "my-app"

    def test_set_rejects_invalid_key(self, temp_config_path):
        """Test that set rejects unknown configuration keys."""
        result = runner.invoke(app, ["set", "invalid_key", "value"])

        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "Unknown configuration key" in output
        assert "Available keys" in output

    def test_set_validates_boolean_values(self, temp_config_path):
        """Test that set validates boolean values correctly."""
        # Test valid boolean values
        for value in ["true", "false", "yes", "no", "1", "0", "on", "off"]:
            result = runner.invoke(app, ["set", "debug", value])
            assert result.exit_code == 0, f"Failed for value: {value}"

        # Test invalid boolean value
        result = runner.invoke(app, ["set", "debug", "maybe"])
        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "Invalid" in output or "invalid" in output.lower()

    def test_set_validates_integer_values(self, temp_config_path):
        """Test that set validates integer values correctly."""
        # Valid integer
        result = runner.invoke(app, ["set", "api_port", "9000"])
        assert result.exit_code == 0
        assert "Set api_port = 9000" in result.stdout

        # Invalid integer
        result = runner.invoke(app, ["set", "api_port", "not-a-number"])
        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "Invalid" in output or "invalid" in output.lower()

    def test_set_validates_literal_values(self, temp_config_path):
        """Test that set validates Literal field values."""
        # Valid literal value
        result = runner.invoke(app, ["set", "log_level", "ERROR"])
        assert result.exit_code == 0

        # Invalid literal value
        result = runner.invoke(app, ["set", "log_level", "INVALID_LEVEL"])
        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "Invalid" in output or "invalid" in output.lower()

    def test_set_validates_range_constraints(self, temp_config_path):
        """Test that set validates field constraints (e.g., port range)."""
        # Valid port
        result = runner.invoke(app, ["set", "api_port", "8080"])
        assert result.exit_code == 0

        # Port too large
        result = runner.invoke(app, ["set", "api_port", "99999"])
        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "Invalid" in output or "invalid" in output.lower()

        # Port too small (0 or negative)
        result = runner.invoke(app, ["set", "api_port", "0"])
        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "Invalid" in output or "invalid" in output.lower()

    def test_set_creates_directory_if_needed(self, temp_config_path):
        """Test that set creates config directory if it doesn't exist."""
        config_dir = temp_config_path.parent
        assert not config_dir.exists()

        result = runner.invoke(app, ["set", "log_level", "DEBUG"])

        assert result.exit_code == 0
        assert config_dir.exists()
        assert temp_config_path.exists()

    def test_set_handles_invalid_existing_toml(self, temp_config_path):
        """Test that set handles invalid TOML in existing file."""
        temp_config_path.parent.mkdir(parents=True)
        temp_config_path.write_text("invalid toml {{{", encoding="utf-8")

        result = runner.invoke(app, ["set", "log_level", "DEBUG"])

        assert result.exit_code == 1
        # Check exception attribute as well since stderr might not be captured
        output = result.stdout + result.stderr
        if result.exception:
            output += str(result.exception)
        assert "TOML" in output or "toml" in output.lower()

    def test_set_string_value(self, temp_config_path):
        """Test that set handles string values correctly."""
        result = runner.invoke(app, ["set", "app_name", "custom-app"])

        assert result.exit_code == 0
        assert "Set app_name = custom-app" in result.stdout

        with temp_config_path.open("rb") as f:
            config_data = tomllib.load(f)
            assert config_data["app_name"] == "custom-app"

    def test_set_shows_cache_warning(self, temp_config_path):
        """Test that set warns about settings cache."""
        result = runner.invoke(app, ["set", "log_level", "DEBUG"])

        assert result.exit_code == 0
        assert "Clear settings cache" in result.stdout or "restart" in result.stdout


class TestConfigIntegration:
    """Integration tests for config commands."""

    def test_init_then_show(self, temp_config_path):
        """Test workflow: init then show."""
        # Initialize config
        result1 = runner.invoke(app, ["init"])
        assert result1.exit_code == 0

        # Show should work without errors
        result2 = runner.invoke(app, ["show"])
        assert result2.exit_code == 0
        assert "Current Configuration" in result2.stdout

    def test_set_then_show_reflects_changes(self, temp_config_path, monkeypatch):
        """Test that set changes are visible in show (after cache clear)."""
        # Set a value
        result1 = runner.invoke(app, ["set", "log_level", "WARNING"])
        assert result1.exit_code == 0

        # Clear cache (simulating restart)
        get_settings.cache_clear()
        # Ensure environment doesn't override
        monkeypatch.delenv("LOG_LEVEL", raising=False)

        # Show should reflect the change
        result2 = runner.invoke(app, ["show"])
        assert result2.exit_code == 0
        assert "WARNING" in result2.stdout
        assert "config" in result2.stdout  # Source should be config file

    def test_env_override_visible_in_show(self, temp_config_path, monkeypatch):
        """Test that environment variables override config file."""
        # Set value in config file
        runner.invoke(app, ["set", "log_level", "INFO"])

        # Set environment variable
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        get_settings.cache_clear()

        # Show should display env value with env source
        result = runner.invoke(app, ["show"])
        assert result.exit_code == 0
        assert "DEBUG" in result.stdout
        assert "env:LOG_LEVEL" in result.stdout
