# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
UFO Fleet Operations and Control Plane.

Exposes APIs for Human-In-The-Loop (HITL) resolution, fleet telemetry,
and distributed task orchestration.
"""

from .api_server import app, run_server

from .hitl_manager import HITLManager

from .telemetry_viewer import router as telemetry_router

__all__ = [
    "app",
    "run_server",
    "HITLManager",
    "telemetry_router",
]
