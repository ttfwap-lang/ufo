"""The stale-control error path must report the control, not raise TypeError.

Regression: action_execution called action.action_representation(), but that is
a str field on ActionCommandInfo (the method is to_representation()), so every
stale-control failure surfaced as "'str' object is not callable" and hid the
real cause.
"""
import pytest

from ufo.agents.processors.schemas.actions import ActionCommandInfo, TargetInfo
from ufo.automator.action_execution import ActionExecutor


def test_stale_control_raises_readable_valueerror(monkeypatch):
    action = ActionCommandInfo(
        function="set_edit_text",
        arguments={"text": "hello"},
        target=TargetInfo(id="42", name="Text Editor"),
    )
    monkeypatch.setattr(ActionExecutor, "_control_validation", staticmethod(lambda c: False))

    with pytest.raises(ValueError) as excinfo:
        ActionExecutor().execute(action, puppeteer=None, control_dict={"42": object()},
                                 application_window=None)

    msg = str(excinfo.value)
    assert "42" in msg and "Text Editor" in msg
    assert "set_edit_text" in msg, "the action itself must appear in the message"


def test_action_representation_is_a_field_not_a_method():
    """Guards the exact confusion that caused the bug."""
    action = ActionCommandInfo(function="click_input", arguments={})
    assert isinstance(action.action_representation, str)
    assert callable(action.to_representation)
