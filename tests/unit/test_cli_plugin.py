"""Unit tests for the plugin CLI commands.

Tests cover:
- plugin list with no plugins
- plugin list with existing plugins
- plugin info for existing plugin
- plugin info for missing plugin
- plugin list showing error status for failed plugins
"""

from unittest.mock import Mock, patch

from typer.testing import CliRunner

from taskmanager.cli import app


runner = CliRunner()


class TestPluginList:
    """Tests for the 'plugin list' command."""

    def test_list_with_no_plugins(self) -> None:
        """Should show 'No plugins installed' when no plugins exist."""
        with patch("taskmanager.cli.plugin.PluginManager") as mock_pm_class:
            mock_pm = Mock()
            mock_pm.list_plugins.return_value = []
            mock_pm_class.return_value = mock_pm

            result = runner.invoke(app, ["plugin", "list"])

            assert result.exit_code == 0
            assert "No plugins installed" in result.stdout

    def test_list_with_plugins(self) -> None:
        """Should show table with plugin information when plugins exist."""
        with patch("taskmanager.cli.plugin.PluginManager") as mock_pm_class:
            mock_pm = Mock()
            mock_pm.list_plugins.return_value = [
                {
                    "name": "test-plugin",
                    "version": "1.0.0",
                    "module": "test_module:TestPlugin",
                    "status": "loaded",
                    "error": None,
                },
                {
                    "name": "another-plugin",
                    "version": "2.0.0",
                    "module": "another_module:AnotherPlugin",
                    "status": "loaded",
                    "error": None,
                },
            ]
            mock_pm_class.return_value = mock_pm

            result = runner.invoke(app, ["plugin", "list"])

            assert result.exit_code == 0
            assert "Installed Plugins" in result.stdout
            assert "test-plugin" in result.stdout
            assert "1.0.0" in result.stdout
            assert "another-plugin" in result.stdout
            assert "2.0.0" in result.stdout
            assert "loaded" in result.stdout

    def test_list_with_failed_plugin(self) -> None:
        """Should show error status and message for failed plugins."""
        with patch("taskmanager.cli.plugin.PluginManager") as mock_pm_class:
            mock_pm = Mock()
            mock_pm.list_plugins.return_value = [
                {
                    "name": "broken-plugin",
                    "version": "unknown",
                    "module": "broken_module:BrokenPlugin",
                    "status": "error",
                    "error": "Module not found",
                }
            ]
            mock_pm_class.return_value = mock_pm

            result = runner.invoke(app, ["plugin", "list"])

            assert result.exit_code == 0
            assert "broken-plugin" in result.stdout
            assert "error" in result.stdout
            assert "Module not found" in result.stdout


class TestPluginInfo:
    """Tests for the 'plugin info' command."""

    def test_info_for_existing_plugin(self) -> None:
        """Should show detailed information for existing plugin."""
        with patch("taskmanager.cli.plugin.PluginManager") as mock_pm_class:
            mock_pm = Mock()
            mock_pm.list_plugins.return_value = [
                {
                    "name": "test-plugin",
                    "version": "1.0.0",
                    "module": "test_module:TestPlugin",
                    "status": "loaded",
                    "error": None,
                }
            ]
            mock_pm_class.return_value = mock_pm

            result = runner.invoke(app, ["plugin", "info", "test-plugin"])

            assert result.exit_code == 0
            assert "Plugin: test-plugin" in result.stdout
            assert "Version: 1.0.0" in result.stdout
            assert "Module: test_module:TestPlugin" in result.stdout
            assert "Status: loaded" in result.stdout

    def test_info_for_missing_plugin(self) -> None:
        """Should exit with error when plugin is not found."""
        with patch("taskmanager.cli.plugin.PluginManager") as mock_pm_class:
            mock_pm = Mock()
            mock_pm.list_plugins.return_value = []
            mock_pm_class.return_value = mock_pm

            result = runner.invoke(app, ["plugin", "info", "missing-plugin"])

            assert result.exit_code == 1
            # Error messages go to stderr with console_err
            output = result.stdout + result.stderr
            assert "Error" in output
            assert "not found" in output

    def test_info_for_failed_plugin(self) -> None:
        """Should show error details for failed plugin."""
        with patch("taskmanager.cli.plugin.PluginManager") as mock_pm_class:
            mock_pm = Mock()
            mock_pm.list_plugins.return_value = [
                {
                    "name": "broken-plugin",
                    "version": "unknown",
                    "module": "broken_module:BrokenPlugin",
                    "status": "error",
                    "error": "Import failed: missing dependency",
                }
            ]
            mock_pm_class.return_value = mock_pm

            result = runner.invoke(app, ["plugin", "info", "broken-plugin"])

            assert result.exit_code == 0
            assert "Plugin: broken-plugin" in result.stdout
            assert "Status: error" in result.stdout
            assert "Error: Import failed: missing dependency" in result.stdout
