# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ConstellationUpdater: batch edits on a TaskConstellation, including a small
line-based instruction format for LLM-proposed changes:

    ADD TASK: <description>
    REMOVE TASK: <task_id>
    ADD DEPENDENCY: <from_task_id> -> <to_task_id>
"""

import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from ufo.galaxy.constellation.task_constellation import TaskConstellation
from ufo.galaxy.constellation.task_star import TaskPriority, TaskStar
from ufo.galaxy.constellation.task_star_line import TaskStarLine

_INSTRUCTION = re.compile(r"^\s*(ADD TASK|REMOVE TASK|ADD DEPENDENCY)\s*:\s*(.+?)\s*$", re.I | re.M)
_DEPENDENCY = re.compile(r"^\s*([\w.-]+)\s*->\s*([\w.-]+)\s*$")


class ConstellationUpdater:
    def __init__(self, enable_logging: bool = True, logger: Optional[logging.Logger] = None):
        self.enable_logging = enable_logging
        self.logger = logger or logging.getLogger(__name__)

    # ---- tasks -----------------------------------------------------------------

    def add_tasks(self, constellation: TaskConstellation, descriptions: List[str], priority: TaskPriority = TaskPriority.MEDIUM) -> List[TaskStar]:
        created = []
        for description in descriptions:
            task = TaskStar(task_id=f"task_{uuid.uuid4().hex[:8]}", description=description, priority=priority)
            constellation.add_task(task)
            created.append(task)
        self.logger.info(f"Added {len(created)} task(s) to constellation {constellation.name}")
        return created

    def remove_tasks(self, constellation: TaskConstellation, task_ids: List[str], remove_dependencies: bool = True) -> List[str]:
        """Remove tasks (their dependencies always go with them). Returns removed ids."""
        removed = []
        for task_id in task_ids:
            if task_id in constellation.tasks:
                constellation.remove_task(task_id)
                removed.append(task_id)
        self.logger.info(f"Removed {len(removed)} task(s) from constellation {constellation.name}")
        return removed

    def add_task(self, constellation: TaskConstellation, task: TaskStar, dependencies: Optional[List[str]] = None) -> bool:
        constellation.add_task(task)
        for dep in dependencies or []:
            if dep in constellation.tasks:
                constellation.add_dependency(dep, task.task_id)
        return True

    def remove_task(self, constellation: TaskConstellation, task_id: str) -> bool:
        return bool(self.remove_tasks(constellation, [task_id]))

    # ---- dependencies ------------------------------------------------------------

    def add_dependencies(self, constellation: TaskConstellation, dependency_specs: List[Dict[str, Any]]) -> List[TaskStarLine]:
        created = []
        for spec in dependency_specs:
            dep = self._create_dependency_from_spec(constellation, spec)
            if dep is not None:
                created.append(dep)
        return created

    def _create_dependency_from_spec(self, constellation: TaskConstellation, spec: Dict[str, Any]) -> Optional[TaskStarLine]:
        from_id = spec.get("from_task_id") or spec.get("predecessor_id")
        to_id = spec.get("to_task_id") or spec.get("successor_id")
        if from_id not in constellation.tasks or to_id not in constellation.tasks:
            self.logger.warning(f"Skipping dependency {from_id} -> {to_id}: unknown task")
            return None
        dep = TaskStarLine.create_unconditional(from_id, to_id, spec.get("description", "Unconditional dependency"))
        try:
            constellation.add_dependency(dep)
        except ValueError as e:  # would create a cycle
            self.logger.warning(f"Skipping dependency {from_id} -> {to_id}: {e}")
            return None
        return dep

    def _remove_task_dependencies(self, constellation: TaskConstellation, task_id: str) -> int:
        """Remove every dependency touching task_id, keeping the task itself."""
        dep_ids = [d_id for d_id, d in constellation.dependencies.items() if task_id in (d.from_task_id, d.to_task_id)]
        for dep_id in dep_ids:
            constellation.remove_dependency(dep_id)
        return len(dep_ids)

    @staticmethod
    def _parse_dependency_spec(spec: str) -> Optional[Dict[str, str]]:
        match = _DEPENDENCY.match(spec or "")
        if not match:
            return None
        return {"from_task_id": match.group(1), "to_task_id": match.group(2)}

    # ---- LLM instructions ----------------------------------------------------------

    def _parse_llm_update_instructions(self, llm_output: str) -> List[Dict[str, Any]]:
        instructions = []
        for kind, value in _INSTRUCTION.findall(llm_output or ""):
            kind = kind.upper()
            if kind == "ADD TASK":
                instructions.append({"type": "add_task", "description": value})
            elif kind == "REMOVE TASK":
                instructions.append({"type": "remove_task", "task_id": value})
            else:
                spec = self._parse_dependency_spec(value)
                if spec:
                    instructions.append({"type": "add_dependency", **spec})
        return instructions

    def update_from_llm_output(self, constellation: TaskConstellation, llm_output: str, preserve_existing: bool = True) -> TaskConstellation:
        """Apply ADD/REMOVE instructions; with preserve_existing, removals are ignored."""
        for instruction in self._parse_llm_update_instructions(llm_output):
            if instruction["type"] == "add_task":
                self.add_tasks(constellation, [instruction["description"]])
            elif instruction["type"] == "remove_task":
                if not preserve_existing:
                    self.remove_tasks(constellation, [instruction["task_id"]])
            else:
                self.add_dependencies(constellation, [instruction])
        return constellation
