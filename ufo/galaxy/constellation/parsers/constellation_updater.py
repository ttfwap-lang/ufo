# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ConstellationUpdater wrapper module.
"""

from typing import Optional, List

from ufo.galaxy.constellation.task_constellation import TaskConstellation

from ufo.galaxy.constellation.task_star import TaskStar

class ConstellationUpdater:
    def __init__(self, enable_logging: bool = True):
        self.enable_logging = enable_logging

    def add_task(self, constellation: TaskConstellation, task: TaskStar, dependencies: Optional[List[str]] = None) -> bool:
        constellation.add_task(task)
        if dependencies:
            for dep in dependencies:
                constellation.add_dependency(dep, task.task_id)
        return True

    def remove_task(self, constellation: TaskConstellation, task_id: str) -> bool:
        return constellation.remove_task(task_id)
