# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ConstellationParser: convenience API for building and manipulating
TaskConstellation objects (create from LLM text / JSON, simple sequential or
parallel plans, add/remove tasks, validate, export, clone, merge).
"""

import json
import uuid
from typing import List, Optional, Tuple

from ufo.galaxy.constellation.orchestrator.orchestrator import TaskConstellationOrchestrator
from ufo.galaxy.constellation.parsers.constellation_serializer import ConstellationSerializer
from ufo.galaxy.constellation.task_constellation import TaskConstellation
from ufo.galaxy.constellation.task_star import TaskStar


class ConstellationParser:
    def __init__(self, enable_logging: bool = True):
        self.enable_logging = enable_logging
        self.orchestrator = TaskConstellationOrchestrator(enable_logging=enable_logging)

    # ---- creation -----------------------------------------------------------

    async def create_from_llm(self, llm_output: str, name: str = "LLM Constellation") -> TaskConstellation:
        return await self.orchestrator.create_constellation_from_llm(llm_output or "", name)

    async def create_from_json(self, json_data: str, name: Optional[str] = None) -> TaskConstellation:
        constellation = ConstellationSerializer.from_json(json_data)
        if name:
            constellation.name = name
        return constellation

    def create_simple_sequential(self, task_descriptions: List[str], name: str = "Sequential Constellation") -> TaskConstellation:
        return self._simple(task_descriptions, name, sequential=True)

    def create_simple_parallel(self, task_descriptions: List[str], name: str = "Parallel Constellation") -> TaskConstellation:
        return self._simple(task_descriptions, name, sequential=False)

    @staticmethod
    def _simple(task_descriptions: List[str], name: str, sequential: bool) -> TaskConstellation:
        constellation = TaskConstellation(name=name)
        previous = None
        for i, description in enumerate(task_descriptions):
            task_id = f"task_{i + 1}"
            constellation.add_task(TaskStar(task_id=task_id, description=description))
            if sequential and previous:
                constellation.add_dependency(previous, task_id)
            previous = task_id
        return constellation

    # Backwards-compatible names used by earlier callers.
    async def create_simple_constellation(self, task_descriptions: List[str], name: str = "Simple Constellation", sequential: bool = True) -> TaskConstellation:
        return self._simple(task_descriptions, name, sequential)

    async def parse_llm_response(self, llm_response: str, name: str = "LLM Constellation") -> TaskConstellation:
        return await self.create_from_llm(llm_response, name)

    async def parse_json(self, json_data: str, name: Optional[str] = None) -> TaskConstellation:
        return await self.create_from_json(json_data, name)

    # ---- modification ---------------------------------------------------------

    async def update_from_llm(self, constellation: TaskConstellation, modification_request: str) -> TaskConstellation:
        """LLM-driven edits happen in the ConstellationAgent's editing loop; here
        the constellation is returned unchanged."""
        return constellation

    def add_task_to_constellation(self, constellation: TaskConstellation, task: TaskStar, dependencies: Optional[List[str]] = None) -> bool:
        constellation.add_task(task)
        for dep in dependencies or []:
            if dep in constellation.tasks:
                constellation.add_dependency(dep, task.task_id)
        return True

    def remove_task_from_constellation(self, constellation: TaskConstellation, task_id: str) -> bool:
        if task_id not in constellation.tasks:
            return False
        constellation.remove_task(task_id)
        return True

    # ---- inspection / export ----------------------------------------------------

    def validate_constellation(self, constellation: TaskConstellation) -> Tuple[bool, List[str]]:
        if not constellation.tasks:
            return False, ["Constellation has no tasks"]
        return constellation.validate_dag()

    def export_constellation(self, constellation: TaskConstellation, format: str = "json") -> str:
        fmt = (format or "").lower()
        if fmt == "json":
            return constellation.to_json()
        if fmt == "llm":
            lines = [f"Constellation: {constellation.name}", f"Tasks ({constellation.task_count}):"]
            for task_id, task in constellation.tasks.items():
                deps = [d.from_task_id for d in constellation.dependencies.values() if d.to_task_id == task_id]
                suffix = f" (after: {', '.join(deps)})" if deps else ""
                lines.append(f"- {task_id}: {task.description}{suffix}")
            return "\n".join(lines)
        if fmt == "yaml":
            return f"# YAML export not implemented; JSON follows\n{constellation.to_json()}"
        raise ValueError(f"Unsupported export format: {format}")

    # ---- composition -------------------------------------------------------------

    def clone_constellation(self, constellation: TaskConstellation, name: Optional[str] = None) -> TaskConstellation:
        cloned = TaskConstellation.from_json(constellation.to_json())
        cloned._constellation_id = str(uuid.uuid4())
        cloned.name = name or f"{constellation.name} (Copy)"
        return cloned

    def merge_constellations(self, constellation1: TaskConstellation, constellation2: TaskConstellation, name: Optional[str] = None) -> TaskConstellation:
        """Merge two constellations; task ids are prefixed c1_/c2_ so they never collide."""
        merged = TaskConstellation(name=name or f"{constellation1.name} + {constellation2.name}")
        for prefix, source in (("c1_", constellation1), ("c2_", constellation2)):
            for task_id, task in source.tasks.items():
                merged.add_task(TaskStar(task_id=f"{prefix}{task_id}", description=task.description))
            for dep in source.dependencies.values():
                merged.add_dependency(f"{prefix}{dep.from_task_id}", f"{prefix}{dep.to_task_id}")
        return merged
