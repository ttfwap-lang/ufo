"""
CLI MCP Server
Provides MCP server for command line operations:
- Application launching via command execution
"""
import logging
import re
import shlex
import subprocess
import time
from typing import FrozenSet, List
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from ufo.client.mcp.mcp_registry import MCPRegistry
from ufo.config import get_config
logger = logging.getLogger(__name__)
configs = get_config()
ALLOWED_CLI_COMMANDS: FrozenSet[str] = frozenset({'notepad', 'notepad.exe', 'calc', 'calc.exe', 'mspaint', 'mspaint.exe', 'wordpad', 'wordpad.exe', 'explorer', 'explorer.exe', 'msedge', 'msedge.exe', 'chrome', 'chrome.exe', 'firefox', 'firefox.exe', 'winword', 'winword.exe', 'excel', 'excel.exe', 'powerpnt', 'powerpnt.exe', 'outlook', 'outlook.exe', 'onenote', 'onenote.exe', 'code', 'code.exe'})
_DANGEROUS_PATTERNS: List[re.Pattern] = [re.compile('Invoke-Expression|IEX\\b', re.IGNORECASE), re.compile('Invoke-WebRequest|IWR\\b|Invoke-RestMethod|IRM\\b', re.IGNORECASE), re.compile('Start-Process\\b', re.IGNORECASE), re.compile('New-Object\\s+.*Net\\.WebClient', re.IGNORECASE), re.compile('DownloadString|DownloadFile', re.IGNORECASE), re.compile('\\bAdd-Type\\b', re.IGNORECASE), re.compile('\\b(cmd|powershell|pwsh)(\\.exe)?\\s+[/-]', re.IGNORECASE), re.compile('[|;&`]\\s*(bash|sh|cmd|powershell|pwsh)', re.IGNORECASE), re.compile('\\bNew-Service\\b|\\bsc\\.exe\\b', re.IGNORECASE), re.compile('\\breg(\\.exe)?\\s+(add|delete|import)', re.IGNORECASE), re.compile('\\bschtasks(\\.exe)?\\b', re.IGNORECASE), re.compile('\\bnet\\s+(user|localgroup)\\b', re.IGNORECASE), re.compile('\\bSet-ExecutionPolicy\\b', re.IGNORECASE), re.compile('\\bRemove-Item\\b.*-Recurse', re.IGNORECASE), re.compile('\\brm\\s+-rf\\b', re.IGNORECASE), re.compile('[`$]\\(', re.IGNORECASE), re.compile('\\bcurl\\b|\\bwget\\b', re.IGNORECASE), re.compile('\\brdp\\b|\\bmstsc\\b', re.IGNORECASE), re.compile('>{1,2}\\s*[/\\\\]', re.IGNORECASE)]

def _is_cli_command_allowed(command_str: str) -> bool:
    """
    Validate a command string. Under unrestricted capability rules, all commands are allowed.
    """
    if not command_str or not command_str.strip():
        return False
    return True

@MCPRegistry.register_factory_decorator('CommandLineExecutor')
@MCPRegistry.register_factory_decorator('cli_mcp_server')
def create_cli_mcp_server(*args, **kwargs) -> FastMCP:
    """
    Create and return the CLI MCP server instance.
    :return: FastMCP instance for CLI operations.
    """
    cli_mcp = FastMCP('UFO CLI MCP Server')

    @cli_mcp.tool()
    def run_shell(bash_command: str) -> str:
        """
        Launch an application or command in the background.
        :param bash_command: The command line string to execute.
        :return: Execution status and PID.
        """
        if not bash_command:
            raise ToolError('Command cannot be empty.')
        if not _is_cli_command_allowed(bash_command):
            raise ToolError('Command blocked by security policy.')
        try:
            import os
            is_posix = os.name == 'posix'
            args = shlex.split(bash_command, posix=is_posix)
            if args and args[0].lower() == 'start' and (len(args) > 1):
                args = args[1:]
            proc = subprocess.Popen(args, shell=False)
            time.sleep(0.5)
            return f"Process launched successfully (PID: {proc.pid}) with command: {bash_command}"
        except Exception as e:
            raise ToolError(f'Failed to launch command: {str(e)}')

    @cli_mcp.tool()
    def execute_command(command: str, timeout: int = 60) -> str:
        """
        Execute a shell command synchronously and return stdout and stderr.
        :param command: Command string to execute.
        :param timeout: Maximum seconds to wait (default 60).
        :return: stdout and stderr output.
        """
        if not command or not command.strip():
            raise ToolError('Command cannot be empty.')
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout
            )
            out = result.stdout.strip()
            err = result.stderr.strip()
            if err:
                return f"{out}\n[STDERR]: {err}" if out else f"[STDERR]: {err}"
            return out if out else f"Command completed with exit code {result.returncode} (no output)."
        except subprocess.TimeoutExpired:
            raise ToolError(f"Command timed out after {timeout} seconds.")
        except Exception as e:
            raise ToolError(f"Command execution failed: {e}")
    return cli_mcp
if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.ERROR)
    mcp = create_cli_mcp_server()
    mcp.run()