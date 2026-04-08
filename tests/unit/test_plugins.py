"""Unit tests for the plugin system.

Tests cover:
- Plugin discovery via entry points
- Hookspec registration and invocation
- Hook invocation order
- Execution veto via on_before_execute
- Error handling for failed plugin loads
- Plugin metadata listing
"""

from unittest.mock import MagicMock, Mock, patch

from pluggy import HookimplMarker

from taskmanager.models import Run, Task
from taskmanager.plugins import PluginManager


hookimpl = HookimplMarker("taskmanager")


# Mock plugin implementations for testing
class MockPluginA:
    """Test plugin that tracks hook calls."""

    def __init__(self) -> None:
        self.task_registered_calls: list[Task] = []
        self.before_execute_calls: list[tuple[Task, Run]] = []
        self.after_execute_calls: list[tuple[Task, Run]] = []

    @hookimpl
    def on_task_registered(self, task: Task) -> None:
        self.task_registered_calls.append(task)

    @hookimpl
    def on_before_execute(self, task: Task, run: Run) -> None:
        self.before_execute_calls.append((task, run))

    @hookimpl
    def on_after_execute(self, task: Task, run: Run) -> None:
        self.after_execute_calls.append((task, run))


class MockPluginB:
    """Test plugin that can veto execution."""

    def __init__(self, should_veto: bool = False) -> None:
        self.should_veto = should_veto
        self.before_execute_called = False

    @hookimpl
    def on_before_execute(self, task: Task, run: Run) -> bool | None:
        self.before_execute_called = True
        if self.should_veto:
            return False
        return None


class MockPluginWithCommands:
    """Test plugin that registers CLI commands."""

    @hookimpl
    def register_commands(self, app: object) -> None:
        # Simulate adding a command
        if hasattr(app, "add_command"):
            app.add_command("test-command")  # type: ignore[attr-defined]


class MockPluginWithRoutes:
    """Test plugin that registers API routes."""

    @hookimpl
    def register_api_routes(self, router: object) -> None:
        # Simulate adding a route
        if hasattr(router, "add_route"):
            router.add_route("/test-route")  # type: ignore[attr-defined]


class TestPluginDiscovery:
    """Test plugin discovery via entry points."""

    def test_discovery_with_no_plugins(self) -> None:
        """Empty entry points should result in no plugins loaded."""
        with patch(
            "importlib.metadata.entry_points", return_value=[]
        ):
            pm = PluginManager()
            assert pm.list_plugins() == []

    def test_discovery_with_valid_plugin(self) -> None:
        """Valid plugin should be loaded and registered."""
        mock_ep = Mock()
        mock_ep.name = "test-plugin"
        mock_ep.value = "test_module:TestPlugin"
        mock_ep.load.return_value = MockPluginA()
        mock_ep.dist = Mock()
        mock_ep.dist.version = "1.0.0"

        with patch(
            "importlib.metadata.entry_points",
            return_value=[mock_ep],
        ):
            pm = PluginManager()
            plugins = pm.list_plugins()

            assert len(plugins) == 1
            assert plugins[0]["name"] == "test-plugin"
            assert plugins[0]["version"] == "1.0.0"
            assert plugins[0]["status"] == "loaded"
            assert plugins[0]["error"] is None

    def test_discovery_with_failing_plugin(self) -> None:
        """Plugin that fails to load should be tracked as error."""
        mock_ep = Mock()
        mock_ep.name = "broken-plugin"
        mock_ep.value = "broken_module:BrokenPlugin"
        mock_ep.load.side_effect = ImportError("Module not found")

        with patch(
            "importlib.metadata.entry_points",
            return_value=[mock_ep],
        ):
            pm = PluginManager()
            plugins = pm.list_plugins()

            assert len(plugins) == 1
            assert plugins[0]["name"] == "broken-plugin"
            assert plugins[0]["status"] == "error"
            assert "Module not found" in plugins[0]["error"]

    def test_discovery_continues_after_plugin_error(self) -> None:
        """Plugin load errors should not prevent other plugins from loading."""
        mock_ep_broken = Mock()
        mock_ep_broken.name = "broken-plugin"
        mock_ep_broken.value = "broken_module:BrokenPlugin"
        mock_ep_broken.load.side_effect = ImportError("Module not found")

        mock_ep_working = Mock()
        mock_ep_working.name = "working-plugin"
        mock_ep_working.value = "working_module:WorkingPlugin"
        mock_ep_working.load.return_value = MockPluginA()
        mock_ep_working.dist = Mock()
        mock_ep_working.dist.version = "2.0.0"

        with patch(
            "importlib.metadata.entry_points",
            return_value=[mock_ep_broken, mock_ep_working],
        ):
            pm = PluginManager()
            plugins = pm.list_plugins()

            assert len(plugins) == 2
            # Check broken plugin
            broken = next(p for p in plugins if p["name"] == "broken-plugin")
            assert broken["status"] == "error"
            # Check working plugin
            working = next(p for p in plugins if p["name"] == "working-plugin")
            assert working["status"] == "loaded"

    def test_discovery_with_no_dist_version(self) -> None:
        """Plugin with no dist metadata should default to 'unknown' version."""
        mock_ep = Mock()
        mock_ep.name = "no-version-plugin"
        mock_ep.value = "test_module:TestPlugin"
        mock_ep.load.return_value = MockPluginA()
        mock_ep.dist = None

        with patch(
            "importlib.metadata.entry_points",
            return_value=[mock_ep],
        ):
            pm = PluginManager()
            plugins = pm.list_plugins()

            assert len(plugins) == 1
            assert plugins[0]["version"] == "unknown"


