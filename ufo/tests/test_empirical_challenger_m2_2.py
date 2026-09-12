# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Adversarial Empirical Verification Suite — Challenger 2 (Milestone 2)

Empirical stress tests for:
1. websockets 14+ transport adapter (aip/transport/adapters.py and websocket.py)
2. session manager cancellation handling & exception preservation (server/services/session_manager.py)
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from aip.transport.adapters import (
    WebSocketsLibAdapter,
    FastAPIWebSocketAdapter,
    create_adapter,
    State,
)
from aip.transport.websocket import WebSocketTransport
from aip.messages import ServerMessageType, TaskStatus
from ufo.server.services.session_manager import SessionManager, SessionOwnershipError
from ufo.module.basic import BaseSession


class MockWebsocket14Connection:
    """Mock representing a websockets >=14 ClientConnection object."""

    def __init__(self, is_open=True):
        self.state = State.OPEN if is_open and State is not None else (State.CLOSED if State is not None else "CLOSED")
        self.sent_messages = []
        self.recv_queue = asyncio.Queue()

    async def send(self, data):
        self.sent_messages.append(data)

    async def recv(self):
        return await self.recv_queue.get()

    async def close(self):
        if State is not None:
            self.state = State.CLOSED
        else:
            self.state = "CLOSED"


class MockFastAPIWebsocket:
    """Mock representing a FastAPI / Starlette WebSocket."""

    def __init__(self, connected=True):
        from starlette.websockets import WebSocketState
        self.client_state = WebSocketState.CONNECTED if connected else WebSocketState.DISCONNECTED
        self.sent_messages = []
        self.recv_queue = asyncio.Queue()

    async def send_text(self, data: str):
        self.sent_messages.append(("text", data))

    async def send_bytes(self, data: bytes):
        self.sent_messages.append(("bytes", data))

    async def receive_text(self) -> str:
        res = await self.recv_queue.get()
        if isinstance(res, str):
            return res
        raise ValueError("Not text")

    async def receive_bytes(self) -> bytes:
        res = await self.recv_queue.get()
        if isinstance(res, bytes):
            return res
        raise ValueError("Expected binary WebSocket frame, but received text frame.")

    async def receive(self) -> dict:
        res = await self.recv_queue.get()
        if isinstance(res, bytes):
            return {"bytes": res}
        return {"text": res}

    async def close(self):
        from starlette.websockets import WebSocketState
        self.client_state = WebSocketState.DISCONNECTED


# ============================================================================
# 1. Websockets 14+ Transport Adapter Empirical Stress Tests
# ============================================================================

def test_websockets_14_lib_adapter_is_open_and_states():
    """Empirically test WebSocketsLibAdapter state checking for websockets 14+ and legacy objects."""
    # websockets 14+ ClientConnection with State enum
    ws_open = MockWebsocket14Connection(is_open=True)
    adapter_open = WebSocketsLibAdapter(ws_open)
    assert adapter_open.is_open() is True

    ws_closed = MockWebsocket14Connection(is_open=False)
    adapter_closed = WebSocketsLibAdapter(ws_closed)
    assert adapter_closed.is_open() is False

    # Mock legacy object with .closed property
    class LegacyClosedObj:
        closed = True
    assert WebSocketsLibAdapter(LegacyClosedObj()).is_open() is False

    class LegacyOpenObj:
        closed = False
    assert WebSocketsLibAdapter(LegacyOpenObj()).is_open() is True

    # Mock legacy object with .open property
    class LegacyOpenPropObj:
        open = True
    assert WebSocketsLibAdapter(LegacyOpenPropObj()).is_open() is True


def test_websockets_adapter_factory_and_fastapi():
    """Empirically verify create_adapter factory and FastAPIWebSocketAdapter."""
    fastapi_ws = MockFastAPIWebsocket(connected=True)
    adapter = create_adapter(fastapi_ws)
    assert isinstance(adapter, FastAPIWebSocketAdapter)
    assert adapter.is_open() is True

    fastapi_ws_disc = MockFastAPIWebsocket(connected=False)
    adapter_disc = create_adapter(fastapi_ws_disc)
    assert adapter_disc.is_open() is False

    lib_ws = MockWebsocket14Connection(is_open=True)
    adapter_lib = create_adapter(lib_ws)
    assert isinstance(adapter_lib, WebSocketsLibAdapter)


