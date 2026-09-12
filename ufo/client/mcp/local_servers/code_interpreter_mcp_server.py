"""
Code Interpreter MCP Server
Provides MCP server for executing arbitrary Python code to manipulate files, PDFs, etc.
"""
import logging
import subprocess
import tempfile
import os
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from ufo.client.mcp.mcp_registry import MCPRegistry
import sys
logger = logging.getLogger(__name__)

@MCPRegistry.register_factory_decorator('CodeInterpreterExecutor')
@MCPRegistry.register_factory_decorator('mcp_code_interpreter')
def create_code_interpreter_mcp_server(*args, **kwargs) -> FastMCP:
    """
    Create and return the Code Interpreter MCP server instance.
    """
    mcp = FastMCP('UFO Code Interpreter MCP Server')

    @mcp.tool()
    def execute_python_code(code: str) -> str:
        """
        Execute arbitrary Python code. This allows for parsing PDFs, modifying Excel files,
        image processing, and anything else Python can do.
        :param code: The raw Python code to execute.
        :return: The standard output and standard error of the execution.
        """
        if not code:
            raise ToolError('Code cannot be empty.')
        try:
            fd, path = tempfile.mkstemp(suffix='.py')
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(code)
            python_exe = sys.executable if sys.executable and os.path.isfile(sys.executable) else 'C:\\ufo\\ufo\\python_env\\python.exe'
            result = subprocess.run([python_exe, path], capture_output=True, text=True, timeout=60)
            try:
                os.remove(path)
            except Exception:
                pass
            output = result.stdout
            if result.stderr:
                output += f'\nSTDERR:\n{result.stderr}'
            return output if output else 'Execution completed successfully with no output.'
        except subprocess.TimeoutExpired:
            raise ToolError('Code execution timed out after 60 seconds.')
        except Exception as e:
            raise ToolError(f'Failed to execute Python code: {str(e)}')
    return mcp
if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.ERROR)
    mcp = create_code_interpreter_mcp_server()
    mcp.run()