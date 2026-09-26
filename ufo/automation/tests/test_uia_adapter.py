"""Unit tests for automation.uia_adapter.

These tests mock out the underlying pywinauto calls entirely -- they do
not require the ``pywinauto``/``uiautomation`` packages to be installed,
nor a real Windows GUI session. Constructing a ``UIADesktop`` never
imports pywinauto; only calling ``launch``/``find_window``/etc. does, so
we patch ``automation.uia_adapter._import_pywinauto`` directly to make
the tests independent of what's actually installed in this environment.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT.parent))

from ufo.automation.desktop import Element
from ufo.automation.uia_adapter import UIADesktop


def test_import_guard_raises_clear_runtime_error_when_pywinauto_missing():
    """If pywinauto truly is not installed, instantiating the class must
    not fail, and calling launch() must raise a clear, actionable error."""
    with patch.dict(sys.modules, {"pywinauto": None}):
        adapter = UIADesktop()
        import asyncio

        with pytest.raises(RuntimeError, match="pywinauto"):
            asyncio.run(adapter.launch("notepad.exe"))


@pytest.mark.asyncio
async def test_launch_starts_application_and_returns_pid():
    mock_process = MagicMock(pid=1234)
    mock_app_instance = MagicMock()
    mock_app_instance.process = mock_process

    mock_application_cls = MagicMock()
    mock_application_cls.return_value.start.return_value = mock_app_instance

    fake_pywinauto_module = MagicMock()

    with patch(
        "ufo.automation.uia_adapter._import_pywinauto",
        return_value=(fake_pywinauto_module, mock_application_cls),
    ):
        adapter = UIADesktop()
        pid = await adapter.launch("notepad.exe")

    assert pid == 1234
    mock_application_cls.assert_called_once_with(backend="uia")
    mock_application_cls.return_value.start.assert_called_once_with("notepad.exe")


@pytest.mark.asyncio
async def test_find_window_returns_element_with_rect():
    mock_rect = MagicMock(left=0, top=0, right=800, bottom=600)
    mock_info = MagicMock(
        class_name="Notepad",
        rectangle=mock_rect,
        automation_id="",
    )
    mock_info.name = "Untitled - Notepad"
    mock_window = MagicMock()
    mock_window.element_info = mock_info

    mock_app = MagicMock()
    mock_app.window.return_value = mock_window

    adapter = UIADesktop()
    adapter._app = mock_app
    adapter._pywinauto = MagicMock()
    adapter._application_cls = MagicMock()

    element = await adapter.find_window(r"Notepad", class_name="Notepad")

    assert element.name == "Untitled - Notepad"
    assert element.class_name == "Notepad"
    assert element.rect is not None
    assert element.rect.width == 800
    assert element.rect.height == 600
    mock_window.wait.assert_called_once_with("exists", timeout=10)


@pytest.mark.asyncio
async def test_find_window_without_app_searches_desktop(monkeypatch):
    """find_window with no connection falls back to a desktop-wide search.

    The old version of this test expected a RuntimeError mentioning "launch",
    from a time when find_window required a connection. The code now documents
    and implements the fallback instead: with _app unset it searches all
    top-level windows via pywinauto's Desktop class and raises whatever that
    search reports - which for a window that is not there is a timeout.

    It was left asserting the removed behaviour and failed on every run. The
    search is mocked so this does not depend on whether a Notepad happens to be
    open on the machine running the suite.
    """
    adapter = UIADesktop()
    adapter._pywinauto = MagicMock()
    adapter._application_cls = MagicMock()

    fake_window = MagicMock()
    fake_window.wait.side_effect = RuntimeError("timed out")
    fake_desktop = MagicMock()
    fake_desktop.window.return_value = fake_window

    import pywinauto
    monkeypatch.setattr(pywinauto, "Desktop", MagicMock(return_value=fake_desktop))

    with pytest.raises(RuntimeError, match="timed out"):
        await adapter.find_window("Notepad")

    # The desktop fallback really was taken, not an in-app search.
    fake_desktop.window.assert_called_once()
    fake_window.wait.assert_called_once_with("exists", timeout=10)
    assert adapter._app is None


@pytest.mark.asyncio
async def test_find_element_passes_criteria_to_child_window():
    mock_rect = MagicMock(left=1, top=2, right=3, bottom=4)
    mock_info = MagicMock(
        class_name="Button", rectangle=mock_rect, automation_id="okBtn"
    )
    mock_info.name = "OK"
    mock_control = MagicMock()
    mock_control.element_info = mock_info

    mock_parent_window = MagicMock()
    mock_parent_window.child_window.return_value = mock_control

    parent_element = Element(handle=mock_parent_window, name="parent")

    adapter = UIADesktop()
    adapter._pywinauto = MagicMock()
    adapter._application_cls = MagicMock()

    result = await adapter.find_element(parent_element, title="OK", control_type="Button")

    mock_parent_window.child_window.assert_called_once_with(
        title="OK", control_type="Button"
    )
    assert result.name == "OK"
    assert result.automation_id == "okBtn"


@pytest.mark.asyncio
async def test_click_and_type_text_delegate_to_control():
    mock_control = MagicMock()
    element = Element(handle=mock_control, name="button")

    adapter = UIADesktop()
    await adapter.click(element)
    mock_control.click_input.assert_called_once()

    await adapter.type_text(element, "hello")
    mock_control.type_keys.assert_called_once_with("hello", with_spaces=True)


@pytest.mark.asyncio
async def test_get_text_uses_window_text():
    mock_control = MagicMock()
    mock_control.window_text.return_value = "some text"
    element = Element(handle=mock_control, name="label")

    adapter = UIADesktop()
    text = await adapter.get_text(element)
    assert text == "some text"


@pytest.mark.asyncio
async def test_close_kills_application_process():
    """A process WE started is cleaned up when the adapter closes.

    launch() spawns it, so leaving it running after teardown would leak a
    session nobody asked for.
    """
    mock_app = MagicMock()
    factory = MagicMock()
    factory.return_value.start.return_value = mock_app
    adapter = UIADesktop()
    adapter._pywinauto = object()        # keep _ensure_imported() from re-importing
    adapter._application_cls = factory

    await adapter.launch("Telegram.exe")
    assert adapter._launched is True

    await adapter.close()

    mock_app.kill.assert_called_once()
    assert adapter._app is None


@pytest.mark.asyncio
async def test_close_does_not_kill_attached_application():
    """connect() attaches to an ALREADY-RUNNING app, so close() must not kill it.

    This was the missing case: close() killed the app whenever _app was set, and
    connect()/connect_handle() both set it while only launch() actually started
    anything. The result was that attaching to the operator's running Telegram
    and then tidying up TERMINATED TELEGRAM DESKTOP - with kill()'s exception
    swallowed, so nothing reported it. Callers include ufo_bridge.py and
    telegram_receiver.py, so it reached production.
    """
    mock_app = MagicMock()
    factory = MagicMock()
    factory.return_value.connect.return_value = mock_app
    adapter = UIADesktop()
    adapter._pywinauto = object()
    adapter._application_cls = factory

    await adapter.connect(process_id=1234)
    assert adapter._launched is False    # attached, not started

    await adapter.close()

    mock_app.kill.assert_not_called()    # the running app survives
    assert adapter._app is None


@pytest.mark.asyncio
async def test_close_is_noop_when_never_launched():
    adapter = UIADesktop()
    await adapter.close()  # should not raise
    assert adapter._app is None
