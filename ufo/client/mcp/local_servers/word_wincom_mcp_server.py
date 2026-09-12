"""
UI MCP Servers
Provides two MCP servers:
1. UI Data MCP Server - for data retrieval operations
2. UI Action MCP Server - for UI automation actions
Both servers share the same UI state for coordinated operations.
"""
import platform
import sys
if platform.system() != 'Windows':
    import logging
    logging.warning(f'word_wincom_mcp_server.py requires Windows platform. Current: {platform.system()}. Skipping module initialization.')
    sys.exit(0)
from typing import Annotated, Any, Dict, Optional
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.client import Client
from pydantic import Field
from ufo.agents.processors.schemas.actions import ActionCommandInfo
from ufo.automator.action_execution import ActionExecutor
from ufo.automator.puppeteer import AppPuppeteer
from ufo.config import get_config
from ufo.client.mcp.mcp_registry import MCPRegistry
configs = get_config()

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
            _ = puppeteer.receiver_manager.get_api_receiver()
            return True
        except Exception:
            return False

@MCPRegistry.register_factory_decorator('WordCOMExecutor')
@MCPRegistry.register_factory_decorator('server_5_WordCOMExecutor')
@MCPRegistry.register_factory_decorator('word_wincom_mcp_server')
def create_word_mcp_server(process_name: str='WINWORD.EXE', *args, **kwargs) -> FastMCP:
    """
    Create and return the AppAgent Action MCP server instance.
    :return: FastMCP instance for AppAgent action operations.
    """
    ui_state = UIServerState()
    executor = ActionExecutor()

    def _ensure_puppeteer():
        if ui_state.puppeteer is None:
            try:
                ui_state.puppeteer = AppPuppeteer(process_name=process_name, app_root_name='WINWORD.EXE')
                ui_state.puppeteer.receiver_manager.create_api_receiver(app_root_name='WINWORD.EXE', process_name=process_name)
            except Exception as e:
                raise ToolError(f'Word COM automation interface unavailable: {e}')

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
                    raise ToolError('COM Health Check Failed prior to action.')
                res = executor.execute(action, ui_state.puppeteer, control_dict={})
                result_queue.put(('success', res))
            except Exception as e:
                result_queue.put(('error', e))
            finally:
                if pythoncom:
                    pythoncom.CoUninitialize()
        t = threading.Thread(target=worker)
        t.daemon = True
        t.start()
        t.join(timeout=30)
        if t.is_alive():
            try:
                import psutil
                for proc in psutil.process_iter(['name', 'pid']):
                    if proc.info['name'] and proc.info['name'].upper() == 'WINWORD.EXE':
                        logger.warning(f"Hard-killing hung WINWORD.EXE (PID {proc.info['pid']}) after 30s timeout")
                        proc.kill()
                        break
            except Exception as kill_err:
                logger.warning(f'Failed to kill hung Word process: {kill_err}')
            raise ToolError('Word COM automation action timed out. Hung process was killed.')
        status, data = result_queue.get()
        if status == 'error':
            raise ToolError(f'Word COM automation failed: {data}')
        return data
    mcp = FastMCP('UFO UI AppAgent Action MCP Server')

    @mcp.tool(tags={'AppAgent'})
    def insert_table(rows: Annotated[int, Field(description='The number of rows in the table.')], columns: Annotated[int, Field(description='The number of columns in the table.')]) -> Annotated[str, Field(description='A message indicating the result of the operation.')]:
        """
        Insert a table to a Word document.
        """
        action = ActionCommandInfo(function='insert_table', arguments={'rows': rows, 'columns': columns})
        return _execute_action(action)

    @mcp.tool(tags={'AppAgent'})
    def select_text(text: Annotated[str, Field(description='The exact text to be selected.')]) -> Annotated[str, Field(description='A string of the selected text if successful, otherwise a text not found message.')]:
        """
        Select the text in a Word document for further operations, such as changing the font size or color.
        """
        action = ActionCommandInfo(function='select_text', arguments={'text': text})
        return _execute_action(action)

    @mcp.tool(tags={'AppAgent'})
    def select_table(number: Annotated[int, Field(description='The index number of the table to be selected.')]) -> Annotated[str, Field(description='A string of the selected table if successful, otherwise an out of range message.')]:
        """
        Select a table in a Word document for further operations, such as deleting the table or changing the border color.
        """
        action = ActionCommandInfo(function='select_table', arguments={'number': number})
        return _execute_action(action)

    @mcp.tool(tags={'AppAgent'})
    def select_paragraph(start_index: Annotated[int, Field(description='The start index of the paragraph to be selected.')], end_index: Annotated[int, Field(description='The end index of the paragraph, if ==-1, select to the end of the document.')], non_empty: Annotated[bool, Field(description='If True, select the non-empty paragraphs only.')]=True) -> Annotated[str, Field(description='A message indicating the result of the operation.')]:
        """
        Select a paragraph in a Word document for further operations, such as changing the alignment or indentation.
        """
        action = ActionCommandInfo(function='select_paragraph', arguments={'start_index': start_index, 'end_index': end_index, 'non_empty': non_empty})
        return _execute_action(action)

    @mcp.tool(tags={'AppAgent'})
    def save_as(file_dir: Annotated[str, Field(description='The directory to save the file. If not specified, the current directory will be used.')]='', file_name: Annotated[str, Field(description='The name of the file without extension. If not specified, the name of the current document will be used.')]='', file_ext: Annotated[str, Field(description="The extension of the file. If not specified, the default extension is '.pdf'.")]='') -> Annotated[str, Field(description='A message indicating the success or failure of saving the document.')]:
        """
        The fastest way to save or export the Word document to a specified file format with one command.
        You should use this API to save your work since it is more efficient than manually saving the document.
        """
        action = ActionCommandInfo(function='save_as', arguments={'file_dir': file_dir, 'file_name': file_name, 'file_ext': file_ext})
        return _execute_action(action)

    @mcp.tool(tags={'AppAgent'})
    def set_font(font_name: Annotated[Optional[str], Field(description="The name of the font (e.g., 'Arial', 'Times New Roman', '宋体'). If None, the font name will not be changed.")]=None, font_size: Annotated[Optional[int], Field(description='The font size (e.g., 12). If None, the font size will not be changed.')]=None) -> Annotated[str, Field(description='A message indicating the font and font size changes if successful, otherwise a message indicating no text selected.')]:
        """
        Set the font of the selected text in a Word document. The text must be selected before calling this command.
        """
        action = ActionCommandInfo(function='set_font', arguments={'font_name': font_name, 'font_size': font_size})
        return _execute_action(action)
    return mcp
if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.ERROR)
    mcp = create_word_mcp_server()
    mcp.run()