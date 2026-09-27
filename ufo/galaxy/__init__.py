# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
UFO Galaxy Framework

A comprehensive framework for DAG-based task orchestration and device management.

This package provides:
- Constellation: DAG management and execution
- Agents: Task orchestration agents (GalaxyWeaverAgent)
- Session: Galaxy session management
- Client: Device management and coordination
"""

# Core constellation components
# Agent components
from .agents import ConstellationAgent
from .constellation import (
    ConstellationManager,
    ConstellationState,
    DependencyType,
    DeviceType,
    TaskConstellation,
    TaskConstellationOrchestrator,
    TaskPriority,
    TaskStar,
    TaskStarLine,
    TaskStatus,
)

# Client entry points
from .galaxy_client import GalaxyClient

# Session components
from .session import GalaxySession

__all__ = [
    # Constellation
    "TaskConstellationOrchestrator",
    "TaskConstellation",
    "TaskStar",
    "TaskStarLine",
    "TaskStatus",
    "DependencyType",
    "ConstellationState",
    "DeviceType",
    "TaskPriority",
    "ConstellationManager",
    # Agents
    "ConstellationAgent",
    # Session
    "GalaxySession",
    # Client
    "GalaxyClient",
]
