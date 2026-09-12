# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import pytest
from ufo.utils import json_parser, _normalize_keys, regex_normalize_pascal_keys
from ufo.agents.processors.schemas.response_schema import HostAgentResponse, AppAgentResponse


def test_regex_normalize_pascal_keys():
    raw_json = '{"Function": "run_shell", "Args": {"Cmd": "dir"}, "CurrentSubtask": "Step 1"}'
    normalized = regex_normalize_pascal_keys(raw_json)
    assert '"function":' in normalized
    assert '"arguments":' in normalized
    assert '"current_subtask":' in normalized


def test_normalize_keys_dict():
    raw_dict = {
        "Function": "bash",
        "Args": {
            "cmd": "echo hello",
            "app_name": "notepad"
        },
        "CurrentSubtask": "testing"
    }
    norm = _normalize_keys(raw_dict)
    assert norm["function"] == "bash"
    assert norm["arguments"]["bash_command"] == "echo hello"
    assert norm["arguments"]["name"] == "notepad"
    assert norm["current_subtask"] == "testing"


def test_json_parser_with_pascal_case_and_aliases():
    json_str = """
    ```json
    {
        "Observation": "Desktop visible",
        "Thought": "Run shell command",
        "Status": "CONTINUE",
        "Function": "bash",
        "Args": {
            "command": "dir"
        },
        "CurrentSubtask": "listing files"
    }
    ```
    """
    parsed = json_parser(json_str)
    assert parsed["observation"] == "Desktop visible"
    assert parsed["thought"] == "Run shell command"
    assert parsed["status"] == "CONTINUE"
    assert parsed["function"] == "bash"
    assert parsed["arguments"]["bash_command"] == "dir"
    assert parsed["current_subtask"] == "listing files"


def test_host_agent_response_validation():
    json_str = '{"Observation": "Obs", "Thought": "Th", "Status": "CONTINUE", "Function": "click", "Args": {"cmd": "test"}}'
    parsed = json_parser(json_str)
    response = HostAgentResponse.model_validate(parsed)
    assert response.observation == "Obs"
    assert response.thought == "Th"
    assert response.status == "CONTINUE"
    assert response.function == "click"
    assert response.arguments == {"bash_command": "test"}


def test_app_agent_response_validation():
    json_str = """{
        "Observation": "Obs app",
        "Thought": "Th app",
        "Action": {
            "Function": "click",
            "Args": {
                "cmd": "start"
            }
        }
    }"""
    parsed = json_parser(json_str)
    # Perform action normalization as done in _parse_app_response
    if isinstance(parsed.get("action"), dict):
        if "cmd" in parsed["action"].get("arguments", {}):
            parsed["action"]["arguments"]["bash_command"] = parsed["action"]["arguments"].pop("cmd")
    response = AppAgentResponse.model_validate(parsed)
    assert response.observation == "Obs app"
    assert response.thought == "Th app"
    assert response.action.function == "click"
    assert response.action.arguments == {"bash_command": "start"}
