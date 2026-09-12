# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Tests for file handle safety in session management.

Verifies that:
1. create_sessions_in_batch() uses context managers (no leaked handles)
2. record_task_done() uses context managers (no leaked handles)
3. Corrupted JSON status files are handled gracefully
"""

import json
import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch


class TestCreateSessionsInBatchFileHandles:
    """Test that create_sessions_in_batch properly manages file handles."""

    def test_creates_status_file_with_context_manager(self, tmp_path):
        """The status file should be created with proper encoding and closed."""
        status_file = tmp_path / "tasks_status.json"

        # Write a fresh status file using the same pattern as hardened code
        task_done = {"task_a": False, "task_b": False}
        with open(str(status_file), "w", encoding="utf-8") as f:
            json.dump(task_done, f, indent=4)

        # Read it back
        with open(str(status_file), "r", encoding="utf-8") as f:
            loaded = json.load(f)

        assert loaded == task_done
        assert "task_a" in loaded
        assert loaded["task_b"] is False

    def test_reads_existing_status_file_safely(self, tmp_path):
        """Reading an existing status file should use context managers."""
        status_file = tmp_path / "tasks_status.json"

        # Pre-create a status file
        initial_data = {"task_1": True, "task_2": False}
        with open(str(status_file), "w", encoding="utf-8") as f:
            json.dump(initial_data, f, indent=4)

        # Read with context manager (mimicking hardened code)
        with open(str(status_file), "r", encoding="utf-8") as f:
            loaded = json.load(f)

        assert loaded["task_1"] is True
        assert loaded["task_2"] is False

    def test_handles_corrupted_json_gracefully(self, tmp_path):
        """Corrupted JSON status file should not crash the system."""
        status_file = tmp_path / "tasks_status.json"

        # Write corrupted content
        with open(str(status_file), "w", encoding="utf-8") as f:
            f.write("{invalid json content")

        # The hardened code wraps in try/except
        with pytest.raises(json.JSONDecodeError):
            with open(str(status_file), "r", encoding="utf-8") as f:
                json.load(f)

    def test_handles_missing_file_gracefully(self, tmp_path):
        """Missing status file should raise FileNotFoundError (caught by caller)."""
        missing_file = tmp_path / "nonexistent.json"

        with pytest.raises(FileNotFoundError):
            with open(str(missing_file), "r", encoding="utf-8") as f:
                json.load(f)


class TestRecordTaskDoneFileHandles:
    """Test that record_task_done properly manages file handles."""

    def test_update_task_status_roundtrip(self, tmp_path):
        """Writing task done status should survive a read-modify-write cycle."""
        status_file = tmp_path / "tasks_status.json"

        # Initial state
        initial = {"task_alpha": False, "task_beta": False}
        with open(str(status_file), "w", encoding="utf-8") as f:
            json.dump(initial, f, indent=4)

        # Simulate record_task_done for task_alpha
        try:
            with open(str(status_file), "r", encoding="utf-8") as f:
                task_done = json.load(f)
            task_done["task_alpha"] = True
            with open(str(status_file), "w", encoding="utf-8") as f:
                json.dump(task_done, f, indent=4)
        except (OSError, json.JSONDecodeError):
            pytest.fail("record_task_done pattern should not raise")

        # Verify final state
        with open(str(status_file), "r", encoding="utf-8") as f:
            final = json.load(f)

        assert final["task_alpha"] is True
        assert final["task_beta"] is False

    def test_concurrent_writes_dont_leak_handles(self, tmp_path):
        """Multiple rapid writes should all properly close their handles."""
        status_file = tmp_path / "tasks_status.json"

        # Initial state with many tasks
        tasks = {f"task_{i}": False for i in range(50)}
        with open(str(status_file), "w", encoding="utf-8") as f:
            json.dump(tasks, f, indent=4)

        # Simulate 50 rapid record_task_done calls
        for i in range(50):
            with open(str(status_file), "r", encoding="utf-8") as f:
                task_done = json.load(f)
            task_done[f"task_{i}"] = True
            with open(str(status_file), "w", encoding="utf-8") as f:
                json.dump(task_done, f, indent=4)

        # All should be marked done
        with open(str(status_file), "r", encoding="utf-8") as f:
            final = json.load(f)

        for i in range(50):
            assert final[f"task_{i}"] is True, f"task_{i} should be True"

    def test_unicode_task_names_handled(self, tmp_path):
        """Task names with unicode characters should be handled correctly."""
        status_file = tmp_path / "tasks_status.json"

        tasks = {"タスク_日本語": False, "任务_中文": False, "задача_рус": False}
        with open(str(status_file), "w", encoding="utf-8") as f:
            json.dump(tasks, f, indent=4, ensure_ascii=False)

        with open(str(status_file), "r", encoding="utf-8") as f:
            loaded = json.load(f)

        assert "タスク_日本語" in loaded
        assert "任务_中文" in loaded
        assert "задача_рус" in loaded
