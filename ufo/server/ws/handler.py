import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect
from ufo.aip.protocol.registration import RegistrationProtocol
from ufo.aip.protocol.heartbeat import HeartbeatProtocol
from ufo.aip.protocol.device_info import DeviceInfoProtocol
from ufo.aip.protocol.task_execution import TaskExecutionProtocol
from ufo.aip.transport.websocket import WebSocketTransport
from ufo.aip.messages import ClientMessage, ClientMessageType, ClientType, ServerMessage
from ufo.module.dispatcher import WebSocketCommandDispatcher
from ufo.server.services.session_manager import SessionManager, SessionOwnershipError
from ufo.server.services.client_connection_manager import ClientConnectionManager, DuplicateClientError
from ufo.utils import sanitize_task_name

@dataclass
class ConnectionContext:
    """Per-WebSocket-connection state for the UFO server.

    The :class:`UFOWebSocketHandler` instance is shared across every
    accepted WebSocket connection, so any per-connection state stored on
    the handler itself would be silently overwritten when another client
    connects — and responses computed in reply to one client's request
    could be delivered on a different client's transport. To prevent
    that cross-client response confusion, each accepted connection
    receives its own ``ConnectionContext`` that owns the transport and
    the AIP protocol helpers bound to *that* socket. The context is
    threaded explicitly through :meth:`UFOWebSocketHandler.handle_message`
    and the ``handle_*`` dispatch methods so responses are always sent
    on the originating connection's transport.
    """
    transport: Optional[WebSocketTransport] = None
    registration_protocol: Optional[RegistrationProtocol] = None
    heartbeat_protocol: Optional[HeartbeatProtocol] = None
    device_info_protocol: Optional[DeviceInfoProtocol] = None
    task_protocol: Optional[TaskExecutionProtocol] = None
    registered_client_id: Optional[str] = None
    registered_client_type: Optional[ClientType] = None
    registered_target_id: Optional[str] = None

