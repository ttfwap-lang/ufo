"""
Excel COM MCP server: workbook-level Excel operations through the Office COM API,
which are faster and more reliable than typing into cells.
"""
import logging
import platform
import sys

if platform.system() != 'Windows':
    logging.warning(f'excel_wincom_mcp_server.py requires Windows platform. Current: {platform.system()}. Skipping module initialization.')
    sys.exit(0)
from typing import Annotated, Any, Callable, List, Union

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from ufo.automator.app_apis.excel.excelclient import ExcelWinCOMReceiver
from ufo.automator.app_apis.office_com import OfficeComSession
from ufo.client.mcp.mcp_registry import MCPRegistry

logger = logging.getLogger(__name__)
SheetName = Annotated[Union[str, int], Field(description='Sheet name, or 1-based sheet index.')]


@MCPRegistry.register_factory_decorator('ExcelCOMExecutor')
@MCPRegistry.register_factory_decorator('excel_wincom_mcp_server')
def create_excel_mcp_server(process_name: str = '', *args, **kwargs) -> FastMCP:
    """
    :param process_name: The Excel window title; used to pick the matching open workbook.
    """
    session = OfficeComSession('Excel.Application', ExcelWinCOMReceiver, 'EXCEL.EXE', process_name)

    def run(fn: Callable[[ExcelWinCOMReceiver], Any]) -> Any:
        try:
            return session.call(fn)
        except Exception as e:
            raise ToolError(f'Excel: {e}')

    mcp = FastMCP('UFO Excel COM MCP Server')

    @mcp.tool(tags={'AppAgent'})
    def set_cell_values(sheet_name: SheetName, start_cell: Annotated[str, Field(description="Top-left cell, e.g. 'A1'.")], values: Annotated[List[List[Any]], Field(description='Rows of values, e.g. [["Name","Score"],["Ann",9]].')]) -> str:
        """Write a block of values into cells in one step (much faster and more reliable than typing into cells)."""
        return run(lambda r: r.set_cell_values(sheet_name, start_cell, values))

    @mcp.tool(tags={'AppAgent'})
    def set_formula(sheet_name: SheetName, cell: Annotated[str, Field(description="Cell or range, e.g. 'C2' or 'C2:C10'.")], formula: Annotated[str, Field(description="Excel formula, e.g. '=SUM(B2:B10)'.")]) -> str:
        """Set a formula in a cell or range; returns the computed value."""
        return run(lambda r: r.set_formula(sheet_name, cell, formula))

    @mcp.tool(tags={'AppAgent'})
    def add_sheet(name: Annotated[str, Field(description='Name of the new worksheet.')]) -> str:
        """Add a new worksheet at the end of the workbook."""
        return run(lambda r: r.add_sheet(name))

    @mcp.tool(tags={'AppAgent'})
    def create_chart(sheet_name: SheetName, data_range: Annotated[str, Field(description="Data including the header row, e.g. 'A1:B6'.")], chart_type: Annotated[str, Field(description="One of: column, bar, line, pie, scatter, area.")] = 'column', title: Annotated[str, Field(description='Chart title (optional).')] = '') -> str:
        """Create a chart from a data range, placed next to the data."""
        return run(lambda r: r.create_chart(sheet_name, data_range, chart_type, title))

    @mcp.tool(tags={'AppAgent'})
    def sort_range(sheet_name: SheetName, data_range: Annotated[str, Field(description="Range to sort, e.g. 'A1:C20'.")], key_column: Annotated[int, Field(description='1-based column within the range to sort by.')], ascending: Annotated[bool, Field(description='Ascending (true) or descending (false).')] = True, has_header: Annotated[bool, Field(description='Whether the first row is a header.')] = True) -> str:
        """Sort a range of rows by one column."""
        return run(lambda r: r.sort_range(sheet_name, data_range, key_column, ascending, has_header))

    @mcp.tool(tags={'AppAgent'})
    def table2markdown(sheet_name: SheetName) -> str:
        """Read the used range of a sheet as a markdown table."""
        return run(lambda r: r.table2markdown(sheet_name))

    @mcp.tool(tags={'AppAgent'})
    def get_range_values(sheet_name: SheetName, start_row: Annotated[int, Field(description='The start row, starting from 1.')], start_col: Annotated[int, Field(description='The start column, starting from 1.')], end_row: Annotated[int, Field(description='The end row; -1 for the last used row.')] = -1, end_col: Annotated[int, Field(description='The end column; -1 for the last used column.')] = -1) -> List:
        """Read the values of a range of cells."""
        return run(lambda r: r.get_range_values(sheet_name, start_row, start_col, end_row, end_col))

    @mcp.tool(tags={'AppAgent'})
    def insert_excel_table(table: Annotated[List[List[Any]], Field(description='The table content: a list of rows of strings or numbers.')], sheet_name: Annotated[str, Field(description='The name of the sheet to insert the table.')], start_row: Annotated[int, Field(description='The start row, starting from 1.')], start_col: Annotated[int, Field(description='The start column, starting from 1.')]) -> str:
        """Insert a table into the sheet at a row/column position."""
        return run(lambda r: r.insert_excel_table(sheet_name, table, start_row, start_col))

    @mcp.tool(tags={'AppAgent'})
    def select_table_range(sheet_name: Annotated[str, Field(description='The name of the sheet.')], start_row: Annotated[int, Field(description='The start row, starting from 1.')], start_col: Annotated[int, Field(description='The start column, starting from 1 (A=1, B=2, ...).')], end_row: Annotated[int, Field(description='The end row; -1 for the last row with content.')], end_col: Annotated[int, Field(description='The end column; -1 for the last column with content.')]) -> str:
        """Select a range of cells instead of dragging the mouse."""
        return run(lambda r: r.select_table_range(sheet_name, start_row, start_col, end_row, end_col))

    @mcp.tool(tags={'AppAgent'})
    def reorder_columns(sheet_name: Annotated[str, Field(description='The name of the sheet.')], desired_order: Annotated[List[str], Field(description='The column header names in the new order.')]) -> str:
        """Reorder the columns of a sheet by header name."""
        return run(lambda r: r.reorder_columns(sheet_name, desired_order))

    @mcp.tool(tags={'AppAgent'})
    def save_as(file_dir: Annotated[str, Field(description="Directory to save to. Defaults to the workbook's folder, or Documents if it was never saved.")] = '', file_name: Annotated[str, Field(description='File name without extension. Defaults to the current name.')] = '', file_ext: Annotated[str, Field(description="Extension, e.g. '.xlsx', '.csv' or '.pdf'. Defaults to '.csv'.")] = '') -> str:
        """Save or export the workbook in one step (faster and more reliable than the Save dialog)."""
        return run(lambda r: r.save_as(file_dir, file_name, file_ext))

    return mcp


if __name__ == '__main__':
    logging.basicConfig(level=logging.ERROR)
    create_excel_mcp_server().run()