class TestHookspecRegistration:
    """Test programmatic plugin registration."""

    def test_register_plugin_programmatically(self) -> None:
        """Plugins can be registered directly for testing."""
        with patch("importlib.metadata.entry_points", return_value=[]):
            pm = PluginManager()
            plugin = MockPluginA()
            pm.register_plugin(plugin, name="test-plugin")

            plugins = pm.list_plugins()
            assert len(plugins) == 1
            assert plugins[0]["name"] == "test-plugin"
            assert plugins[0]["status"] == "loaded"

    def test_register_plugin_without_name(self) -> None:
        """Plugin registered without name should use class name."""
        with patch("importlib.metadata.entry_points", return_value=[]):
            pm = PluginManager()
            plugin = MockPluginA()
            pm.register_plugin(plugin)

            plugins = pm.list_plugins()
            assert len(plugins) == 1
            assert plugins[0]["name"] == "MockPluginA"


class TestHookInvocation:
    """Test hook invocation and call propagation."""

    def test_on_task_registered_hook(self) -> None:
        """on_task_registered should be called for all plugins."""
        with patch("importlib.metadata.entry_points", return_value=[]):
            pm = PluginManager()
            plugin = MockPluginA()
            pm.register_plugin(plugin)

            mock_task = Mock(spec=Task)
            pm.call_on_task_registered(mock_task)

            assert len(plugin.task_registered_calls) == 1
            assert plugin.task_registered_calls[0] is mock_task

    def test_on_before_execute_hook(self) -> None:
        """on_before_execute should be called for all plugins."""
        with patch("importlib.metadata.entry_points", return_value=[]):
            pm = PluginManager()
            plugin = MockPluginA()
            pm.register_plugin(plugin)

            mock_task = Mock(spec=Task)
            mock_run = Mock(spec=Run)
            result = pm.call_on_before_execute(mock_task, mock_run)

            assert result is True  # No veto
            assert len(plugin.before_execute_calls) == 1
            assert plugin.before_execute_calls[0] == (mock_task, mock_run)

    def test_on_after_execute_hook(self) -> None:
        """on_after_execute should be called for all plugins."""
        with patch("importlib.metadata.entry_points", return_value=[]):
            pm = PluginManager()
            plugin = MockPluginA()
            pm.register_plugin(plugin)

            mock_task = Mock(spec=Task)
            mock_run = Mock(spec=Run)
            pm.call_on_after_execute(mock_task, mock_run)

            assert len(plugin.after_execute_calls) == 1
            assert plugin.after_execute_calls[0] == (mock_task, mock_run)


class TestHookInvocationOrder:
    """Test that multiple plugins are called in registration order."""

    def test_multiple_plugins_called_in_order(self) -> None:
        """All registered plugins should receive hook calls."""
        with patch("importlib.metadata.entry_points", return_value=[]):
            pm = PluginManager()
            plugin_a = MockPluginA()
            plugin_b = MockPluginA()

            pm.register_plugin(plugin_a, name="plugin-a")
            pm.register_plugin(plugin_b, name="plugin-b")

            mock_task = Mock(spec=Task)
            pm.call_on_task_registered(mock_task)

            # Both plugins should have been called
            assert len(plugin_a.task_registered_calls) == 1
            assert len(plugin_b.task_registered_calls) == 1


class TestExecutionVeto:
    """Test on_before_execute veto mechanism."""

    def test_veto_prevents_execution(self) -> None:
        """Plugin returning False should veto execution."""
        with patch("importlib.metadata.entry_points", return_value=[]):
            pm = PluginManager()
            plugin = MockPluginB(should_veto=True)
            pm.register_plugin(plugin)

            mock_task = Mock(spec=Task)
            mock_run = Mock(spec=Run)
            result = pm.call_on_before_execute(mock_task, mock_run)

            assert result is False
            assert plugin.before_execute_called is True

    def test_no_veto_allows_execution(self) -> None:
        """Plugin returning None should allow execution."""
        with patch("importlib.metadata.entry_points", return_value=[]):
            pm = PluginManager()
            plugin = MockPluginB(should_veto=False)
            pm.register_plugin(plugin)

            mock_task = Mock(spec=Task)
            mock_run = Mock(spec=Run)
            result = pm.call_on_before_execute(mock_task, mock_run)

            assert result is True
            assert plugin.before_execute_called is True

    def test_any_plugin_can_veto(self) -> None:
        """Single veto should prevent execution even with multiple plugins."""
        with patch("importlib.metadata.entry_points", return_value=[]):
            pm = PluginManager()
            plugin_allow = MockPluginB(should_veto=False)
            plugin_veto = MockPluginB(should_veto=True)

            pm.register_plugin(plugin_allow, name="allow")
            pm.register_plugin(plugin_veto, name="veto")

            mock_task = Mock(spec=Task)
            mock_run = Mock(spec=Run)
            result = pm.call_on_before_execute(mock_task, mock_run)

            assert result is False