@pytest.mark.asyncio
async def test_websockets_binary_and_text_frame_behavior():
    """Verify text and binary frame routing and frame-mismatch detection."""
    ws = MockWebsocket14Connection(is_open=True)
    adapter = WebSocketsLibAdapter(ws)

    # Queue binary payload
    await ws.recv_queue.put(b"\x00\x01\x02\x03")
    received_bytes = await adapter.receive_bytes()
    assert received_bytes == b"\x00\x01\x02\x03"

    # Queue text payload and expect receive_bytes to raise ValueError
    await ws.recv_queue.put("hello text payload")
    with pytest.raises(ValueError, match="Expected binary WebSocket frame"):
        await adapter.receive_bytes()

    # Test auto-receive
    await ws.recv_queue.put("text frame")
    assert await adapter.receive_auto() == "text frame"

    await ws.recv_queue.put(b"binary frame")
    assert await adapter.receive_auto() == b"binary frame"


# ============================================================================
# 2. Session Manager Cancellation & Exception Handling Stress Tests
# ============================================================================

class DummySession(BaseSession):
    """Dummy session for SessionManager testing."""
    def __init__(self, session_id="test_session", task_name="test_task"):
        super().__init__(task=task_name, should_evaluate=False, id=session_id)
        self._finished = False
        self._error = False
        self._run_delay = 0.05
        self.should_raise = None
        self.results = {}

    def _init_agents(self):
        pass

    def create_new_round(self):
        pass

    def next_request(self):
        pass

    def request_to_evaluate(self):
        return ""

    def reset(self):
        pass

    async def run(self):
        if self.should_raise:
            raise self.should_raise
        await asyncio.sleep(self._run_delay)
        self._finished = True

    def is_finished(self) -> bool:
        return self._finished

    def is_error(self) -> bool:
        return self._error


@pytest.mark.asyncio
async def test_session_manager_successful_task_completion():
    """Verify background task completes and invokes callback without swallowing exceptions."""
    sm = SessionManager(platform_override="windows")
    session_id = "test_success_session"

    session = DummySession(session_id=session_id)
    sm.sessions[session_id] = session
    sm._session_owners[session_id] = "client_1"

    callback_called = asyncio.Event()
    callback_message = None

    async def sample_callback(s_id: str, msg):
        nonlocal callback_message
        callback_message = msg
        callback_called.set()

    await sm.execute_task_async(
        session_id=session_id,
        task_name="test_task",
        request="test request",
        callback=sample_callback,
        owner_client_id="client_1",
    )

    await asyncio.wait_for(callback_called.wait(), timeout=2.0)

    assert callback_message is not None
    assert callback_message.type == ServerMessageType.TASK_END
    assert callback_message.status == TaskStatus.COMPLETED
    assert session_id not in sm._running_tasks
    assert session_id not in sm.sessions


@pytest.mark.asyncio
async def test_session_manager_task_exception_preservation():
    """Verify exceptions inside session.run() are caught, logged, and reported via callback without return-in-finally truncation."""
    sm = SessionManager(platform_override="windows")
    session_id = "test_error_session"

    session = DummySession(session_id=session_id)
    session.should_raise = RuntimeError("LLM worker connection timeout")
    sm.sessions[session_id] = session
    sm._session_owners[session_id] = "client_1"

    callback_called = asyncio.Event()
    callback_message = None

    async def sample_callback(s_id: str, msg):
        nonlocal callback_message
        callback_message = msg
        callback_called.set()

    await sm.execute_task_async(
        session_id=session_id,
        task_name="test_task",
        request="test request",
        callback=sample_callback,
        owner_client_id="client_1",
    )

    await asyncio.wait_for(callback_called.wait(), timeout=2.0)

    assert callback_message is not None
    assert callback_message.type == ServerMessageType.TASK_END
    assert callback_message.status == TaskStatus.FAILED
    assert "LLM worker connection timeout" in callback_message.error
    # Ensure cleanup still happened
    assert session_id not in sm._running_tasks
    assert session_id not in sm.sessions


