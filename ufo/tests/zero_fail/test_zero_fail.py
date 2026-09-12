# Unit tests for Zero-Fail Phase implementations

import asyncio
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timezone


class TestLLMWatchdogHealthCheck(unittest.TestCase):
    """Test the LLM Watchdog health checking logic."""

    def test_watchdog_init(self):
        """Test watchdog can be instantiated with default config."""
        from ufo.utils.llm_resilience import LLMWatchdog, DEFAULT_SERVERS
        watchdog = LLMWatchdog()
        self.assertEqual(len(watchdog.servers), len(DEFAULT_SERVERS))
        self.assertEqual(watchdog.check_interval, 30.0)
        self.assertEqual(watchdog.health_timeout, 5.0)

    def test_watchdog_singleton(self):
        """Test get_watchdog returns the same instance."""
        from ufo.utils.llm_resilience import get_watchdog
        w1 = get_watchdog()
        w2 = get_watchdog()
        self.assertIs(w1, w2)

    @patch("urllib.request.urlopen")
    def test_health_check_success(self, mock_urlopen):
        """Test successful health check."""
        from ufo.utils.llm_resilience import LLMWatchdog, LLMServerConfig
        
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response
        
        server = LLMServerConfig(name="test", port=8080, model_path="dummy.gguf")
        watchdog = LLMWatchdog(servers=[server])
        self.assertTrue(watchdog._check_health(server))

    @patch("urllib.request.urlopen", side_effect=ConnectionRefusedError)
    def test_health_check_failure(self, mock_urlopen):
        """Test failed health check."""
        from ufo.utils.llm_resilience import LLMWatchdog, LLMServerConfig
        
        server = LLMServerConfig(name="test", port=8080, model_path="dummy.gguf")
        watchdog = LLMWatchdog(servers=[server])
        self.assertFalse(watchdog._check_health(server))

    def test_max_restarts_triggers_failover(self):
        """Test that exceeding max restarts triggers cloud failover."""
        from ufo.utils.llm_resilience import LLMWatchdog, LLMServerConfig
        
        server = LLMServerConfig(name="test", port=8080, model_path="dummy.gguf")
        server.max_restarts = 2
        server.restart_count = 2  # Already at max
        
        watchdog = LLMWatchdog(servers=[server])
        with patch.object(watchdog, '_trigger_cloud_failover') as mock_failover:
            watchdog._handle_unhealthy(server)
            mock_failover.assert_called_once()


class TestCUASkills(unittest.TestCase):
    """Test the CUA-Skills primitives."""

    def test_cua_skills_import(self):
        """Test CUA-Skills can be imported."""
        from ufo.automator.ui_control.cua_skills import CUASkills
        self.assertTrue(callable(CUASkills))

    @patch("pyautogui.press")
    def test_dismiss_dialog(self, mock_press):
        """Test dismiss dialog tries Escape first."""
        from ufo.automator.ui_control.cua_skills import CUASkills
        skills = CUASkills(action_delay=0.01)
        result = skills.dismiss_dialog()
        mock_press.assert_called_with('escape')
        self.assertIn("Escape", result)


class TestDynamicRecoveryNodeInjection(unittest.TestCase):
    """Test DAG recovery node injection."""

    def test_recovery_node_creation(self):
        """Test that a recovery TaskStar can be created."""
        from ufo.galaxy.constellation.task_star import TaskStar, TaskPriority
        
        failed = TaskStar(
            task_id="failed_001",
            name="Open Notepad",
            description="Open Notepad and type Hello",
            target_device_id="local",
            retry_count=0,
        )
        
        recovery = TaskStar(
            task_id="recovery_failed_0_abc123",
            name=f"Recovery: {failed.name}",
            description=f"RECOVERY NODE: Previous task failed. Original: {failed.description}",
            target_device_id=failed.target_device_id,
            priority=failed.priority,
            retry_count=1,
        )
        
        self.assertIn("RECOVERY NODE", recovery.description)
        self.assertEqual(recovery.target_device_id, "local")
        self.assertEqual(recovery._retry_count, 1)


class TestTaskStarRetry(unittest.TestCase):
    """Test the existing TaskStar retry mechanism."""

    def test_should_retry_true(self):
        """Test should_retry returns True when retries remain."""
        from ufo.galaxy.constellation.task_star import TaskStar
        from ufo.galaxy.constellation.enums import TaskStatus
        
        task = TaskStar(task_id="t1", retry_count=3)
        task._status = TaskStatus.FAILED
        task._current_retry = 0
        
        self.assertTrue(task.should_retry())

    def test_should_retry_false_exhausted(self):
        """Test should_retry returns False when retries exhausted."""
        from ufo.galaxy.constellation.task_star import TaskStar
        from ufo.galaxy.constellation.enums import TaskStatus
        
        task = TaskStar(task_id="t1", retry_count=3)
        task._status = TaskStatus.FAILED
        task._current_retry = 3
        
        self.assertFalse(task.should_retry())

    def test_retry_resets_state(self):
        """Test that retry() resets task state properly."""
        from ufo.galaxy.constellation.task_star import TaskStar
        from ufo.galaxy.constellation.enums import TaskStatus
        
        task = TaskStar(task_id="t1", retry_count=3)
        task._status = TaskStatus.FAILED
        task._current_retry = 0
        task._error = Exception("test")
        task._execution_start_time = datetime.now(timezone.utc)
        
        task.retry()
        
        self.assertEqual(task._status, TaskStatus.PENDING)
        self.assertIsNone(task._error)
        self.assertIsNone(task._execution_start_time)
        self.assertEqual(task._current_retry, 1)


if __name__ == "__main__":
    unittest.main()
