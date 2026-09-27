# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Data models for Galaxy Web UI.

This package contains Pydantic models and enums used throughout the Web UI.
"""

from ufo.galaxy.webui.models.enums import (
    RequestStatus,
    WebSocketMessageType,
)
from ufo.galaxy.webui.models.requests import (
    DeviceAddRequest,
    NextSessionMessage,
    PingMessage,
    RequestMessage,
    ResetMessage,
    StopTaskMessage,
    WebSocketMessage,
)
from ufo.galaxy.webui.models.responses import (
    DeviceAddResponse,
    ErrorMessage,
    HealthResponse,
    NextSessionAcknowledgedMessage,
    PongMessage,
    RequestCompletedMessage,
    RequestFailedMessage,
    RequestReceivedMessage,
    ResetAcknowledgedMessage,
    StandardResponse,
    StopAcknowledgedMessage,
    WelcomeMessage,
)

__all__ = [
    # Enums
    "WebSocketMessageType",
    "RequestStatus",
    # Requests
    "DeviceAddRequest",
    "WebSocketMessage",
    "RequestMessage",
    "ResetMessage",
    "NextSessionMessage",
    "StopTaskMessage",
    "PingMessage",
    # Responses
    "StandardResponse",
    "HealthResponse",
    "DeviceAddResponse",
    "WelcomeMessage",
    "RequestReceivedMessage",
    "RequestCompletedMessage",
    "RequestFailedMessage",
    "ResetAcknowledgedMessage",
    "NextSessionAcknowledgedMessage",
    "StopAcknowledgedMessage",
    "PongMessage",
    "ErrorMessage",
]
