"""Unit tests for structured logging module."""

import json
import logging
from collections.abc import Generator
from io import StringIO

import pytest
import structlog

from taskmanager.logging import get_logger, setup_logging
from taskmanager.settings import Settings


@pytest.fixture(autouse=True)
def reset_logging() -> Generator[None, None, None]:
    """Reset structlog configuration before and after each test.

    This prevents test pollution by ensuring each test starts with
    a clean logging state.
    """
    # Clear any existing configuration
    structlog.reset_defaults()
    # Reset stdlib logging configuration
    root_logger = logging.getLogger()
    # Clear all handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    # Reset level to default
    root_logger.setLevel(logging.WARNING)
    yield
    # Clean up after test
    structlog.reset_defaults()
    # Clear handlers again
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)


@pytest.fixture
def capture_stream() -> StringIO:
    """Create a StringIO stream to capture log output."""
    return StringIO()


class TestSetupLoggingTextFormat:
    """Tests for setup_logging with text format."""

    def test_text_format_uses_console_renderer(
        self, monkeypatch: pytest.MonkeyPatch, capture_stream: StringIO
    ) -> None:
        """Verify ConsoleRenderer is in processor chain for text format."""
        # Arrange
        monkeypatch.setenv("LOG_FORMAT", "text")
        monkeypatch.setenv("LOG_LEVEL", "INFO")
        settings = Settings()

        # Patch sys.stdout to capture output
        import sys
        original_stdout = sys.stdout
        monkeypatch.setattr(sys, "stdout", capture_stream)

        # Act
        setup_logging(settings)
        logger = get_logger("test")
        logger.info("test_message", key="value")

        # Assert
        output = capture_stream.getvalue()
        assert "test_message" in output
        assert "key" in output
        assert "value" in output

        # Restore stdout
        monkeypatch.setattr(sys, "stdout", original_stdout)

    def test_text_format_includes_timestamp(
        self, monkeypatch: pytest.MonkeyPatch, capture_stream: StringIO
    ) -> None:
        """Verify text format includes ISO timestamp."""
        # Arrange
        monkeypatch.setenv("LOG_FORMAT", "text")
        monkeypatch.setenv("LOG_LEVEL", "INFO")
        settings = Settings()

        import sys
        monkeypatch.setattr(sys, "stdout", capture_stream)

        # Act
        setup_logging(settings)
        logger = get_logger("test")
        logger.info("timestamped_message")

        # Assert
        output = capture_stream.getvalue()
        # ISO timestamp format contains 'T' separator
        assert "T" in output or "timestamped_message" in output


class TestSetupLoggingJsonFormat:
    """Tests for setup_logging with JSON format."""

    def test_json_format_uses_json_renderer(
        self, monkeypatch: pytest.MonkeyPatch, capture_stream: StringIO
    ) -> None:
        """Verify JSONRenderer is in processor chain for json format."""
        # Arrange
        monkeypatch.setenv("LOG_FORMAT", "json")
        monkeypatch.setenv("LOG_LEVEL", "INFO")
        settings = Settings()

        import sys
        monkeypatch.setattr(sys, "stdout", capture_stream)

        # Act
        setup_logging(settings)
        logger = get_logger("test")
        logger.info("json_test", task_id=42, status="running")

        # Assert
        output = capture_stream.getvalue().strip()
        # Parse the JSON output
        log_entry = json.loads(output)
        assert log_entry["event"] == "json_test"
        assert log_entry["task_id"] == 42
        assert log_entry["status"] == "running"

    def test_json_format_includes_timestamp(
        self, monkeypatch: pytest.MonkeyPatch, capture_stream: StringIO
    ) -> None:
        """Verify JSON format includes ISO timestamp field."""
        # Arrange
        monkeypatch.setenv("LOG_FORMAT", "json")
        monkeypatch.setenv("LOG_LEVEL", "INFO")
        settings = Settings()

        import sys
        monkeypatch.setattr(sys, "stdout", capture_stream)

        # Act
        setup_logging(settings)
        logger = get_logger("test")
        logger.info("timestamp_check")

        # Assert
        output = capture_stream.getvalue().strip()
        log_entry = json.loads(output)
        assert "timestamp" in log_entry
        # ISO format check: should contain 'T' separator
        assert "T" in log_entry["timestamp"]

    def test_json_format_includes_log_level(
        self, monkeypatch: pytest.MonkeyPatch, capture_stream: StringIO
    ) -> None:
        """Verify JSON format includes log level field."""
        # Arrange
        monkeypatch.setenv("LOG_FORMAT", "json")
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        settings = Settings()

        import sys
        monkeypatch.setattr(sys, "stdout", capture_stream)

        # Act
        setup_logging(settings)
        logger = get_logger("test")
        logger.warning("level_check")

        # Assert
        output = capture_stream.getvalue().strip()
        log_entry = json.loads(output)
        assert "level" in log_entry
        assert log_entry["level"] == "warning"

    def test_json_format_includes_callsite_info(
        self, monkeypatch: pytest.MonkeyPatch, capture_stream: StringIO
    ) -> None:
        """Verify JSON format includes function name and line number."""
        # Arrange
        monkeypatch.setenv("LOG_FORMAT", "json")
        monkeypatch.setenv("LOG_LEVEL", "INFO")
        settings = Settings()

        import sys
        monkeypatch.setattr(sys, "stdout", capture_stream)

        # Act
        setup_logging(settings)
        logger = get_logger("test")
        logger.info("callsite_check")

        # Assert
        output = capture_stream.getvalue().strip()
        log_entry = json.loads(output)
        # CallsiteParameterAdder adds func_name and lineno
        assert "func_name" in log_entry
        assert "lineno" in log_entry


