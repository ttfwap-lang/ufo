# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ConstellationSerializer wrapper module.
"""

import json
from typing import Dict, Any
from ufo.galaxy.constellation.task_constellation import TaskConstellation

class ConstellationSerializer:
    def __init__(self, enable_logging: bool = True):
        self.enable_logging = enable_logging

    def serialize_to_json(self, constellation: TaskConstellation) -> str:
        return constellation.to_json()

    def deserialize_from_json(self, json_data: str) -> TaskConstellation:
        return TaskConstellation.from_json(json_data)

    def serialize_to_dict(self, constellation: TaskConstellation) -> Dict[str, Any]:
        return json.loads(constellation.to_json())
