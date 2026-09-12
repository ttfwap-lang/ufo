# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit tests for Dead Letter Queue diagnostic recorder.
"""

import os
import shutil
import tempfile
from ufo.dlq.dead_letter_queue import DeadLetterQueue


def test_dlq_records_event():
    """Verify DLQ records snapshot to disk with correct schema."""
    temp_dir = tempfile.mkdtemp()
    try:
        dlq = DeadLetterQueue(snapshot_dir=temp_dir, max_snapshots=10, enabled=True)

        snapshot_path = dlq.record_failure(
            agent_type="HOST_AGENT",
            messages=[{"role": "user", "content": "Test prompt"}],
            error=RuntimeError("Test failure"),
            model="gpt-5.6-terra",
            circuit_breaker_state="OPEN",
        )

        assert snapshot_path is not None
        assert os.path.exists(snapshot_path)

        snapshots = dlq.list_snapshots()
        assert len(snapshots) == 1
        assert snapshots[0]["agent_type"] == "HOST_AGENT"
        assert snapshots[0]["model"] == "gpt-5.6-terra"
        assert snapshots[0]["circuit_breaker_state"] == "OPEN"
        assert "Test failure" in snapshots[0]["error"]
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_dlq_pruning_max_snapshots():
    """Verify DLQ auto-prunes oldest snapshots when max_snapshots limit is reached."""
    temp_dir = tempfile.mkdtemp()
    try:
        dlq = DeadLetterQueue(snapshot_dir=temp_dir, max_snapshots=3, enabled=True)

        for i in range(5):
            dlq.record_failure(
                agent_type="HOST_AGENT",
                messages=[{"role": "user", "content": f"Prompt {i}"}],
                error=RuntimeError(f"Error {i}"),
                model="gpt-5.6-terra",
                circuit_breaker_state="OPEN",
            )

        snapshots = dlq.list_snapshots()
        assert len(snapshots) <= 3
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_dlq_no_init_directory_creation():
    """Verify DeadLetterQueue does not create directories at __init__ time."""
    temp_parent = tempfile.mkdtemp()
    target_subdir = os.path.join(temp_parent, "dlq_lazy_test_dir")
    try:
        assert not os.path.exists(target_subdir)
        dlq = DeadLetterQueue(snapshot_dir=target_subdir, enabled=True)
        # Directory must NOT exist yet after __init__
        assert not os.path.exists(target_subdir)

        # Directory is created on demand during record_failure
        snapshot_path = dlq.record_failure(
            agent_type="TEST_AGENT",
            messages=[{"role": "user", "content": "hi"}],
            error=RuntimeError("err"),
        )
        assert os.path.exists(target_subdir)
        assert snapshot_path is not None and os.path.exists(snapshot_path)
    finally:
        shutil.rmtree(temp_parent, ignore_errors=True)


def test_get_default_dlq_lazy():
    """Verify get_default_dlq returns configured singleton."""
    from ufo.dlq.dead_letter_queue import get_default_dlq
    default_dlq = get_default_dlq()
    assert default_dlq is not None
    assert default_dlq._max_snapshots >= 1
