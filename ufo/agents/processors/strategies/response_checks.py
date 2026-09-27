"""Checks on a parsed AppAgent reply that are cheap to catch before execution.

Each problem found is turned into feedback for one more model attempt, instead
of executing a call that is guaranteed to fail.
"""
from collections.abc import Iterable
from typing import Any

_CONTROL_ID_FUNCTIONS = {"set_edit_text", "click_input", "texts", "keyboard_input", "wheel_mouse_input"}
_TERMINAL_STATUSES = {"FINISH", "FAIL", "PENDING", "CONFIRM"}


def app_response_problems(
    actions: Iterable[Any],
    status: str | None,
    valid_control_ids: set[str],
    valid_tool_names: set[str] | None = None,
) -> list[str]:
    problems: list[str] = []
    actions = [a for a in actions if a]
    status = (status or "").upper()
    if not any(getattr(a, "function", None) for a in actions) and status not in _TERMINAL_STATUSES:
        problems.append(
            'No "function" was given but status is not FINISH. Either call one of the available functions, '
            'or set "status" to "FINISH" if the subtask is already complete.'
        )
    for act in actions:
        function = getattr(act, "function", "") or ""
        arguments = getattr(act, "arguments", None) or {}
        if not function:
            continue
        if valid_tool_names and function not in valid_tool_names:
            problems.append(
                f"Function '{function}' does not exist. Use exactly one of: {', '.join(sorted(valid_tool_names))}."
            )
            continue
        if function in _CONTROL_ID_FUNCTIONS and isinstance(arguments, dict):
            control_id = arguments.get("id")
            if control_id is not None and valid_control_ids and str(control_id) not in valid_control_ids:
                hint = ""
                if valid_tool_names and "click_on_description" in valid_tool_names:
                    hint = " If the element you want is not in the control list, use click_on_description with a short description of it instead."
                problems.append(f"Control ID '{control_id}' does not exist in the current UI.{hint}")
    return problems


def feedback_text(problems: list[str]) -> str:
    return (
        "Your previous reply cannot be executed:\n- "
        + "\n- ".join(problems)
        + "\nReply again with a corrected JSON object."
    )
