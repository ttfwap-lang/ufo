"""
PowerPoint COM MCP server: presentation-level PowerPoint operations through the
Office COM API, which are faster and more reliable than clicking the ribbon.
"""
import logging
import platform
import sys

if platform.system() != 'Windows':
    logging.warning(f'ppt_wincom_mcp_server.py requires Windows platform. Current: {platform.system()}. Skipping module initialization.')
    sys.exit(0)
from typing import Annotated, Any, Callable, List, Optional

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from ufo.automator.app_apis.office_com import OfficeComSession
from ufo.automator.app_apis.powerpoint.powerpointclient import PowerPointWinCOMReceiver
from ufo.client.mcp.mcp_registry import MCPRegistry

logger = logging.getLogger(__name__)


@MCPRegistry.register_factory_decorator('PowerPointCOMExecutor')
@MCPRegistry.register_factory_decorator('ppt_wincom_mcp_server')
def create_powerpoint_mcp_server(process_name: str = '', *args, **kwargs) -> FastMCP:
    """
    :param process_name: The PowerPoint window title; used to pick the matching open presentation.
    """
    session = OfficeComSession('PowerPoint.Application', PowerPointWinCOMReceiver, 'POWERPNT.EXE', process_name)

    def run(fn: Callable[[PowerPointWinCOMReceiver], Any]) -> Any:
        try:
            return session.call(fn)
        except Exception as e:
            raise ToolError(f'PowerPoint: {e}')

    mcp = FastMCP('UFO PowerPoint COM MCP Server')

    @mcp.tool(tags={'AppAgent'})
    def add_slide(title: Annotated[str, Field(description='Slide title text.')] = '', body: Annotated[str, Field(description='Body text; use \\n for separate bullet lines.')] = '', layout: Annotated[str, Field(description='One of: title, title_and_content, title_only, blank.')] = 'title_and_content', position: Annotated[int, Field(description='1-based position; -1 appends at the end.')] = -1) -> str:
        """Add a slide with a title and body text in one step."""
        return run(lambda r: r.add_slide(title, body, layout, position))

    @mcp.tool(tags={'AppAgent'})
    def set_slide_text(slide_index: Annotated[int, Field(description='1-based slide number.')], placeholder_index: Annotated[int, Field(description='1 = title, 2 = body on most layouts.')], text: Annotated[str, Field(description='The new text.')]) -> str:
        """Replace the text of a title/body placeholder on a slide."""
        return run(lambda r: r.set_slide_text(slide_index, placeholder_index, text))

    @mcp.tool(tags={'AppAgent'})
    def get_slides_text() -> str:
        """Read all text on every slide (to check content)."""
        return run(lambda r: r.get_slides_text())

    @mcp.tool(tags={'AppAgent'})
    def insert_image(slide_index: Annotated[int, Field(description='1-based slide number.')], image_path: Annotated[str, Field(description='Absolute path of the image file.')], left: Annotated[float, Field(description='Left position in points.')] = 50, top: Annotated[float, Field(description='Top position in points.')] = 100, width: Annotated[float, Field(description='Width in points (0 keeps the original size).')] = 0) -> str:
        """Insert a picture on a slide."""
        return run(lambda r: r.insert_image(slide_index, image_path, left, top, width))

    @mcp.tool(tags={'AppAgent'})
    def set_background_color(color: Annotated[str, Field(description="Hex RGB color, e.g. 'FFFFFF'.")], slide_index: Annotated[Optional[List[int]], Field(description='Slide numbers to change; None for all slides.')] = None) -> str:
        """Set the background color of slides."""
        return run(lambda r: r.set_background_color(color, slide_index))

    @mcp.tool(tags={'AppAgent'})
    def save_as(file_dir: Annotated[str, Field(description="Directory to save to. Defaults to the presentation's folder, or Documents if it was never saved.")] = '', file_name: Annotated[str, Field(description='File name without extension. Defaults to the current name.')] = '', file_ext: Annotated[str, Field(description="Extension, e.g. '.pptx', '.pdf' or '.png'. Defaults to '.pptx'.")] = '', current_slide_only: Annotated[bool, Field(description='For image formats, export only the current slide.')] = False) -> str:
        """Save or export the presentation in one step (faster and more reliable than the Save dialog)."""
        return run(lambda r: r.save_as(file_dir, file_name, file_ext, current_slide_only))

    return mcp


if __name__ == '__main__':
    logging.basicConfig(level=logging.ERROR)
    create_powerpoint_mcp_server().run()
