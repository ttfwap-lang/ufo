# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Device Manager Types

Common types and data structures used across device manager components.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class DeviceStatus(Enum):
    """Device connection status"""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FAILED = "failed"
    REGISTERING = "registering"
    BUSY = "busy"  # Device is executing a task
    IDLE = "idle"  # Device is connected and ready for tasks


@dataclass
class AgentProfile:
    """Device information and capabilities"""

    device_id: str
    server_url: str
    os: str | None = None
    capabilities: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    status: DeviceStatus = DeviceStatus.DISCONNECTED
    last_heartbeat: datetime | None = None
    connection_attempts: int = 0
    max_retries: int = 5
    current_task_id: str | None = None  # Track current executing task
    auto_connect: bool = True  # False: never (re)connected automatically


@dataclass
class TaskRequest:
    """Task request for device execution"""

    task_id: str
    device_id: str
    request: str
    task_name: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timeout: float = 300.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DeviceEventHandler(ABC):
    """Abstract base class for device event handlers"""

    @abstractmethod
    async def on_device_connected(
        self, device_id: str, device_info: AgentProfile
    ) -> None:
        """Handle device connection event"""
        pass

    @abstractmethod
    async def on_device_disconnected(self, device_id: str) -> None:
        """Handle device disconnection event"""
        pass

    @abstractmethod
    async def on_task_completed(
        self, device_id: str, task_id: str, result: dict[str, Any]
    ) -> None:
        """Handle task completion event"""
        pass
