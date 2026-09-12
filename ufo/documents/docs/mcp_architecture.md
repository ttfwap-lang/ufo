# UFO Model Context Protocol (MCP) Architecture

This document outlines how the **UFO (UI-Focused Agent)** integrates with the **Model Context Protocol (MCP)** to expose local COM automation and other system capabilities as standard tools to LLM clients (such as Antigravity IDE and Galaxy TaskOrchestrator).

## Overview

UFO utilizes MCP to bridge the gap between high-level reasoning agents and low-level desktop execution environments. By wrapping application-specific logic (e.g., interacting with Excel, Word, or VirtualBox) in isolated MCP servers, we ensure a clean separation of concerns and robust error handling.

UFO supports 13 core MCP servers, which are primarily defined in `config/ufo/mcp.yaml`.

## Core Design Principles

### 1. `stdio` Transport over `FastMCP`
All UFO local MCP servers are built using the `FastMCP` Python library. They communicate with the client (Antigravity IDE or UFO orchestrator) exclusively over standard input/output (`stdio`).

This design allows the IDE or parent process to spawn the Python interpreter as a subprocess and seamlessly exchange JSONRPC payloads without requiring networking (TCP/IP) overhead.

### 2. Execution Entry Points (`__main__`)
To prevent `stdio` stream corruption, local server scripts (e.g., `excel_wincom_mcp_server.py`) must *never* execute test logic or print debug information to `stdout` when invoked directly. 

**Standard Execution Block:**
Every local server in `C:\ufo\ufo\client\mcp\local_servers\` must implement the following execution block:

```python
if __name__ == "__main__":
    import logging
    # Suppress output that might corrupt JSONRPC
    logging.basicConfig(level=logging.ERROR)
    mcp = create_excel_mcp_server()  # Replace with specific factory
    mcp.run()
```
*Failure to use `mcp.run()` will result in premature EOF and JSON parsing errors (`invalid character 'S'`) in the client.*

### 3. Graceful Degradation
If a requested COM application (e.g., PowerPoint) is not installed on the host machine, the MCP server should gracefully catch the `win32com` error (`-2147221005, 'Invalid class string'`) and return a structured error message to the LLM, rather than crashing the subprocess.

## Key Servers

| Server Name | Description | Tools Provided |
|-------------|-------------|----------------|
| **ExcelCOMExecutor** | COM-based Excel automation | `insert_excel_table`, `read_range`, etc. |
| **WordCOMExecutor** | COM-based Word automation | `insert_table`, `select_text`, etc. |
| **VirtualBoxExecutor** | VBoxManage wrapper | `list_vms`, `start_vm`, `take_snapshot` |
| **RDPController** | Remote Desktop control | `connect_rdp`, `send_keys_to_rdp` |
| **UICollector** | Windows UIA interactions | Screenshot, Window Tree, Click |

## Configuration
MCP servers are registered and loaded via `C:\ufo\ufo\config\ufo\mcp.yaml`. 

```yaml
mcpServers:
  ufo-excel:
    command: python_env/python.exe
    args:
      - -W
      - ignore
      - -m
      - ufo.client.mcp.local_servers.excel_wincom_mcp_server
```

> [!TIP]
> The `-W ignore` flag is used to suppress third-party dependency warnings (such as `AuthlibDeprecationWarning`) that could otherwise leak into `stderr` and clutter the client logs.
