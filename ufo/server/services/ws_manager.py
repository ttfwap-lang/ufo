# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Backward compatibility module for ws_manager.
"""

from ufo.server.services.client_connection_manager import (
    ClientConnectionManager as WSManager,
)
from ufo.server.services.client_connection_manager import (
    ClientInfo,
)

__all__ = ["WSManager", "ClientInfo"]
