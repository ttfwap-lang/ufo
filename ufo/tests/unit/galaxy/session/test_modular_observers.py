# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Test for the new modular observer structure.
"""

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock

from ufo.galaxy.session.observers import (
    ConstellationProgressObserver,
    SessionMetricsObserver,
    DAGVisualizationObserver,
)
from ufo.galaxy.core.events import TaskEvent, ConstellationEvent, EventType


class TestModularObservers:
    """Test the new modular observer structure."""

    def test_observer_imports(self):
        """Test that all observers can be imported."""
        assert ConstellationProgressObserver is not None
        assert SessionMetricsObserver is not None
        assert DAGVisualizationObserver is not None

    def test_constellation_progress_observer_creation(self):
        """Test ConstellationProgressObserver can be created."""
        mock_agent = Mock()
        mock_context = Mock()

        observer = ConstellationProgressObserver(agent=mock_agent, context=mock_context)

        assert observer.agent == mock_agent
        assert observer.context == mock_context
        assert observer.task_results == {}

    def test_session_metrics_observer_creation(self):
        """Test SessionMetricsObserver can be created."""
        observer = SessionMetricsObserver(session_id="test_session")

        assert observer.metrics["session_id"] == "test_session"
        assert observer.metrics["task_count"] == 0
        assert observer.metrics["completed_tasks"] == 0
        assert observer.metrics["failed_tasks"] == 0

    def test_dag_visualization_observer_creation(self):
        """Test DAGVisualizationObserver can be created."""
        observer = DAGVisualizationObserver(enable_visualization=False)

        assert observer.enable_visualization == False
        assert observer._constellations == {}

    @pytest.mark.asyncio
    async def test_progress_observer_task_event_handling(self):
        """Test ConstellationProgressObserver handles task events."""
        mock_agent = Mock()
        mock_agent.task_completion_queue = AsyncMock()
        mock_agent.task_completion_queue.put = AsyncMock()
        mock_context = Mock()

        observer = ConstellationProgressObserver(agent=mock_agent, context=mock_context)

        # Create a task event
        task_event = TaskEvent(
            event_type=EventType.TASK_COMPLETED,
            source_id="test",
            timestamp=1234567890,
            data={},
            task_id="test_task",
            status="completed",
            result="success",
            error=None,
        )

        # Handle the event
        await observer.on_event(task_event)

        # Verify task result was stored
        assert "test_task" in observer.task_results
        assert observer.task_results["test_task"]["status"] == "completed"

        # Verify event was queued to agent
        mock_agent.task_completion_queue.put.assert_called_once_with(task_event)

    @pytest.mark.asyncio
    async def test_metrics_observer_task_event_handling(self):
        """Test SessionMetricsObserver collects metrics from task events."""
        observer = SessionMetricsObserver(session_id="test_session")

        # Create a task started event
        task_started_event = TaskEvent(
            event_type=EventType.TASK_STARTED,
            source_id="test",
            timestamp=1234567890,
            data={},
            task_id="test_task",
            status="started",
            result=None,
            error=None,
        )

        await observer.on_event(task_started_event)

        # Verify metrics were updated
        assert observer.metrics["task_count"] == 1
        assert "test_task" in observer.metrics["task_timings"]

        # Create a task completed event
        task_completed_event = TaskEvent(
            event_type=EventType.TASK_COMPLETED,
            source_id="test",
            timestamp=1234567900,
            data={},
            task_id="test_task",
            status="completed",
            result=None,
            error=None,
        )

        await observer.on_event(task_completed_event)

        # Verify completion metrics
        assert observer.metrics["completed_tasks"] == 1
        assert observer.metrics["task_timings"]["test_task"]["duration"] == 10

    def test_observer_module_locations(self):
        """Test that observers are loaded from correct modules."""
        assert (
            ConstellationProgressObserver.__module__
            in ("ufo.galaxy.session.observers.base_observer", "galaxy.session.observers.base_observer")
        )
        assert (
            SessionMetricsObserver.__module__
            in ("ufo.galaxy.session.observers.base_observer", "galaxy.session.observers.base_observer")
        )
        assert (
            DAGVisualizationObserver.__module__
            in ["ufo.galaxy.session.observers.dag_visualization_observer", "galaxy.session.observers.dag_visualization_observer"]
        )


if __name__ == "__main__":
    # Run basic tests
    test = TestModularObservers()

    print("Testing observer imports...")
    test.test_observer_imports()
    print("✓ Observer imports test passed")

    print("Testing observer creation...")
    test.test_constellation_progress_observer_creation()
    test.test_session_metrics_observer_creation()
    test.test_dag_visualization_observer_creation()
    print("✓ Observer creation tests passed")

    print("Testing module locations...")
    test.test_observer_module_locations()
    print("✓ Module location tests passed")

    print("\nAll basic tests passed! ✓")
    print("Note: Async tests require pytest to run properly.")
