"""Plugin manager for discovering and loading taskmanager plugins.

This module handles plugin discovery via entry points, loading plugins with
error handling, and providing a unified interface for invoking plugin hooks.
"""

import importlib.metadata
import logging
from typing import TYPE_CHECKING, Any

import pluggy

from taskmanager.plugins.hookspecs import TaskManagerHookspec


if TYPE_CHECKING:
    from taskmanager.models import Run, Task

logger = logging.getLogger(__name__)


class PluginManager:
    """Manages plugin discovery, loading, and hook invocation.

    Plugins are discovered via the 'taskmanager.plugins' entry point group.
    Failed plugins are logged but do not prevent the manager from initializing.
    """

    def __init__(self) -> None:
        """Initialize the plugin manager and discover plugins."""
        self.pm = pluggy.PluginManager("taskmanager")
        self.pm.add_hookspecs(TaskManagerHookspec)

        # Track plugin metadata: name -> {name, version, module, status, error}
        self._plugin_metadata: dict[str, dict[str, Any]] = {}

        self._discover_and_load_plugins()

    def _discover_and_load_plugins(self) -> None:
        """Discover and load plugins from entry points.

        Plugins that fail to load are logged and stored in metadata with
        status='error', but do not prevent other plugins from loading.
        """
        try:
            entry_points = importlib.metadata.entry_points(
                group="taskmanager.plugins"
            )
        except Exception:
            logger.exception("Failed to discover entry points")
            return

        for ep in entry_points:
            try:
                plugin_module = ep.load()
                self.pm.register(plugin_module, name=ep.name)

                # Extract version from distribution metadata
                version = "unknown"
                try:
                    # Get the distribution that provided this entry point
                    dist = ep.dist
                    if dist:
                        version = dist.version
                except Exception:
                    pass

                self._plugin_metadata[ep.name] = {
                    "name": ep.name,
                    "version": version,
                    "module": ep.value,
                    "status": "loaded",
                    "error": None,
                }
                logger.info(f"Loaded plugin: {ep.name} (v{version})")

            except Exception as e:
                logger.exception(f"Failed to load plugin '{ep.name}'")
                self._plugin_metadata[ep.name] = {
                    "name": ep.name,
                    "version": "unknown",
                    "module": ep.value,
                    "status": "error",
                    "error": str(e),
                }

    def register_plugin(self, plugin: Any, name: str | None = None) -> None:
        """Register a plugin programmatically (for testing).

        Parameters
        ----------
        plugin:
            The plugin object implementing one or more hook methods.
        name:
            Optional name for the plugin. If not provided, uses the plugin's
            module name.
        """
        plugin_name = name or plugin.__class__.__name__
        self.pm.register(plugin, name=plugin_name)

        self._plugin_metadata[plugin_name] = {
            "name": plugin_name,
            "version": "dev",
            "module": plugin.__class__.__module__,
            "status": "loaded",
            "error": None,
        }

    def call_on_task_registered(self, task: "Task") -> None:
        """Call the on_task_registered hook for all plugins.

        Parameters
        ----------
        task:
            The newly created Task object.
        """
        try:
            self.pm.hook.on_task_registered(task=task)
        except Exception:
            logger.exception("Error calling on_task_registered hook")

    def call_on_before_execute(self, task: "Task", run: "Run") -> bool:
        """Call the on_before_execute hook for all plugins.

        If any plugin returns False, execution should be vetoed.

        Parameters
        ----------
        task:
            The Task object about to be executed.
        run:
            The Run object representing this execution attempt.

        Returns
        -------
        bool
            False if any plugin vetoed execution, True otherwise.
        """
        try:
            results = self.pm.hook.on_before_execute(task=task, run=run)
        except Exception:
            logger.exception("Error calling on_before_execute hook")
            # On error, allow execution to proceed
            return True
        else:
            # If any plugin explicitly returns False, veto execution
            return False not in results

    def call_on_after_execute(self, task: "Task", run: "Run") -> None:
        """Call the on_after_execute hook for all plugins.

        Parameters
        ----------
        task:
            The Task object that was executed.
        run:
            The completed Run object with execution results.
        """
        try:
            self.pm.hook.on_after_execute(task=task, run=run)
        except Exception:
            logger.exception("Error calling on_after_execute hook")

    def call_register_commands(self, app: Any) -> None:
        """Call the register_commands hook for all plugins.

        Parameters
        ----------
        app:
            The Typer app instance to register commands with.
        """
        try:
            self.pm.hook.register_commands(app=app)
        except Exception:
            logger.exception("Error calling register_commands hook")

    def call_register_api_routes(self, router: Any) -> None:
        """Call the register_api_routes hook for all plugins.

        Parameters
        ----------
        router:
            The FastAPI APIRouter instance to register routes with.
        """
        try:
            self.pm.hook.register_api_routes(router=router)
        except Exception:
            logger.exception("Error calling register_api_routes hook")

    def list_plugins(self) -> list[dict[str, Any]]:
        """List all discovered plugins with their metadata.

        Returns
        -------
        list[dict[str, Any]]
            List of plugin metadata dictionaries with keys:
            - name: Plugin name
            - version: Plugin version
            - module: Module path
            - status: 'loaded' or 'error'
            - error: Error message if status is 'error', None otherwise
        """
        return list(self._plugin_metadata.values())
