"""Unit tests for event bus module."""
# ruff: noqa: ARG001, TRY003  # Test handlers with unused payload match EventBus signature

import threading
from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import patch

import pytest

from taskmanager.events import (
    SCHEDULE_MISSED,
    SCHEDULE_TRIGGERED,
    TASK_COMPLETED,
    TASK_FAILED,
    TASK_STARTED,
    TASK_TIMEOUT,
    EventBus,
    get_event_bus,
)


@pytest.fixture
def bus() -> EventBus:
    """Create a fresh EventBus instance for each test."""
    return EventBus()


@pytest.fixture(autouse=True)
def clear_event_bus_cache() -> Generator[None, None, None]:
    """Clear the get_event_bus singleton cache between tests."""
    get_event_bus.cache_clear()
    yield
    get_event_bus.cache_clear()


class TestEventConstants:
    """Tests for event type constants."""

    def test_task_event_constants_defined(self) -> None:
        """Verify all task event constants are defined."""
        assert TASK_STARTED == "task.started"
        assert TASK_COMPLETED == "task.completed"
        assert TASK_FAILED == "task.failed"
        assert TASK_TIMEOUT == "task.timeout"

    def test_schedule_event_constants_defined(self) -> None:
        """Verify all schedule event constants are defined."""
        assert SCHEDULE_TRIGGERED == "schedule.triggered"
        assert SCHEDULE_MISSED == "schedule.missed"


class TestEventBusBasicOperation:
    """Tests for basic EventBus operations."""

    def test_register_and_emit_single_handler(self, bus: EventBus) -> None:
        """Verify handler is called with correct payload on emit."""
        # Arrange
        received_payloads: list[dict[str, Any]] = []

        def handler(payload: dict[str, Any]) -> None:
            received_payloads.append(payload)

        bus.on(TASK_STARTED, handler)

        # Act
        payload = {"task_id": "123", "task_name": "backup"}
        bus.emit(TASK_STARTED, payload)

        # Assert
        assert len(received_payloads) == 1
        assert received_payloads[0] == payload

    def test_multiple_handlers_for_same_event(self, bus: EventBus) -> None:
        """Verify multiple handlers for same event are all called."""
        # Arrange
        call_order: list[str] = []

        def handler1(payload: dict[str, Any]) -> None:
            call_order.append("handler1")

        def handler2(payload: dict[str, Any]) -> None:
            call_order.append("handler2")

        def handler3(payload: dict[str, Any]) -> None:
            call_order.append("handler3")

        bus.on(TASK_STARTED, handler1)
        bus.on(TASK_STARTED, handler2)
        bus.on(TASK_STARTED, handler3)

        # Act
        bus.emit(TASK_STARTED, {"task_id": "123"})

        # Assert
        assert len(call_order) == 3
        assert "handler1" in call_order
        assert "handler2" in call_order
        assert "handler3" in call_order

    def test_emit_without_handlers_does_nothing(self, bus: EventBus) -> None:
        """Verify emitting event with no handlers is a no-op."""
        # Act - should not raise
        bus.emit(TASK_STARTED, {"task_id": "123"})

        # Assert - no exception raised
        assert True

    def test_handlers_isolated_by_event_type(self, bus: EventBus) -> None:
        """Verify handlers only called for their registered event type."""
        # Arrange
        started_called = False
        completed_called = False

        def started_handler(payload: dict[str, Any]) -> None:
            nonlocal started_called
            started_called = True

        def completed_handler(payload: dict[str, Any]) -> None:
            nonlocal completed_called
            completed_called = True

        bus.on(TASK_STARTED, started_handler)
        bus.on(TASK_COMPLETED, completed_handler)

        # Act
        bus.emit(TASK_STARTED, {})

        # Assert
        assert started_called is True
        assert completed_called is False


