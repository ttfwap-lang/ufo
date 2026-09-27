# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Device Manager Components

This package contains the modular components that make up the Constellation Device Manager:
- DeviceRegistry: Device registration and information management
- WebSocketConnectionManager: WebSocket connection management
- HeartbeatManager: Device health monitoring
- MessageProcessor: Message handling and routing
- TaskQueueManager: Task queuing and scheduling
"""

from .connection_manager import WebSocketConnectionManager
from .device_registry import DeviceRegistry
from .heartbeat_manager import HeartbeatManager
from .message_processor import MessageProcessor
from .task_queue_manager import TaskQueueManager
from .types import AgentProfile, DeviceEventHandler, DeviceStatus, TaskRequest

__all__ = [
    "DeviceStatus",
    "AgentProfile",
    "TaskRequest",
    "DeviceEventHandler",
    "DeviceRegistry",
    "WebSocketConnectionManager",
    "HeartbeatManager",
    "MessageProcessor",
    "TaskQueueManager",
]
