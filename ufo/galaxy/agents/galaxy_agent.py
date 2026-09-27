# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Backward compatibility module for galaxy_agent.
"""

from unittest.mock import Mock

from ufo.galaxy.agents.constellation_agent import ConstellationAgent, ConstellationAgent as GalaxyAgent

class MockGalaxyWeaverAgent:
    """Mock agent for testing backward compatibility."""
    def __init__(self, *args, **kwargs):
        self._task_completion_queue = None
        self.logger = None

    @property
    def task_completion_queue(self):
        return self._task_completion_queue

    @task_completion_queue.setter
    def task_completion_queue(self, value):
        self._task_completion_queue = value


__all__ = ["ConstellationAgent", "GalaxyAgent", "MockGalaxyWeaverAgent"]
