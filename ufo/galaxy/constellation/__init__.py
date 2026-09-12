# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Task System for Constellation V2 - Modular task orchestration system.

This module provides a comprehensive task management system for multi-device
orchestration with LLM integration, dynamic task creation, and async execution.
"""

from .enums import (
    TaskStatus,
    DependencyType,
    ConstellationState,
    TaskPriority,
    DeviceType,
)
from .task_star import TaskStar

from .task_star_line import TaskStarLine

from .task_constellation import TaskConstellation

from .orchestrator.orchestrator import TaskConstellationOrchestrator

from .orchestrator.constellation_manager import ConstellationManager

def create_simple_constellation(task_descriptions, name="Simple Constellation", sequential=True):
    constellation = TaskConstellation(name=name)
    prev_id = None
    for i, desc in enumerate(task_descriptions):
        task_id = f"task_{i+1}"
        task = TaskStar(task_id=task_id, description=desc, target_device_id="device1")
        constellation.add_task(task)
        if sequential and prev_id:
            constellation.add_dependency(prev_id, task_id)
        prev_id = task_id
    return constellation


from .parsers.constellation_parser import ConstellationParser as LLMParser


async def create_and_orchestrate_from_llm(llm_output, orchestrator=None, name="LLM Constellation"):
    if orchestrator is None:
        orchestrator = TaskConstellationOrchestrator()
    return await orchestrator.create_constellation_from_llm(llm_output, name)


__all__ = [
    "TaskStatus",
    "DependencyType",
    "ConstellationState",
    "TaskPriority",
    "DeviceType",
    "TaskStar",
    "TaskStarLine",
    "TaskConstellation",
    "TaskConstellationOrchestrator",
    "ConstellationManager",
    "create_simple_constellation",
    "create_and_orchestrate_from_llm",
    "LLMParser",
]
