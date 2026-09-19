# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ConstellationSerializer: dict/JSON conversion for TaskConstellation.

Thin static helpers over TaskConstellation.to_dict/from_dict/to_json/from_json,
plus normalisation of the list-style dependency format some LLM and legacy
payloads use ([{"predecessor_id", "successor_id", ...}]) into the dict keyed
format TaskConstellation expects.
"""

import json
from typing import Any, Dict

from ufo.galaxy.constellation.task_constellation import TaskConstellation


class ConstellationSerializer:
    def __init__(self, enable_logging: bool = True):
        self.enable_logging = enable_logging

    # ---- static API -------------------------------------------------------

    @staticmethod
    def to_dict(constellation: TaskConstellation) -> Dict[str, Any]:
        return constellation.to_dict()

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> TaskConstellation:
        return TaskConstellation.from_dict(ConstellationSerializer.normalize_json_data(data))

    @staticmethod
    def to_json(constellation: TaskConstellation) -> str:
        return constellation.to_json()

    @staticmethod
    def from_json(json_data: str) -> TaskConstellation:
        # json.loads raises json.JSONDecodeError on malformed input.
        return ConstellationSerializer.from_dict(json.loads(json_data))

    @staticmethod
    def normalize_json_data(data: Dict[str, Any]) -> Dict[str, Any]:
        """Return a copy of data whose "dependencies" is a dict keyed by id.

        List entries may use predecessor_id/successor_id or from_task_id/to_task_id;
        they become {"dep_<i>": {"from_task_id", "to_task_id", ...}}.
        """
        normalized = dict(data)
        deps = data.get("dependencies")
        if isinstance(deps, list):
            converted = {}
            for i, dep in enumerate(deps):
                if not isinstance(dep, dict):
                    continue
                entry = dict(dep)
                entry["from_task_id"] = entry.pop("predecessor_id", entry.get("from_task_id"))
                entry["to_task_id"] = entry.pop("successor_id", entry.get("to_task_id"))
                converted[entry.get("line_id") or f"dep_{i}"] = entry
            normalized["dependencies"] = converted
        return normalized

    # ---- instance API (kept for existing callers) -----------------------------

    def serialize_to_json(self, constellation: TaskConstellation) -> str:
        return self.to_json(constellation)

    def deserialize_from_json(self, json_data: str) -> TaskConstellation:
        return self.from_json(json_data)

    def serialize_to_dict(self, constellation: TaskConstellation) -> Dict[str, Any]:
        return json.loads(constellation.to_json())