class UFOWebSocketHandler:
    """
    Handles WebSocket connections for the UFO server.
    Uses AIP (Agent Interaction Protocol) for structured message handling.

    A single ``UFOWebSocketHandler`` instance is shared by the FastAPI
    application across every ``/ws`` connection. Per-connection state
    (transport + AIP protocol helpers + registered identity) therefore
    MUST NOT live on the handler instance. Each call to :meth:`handler`
    builds its own :class:`ConnectionContext` and threads it through the
    message-dispatch chain so that responses are always sent on the
    originating connection's transport.
    """

    def __init__(self, client_manager: ClientConnectionManager, session_manager: SessionManager, local: bool=False):
        """
        Initializes the WebSocket handler.
        :param client_manager: The client connection manager.
        :param session_manager: The session manager.
        :param local: Whether running in local mode with client auto-connect.
        """
        self.client_manager = client_manager
        self.session_manager = session_manager
        self.local = local
        self.logger = logging.getLogger(self.__class__.__name__)

    async def connect(self, websocket: WebSocket) -> ConnectionContext:
        """
        Connects a client and registers it in the client manager.
        Uses AIP RegistrationProtocol for structured registration.
        Expects the first message to contain {"client_id": ...}.

        :param websocket: The WebSocket connection.
        :return: The :class:`ConnectionContext` bound to this connection.
            The context owns the transport and AIP protocol helpers and
            carries the registered identity (``registered_client_id`` /
            ``registered_client_type``). Callers must thread this context
            through :meth:`handle_message` so responses are routed back
            to the originating connection.
        """
        await websocket.accept()
        ctx = ConnectionContext(transport=WebSocketTransport(websocket))
        ctx.registration_protocol = RegistrationProtocol(ctx.transport)
        ctx.heartbeat_protocol = HeartbeatProtocol(ctx.transport)
        ctx.device_info_protocol = DeviceInfoProtocol(ctx.transport)
        ctx.task_protocol = TaskExecutionProtocol(ctx.transport)
        reg_info = await self._parse_registration_message(ctx)
        client_type = reg_info.client_type
        platform = reg_info.metadata.get('platform', 'windows') if reg_info.metadata else 'windows'
        client_id = reg_info.client_id
        if client_type == ClientType.CONSTELLATION:
            await self._validate_constellation_client(reg_info, ctx)
        try:
            self.client_manager.add_client(client_id, platform, websocket, client_type, reg_info.metadata, transport=ctx.transport, task_protocol=ctx.task_protocol)
        except DuplicateClientError as dup_err:
            self.logger.warning(f'[WS] 🚨 duplicate client_id rejected: {dup_err}')
            await self._send_error_response(str(dup_err), ctx)
            try:
                await ctx.transport.close()
            except Exception as close_err:
                self.logger.warning(f'[WS] Transport close error on duplicate client rejection: {close_err}')
            raise ValueError(str(dup_err)) from dup_err
        await self._send_registration_confirmation(ctx)
        self._log_client_connection(client_id, client_type)
        ctx.registered_client_id = client_id
        ctx.registered_client_type = client_type
        if client_type == ClientType.CONSTELLATION:
            ctx.registered_target_id = reg_info.target_id
        return ctx

    async def _parse_registration_message(self, ctx: ConnectionContext) -> ClientMessage:
        """
        Parse and validate the registration message from client using AIP Transport.
        :param ctx: The per-connection context whose transport is used to
            receive the registration message.
        :return: Parsed registration message.
        :raises: ValueError if message is invalid.
        """
        self.logger.info('[WS] [AIP] Waiting for registration message...')
        reg_data = await ctx.transport.receive()
        if isinstance(reg_data, bytes):
            reg_data = reg_data.decode('utf-8')
        reg_info = ClientMessage.model_validate_json(reg_data)
        self.logger.info(f'[WS] [AIP] Received registration from {reg_info.client_id}, type={reg_info.client_type}')
        if not reg_info.client_id:
            raise ValueError('Client ID is required for WebSocket registration')
        if reg_info.type != ClientMessageType.REGISTER:
            raise ValueError('First message must be a registration message')
        return reg_info

    async def _validate_constellation_client(self, reg_info: ClientMessage, ctx: ConnectionContext) -> None:
        """
        Validate constellation client's claimed device_id.
        Uses AIP to send error response and close transport if validation fails.

        :param reg_info: Registration message information.
        :param ctx: The per-connection context bound to this socket.
        :raises: ValueError if validation fails.
        """
        claimed_device_id = reg_info.target_id
        if not claimed_device_id:
            return
        if not self.client_manager.is_device_connected(claimed_device_id):
            error_msg = f"Target device '{claimed_device_id}' is not connected"
            self.logger.warning(f'[WS] Constellation registration failed: {error_msg}')
            await self._send_error_response(error_msg, ctx)
            await ctx.transport.close()
            raise ValueError(error_msg)

    async def _send_registration_confirmation(self, ctx: ConnectionContext) -> None:
        """
        Send successful registration confirmation to client using AIP RegistrationProtocol.
        :param ctx: The per-connection context whose registration
            protocol is used to send the confirmation.
        """
        self.logger.info('[WS] [AIP] Sending registration confirmation...')
        await ctx.registration_protocol.send_registration_confirmation()
        self.logger.info('[WS] [AIP] Registration confirmation sent')

    async def _send_error_response(self, error_msg: str, ctx: ConnectionContext) -> None:
        """
        Send error response to client using AIP RegistrationProtocol.
        :param error_msg: Error message to send.
        :param ctx: The per-connection context whose registration
            protocol is used to send the error.
        """
        await ctx.registration_protocol.send_registration_error(error_msg)

    def _log_client_connection(self, client_id: str, client_type: ClientType) -> None:
        """
        Log successful client connection with appropriate emoji.
        :param client_id: The client ID.
        :param client_type: The client type.
        """
        if client_type == ClientType.CONSTELLATION:
            self.logger.info(f'[WS] 🌟 Constellation client {client_id} connected')
        else:
            system_info = self.client_manager.get_device_system_info(client_id)
            if system_info:
                self.logger.info(f"[WS] 📱 Device client {client_id} connected - Platform: {system_info.get('platform', 'unknown')}, CPU: {system_info.get('cpu_count', 'N/A')}, Memory: {system_info.get('memory_total_gb', 'N/A')}GB")
            else:
                self.logger.info(f'[WS] 📱 Device client {client_id} connected')

    async def disconnect(self, client_id: str) -> None:
        """
        Disconnects a client and removes it from the WS manager.
        :param client_id: The ID of the client.
        """
        client_info = self.client_manager.get_client_info(client_id)
        if client_info and client_info.client_type == ClientType.CONSTELLATION:
            session_ids = self.client_manager.get_constellation_sessions(client_id)
            if session_ids:
                self.logger.info(f'[WS] 🌟 Constellation {client_id} disconnected, cancelling {len(session_ids)} active session(s)')
            for session_id in session_ids:
                try:
                    await self.session_manager.cancel_task(session_id, reason='constellation_disconnected')
                except Exception as e:
                    self.logger.error(f'[WS] Error cancelling session {session_id}: {e}')
                self.client_manager.remove_constellation_sessions(client_id)
        elif client_info and client_info.client_type == ClientType.DEVICE:
            session_ids = self.client_manager.get_device_sessions(client_id)
            if session_ids:
                self.logger.info(f'[WS] 📱 Device {client_id} disconnected, cancelling {len(session_ids)} active session(s)')
            for session_id in session_ids:
                try:
                    await self.session_manager.cancel_task(session_id, reason='device_disconnected')
                except Exception as e:
                    self.logger.error(f'[WS] Error cancelling session {session_id}: {e}')
                self.client_manager.remove_device_sessions(client_id)
        self.client_manager.remove_client(client_id)
        self.logger.info(f'[WS] {client_id} disconnected')

    async def handler(self, websocket: WebSocket) -> None:
        """
        FastAPI WebSocket entry point.

        A fresh :class:`ConnectionContext` is built per accepted
        connection and threaded into every dispatched message. The
        context is captured as a local variable so concurrent handlers
        for different sockets cannot share or overwrite each other's
        transport and protocol helpers.

        :param websocket: The WebSocket connection.
        """
        client_id = None
        ctx: Optional[ConnectionContext] = None
        try:
            ctx = await self.connect(websocket)
            client_id = ctx.registered_client_id
            while True:
                msg = await websocket.receive_text()
                asyncio.create_task(self.handle_message(msg, ctx))
        except WebSocketDisconnect as e:
            self.logger.warning(f'[WS] {client_id} disconnected - code={e.code}, reason={e.reason}')
            if client_id:
                await self.disconnect(client_id)
        except Exception as e:
            self.logger.error(f'[WS] Error with client {client_id}: {e}')
            if client_id:
                await self.disconnect(client_id)

    async def handle_message(self, msg: str, ctx: Optional[ConnectionContext]=None, *, registered_client_id: Optional[str]=None, registered_client_type: Optional[ClientType]=None) -> None:
        """
        Dispatch incoming WS messages to specific handlers.

        Security: the per-connection identity established at registration
        (``ctx.registered_client_id`` and ``ctx.registered_client_type``)
        is the authoritative source of truth for the connection's role
        and principal. The values carried in ``ClientMessage`` are
        validated against the registered identity to defeat
        role/identity spoofing: a connection that registered as a
        ``DEVICE`` cannot later send messages claiming to be a
        ``CONSTELLATION`` (or impersonate a different ``client_id``).

        Cross-client isolation: responses are sent on
        ``ctx.task_protocol`` / ``ctx.heartbeat_protocol`` /
        ``ctx.device_info_protocol``, all of which are bound to the
        originating connection's transport. This prevents the
        cross-client response confusion that would occur if responses
        were sent on shared handler-level protocol fields that a later
        connection had overwritten.

        :param msg: The raw JSON message received from the client.
        :param ctx: The per-connection context bound to the originating
            websocket. Production callers (:meth:`handler`) always pass
            this; the legacy keyword-only ``registered_*`` parameters
            below remain only so existing unit tests that exercise
            :meth:`handle_message` directly (without going through
            :meth:`connect`) keep working.
        :param registered_client_id: Legacy fallback for the registered
            ``client_id`` when ``ctx`` is not supplied.
        :param registered_client_type: Legacy fallback for the registered
            ``client_type`` when ``ctx`` is not supplied.
        """
        import traceback
        ctx = self._effective_ctx(ctx, registered_client_id=registered_client_id, registered_client_type=registered_client_type)
        registered_client_id = ctx.registered_client_id
        registered_client_type = ctx.registered_client_type
        client_id = registered_client_id
        try:
            data = ClientMessage.model_validate_json(msg)
            if registered_client_id is not None:
                if data.client_id and data.client_id != registered_client_id:
                    self.logger.warning(f'[WS] 🚨 client_id spoof rejected: connection registered as {registered_client_id!r} but message claimed client_id={data.client_id!r}')
                    await self._safe_send_error('client_id does not match the registered connection', ctx)
                    return
                if registered_client_type is not None and data.client_type != registered_client_type:
                    self.logger.warning(f'[WS] 🚨 client_type/role spoof rejected: connection registered as {registered_client_type} but message claimed client_type={data.client_type}')
                    await self._safe_send_error('client_type does not match the registered connection', ctx)
                    return
                data.client_id = registered_client_id
                if registered_client_type is not None:
                    data.client_type = registered_client_type
            elif data.type in (ClientMessageType.TASK, ClientMessageType.COMMAND_RESULTS, ClientMessageType.DEVICE_INFO_REQUEST, ClientMessageType.REGISTER):
                self.logger.warning(f'[WS] 🚨 refusing privileged message of type {data.type} on a connection with no bound identity (possible identity spoof attempt)')
                await self._safe_send_error('Connection is not registered; refusing privileged message', ctx)
                return
            client_id = data.client_id
            client_type = data.client_type
            if client_type == ClientType.CONSTELLATION:
                self.logger.debug(f'[WS] 🌟 Handling constellation message from {client_id}, type: {data.type}')
            else:
                self.logger.debug(f'[WS] 📱 Received device message from {client_id}, type: {data.type}')
            msg_type = data.type
            if msg_type == ClientMessageType.TASK:
                await self.handle_task_request(data, ctx)
            elif msg_type == ClientMessageType.COMMAND_RESULTS:
                await self.handle_command_result(data, ctx)
            elif msg_type == ClientMessageType.HEARTBEAT:
                await self.handle_heartbeat(data, ctx)
            elif msg_type == ClientMessageType.ERROR:
                await self.handle_error(data, ctx)
            elif msg_type == ClientMessageType.DEVICE_INFO_REQUEST:
                await self.handle_device_info_request(data, ctx)
            elif msg_type == ClientMessageType.DEVICE_INFO_RESPONSE:
                await self.handle_device_info_response(data)
            else:
                await self.handle_unknown(data, ctx)
        except Exception as e:
            traceback.print_exc()
            self.logger.error(f'[WS] Error handling message from {client_id}: {e}')
            await self._safe_send_error(str(e), ctx)

    def _effective_ctx(self, ctx: Optional[ConnectionContext], *, registered_client_id: Optional[str]=None, registered_client_type: Optional[ClientType]=None) -> ConnectionContext:
        """Return the context to use for an incoming message.

        Production callers always supply ``ctx``; this helper exists for
        the legacy unit-test pattern where :meth:`handle_message` is
        invoked directly on a freshly constructed handler with no
        accompanying ``ConnectionContext``. In that case the tests
        typically pre-assign a stub protocol on ``self`` (e.g.
        ``handler.task_protocol = recorder``); we synthesise a context
        from those attributes so error responses still flow to the test
        recorder. This path is NEVER taken from :meth:`handler`, which
        is the only production caller.
        """
        if ctx is not None:
            if registered_client_id is not None and ctx.registered_client_id is None:
                ctx.registered_client_id = registered_client_id
            if registered_client_type is not None and ctx.registered_client_type is None:
                ctx.registered_client_type = registered_client_type
            return ctx
        return ConnectionContext(transport=getattr(self, 'transport', None), registration_protocol=getattr(self, 'registration_protocol', None), heartbeat_protocol=getattr(self, 'heartbeat_protocol', None), device_info_protocol=getattr(self, 'device_info_protocol', None), task_protocol=getattr(self, 'task_protocol', None), registered_client_id=registered_client_id, registered_client_type=registered_client_type)

    async def _safe_send_error(self, error: str, ctx: ConnectionContext) -> None:
        """
        Best-effort send of an error response to the current connection.

        Used by the message validator and the dispatch error handler.
        Swallows transport-level failures (closed connection) and the
        case where the per-connection task protocol has not been
        established yet (e.g. tests that exercise ``handle_message``
        without going through ``connect``).

        :param error: The error message to send.
        :param ctx: The per-connection context whose ``task_protocol``
            is used to deliver the error to the originating client.
        """
        try:
            if ctx.task_protocol is not None:
                await ctx.task_protocol.send_error(error)
        except (ConnectionError, IOError) as send_error:
            self.logger.debug(f'[WS] Could not send error response (connection closed): {send_error}')
        except Exception as send_error:
            self.logger.debug(f'[WS] Suppressed error while sending error response: {send_error}')

    async def handle_heartbeat(self, data: ClientMessage, ctx: ConnectionContext) -> None:
        """
        Handle heartbeat messages from the client using AIP HeartbeatProtocol.
        :param data: The data from the client.
        :param ctx: The per-connection context whose ``heartbeat_protocol``
            is used to send the acknowledgment back to the originating
            client.
        """
        self.logger.debug(f'[WS] [AIP] Heartbeat from {data.client_id}')
        try:
            if ctx.heartbeat_protocol is not None:
                await ctx.heartbeat_protocol.send_heartbeat_ack()
            self.logger.debug(f'[WS] [AIP] Heartbeat response sent to {data.client_id}')
        except (ConnectionError, IOError) as e:
            self.logger.debug(f'[WS] [AIP] Could not send heartbeat ack (connection closed): {e}')

    async def handle_error(self, data: ClientMessage, ctx: ConnectionContext) -> None:
        """
        Handle error messages from the client.
        :param data: The data from the client.
        :param ctx: The per-connection context whose ``task_protocol``
            is used to acknowledge the error to the originating client.
        """
        self.logger.error(f'[WS] [AIP] Error from {data.client_id}: {data.error}')
        if ctx.task_protocol is not None:
            await ctx.task_protocol.send_error(data.error or 'Unknown error')

    async def handle_unknown(self, data: ClientMessage, ctx: ConnectionContext) -> None:
        """
        Handle unknown message types.
        :param data: The data from the client.
        :param ctx: The per-connection context whose ``task_protocol``
            is used to inform the originating client of the unknown
            message type.
        """
        self.logger.warning(f'[WS] [AIP] Unknown message type: {data.type}')
        if ctx.task_protocol is not None:
            await ctx.task_protocol.send_error(f'Unknown message type: {data.type}')

    async def handle_task_request(self, data: ClientMessage, ctx: ConnectionContext) -> None:
        """
        Handle a task request message from the client.

        This method now delegates session execution to SessionManager,
        which runs tasks in background without blocking the event loop.
        This allows WebSocket ping/pong and heartbeat messages to continue.

        Uses AIP protocols for all communication, no direct WebSocket access needed.

        Security: ``data.client_id`` and ``data.client_type`` are expected
        to have been pinned to the registered connection identity by
        :meth:`handle_message`. As an additional defense-in-depth check,
        a ``DEVICE`` client is not permitted to set ``target_id`` to
        anything other than its own ``client_id``.

        Cross-client isolation: the immediate acknowledgment is sent on
        ``ctx.task_protocol`` — the protocol bound to *this* connection's
        transport — so ACKs cannot leak onto another client's socket.

        :param data: The data from the client.
        :param ctx: The per-connection context bound to the originating
            socket.
        """
        client_type = data.client_type
        client_id = data.client_id
        target_device_id = None
        if client_type == ClientType.CONSTELLATION:
            target_device_id = data.target_id
            if not target_device_id:
                self.logger.warning(f'[WS] 🌟 Constellation {client_id} sent task without target_id')
                await self._safe_send_error('Constellation task requests require target_id', ctx)
                return
            target_info = self.client_manager.get_client_info(target_device_id)
            if target_info is None:
                self.logger.warning(f'[WS] 🌟 Constellation {client_id} targeted unknown device {target_device_id!r}')
                await self._safe_send_error(f'Target device {target_device_id!r} is not connected', ctx)
                return
            if target_info.client_type != ClientType.DEVICE:
                self.logger.warning(f'[WS] 🌟 Constellation {client_id} targeted non-device client {target_device_id!r}')
                await self._safe_send_error('Constellation tasks may only target device clients', ctx)
                return
            self.logger.info(f'[WS] 🌟 Handling constellation task request: {data.request} from {data.target_id}')
            platform = target_info.platform
        else:
            if data.target_id and data.target_id != client_id:
                self.logger.warning(f'[WS] 🚨 device {client_id} attempted to target peer device {data.target_id!r}; rejecting task request')
                await self._safe_send_error('Device clients may not target other devices', ctx)
                return
            device_info = self.client_manager.get_client_info(client_id)
            if device_info is None:
                self.logger.warning(f'[WS] 📱 Task request from unknown device {client_id!r}')
                await self._safe_send_error(f'Device {client_id!r} is not connected', ctx)
                return
            self.logger.info(f'[WS] 📱 Handling device task request: {data.request} from {data.client_id}')
            platform = device_info.platform
        session_id = str(uuid.uuid4()) if not data.session_id else data.session_id
        raw_task_name = data.task_name if data.task_name else str(uuid.uuid4())
        task_name = sanitize_task_name(raw_task_name)
        if raw_task_name != task_name:
            self.logger.warning(f'[WS] Sanitized unsafe task_name {raw_task_name!r} -> {task_name!r}')
        self.logger.info(f'[WS] 🎯 Prepared task: session_id={session_id}, task_name={task_name}, client_type={client_type}, target_device={target_device_id}')
        if client_type == ClientType.CONSTELLATION:
            self.client_manager.add_constellation_session(data.client_id, session_id)
            if target_device_id:
                self.client_manager.add_device_session(target_device_id, session_id)

        async def send_result(sid: str, result_msg: ServerMessage):
            """Send task result to client when session completes using AIP."""
            self.logger.info(f'[WS] 📬 CALLBACK INVOKED! session={sid}, status={result_msg.status}, client_type={client_type}, target_device={target_device_id}')
            requester_protocol = self.client_manager.get_task_protocol(client_id)
            if not requester_protocol:
                self.logger.warning(f'[WS] ⚠️ Client {client_id} disconnected, skipping result callback for session {sid}')
                return
            try:
                self.logger.info(f'[WS] 📤 Sending result to client {client_id} via AIP...')
                await requester_protocol.send_task_end(session_id=sid, status=result_msg.status, result=result_msg.result, error=result_msg.error, response_id=result_msg.response_id)
                self.logger.info(f'[WS] ✅ Sent to client {client_id} successfully')
                if client_type == ClientType.CONSTELLATION and target_device_id:
                    target_protocol = self.client_manager.get_task_protocol(target_device_id)
                    if target_protocol:
                        self.logger.info(f'[WS] 📤 Sending result to target device {target_device_id} via AIP...')
                        try:
                            await target_protocol.send_task_end(session_id=sid, status=result_msg.status, result=result_msg.result, error=result_msg.error, response_id=result_msg.response_id)
                            self.logger.info(f'[WS] ✅ Sent to target device {target_device_id} successfully')
                        except (ConnectionError, IOError) as target_error:
                            self.logger.warning(f'[WS] ⚠️ Target device {target_device_id} disconnected: {target_error}')
                    else:
                        self.logger.warning(f'[WS] ⚠️ Target device {target_device_id} disconnected, skipping send')
                self.logger.info(f'[WS] ✅ All results sent for session {sid}')
            except (ConnectionError, IOError) as e:
                self.logger.warning(f'[WS] ⚠️ Connection error sending result for {sid}: {e}')
            except Exception as e:
                import traceback
                self.logger.error(f'[WS] ❌ Failed to send result for {sid}: {e}\n{traceback.format_exc()}')
        self.logger.info(f'[WS] 🎯 About to call execute_task_async for session {session_id}')
        target_protocol = self.client_manager.get_task_protocol(target_device_id if client_type == ClientType.CONSTELLATION else client_id)
        try:
            await self.session_manager.execute_task_async(session_id=session_id, task_name=task_name, request=data.request, task_protocol=target_protocol, platform_override=platform, callback=send_result, owner_client_id=client_id, executor_client_id=target_device_id if client_type == ClientType.CONSTELLATION else client_id)
        except SessionOwnershipError as owner_err:
            if client_type == ClientType.CONSTELLATION:
                try:
                    self.client_manager.remove_constellation_sessions(data.client_id)
                except Exception as rollback_err:
                    self.logger.warning(f'[WS] Failed to remove constellation session on rollback: {rollback_err}')
                if target_device_id:
                    try:
                        self.client_manager.remove_device_sessions(target_device_id)
                    except Exception as rollback_err:
                        self.logger.warning(f'[WS] Failed to remove device session on rollback: {rollback_err}')
            self.logger.warning(f'[WS] 🚨 cross-client session reuse rejected: session_id={owner_err.session_id!r} owner={owner_err.owner!r} attempted_by={owner_err.attempted_by!r}')
            await self._safe_send_error(f'session_id {owner_err.session_id!r} is owned by another client', ctx)
            return
        self.logger.info(f'[WS] 🎯 execute_task_async returned for session {session_id}')
        if ctx.task_protocol is not None:
            await ctx.task_protocol.send_ack(session_id=session_id)
        self.logger.info(f'[WS] 📝 Task {session_id} accepted and running in background')

    async def handle_command_result(self, data: ClientMessage, ctx: ConnectionContext) -> None:
        """
        Handle the result of commands. Run in background.

        Security: this path must never *create* a session. ``COMMAND_RESULTS``
        has no role gate, so any authenticated client can reach it with an
        attacker-chosen ``session_id``. Creating a session here (the
        previous behavior) let a peer inject an *unowned* session into the
        shared store under a victim's predictable ``session_id`` — which
        the ownership defense then refuses to hand to the legitimate owner,
        causing a persistent denial of service, and which also enabled
        unbounded phantom-session resource exhaustion.

        The result is therefore bound to the connection's registered
        identity: we look the session up (never create), drop the message
        if no such session exists, and reject results that do not come
        from the principal the session dispatches commands to.

        :param data: The data from the client.
        :param ctx: The per-connection context carrying the registered
            identity bound to this socket at registration.
        """
        self.logger.debug(f'[WS] Handling command result: {data.action_results}')
        response_id = data.prev_response_id
        session_id = data.session_id
        session = self.session_manager.get_session(session_id)
        if session is None:
            self.logger.warning(f'[WS] 🚨 dropping COMMAND_RESULTS for unknown session session_id={session_id!r} from {ctx.registered_client_id!r}; refusing to create a session on the command-result path')
            return
        if not self.session_manager.is_authorized_result_sender(session_id, ctx.registered_client_id):
            self.logger.warning(f'[WS] 🚨 COMMAND_RESULTS rejected: session_id={session_id!r} not owned by sender {ctx.registered_client_id!r}')
            return
        command_dispatcher: WebSocketCommandDispatcher = session.context.command_dispatcher
        await command_dispatcher.set_result(response_id, data)

    async def handle_device_info_response(self, data: ClientMessage) -> None:
        """
        Handle device info response from a client device.
        Stores the received device info in the client manager for later retrieval.
        :param data: The data from the client.
        """
        client_id = data.client_id
        payload = data.payload if hasattr(data, 'payload') else {}
        self.logger.info(f"[WS] Received device info response from {client_id}, payload keys: {(list(payload.keys()) if isinstance(payload, dict) else 'N/A')}")
        try:
            if hasattr(self.client_manager, 'update_device_info'):
                self.client_manager.update_device_info(client_id, payload)
                self.logger.debug(f'[WS] Stored device info for {client_id}')
            else:
                self.logger.debug(f'[WS] Device info from {client_id} received but client_manager does not support update_device_info; data logged only.')
        except Exception as e:
            self.logger.warning(f'[WS] Failed to store device info for {client_id}: {e}')

    async def handle_device_info_request(self, data: ClientMessage, ctx: ConnectionContext) -> None:
        """
        Handle device info request from constellation client using AIP DeviceInfoProtocol.

        Authorization (function-level): ``DEVICE_INFO_REQUEST`` exposes a
        device's stored ``system_info`` (hostname, internal IP, platform,
        CPU/memory, operator metadata and tags). It is an
        orchestration-plane operation reserved for ``CONSTELLATION``
        clients. The role used here is the authoritative identity pinned
        to the connection at registration (``ctx.registered_client_type``),
        never the wire-supplied ``data.client_type``. Without this check a
        connection that registered as a ``DEVICE`` could read any other
        device's ``system_info`` simply by naming it in ``target_id`` —
        a cross-device information-disclosure. Authentication answers
        "who are you"; this is the missing answer to "are you allowed to
        do this".

        Cross-client isolation: the response is sent on
        ``ctx.device_info_protocol`` — bound to the requesting
        constellation's transport — so the device info cannot be
        delivered onto another client's socket even when other clients
        have connected to the same shared :class:`UFOWebSocketHandler`.

        :param data: The request data from constellation.
        :param ctx: The per-connection context bound to the requesting
            constellation client.
        """
        if ctx.registered_client_type != ClientType.CONSTELLATION:
            self.logger.warning(f'[WS] 🚨 DEVICE_INFO_REQUEST rejected for non-constellation {ctx.registered_client_id!r} (role={ctx.registered_client_type}, target_id={data.target_id!r})')
            await self._safe_send_error('DEVICE_INFO_REQUEST is permitted only for constellation clients', ctx)
            return
        device_id = data.target_id
        request_id = data.request_id
        if ctx.registered_target_id is not None and device_id != ctx.registered_target_id:
            self.logger.warning(f'[WS] 🚨 DEVICE_INFO_REQUEST rejected: constellation {ctx.registered_client_id!r} is scoped to device {ctx.registered_target_id!r} but requested {device_id!r}')
            await self._safe_send_error('Not authorized to request device info for this device', ctx)
            return
        self.logger.info(f'[WS] [AIP] 🌟 Constellation requesting device info for {device_id}')
        device_info = await self.get_device_info(device_id)
        if ctx.device_info_protocol is not None:
            await ctx.device_info_protocol.send_device_info_response(device_info=device_info, request_id=request_id)
        self.logger.info(f'[WS] [AIP] 📤 Sent device info response for {device_id} to constellation')

    async def get_device_info(self, device_id: str) -> dict:
        """
        Get device system information for a specific device.
        This is called by constellation clients via WebSocket.

        :param device_id: The device ID to get information for.
        :return: Device system information dictionary.
        """
        device_info = self.client_manager.get_device_system_info(device_id)
        if device_info:
            return device_info
        else:
            return {'error': f'Device {device_id} not found or no system info available'}