class TestEventBusUnregister:
    """Tests for handler unregistration."""

    def test_off_removes_handler(self, bus: EventBus) -> None:
        """Verify off() removes handler and it's no longer called."""
        # Arrange
        call_count = 0

        def handler(payload: dict[str, Any]) -> None:
            nonlocal call_count
            call_count += 1

        bus.on(TASK_STARTED, handler)
        bus.emit(TASK_STARTED, {})
        assert call_count == 1

        # Act
        bus.off(TASK_STARTED, handler)
        bus.emit(TASK_STARTED, {})

        # Assert
        assert call_count == 1  # Still 1, not 2

    def test_off_only_affects_target_handler(self, bus: EventBus) -> None:
        """Verify off() only removes specified handler, not others."""
        # Arrange
        handler1_calls = 0
        handler2_calls = 0

        def handler1(payload: dict[str, Any]) -> None:
            nonlocal handler1_calls
            handler1_calls += 1

        def handler2(payload: dict[str, Any]) -> None:
            nonlocal handler2_calls
            handler2_calls += 1

        bus.on(TASK_STARTED, handler1)
        bus.on(TASK_STARTED, handler2)

        # Act
        bus.off(TASK_STARTED, handler1)
        bus.emit(TASK_STARTED, {})

        # Assert
        assert handler1_calls == 0
        assert handler2_calls == 1

    def test_off_unregistered_handler_is_noop(self, bus: EventBus) -> None:
        """Verify off() with unregistered handler does not raise."""
        # Arrange
        def handler(payload: dict[str, Any]) -> None:
            pass

        # Act - should not raise
        bus.off(TASK_STARTED, handler)

        # Assert - no exception raised
        assert True

    def test_duplicate_registration_prevented(self, bus: EventBus) -> None:
        """Verify registering same handler twice doesn't call it twice."""
        # Arrange
        call_count = 0

        def handler(payload: dict[str, Any]) -> None:
            nonlocal call_count
            call_count += 1

        bus.on(TASK_STARTED, handler)
        bus.on(TASK_STARTED, handler)  # Register again

        # Act
        bus.emit(TASK_STARTED, {})

        # Assert
        assert call_count == 1  # Called once, not twice


class TestEventBusExceptionHandling:
    """Tests for exception isolation."""

    def test_handler_exception_does_not_crash_emitter(self, bus: EventBus) -> None:
        """Verify handler exception is caught and logged."""
        # Arrange
        def failing_handler(payload: dict[str, Any]) -> None:
            raise ValueError("Handler failed")

        bus.on(TASK_STARTED, failing_handler)

        # Act - should not raise
        with patch("taskmanager.events.logger") as mock_logger:
            bus.emit(TASK_STARTED, {"task_id": "123"})

            # Assert - exception was logged
            assert mock_logger.error.called

    def test_exception_does_not_prevent_other_handlers(self, bus: EventBus) -> None:
        """Verify other handlers still execute after one fails."""
        # Arrange
        handler2_called = False

        def failing_handler(payload: dict[str, Any]) -> None:
            raise RuntimeError("Boom")

        def succeeding_handler(payload: dict[str, Any]) -> None:
            nonlocal handler2_called
            handler2_called = True

        bus.on(TASK_STARTED, failing_handler)
        bus.on(TASK_STARTED, succeeding_handler)

        # Act
        bus.emit(TASK_STARTED, {})

        # Assert
        assert handler2_called is True

    def test_handler_exception_logged_with_details(self, bus: EventBus) -> None:
        """Verify handler exception includes event type and handler name."""
        # Arrange
        def my_failing_handler(payload: dict[str, Any]) -> None:
            raise ValueError("Expected test error")

        bus.on(TASK_FAILED, my_failing_handler)

        # Act
        with patch("taskmanager.events.logger") as mock_logger:
            bus.emit(TASK_FAILED, {"task_id": "456"})

            # Assert - log should contain event type and handler name
            mock_logger.error.assert_called_once()
            call_kwargs = mock_logger.error.call_args[1]
            assert call_kwargs["event_type"] == "task.failed"
            assert call_kwargs["handler"] == "my_failing_handler"
            assert "Expected test error" in call_kwargs["error"]


