#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Excel MCP Server
Provides MCP server for Excel automation operations.
"""

import platform
import sys

# Platform check - this module requires Windows
if platform.system() != "Windows":
    import logging

    logging.warning(
        f"excel_wincom_mcp_server.py requires Windows platform. Current: {platform.system()}. Skipping module initialization."
    )
    # Exit module loading gracefully
    sys.exit(0)

from typing import Annotated, Any, Dict, List, Optional, Union

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.client import Client
from pydantic import Field

from ufo.agents.processors.schemas.actions import ActionCommandInfo
from ufo.automator.action_execution import ActionExecutor
from ufo.automator.puppeteer import AppPuppeteer
from ufo.client.mcp.mcp_registry import MCPRegistry
from ufo.config import get_config

# Get config
configs = get_config()


# Singleton UI server state
class UIServerState:
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(UIServerState, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.puppeteer: Optional[AppPuppeteer] = None
            UIServerState._initialized = True


class Win32COMHealthMonitor:
    """Ticket 5.2: Generic health monitor that probes the COM object."""
    @staticmethod
    def ping(puppeteer: AppPuppeteer) -> bool:
        try:
            if not puppeteer or not puppeteer.receiver_manager:
                return False
            # Simple attribute access to ping the COM object
            _ = puppeteer.receiver_manager.get_api_receiver()
            return True
        except Exception:
            return False

@MCPRegistry.register_factory_decorator("ExcelCOMExecutor")
@MCPRegistry.register_factory_decorator("excel_wincom_mcp_server")
def create_excel_mcp_server(process_name: str = "EXCEL.EXE", *args, **kwargs) -> FastMCP:
    """
    Create and return the Excel MCP server instance.
    :return: FastMCP instance for Excel operations.
    """
    # Get singleton UI state instance
    ui_state = UIServerState()
    executor = ActionExecutor()

    def _ensure_puppeteer():
        if ui_state.puppeteer is None:
            try:
                ui_state.puppeteer = AppPuppeteer(
                    process_name=process_name,
                    app_root_name="EXCEL.EXE",
                )
                ui_state.puppeteer.receiver_manager.create_api_receiver(
                    app_root_name="EXCEL.EXE",
                    process_name=process_name,
                )
            except Exception as e:
                raise ToolError(f"Excel COM automation interface unavailable: {e}")

    def _execute_action(action: ActionCommandInfo) -> Dict[str, Any]:
        """
        Execute a single UI action in a detached thread for COM stability (Ticket 5.1).
        :param action: ActionCommandInfo object to execute.
        :return: Execution result as a dictionary.
        """
        import threading
        import queue
        try:
            import pythoncom
        except ImportError:
            pythoncom = None
            
        result_queue = queue.Queue()
        
        def worker():
            try:
                if pythoncom:
                    pythoncom.CoInitialize()
                _ensure_puppeteer()
                if not Win32COMHealthMonitor.ping(ui_state.puppeteer):
                    raise ToolError("COM Health Check Failed prior to action.")
                res = executor.execute(action, ui_state.puppeteer, control_dict={})
                result_queue.put(("success", res))
            except Exception as e:
                result_queue.put(("error", e))
            finally:
                if pythoncom:
                    pythoncom.CoUninitialize()
                    
        t = threading.Thread(target=worker)
        t.daemon = True
        t.start()
        t.join(timeout=30)
        
        if t.is_alive():
            # Phase 5 Zero-Fail: Hard-kill the hung Office process to prevent zombie lockups
            try:
                import psutil
                for proc in psutil.process_iter(['name', 'pid']):
                    if proc.info['name'] and proc.info['name'].upper() == 'EXCEL.EXE':
                        logger.warning(f"Hard-killing hung EXCEL.EXE (PID {proc.info['pid']}) after 30s timeout")
                        proc.kill()
                        break
            except Exception as kill_err:
                logger.warning(f"Failed to kill hung Excel process: {kill_err}")
            raise ToolError("Excel COM automation action timed out. Hung process was killed.")
            
        status, data = result_queue.get()
        if status == "error":
            raise ToolError(f"Excel COM automation failed: {data}")
        return data

    mcp = FastMCP("UFO Excel MCP Server")

    @mcp.tool(tags={"AppAgent"})
    def table2markdown(
        sheet_name: Annotated[
            Union[str, int],
            Field(
                description="The name or index of the sheet to get the table content. The index starts from 1."
            ),
        ],
    ) -> Annotated[
        str,
        Field(
            description="The markdown format string of the table content of the sheet."
        ),
    ]:
        """
        Get the table content in a sheet of the Excel app and convert it to markdown format.
        """
        action = ActionCommandInfo(
            function="table2markdown",
            arguments={"sheet_name": sheet_name},
        )

        return _execute_action(action)

    @mcp.tool(tags={"AppAgent"})
    def insert_excel_table(
        table: Annotated[
            List[List[Any]],
            Field(
                description="The table content to insert. The table is a list of list of strings or numbers."
            ),
        ],
        sheet_name: Annotated[
            str, Field(description="The name of the sheet to insert the table.")
        ],
        start_row: Annotated[
            int,
            Field(description="The start row to insert the table, starting from 1."),
        ],
        start_col: Annotated[
            int,
            Field(description="The start column to insert the table, starting from 1."),
        ],
    ) -> Annotated[
        str, Field(description="The table content is inserted to the Excel sheet.")
    ]:
        """
        Insert a table to the Excel sheet. The table is a list of list of strings or numbers.
        """
        action = ActionCommandInfo(
            function="insert_excel_table",
            arguments={
                "table": table,
                "sheet_name": sheet_name,
                "start_row": start_row,
                "start_col": start_col,
            },
        )

        return _execute_action(action)

    @mcp.tool(tags={"AppAgent"})
    def select_table_range(
        sheet_name: Annotated[str, Field(description="The name of the sheet.")],
        start_row: Annotated[int, Field(description="The start row, starting from 1.")],
        start_col: Annotated[
            int,
            Field(
                description="The start column, starting from 1. Please map the letter to the number, e.g., A=1, B=2, etc."
            ),
        ],
        end_row: Annotated[
            int,
            Field(
                description="The end row. If ==-1, select to the end of the document with content."
            ),
        ],
        end_col: Annotated[
            int,
            Field(
                description="The end column. If ==-1, select to the end of the document with content. Please map the letter to the number, e.g., A=1, B=2, etc."
            ),
        ],
    ) -> Annotated[
        str,
        Field(
            description="A message indicating whether the range is selected successfully or not."
        ),
    ]:
        """
        A quick way to select a range of cells in the sheet of the Excel app instead of dragging the mouse.
        """
        action = ActionCommandInfo(
            function="select_table_range",
            arguments={
                "sheet_name": sheet_name,
                "start_row": start_row,
                "start_col": start_col,
                "end_row": end_row,
                "end_col": end_col,
            },
        )

        return _execute_action(action)

    @mcp.tool(tags={"AppAgent"})
    def save_as(
        file_dir: Annotated[
            str,
            Field(
                description="The directory to save the file. If not specified, the current directory will be used."
            ),
        ] = "",
        file_name: Annotated[
            str,
            Field(
                description="The name of the file without extension. If not specified, the original file name will be used."
            ),
        ] = "",
        file_ext: Annotated[
            str,
            Field(
                description="The extension of the file. If not specified, the default extension '.csv' will be used."
            ),
        ] = "",
    ) -> Annotated[
        str,
        Field(
            description="A message indicating whether the document is saved successfully or not."
        ),
    ]:
        """
        A shortcut and quickest way to save or export the Excel document to a specified file format with one command.
        """
        action = ActionCommandInfo(
            function="save_as",
            arguments={
                "file_dir": file_dir,
                "file_name": file_name,
                "file_ext": file_ext,
            },
        )

        return _execute_action(action)

    @mcp.tool(tags={"AppAgent"})
    def reorder_columns(
        sheet_name: Annotated[str, Field(description="The name of the sheet.")],
        desired_order: Annotated[
            List[str], Field(description="The list of column names in the new order.")
        ],
    ) -> Annotated[
        str,
        Field(
            description="A message indicating whether the columns are reordered successfully or not."
        ),
    ]:
        """
        Reorder the columns in the sheet of the Excel app based on the desired order.
        """
        action = ActionCommandInfo(
            function="reorder_columns",
            arguments={"sheet_name": sheet_name, "desired_order": desired_order},
        )

        return _execute_action(action)

    @mcp.tool(tags={"AppAgent"})
    def get_range_values(
        sheet_name: Annotated[str, Field(description="The name of the sheet.")],
        start_row: Annotated[int, Field(description="The start row.")],
        start_col: Annotated[int, Field(description="The start column.")],
        end_row: Annotated[int, Field(description="The end row.")],
        end_col: Annotated[int, Field(description="The end column.")],
    ) -> Annotated[List, Field(description="The values in the specified range.")]:
        """
        Get the values from a specified range in the sheet.
        """
        action = ActionCommandInfo(
            function="get_range_values",
            arguments={
                "sheet_name": sheet_name,
                "start_row": start_row,
                "start_col": start_col,
                "end_row": end_row,
                "end_col": end_col,
            },
        )

        return _execute_action(action)

    return mcp

if __name__ == "__main__":
    import logging
    # Suppress output that might corrupt JSON
    logging.basicConfig(level=logging.ERROR)
    mcp = create_excel_mcp_server()
    mcp.run()
