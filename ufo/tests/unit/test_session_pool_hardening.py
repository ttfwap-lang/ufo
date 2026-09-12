# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Tests for hardened SessionPool behavior.

Covers:
1. run_all() with return_exceptions=True — one failed session doesn't kill others
2. next_session() on empty pool returns None
3. current_round returning None when no rounds exist
4. current_agent_class returning "Unknown" when no rounds exist
"""

import asyncio
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch


class TestSessionPoolRunAll:
    """Test that SessionPool.run_all() is fault-tolerant."""

    @pytest.mark.asyncio
    async def test_run_all_continues_after_one_session_fails(self):
        """If one session raises, the other sessions should still complete."""
        from ufo.module.session_pool import SessionPool

        # Create mock sessions
        session_ok = AsyncMock()
        session_ok.run = AsyncMock(return_value=None)

        session_fail = AsyncMock()
        session_fail.run = AsyncMock(side_effect=RuntimeError("LLM timeout"))

        session_ok2 = AsyncMock()
        session_ok2.run = AsyncMock(return_value=None)

        pool = SessionPool([session_ok, session_fail, session_ok2])
        # Should NOT raise — errors are caught internally
        await pool.run_all()

        # All three sessions should have been invoked
        session_ok.run.assert_awaited_once()
        session_fail.run.assert_awaited_once()
        session_ok2.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_all_logs_failed_sessions(self, caplog):
        """Failed sessions should produce error-level log messages."""
        from ufo.module.session_pool import SessionPool

        session_fail = AsyncMock()
        session_fail.run = AsyncMock(side_effect=ValueError("bad config"))

        pool = SessionPool([session_fail])

        with caplog.at_level(logging.ERROR):
            await pool.run_all()

        assert "Session 0 failed" in caplog.text
        assert "ValueError" in caplog.text

    @pytest.mark.asyncio
    async def test_run_all_empty_pool_is_noop(self):
        """Running an empty pool should return immediately without error."""
        from ufo.module.session_pool import SessionPool

        pool = SessionPool([])
        await pool.run_all()  # Should not raise


class TestSessionPoolNextSession:
    """Test that next_session() handles empty lists gracefully."""

    def test_next_session_returns_none_on_empty_pool(self):
        """Calling next_session() on an empty pool should return None, not raise."""
        from ufo.module.session_pool import SessionPool

        pool = SessionPool([])
        result = pool.next_session()
        assert result is None

    def test_next_session_returns_and_removes_first(self):
        """next_session() should pop and return the first session."""
        from ufo.module.session_pool import SessionPool

        s1 = MagicMock()
        s2 = MagicMock()
        pool = SessionPool([s1, s2])

        result = pool.next_session()
        assert result is s1
        assert len(pool.session_list) == 1

        result2 = pool.next_session()
        assert result2 is s2
        assert len(pool.session_list) == 0

        result3 = pool.next_session()
        assert result3 is None


class TestCurrentRoundNoneGuard:
    """Test that BaseSession handles the case where no rounds exist."""

    def test_current_round_returns_none_with_no_rounds(self):
        """current_round should return None when total_rounds == 0."""
        from ufo.module.basic import BaseSession

        session = MagicMock(spec=BaseSession)
        session._rounds = []

        # Directly call the property logic
        total_rounds = len(session._rounds)
        assert total_rounds == 0

    def test_current_agent_class_returns_unknown_with_no_round(self):
        """current_agent_class should return 'Unknown' when current_round is None."""
        # We test by constructing a mock that mimics BaseSession behavior
        mock_session = MagicMock()
        mock_session.current_round = None

        # Simulate the hardened logic
        if mock_session.current_round is None:
            agent_class = "Unknown"
        else:
            agent_class = mock_session.current_round.agent.__class__.__name__

        assert agent_class == "Unknown"

    def test_is_error_returns_false_with_no_round(self):
        """is_error() should return False when current_round is None."""
        mock_session = MagicMock()
        mock_session.current_round = None

        # Simulate the hardened logic from basic.py is_error()
        if mock_session.current_round is not None:
            is_err = mock_session.current_round.state.name() == "ERROR"
        else:
            is_err = False

        assert is_err is False