class TestErrorHandling:
    """Test error handling in hook invocation."""

    def test_hook_error_does_not_crash(self) -> None:
        """Errors during hook invocation should be logged but not crash."""

        class BrokenPlugin:
            @hookimpl
            def on_task_registered(self, task: Task) -> None:
                raise RuntimeError("Plugin is broken")  # noqa: TRY003

        with patch("importlib.metadata.entry_points", return_value=[]):
            pm = PluginManager()
            pm.register_plugin(BrokenPlugin())

            mock_task = Mock(spec=Task)
            # Should not raise
            pm.call_on_task_registered(mock_task)

    def test_before_execute_error_allows_execution(self) -> None:
        """Error in on_before_execute should default to allowing execution."""

        class BrokenPlugin:
            @hookimpl
            def on_before_execute(self, task: Task, run: Run) -> bool:
                raise RuntimeError("Plugin is broken")  # noqa: TRY003

        with patch("importlib.metadata.entry_points", return_value=[]):
            pm = PluginManager()
            pm.register_plugin(BrokenPlugin())

            mock_task = Mock(spec=Task)
            mock_run = Mock(spec=Run)
            result = pm.call_on_before_execute(mock_task, mock_run)

            # Error should result in allowing execution
            assert result is True


class TestCommandAndRouteRegistration:
    """Test CLI command and API route registration hooks."""

    def test_register_commands_hook(self) -> None:
        """register_commands should be called with app instance."""
        with patch("importlib.metadata.entry_points", return_value=[]):
            pm = PluginManager()
            pm.register_plugin(MockPluginWithCommands())

            mock_app = MagicMock()
            pm.call_register_commands(mock_app)

            # Verify the command was added
            mock_app.add_command.assert_called_once_with("test-command")

    def test_register_api_routes_hook(self) -> None:
        """register_api_routes should be called with router instance."""
        with patch("importlib.metadata.entry_points", return_value=[]):
            pm = PluginManager()
            pm.register_plugin(MockPluginWithRoutes())

            mock_router = MagicMock()
            pm.call_register_api_routes(mock_router)

            # Verify the route was added
            mock_router.add_route.assert_called_once_with("/test-route")

    def test_command_registration_error_does_not_crash(self) -> None:
        """Error during command registration should be logged."""

        class BrokenCommandPlugin:
            @hookimpl
            def register_commands(self, app: object) -> None:
                raise RuntimeError("Cannot register commands")  # noqa: TRY003

        with patch("importlib.metadata.entry_points", return_value=[]):
            pm = PluginManager()
            pm.register_plugin(BrokenCommandPlugin())

            mock_app = MagicMock()
            # Should not raise
            pm.call_register_commands(mock_app)

    def test_route_registration_error_does_not_crash(self) -> None:
        """Error during route registration should be logged."""

        class BrokenRoutePlugin:
            @hookimpl
            def register_api_routes(self, router: object) -> None:
                raise RuntimeError("Cannot register routes")  # noqa: TRY003

        with patch("importlib.metadata.entry_points", return_value=[]):
            pm = PluginManager()
            pm.register_plugin(BrokenRoutePlugin())

            mock_router = MagicMock()
            # Should not raise
            pm.call_register_api_routes(mock_router)


class TestListPlugins:
    """Test plugin listing functionality."""

    def test_list_plugins_returns_all_metadata(self) -> None:
        """list_plugins should return complete metadata for all plugins."""
        mock_ep = Mock()
        mock_ep.name = "test-plugin"
        mock_ep.value = "test_module:TestPlugin"
        mock_ep.load.return_value = MockPluginA()
        mock_ep.dist = Mock()
        mock_ep.dist.version = "1.2.3"

        with patch(
            "importlib.metadata.entry_points",
            return_value=[mock_ep],
        ):
            pm = PluginManager()
            plugins = pm.list_plugins()

            assert len(plugins) == 1
            plugin = plugins[0]
            assert plugin["name"] == "test-plugin"
            assert plugin["version"] == "1.2.3"
            assert plugin["module"] == "test_module:TestPlugin"
            assert plugin["status"] == "loaded"
            assert plugin["error"] is None

    def test_list_plugins_includes_failed_plugins(self) -> None:
        """list_plugins should include failed plugins with error details."""
        mock_ep = Mock()
        mock_ep.name = "broken-plugin"
        mock_ep.value = "broken_module:BrokenPlugin"
        mock_ep.load.side_effect = ValueError("Invalid plugin")

        with patch(
            "importlib.metadata.entry_points",
            return_value=[mock_ep],
        ):
            pm = PluginManager()
            plugins = pm.list_plugins()

            assert len(plugins) == 1
            plugin = plugins[0]
            assert plugin["name"] == "broken-plugin"
            assert plugin["status"] == "error"
            assert "Invalid plugin" in plugin["error"]