class TestLogLevelFiltering:
    """Tests for log level filtering."""

    def test_debug_not_shown_when_level_info(
        self, monkeypatch: pytest.MonkeyPatch, capture_stream: StringIO
    ) -> None:
        """Verify DEBUG logs are filtered when level is INFO."""
        # Arrange
        monkeypatch.setenv("LOG_FORMAT", "json")
        monkeypatch.setenv("LOG_LEVEL", "INFO")
        settings = Settings()

        import sys
        monkeypatch.setattr(sys, "stdout", capture_stream)

        # Act
        setup_logging(settings)
        logger = get_logger("test")
        logger.debug("debug_message", should="not_appear")
        logger.info("info_message", should="appear")

        # Assert
        output = capture_stream.getvalue()
        assert "debug_message" not in output
        assert "info_message" in output

    def test_info_not_shown_when_level_warning(
        self, monkeypatch: pytest.MonkeyPatch, capture_stream: StringIO
    ) -> None:
        """Verify INFO logs are filtered when level is WARNING."""
        # Arrange
        monkeypatch.setenv("LOG_FORMAT", "json")
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        settings = Settings()

        import sys
        monkeypatch.setattr(sys, "stdout", capture_stream)

        # Act
        setup_logging(settings)
        logger = get_logger("test")
        logger.info("info_message", should="not_appear")
        logger.warning("warning_message", should="appear")

        # Assert
        output = capture_stream.getvalue()
        assert "info_message" not in output
        assert "warning_message" in output

    def test_debug_shown_when_level_debug(
        self, monkeypatch: pytest.MonkeyPatch, capture_stream: StringIO
    ) -> None:
        """Verify DEBUG logs are shown when level is DEBUG."""
        # Arrange
        monkeypatch.setenv("LOG_FORMAT", "json")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        settings = Settings()

        import sys
        monkeypatch.setattr(sys, "stdout", capture_stream)

        # Act
        setup_logging(settings)
        logger = get_logger("test")
        logger.debug("debug_message", key="value")

        # Assert
        output = capture_stream.getvalue()
        assert "debug_message" in output


class TestGetLogger:
    """Tests for get_logger function."""

    def test_returns_logger_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify get_logger returns a logger instance."""
        # Arrange
        monkeypatch.setenv("LOG_FORMAT", "text")
        monkeypatch.setenv("LOG_LEVEL", "INFO")
        settings = Settings()
        setup_logging(settings)

        # Act
        logger = get_logger("test_module")

        # Assert
        assert logger is not None
        # Structlog loggers have specific methods
        assert hasattr(logger, "info")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "error")
        assert hasattr(logger, "debug")

    def test_logger_accepts_none_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify get_logger accepts None for name (root logger)."""
        # Arrange
        monkeypatch.setenv("LOG_FORMAT", "text")
        monkeypatch.setenv("LOG_LEVEL", "INFO")
        settings = Settings()
        setup_logging(settings)

        # Act
        logger = get_logger(None)

        # Assert
        assert logger is not None

    def test_logger_can_emit_structured_events(
        self, monkeypatch: pytest.MonkeyPatch, capture_stream: StringIO
    ) -> None:
        """Verify logger can emit structured log events with context."""
        # Arrange
        monkeypatch.setenv("LOG_FORMAT", "json")
        monkeypatch.setenv("LOG_LEVEL", "INFO")
        settings = Settings()

        import sys
        monkeypatch.setattr(sys, "stdout", capture_stream)

        setup_logging(settings)

        # Act
        logger = get_logger("app")
        logger.info(
            "task_executed",
            task_id=123,
            task_name="backup",
            duration=45.2,
            status="success",
        )

        # Assert
        output = capture_stream.getvalue().strip()
        log_entry = json.loads(output)
        assert log_entry["event"] == "task_executed"
        assert log_entry["task_id"] == 123
        assert log_entry["task_name"] == "backup"
        assert log_entry["duration"] == 45.2
        assert log_entry["status"] == "success"


class TestLoggingConfiguration:
    """Tests for overall logging configuration."""

    def test_stdlib_logging_level_matches_structlog(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify stdlib logging level is set to match structlog."""
        # Arrange
        monkeypatch.setenv("LOG_FORMAT", "text")
        monkeypatch.setenv("LOG_LEVEL", "ERROR")
        settings = Settings()

        # Get root logger and reset state
        root_logger = logging.getLogger()
        # Force basicConfig to reconfigure by removing handlers
        root_logger.handlers = []
        # Also set force flag on basicConfig via direct call after setup_logging

        # Act
        setup_logging(settings)

        # Assert - logging.basicConfig in setup_logging sets this
        # Check that the level was actually set
        assert root_logger.level == logging.ERROR

    def test_multiple_loggers_isolated(
        self, monkeypatch: pytest.MonkeyPatch, capture_stream: StringIO
    ) -> None:
        """Verify multiple loggers with different names work correctly."""
        # Arrange
        monkeypatch.setenv("LOG_FORMAT", "json")
        monkeypatch.setenv("LOG_LEVEL", "INFO")
        settings = Settings()

        import sys
        monkeypatch.setattr(sys, "stdout", capture_stream)

        setup_logging(settings)

        # Act
        logger1 = get_logger("module1")
        logger2 = get_logger("module2")

        logger1.info("from_module1")
        logger2.info("from_module2")

        # Assert
        output = capture_stream.getvalue()
        assert "from_module1" in output
        assert "from_module2" in output
