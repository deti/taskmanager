"""Built-in plugins for taskmanager.

This package provides core plugins that ship with taskmanager:
- retry: Automatically retry failed tasks with exponential backoff
- timeout: Override task execution timeout from task metadata
"""

from taskmanager.plugins.builtin.retry import RetryPlugin
from taskmanager.plugins.builtin.timeout import TimeoutPlugin


__all__ = ["RetryPlugin", "TimeoutPlugin"]