@pytest.mark.asyncio
async def test_session_manager_task_cancellation_constellation_disconnected():
    """Verify task cancellation due to constellation disconnection skips callback and cleans up state."""
    sm = SessionManager(platform_override="windows")
    session_id = "test_cancel_constellation"

    session = DummySession(session_id=session_id)
    session._run_delay = 5.0  # Long running task
    sm.sessions[session_id] = session
    sm._session_owners[session_id] = "client_1"

    callback_called = False

    async def sample_callback(s_id: str, msg):
        nonlocal callback_called
        callback_called = True

    await sm.execute_task_async(
        session_id=session_id,
        task_name="long_task",
        request="long request",
        callback=sample_callback,
        owner_client_id="client_1",
    )

    # Allow task to start running
    await asyncio.sleep(0.02)

    # Cancel task with constellation_disconnected reason
    cancelled = await sm.cancel_task(session_id, reason="constellation_disconnected")
    assert cancelled is True

    # Ensure callback was NOT called because client disconnected
    assert callback_called is False

    # Verify session and running task cleanups
    assert session_id not in sm._running_tasks
    assert session_id not in sm.sessions
    assert session_id not in sm._cancellation_reasons


@pytest.mark.asyncio
async def test_session_manager_task_cancellation_device_disconnected():
    """Verify task cancellation due to device disconnection calls callback with FAILED status and clear error."""
    sm = SessionManager(platform_override="windows")
    session_id = "test_cancel_device"

    session = DummySession(session_id=session_id)
    session._run_delay = 5.0
    sm.sessions[session_id] = session
    sm._session_owners[session_id] = "client_1"

    callback_called = asyncio.Event()
    callback_message = None

    async def sample_callback(s_id: str, msg):
        nonlocal callback_message
        callback_message = msg
        callback_called.set()

    await sm.execute_task_async(
        session_id=session_id,
        task_name="long_task",
        request="long request",
        callback=sample_callback,
        owner_client_id="client_1",
    )

    await asyncio.sleep(0.02)

    cancelled = await sm.cancel_task(session_id, reason="device_disconnected")
    assert cancelled is True

    await asyncio.wait_for(callback_called.wait(), timeout=2.0)

    assert callback_message is not None
    assert callback_message.status == TaskStatus.FAILED
    assert "target device disconnected" in callback_message.error

    assert session_id not in sm._running_tasks
    assert session_id not in sm.sessions


@pytest.mark.asyncio
async def test_session_manager_callback_exception_resilience():
    """Verify exception raised inside callback does not break session cleanup."""
    sm = SessionManager(platform_override="windows")
    session_id = "test_failing_callback_session"

    session = DummySession(session_id=session_id)
    sm.sessions[session_id] = session
    sm._session_owners[session_id] = "client_1"

    async def failing_callback(s_id: str, msg):
        raise ValueError("Callback socket write failed")

    await sm.execute_task_async(
        session_id=session_id,
        task_name="test_task",
        request="test request",
        callback=failing_callback,
        owner_client_id="client_1",
    )

    # Wait for background task to complete
    await asyncio.sleep(0.15)

    # Cleanup must still occur even if callback raised an exception
    assert session_id not in sm._running_tasks
    assert session_id not in sm.sessions


@pytest.mark.asyncio
async def test_session_manager_double_cancellation_and_missing_task():
    """Verify double cancellation and cancelling non-existent task returns False cleanly."""
    sm = SessionManager(platform_override="windows")

    # Cancelling non-existent task
    assert await sm.cancel_task("non_existent_session") is False

    session_id = "double_cancel_session"
    session = DummySession(session_id=session_id)
    session._run_delay = 5.0
    sm.sessions[session_id] = session
    sm._session_owners[session_id] = "client_1"

    await sm.execute_task_async(
        session_id=session_id,
        task_name="test_task",
        request="test request",
        owner_client_id="client_1",
    )
    await asyncio.sleep(0.02)

    res1 = await sm.cancel_task(session_id)
    res2 = await sm.cancel_task(session_id)

    assert res1 is True
    assert res2 is False


@pytest.mark.asyncio
async def test_session_manager_cross_client_ownership_security():
    """Verify cross-client session reuse attempts raise SessionOwnershipError."""
    sm = SessionManager(platform_override="windows")
    session_id = "security_session"

    session = DummySession(session_id=session_id)
    sm.sessions[session_id] = session
    sm._session_owners[session_id] = "owner_alice"

    with pytest.raises(SessionOwnershipError, match="owned by another client"):
        sm.get_or_create_session(
            session_id=session_id,
            owner_client_id="attacker_bob",
        )
