#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Hardware MCP Server
Provides real MCP interface for hardware (mouse, keyboard, etc.) automation via UFO framework.
"""

import argparse
import os
import sys
import time
import pyautogui
from typing import Annotated, Any, Dict, List, Optional, Tuple
from fastmcp import FastMCP
from pydantic import Field

# Add UFO2 to the path
ufo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if ufo_root not in sys.path:
    sys.path.insert(0, ufo_root)

from ufo.automator.ui_control.screenshot import PhotographerFacade

# Configure pyautogui to avoid failsafes if they get in the way of testing
pyautogui.FAILSAFE = False

def create_hardware_mcp_server(host: str = "", port: int = 8006) -> None:
    """Create a real MCP server for hardware control."""

    mcp = FastMCP(
        "Hardware MCP Server",
        instructions="MCP server for controlling hardware components (keyboard, mouse, screen)",
    )

    @mcp.tool()
    async def type_text(text: str) -> Dict[str, Any]:
        """Type a string of text using real keystrokes."""
        if not text:
            return {"success": False, "message": "Text is empty"}
        pyautogui.write(text)
        return {"success": True, "message": f"Typed text: {text[:20]}{'...' if len(text) > 20 else ''}"}

    @mcp.tool()
    async def press_key_sequence(keys: List[str], interval: float = 0.1) -> Dict[str, Any]:
        """Press a sequence of keys."""
        if not keys:
            return {"success": False, "message": "Key sequence is empty"}
        for k in keys:
            pyautogui.press(k)
            time.sleep(interval)
        return {"success": True, "message": f"Pressed key sequence: {keys[:5]}{'...' if len(keys) > 5 else ''}"}

    @mcp.tool()
    async def press_hotkey(keys: List[str]) -> Dict[str, Any]:
        """Press multiple keys simultaneously (hotkey)."""
        if not keys:
            return {"success": False, "message": "Hotkey list is empty"}
        pyautogui.hotkey(*keys)
        return {"success": True, "message": f"Pressed hotkey: {keys}"}

    @mcp.tool()
    async def move_mouse(x: int, y: int, absolute: bool = False) -> Dict[str, Any]:
        """Move the mouse pointer."""
        if absolute:
            pyautogui.moveTo(x, y)
            position_type = "absolute"
        else:
            pyautogui.move(x, y)
            position_type = "relative"
        return {"success": True, "message": f"Moved mouse to {position_type} position ({x}, {y})"}

    @mcp.tool()
    async def click_mouse(button: str = "left", count: int = 1, interval: float = 0.1) -> Dict[str, Any]:
        """Click the specified mouse button."""
        pyautogui.click(button=button, clicks=count, interval=interval)
        return {"success": True, "message": f"Clicked {button} mouse button {count} times"}

    @mcp.tool()
    async def press_mouse_button(button: str = "left") -> Dict[str, Any]:
        """Press and hold the specified mouse button."""
        pyautogui.mouseDown(button=button)
        return {"success": True, "message": f"Pressed {button} mouse button"}

    @mcp.tool()
    async def release_mouse_button(button: str = "left") -> Dict[str, Any]:
        """Release the specified mouse button."""
        pyautogui.mouseUp(button=button)
        return {"success": True, "message": f"Released {button} mouse button"}

    @mcp.tool()
    async def scroll_mouse(vertical: int = 0, horizontal: int = 0) -> Dict[str, Any]:
        """Scroll the mouse wheel."""
        if vertical != 0:
            pyautogui.scroll(vertical)
        if horizontal != 0:
            pyautogui.hscroll(horizontal)
        return {"success": True, "message": f"Scrolled mouse vertical={vertical}, horizontal={horizontal}"}

    @mcp.tool()
    async def drag_mouse(start: Tuple[int, int], end: Tuple[int, int], button: str = "left", duration: float = 0.5) -> Dict[str, Any]:
        """Drag the mouse from start to end position."""
        pyautogui.moveTo(start[0], start[1])
        pyautogui.dragTo(end[0], end[1], duration=duration, button=button)
        return {"success": True, "message": f"Dragged mouse from {start} to {end} using {button} button"}

    @mcp.tool()
    async def double_click_mouse(button: str = "left") -> Dict[str, Any]:
        """Perform a double-click."""
        pyautogui.doubleClick(button=button)
        return {"success": True, "message": f"Double-clicked {button} mouse button"}

    @mcp.tool()
    async def right_click_mouse() -> Dict[str, Any]:
        """Shortcut for right mouse button click."""
        pyautogui.rightClick()
        return {"success": True, "message": "Right-clicked mouse"}

    @mcp.tool()
    async def middle_click_mouse() -> Dict[str, Any]:
        """Shortcut for middle mouse button click."""
        pyautogui.middleClick()
        return {"success": True, "message": "Middle-clicked mouse"}

    @mcp.tool()
    async def touch_screen(location: Tuple[int, int], ctx: Optional[Any] = None) -> Dict[str, Any]:
        """Simulate a touch at the specified location on the screen."""
        pyautogui.click(x=location[0], y=location[1])
        return {"success": True, "message": f"Touched screen at {location}"}

    @mcp.tool()
    async def draw_on_screen(path: List[Tuple[int, int]], ctx: Optional[Any] = None) -> Dict[str, Any]:
        """Simulate drawing on the screen by following a path of coordinates."""
        if not path:
            return {"success": False, "message": "Path is empty"}
        start = path[0]
        pyautogui.moveTo(start[0], start[1])
        pyautogui.mouseDown()
        for p in path[1:]:
            pyautogui.moveTo(p[0], p[1])
        pyautogui.mouseUp()
        return {"success": True, "message": f"Drew path on screen with {len(path)} points"}

    @mcp.tool()
    async def tap_screen(ctx: Optional[Any] = None, location: Tuple[int, int] = (0, 0), count: int = 1, interval: float = 0.1) -> Dict[str, Any]:
        """Simulate tap(s) at the specified location on the screen."""
        pyautogui.click(x=location[0], y=location[1], clicks=count, interval=interval)
        return {"success": True, "message": f"Tapped screen {count} times at {location}"}

    @mcp.tool()
    async def swipe_screen(ctx: Optional[Any] = None, start_location: Tuple[int, int] = (0, 0), end_location: Tuple[int, int] = (0, 0), duration: float = 0.5) -> Dict[str, Any]:
        """Simulate a swipe gesture from start to end location."""
        pyautogui.moveTo(start_location[0], start_location[1])
        pyautogui.dragTo(end_location[0], end_location[1], duration=duration)
        return {"success": True, "message": f"Swiped screen from {start_location} to {end_location}"}

    @mcp.tool()
    async def long_press_screen(ctx: Optional[Any] = None, location: Tuple[int, int] = (0, 0), duration: float = 1.0) -> Dict[str, Any]:
        """Simulate a long press at the specified location."""
        pyautogui.moveTo(location[0], location[1])
        pyautogui.mouseDown()
        time.sleep(duration)
        pyautogui.mouseUp()
        return {"success": True, "message": f"Long pressed screen at {location} for {duration} seconds"}

    @mcp.tool()
    async def double_tap_screen(location: Tuple[int, int], ctx: Optional[Any] = None) -> Dict[str, Any]:
        """Simulate a double tap at the specified location."""
        pyautogui.doubleClick(x=location[0], y=location[1])
        return {"success": True, "message": f"Double tapped screen at {location}"}

    @mcp.tool()
    async def press_key(ctx: Optional[Any] = None, key: str = "", modifiers: Optional[List[str]] = None, duration: float = 0.1) -> Dict[str, Any]:
        """Simulate pressing a keyboard key, optionally with modifier keys."""
        modifiers = modifiers or []
        if modifiers:
            pyautogui.hotkey(*modifiers, key)
        else:
            pyautogui.press(key)
        modifier_text = f" with modifiers {modifiers}" if modifiers else ""
        return {"success": True, "message": f"Pressed key {key}{modifier_text}"}

    @mcp.tool()
    async def tap_trackpad(ctx: Optional[Any] = None, location: Tuple[int, int] = (0, 0), count: int = 1, interval: float = 0.1) -> Dict[str, Any]:
        """Simulate tap(s) at the specified location on the trackpad."""
        pyautogui.click(x=location[0], y=location[1], clicks=count, interval=interval)
        return {"success": True, "message": f"Tapped trackpad {count} times at {location}"}

    @mcp.tool()
    async def swipe_trackpad(ctx: Optional[Any] = None, start_location: Tuple[int, int] = (0, 0), end_location: Tuple[int, int] = (0, 0), duration: float = 0.5) -> Dict[str, Any]:
        """Simulate a swipe gesture on the trackpad from start to end location."""
        pyautogui.moveTo(start_location[0], start_location[1])
        pyautogui.dragTo(end_location[0], end_location[1], duration=duration)
        return {"success": True, "message": f"Swiped trackpad from {start_location} to {end_location}"}

    @mcp.tool()
    async def take_screenshot() -> str:
        """Take a real screenshot."""
        image_path = "./tests/real_screenshot.png"
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        pyautogui.screenshot(image_path)
        image_data = PhotographerFacade().encode_image_from_path(image_path)
        return image_data

    mcp.run(transport="streamable-http", host=host, port=port, json_response=True, stateless_http=True)

def main():
    parser = argparse.ArgumentParser(description="Hardware MCP Server")
    parser.add_argument("--port", type=int, default=8006, help="Port to run the server on")
    parser.add_argument("--host", default="localhost", help="Host to bind the server to")
    args = parser.parse_args()

    print("=" * 50)
    print("UFO Hardware MCP Server (Real PyAutoGUI Implementation)")
    print(f"Running on {args.host}:{args.port}")
    print("=" * 50)

    create_hardware_mcp_server(host=args.host, port=args.port)

if __name__ == "__main__":
    main()
