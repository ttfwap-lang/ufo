#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Fallback Omniparser MCP Server
Provides MCP server for ultimate visual parsing when UI trees fail (Electron/Canvas/Games).
"""

import json
import logging
import os
import tempfile

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from ufo.client.mcp.mcp_registry import MCPRegistry

logger = logging.getLogger(__name__)

@MCPRegistry.register_factory_decorator("FallbackOmniparserExecutor")
@MCPRegistry.register_factory_decorator("mcp_fallback_omniparser")
def create_fallback_omniparser_mcp_server(*args, **kwargs) -> FastMCP:
    """
    Create and return the Omniparser Fallback MCP server instance.
    """
    mcp = FastMCP("UFO Fallback Omniparser MCP Server")

    @mcp.tool()
    def parse_screen_pixels() -> str:
        """
        Forces the agent to take a screenshot and bypass the Windows UIA tree.
        Instead, it sends the image to the OmniParser endpoint to mathematically extract
        all clickable icons, text fields, and boundaries purely from pixels.
        :return: Extracted bounding box JSON data.
        """
        try:
            from ufo.config import get_ufo_config
            ufo_config = get_ufo_config()
            omniparser_config = ufo_config.system.omniparser
            endpoint = omniparser_config.get("ENDPOINT", "") if omniparser_config else ""
        except Exception as e:
            raise ToolError(
                f"OmniParser is not configured. Set OMNIPARSER.ENDPOINT in "
                f"config/ufo/system.yaml to use pixel-based parsing. Error: {e}"
            )

        if not endpoint or "xxx" in endpoint:
            raise ToolError(
                "OmniParser endpoint is not configured. Update OMNIPARSER.ENDPOINT "
                "in config/ufo/system.yaml with a valid OmniParser service URL."
            )

        try:
            from ufo.llm.grounding_model.omniparser_service import OmniParser
            from ufo.automator.ui_control.grounding.omniparser import OmniparserGrounding

            # Capture a screenshot for parsing
            from ufo.automator.ui_control.screenshot import PhotographerFacade
            photographer = PhotographerFacade()
            screenshot_path = os.path.join(tempfile.gettempdir(), "ufo_omniparser_screenshot.png")
            photographer.capture_desktop_screen_screenshot(screenshot_path)

            # Call the real OmniParser service
            service = OmniParser(endpoint=endpoint)
            grounding = OmniparserGrounding(service=service)
            results = grounding.predict(
                screenshot_path,
                box_threshold=omniparser_config.get("BOX_THRESHOLD", 0.05),
                iou_threshold=omniparser_config.get("IOU_THRESHOLD", 0.1),
                use_paddleocr=omniparser_config.get("USE_PADDLEOCR", True),
                imgsz=omniparser_config.get("IMGSZ", 640),
            )

            return json.dumps({
                "status": "success",
                "bounding_boxes": results,
                "count": len(results),
            })

        except ToolError:
            raise
        except Exception as e:
            raise ToolError(
                f"OmniParser pixel parsing failed. Ensure the OmniParser service "
                f"is running at {endpoint}. Error: {e}"
            )

    return mcp

if __name__ == "__main__":
    import logging
    # Suppress output that might corrupt JSON
    logging.basicConfig(level=logging.ERROR)
    mcp = create_fallback_omniparser_mcp_server()
    mcp.run()
