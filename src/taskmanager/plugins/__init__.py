"""Plugin system for extending taskmanager functionality.

This package provides:
- Hook specifications that plugins can implement
- Plugin manager for discovery and lifecycle management
- Entry point based plugin loading
"""

from taskmanager.plugins.hookspecs import TaskManagerHookspec, hookspec
from taskmanager.plugins.manager import PluginManager


__all__ = ["PluginManager", "TaskManagerHookspec", "hookspec"]
