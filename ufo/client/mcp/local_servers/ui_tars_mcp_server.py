"""
UI-TARS MCP Server for Microsoft UFO
Provides visual computer use tools that bypass Windows UIA trees,
allowing high-precision interaction on Canvas, Electron, DirectX, and hostile apps.
"""

import logging
from typing import Annotated, Optional
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field
from ufo.client.mcp.mcp_registry import MCPRegistry
from ufo.automator.ui_tars_bridge import UITarsBridge

logger = logging.getLogger(__name__)

@MCPRegistry.register_factory_decorator('UITarsExecutor')
@MCPRegistry.register_factory_decorator('ui_tars_mcp_server')
def create_ui_tars_mcp_server(*args, **kwargs) -> FastMCP:
    """Create and return the UI-TARS MCP server instance."""
    mcp = FastMCP("UFO UI-TARS Visual Computer Use Server")
    bridge = UITarsBridge()

    @mcp.tool()
    def visual_coordinate_click(
        x: Annotated[int, Field(description="Target X pixel coordinate on screen.")],
        y: Annotated[int, Field(description="Target Y pixel coordinate on screen.")],
        button: Annotated[str, Field(description="Mouse button ('left', 'right', 'middle').")]="left",
        double: Annotated[bool, Field(description="Whether to double click.")]=False,
    ) -> str:
        """Click at absolute screen coordinates using the visual engine."""
        import pyautogui
        try:
            clicks = 2 if double else 1
            pyautogui.click(x, y, button=button, clicks=clicks)
            return f"Visual engine clicked ({button}, double={double}) at screen position ({x}, {y})"
        except Exception as e:
            raise ToolError(f"Visual click failed: {e}")

    @mcp.tool()
    def visual_coordinate_drag(
        start_x: Annotated[int, Field(description="Starting X coordinate.")],
        start_y: Annotated[int, Field(description="Starting Y coordinate.")],
        end_x: Annotated[int, Field(description="Ending X coordinate.")],
        end_y: Annotated[int, Field(description="Ending Y coordinate.")],
        duration: Annotated[float, Field(description="Drag duration in seconds.")]=0.8,
    ) -> str:
        """Drag from start coordinates to end coordinates on screen."""
        import pyautogui
        try:
            pyautogui.moveTo(start_x, start_y)
            pyautogui.dragTo(end_x, end_y, duration=duration, button="left")
            return f"Visual engine dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})"
        except Exception as e:
            raise ToolError(f"Visual drag failed: {e}")

    @mcp.tool()
    def visual_type_text(
        text: Annotated[str, Field(description="Text string to type into focused element.")],
    ) -> str:
        """Type text into the currently focused window using direct keystrokes."""
        import pyautogui
        try:
            pyautogui.write(text, interval=0.02)
            return f"Visual engine typed: '{text}'"
        except Exception as e:
            raise ToolError(f"Visual typing failed: {e}")

    @mcp.tool()
    def visual_hotkey(
        hotkey: Annotated[str, Field(description="Hotkey combination separated by '+' (e.g. 'ctrl+s', 'alt+f4').")],
    ) -> str:
        """Send keyboard shortcut combination."""
        import pyautogui
        try:
            keys = [k.strip().lower() for k in hotkey.split("+")]
            pyautogui.hotkey(*keys)
            return f"Visual engine sent hotkey: {hotkey}"
        except Exception as e:
            raise ToolError(f"Visual hotkey failed: {e}")

    @mcp.tool()
    def execute_visual_action_token(
        action_token: Annotated[str, Field(description="UI-TARS action token string (e.g., Action: click(start_box='(450, 620)'))")],
    ) -> str:
        """Parse and execute a raw UI-TARS action token string."""
        try:
            img, box = bridge.capture_screen_area()
            parsed = bridge.parse_action_string(action_token, img.width, img.height)
            result = bridge.execute_parsed_action(parsed, offset=(box[0], box[1]))
            return result
        except Exception as e:
            raise ToolError(f"Failed to execute visual action token: {e}")

    return mcp

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.ERROR)
    mcp = create_ui_tars_mcp_server()
    mcp.run()
