# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ConstellationParser wrapper module.
"""

from typing import Optional, List, Dict, Any

from ufo.galaxy.constellation.task_constellation import TaskConstellation

from ufo.galaxy.constellation.task_star import TaskStar

from ufo.galaxy.constellation.orchestrator.orchestrator import TaskConstellationOrchestrator

class ConstellationParser:
    def __init__(self, enable_logging: bool = True):
        self.orchestrator = TaskConstellationOrchestrator(enable_logging=enable_logging)

    async def create_simple_constellation(self, task_descriptions: List[str], name: str = "Simple Constellation", sequential: bool = True) -> TaskConstellation:
        return await self.orchestrator.create_simple_constellation(task_descriptions, name, sequential)

    async def parse_llm_response(self, llm_response: str, name: str = "LLM Constellation") -> TaskConstellation:
        return await self.orchestrator.create_constellation_from_llm(llm_response, name)

    async def parse_json(self, json_data: str, name: Optional[str] = None) -> TaskConstellation:
        return await self.orchestrator.create_constellation_from_json(json_data, name)