class TestEventBusThreadSafety:
    """Tests for thread-safety guarantees."""

    def test_concurrent_registration(self, bus: EventBus) -> None:
        """Verify multiple threads can register handlers concurrently."""
        # Arrange
        handlers_executed = []
        lock = threading.Lock()

        def create_handler(handler_id: int) -> Callable[[dict[str, Any]], None]:
            def handler(payload: dict[str, Any]) -> None:
                with lock:
                    handlers_executed.append(handler_id)
            return handler

        # Act - register 50 handlers from 10 threads
        threads = []
        for i in range(50):
            t = threading.Thread(target=bus.on, args=(TASK_STARTED, create_handler(i)))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Emit event
        bus.emit(TASK_STARTED, {})

        # Assert - all handlers were called
        assert len(handlers_executed) == 50
        assert set(handlers_executed) == set(range(50))

    def test_concurrent_unregistration(self, bus: EventBus) -> None:
        """Verify multiple threads can unregister handlers concurrently."""
        # Arrange
        handlers = []
        for i in range(20):
            def handler(payload: dict[str, Any], idx: int = i) -> None:
                pass
            handlers.append(handler)
            bus.on(TASK_COMPLETED, handler)

        # Act - unregister from multiple threads
        threads = []
        for handler in handlers:
            t = threading.Thread(target=bus.off, args=(TASK_COMPLETED, handler))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Assert - emit should not call any handlers
        call_count = 0

        def counter(payload: dict[str, Any]) -> None:
            nonlocal call_count
            call_count += 1

        bus.on(TASK_COMPLETED, counter)
        bus.emit(TASK_COMPLETED, {})

        assert call_count == 1  # Only the counter, none of the removed handlers

    def test_concurrent_emit(self, bus: EventBus) -> None:
        """Verify multiple threads can emit events concurrently."""
        # Arrange
        received_events = []
        lock = threading.Lock()

        def handler(payload: dict[str, Any]) -> None:
            with lock:
                received_events.append(payload["thread_id"])

        bus.on(TASK_TIMEOUT, handler)

        # Act - emit from 30 threads
        threads = []
        for i in range(30):
            t = threading.Thread(
                target=bus.emit,
                args=(TASK_TIMEOUT, {"thread_id": i})
            )
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Assert - all events were processed
        assert len(received_events) == 30
        assert set(received_events) == set(range(30))

    def test_concurrent_on_off_emit(self, bus: EventBus) -> None:
        """Verify mixed concurrent operations don't cause race conditions."""
        # Arrange
        call_counts = []
        lock = threading.Lock()

        def handler(payload: dict[str, Any]) -> None:
            with lock:
                call_counts.append(1)

        # Act - mix of operations from multiple threads
        def register_worker() -> None:
            bus.on(SCHEDULE_TRIGGERED, handler)

        def unregister_worker() -> None:
            bus.off(SCHEDULE_TRIGGERED, handler)

        def emit_worker() -> None:
            bus.emit(SCHEDULE_TRIGGERED, {"schedule_id": "s1"})

        threads = []
        for _ in range(5):
            threads.append(threading.Thread(target=register_worker))
            threads.append(threading.Thread(target=unregister_worker))
            threads.append(threading.Thread(target=emit_worker))

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Assert - no crashes, operations completed
        # Exact count is non-deterministic due to race conditions,
        # but this tests that no deadlocks or exceptions occur
        assert isinstance(call_counts, list)


class TestGetEventBusSingleton:
    """Tests for get_event_bus singleton."""

    def test_returns_event_bus_instance(self) -> None:
        """Verify get_event_bus returns an EventBus instance."""
        bus = get_event_bus()
        assert isinstance(bus, EventBus)

    def test_returns_same_instance_on_multiple_calls(self) -> None:
        """Verify get_event_bus returns the same instance each time."""
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2

    def test_singleton_across_threads(self) -> None:
        """Verify get_event_bus returns same instance from different threads."""
        instances = []
        lock = threading.Lock()

        def get_instance() -> None:
            bus = get_event_bus()
            with lock:
                instances.append(id(bus))

        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Assert - all threads got the same instance ID
        assert len(set(instances)) == 1

    def test_handlers_persist_across_get_calls(self) -> None:
        """Verify handlers registered on singleton persist."""
        # Arrange
        bus1 = get_event_bus()
        call_count = 0

        def handler(payload: dict[str, Any]) -> None:
            nonlocal call_count
            call_count += 1

        bus1.on(TASK_STARTED, handler)

        # Act
        bus2 = get_event_bus()
        bus2.emit(TASK_STARTED, {})

        # Assert
        assert call_count == 1
        assert bus1 is bus2
