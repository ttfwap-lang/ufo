"""
Word COM MCP server: document-level Word operations through the Office COM API,
which are faster and more reliable than clicking through the ribbon.
"""
import logging
import platform
import sys

if platform.system() != 'Windows':
    logging.warning(f'word_wincom_mcp_server.py requires Windows platform. Current: {platform.system()}. Skipping module initialization.')
    sys.exit(0)
from typing import Annotated, Any, Callable, Optional

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from ufo.automator.app_apis.office_com import OfficeComSession
from ufo.automator.app_apis.word.wordclient import WordWinCOMReceiver
from ufo.client.mcp.mcp_registry import MCPRegistry

logger = logging.getLogger(__name__)


@MCPRegistry.register_factory_decorator('WordCOMExecutor')
@MCPRegistry.register_factory_decorator('server_5_WordCOMExecutor')
@MCPRegistry.register_factory_decorator('word_wincom_mcp_server')
def create_word_mcp_server(process_name: str = '', *args, **kwargs) -> FastMCP:
    """
    :param process_name: The Word window title; used to pick the matching open document.
    """
    session = OfficeComSession('Word.Application', WordWinCOMReceiver, 'WINWORD.EXE', process_name)

    def run(fn: Callable[[WordWinCOMReceiver], Any]) -> Any:
        try:
            return session.call(fn)
        except Exception as e:
            raise ToolError(f'Word: {e}')

    mcp = FastMCP('UFO Word COM MCP Server')

    @mcp.tool(tags={'AppAgent'})
    def get_document_text(max_chars: Annotated[int, Field(description='Maximum number of characters to return.')] = 20000) -> str:
        """Read the full plain text of the Word document (to check content or find text to edit)."""
        return run(lambda r: r.get_document_text(max_chars))

    @mcp.tool(tags={'AppAgent'})
    def insert_text(text: Annotated[str, Field(description='The text to insert. Use \\n for new paragraphs.')], position: Annotated[str, Field(description="Where to insert: 'end' or 'start' of the document, or 'cursor'.")] = 'end') -> str:
        """Insert text into the Word document without clicking or typing keystrokes."""
        return run(lambda r: r.insert_text(text, position))

    @mcp.tool(tags={'AppAgent'})
    def find_replace(find_text: Annotated[str, Field(description='The text to find.')], replace_text: Annotated[str, Field(description='The replacement text (empty string deletes).')], replace_all: Annotated[bool, Field(description='Replace every occurrence (true) or only the first (false).')] = True, match_case: Annotated[bool, Field(description='Case-sensitive match.')] = False) -> str:
        """Find and replace text across the whole Word document."""
        return run(lambda r: r.find_replace(find_text, replace_text, replace_all, match_case))

    @mcp.tool(tags={'AppAgent'})
    def apply_style(style_name: Annotated[str, Field(description="Built-in or document style name, e.g. 'Heading 1', 'Title', 'Normal'.")], start_paragraph: Annotated[int, Field(description='First paragraph number (1-based).')], end_paragraph: Annotated[int, Field(description='Last paragraph number; -1 for the end of the document.')] = -1) -> str:
        """Apply a paragraph style to a range of paragraphs."""
        return run(lambda r: r.apply_style(style_name, start_paragraph, end_paragraph))

    @mcp.tool(tags={'AppAgent'})
    def insert_image(image_path: Annotated[str, Field(description='Absolute path of the image file.')], width: Annotated[float, Field(description='Width in points (0 keeps the original size).')] = 0) -> str:
        """Insert a picture at the end of the Word document."""
        return run(lambda r: r.insert_image(image_path, width))

    @mcp.tool(tags={'AppAgent'})
    def insert_table(rows: Annotated[int, Field(description='The number of rows in the table.')], columns: Annotated[int, Field(description='The number of columns in the table.')]) -> str:
        """Insert a table at the end of the Word document."""
        return run(lambda r: r.insert_table(rows, columns))

    @mcp.tool(tags={'AppAgent'})
    def select_text(text: Annotated[str, Field(description='The exact text to be selected.')]) -> str:
        """Select text in the Word document for further operations, such as changing the font."""
        return run(lambda r: r.select_text(text))

    @mcp.tool(tags={'AppAgent'})
    def select_table(number: Annotated[int, Field(description='The index number of the table to be selected.')]) -> str:
        """Select a table in the Word document."""
        return run(lambda r: r.select_table(number))

    @mcp.tool(tags={'AppAgent'})
    def select_paragraph(start_index: Annotated[int, Field(description='The start index of the paragraph to be selected.')], end_index: Annotated[int, Field(description='The end index of the paragraph, if ==-1, select to the end of the document.')], non_empty: Annotated[bool, Field(description='If True, select the non-empty paragraphs only.')] = True) -> str:
        """Select paragraphs in the Word document."""
        return run(lambda r: r.select_paragraph(start_index, end_index, non_empty))

    @mcp.tool(tags={'AppAgent'})
    def set_font(font_name: Annotated[Optional[str], Field(description="Font name, e.g. 'Arial'. None keeps the current font.")] = None, font_size: Annotated[Optional[int], Field(description='Font size, e.g. 12. None keeps the current size.')] = None) -> str:
        """Set the font of the currently selected text (select it first)."""
        return run(lambda r: r.set_font(font_name, font_size))

    @mcp.tool(tags={'AppAgent'})
    def save_as(file_dir: Annotated[str, Field(description="Directory to save to. Defaults to the document's folder, or Documents if it was never saved.")] = '', file_name: Annotated[str, Field(description='File name without extension. Defaults to the current name.')] = '', file_ext: Annotated[str, Field(description="Extension, e.g. '.docx' or '.pdf'. Defaults to '.pdf'.")] = '') -> str:
        """Save or export the Word document in one step (faster and more reliable than the Save dialog)."""
        return run(lambda r: r.save_as(file_dir, file_name, file_ext))

    return mcp


if __name__ == '__main__':
    logging.basicConfig(level=logging.ERROR)
    create_word_mcp_server().run()
