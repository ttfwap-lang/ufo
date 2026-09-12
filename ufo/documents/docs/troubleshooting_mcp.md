# Troubleshooting MCP Integration

This guide covers common issues and resolutions when working with UFO's local Model Context Protocol (MCP) servers and their integration with IDE clients (like Antigravity).

## 1. JSONRPC Parsing Errors (`invalid character 'S'`)

### Symptoms
When an LLM client attempts to connect to an MCP server (e.g., `ufo-excel`), the connection immediately closes, and the client reports an error similar to:
```
ToolError: connection closed: calling "initialize": client is closing: invalid character 'S' looking for beginning of value
```

### Root Cause
This error occurs when the MCP server writes non-JSON formatted text to `stdout`. The standard MCP protocol uses `stdio` as a transport mechanism, expecting strict JSONRPC payloads. If a Python script prints something like `"Starting MCP server..."` or `"Server listening..."` before the JSONRPC handshake, the client's parser will fail to decode it (e.g., `S` from `Starting`).

### Resolution
Ensure that the entry point (`__main__`) of the MCP server script correctly initializes and runs the FastMCP server, rather than running standalone tests or printing debug info:
```python
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.ERROR)  # Suppress stdout noise
    mcp = create_excel_mcp_server()
    mcp.run() # This binds correctly to stdio for JSONRPC
```

---

## 2. Dependency Deprecation Warnings (e.g., `AuthlibDeprecationWarning`)

### Symptoms
The LLM client's console is cluttered with warnings:
```
jwt.py:10: AuthlibDeprecationWarning: authlib.jose module is deprecated, please use joserfc instead.
```

### Root Cause
Third-party dependencies (such as `fastmcp` or `authlib`) may raise Python warnings during import. While these warnings are often printed to `stderr` and do not break the JSONRPC protocol, they create unnecessary noise in the IDE.

### Resolution
1. **Command-Line Argument:** In `mcp.yaml`, ensure that the Python invocation uses the `-W ignore` flag to globally suppress warnings:
   ```yaml
   args:
     - -W
     - ignore
     - -m
     - ufo.client.mcp.local_servers.excel_wincom_mcp_server
   ```
2. **Code-Level Suppression:** Wrap the offending imports in the dependency using a warnings filter:
   ```python
   import warnings
   with warnings.catch_warnings():
       warnings.simplefilter("ignore")
       from authlib.jose import JsonWebKey, JsonWebToken
   ```

---

## 3. COM Automation Failures (`Invalid class string`)

### Symptoms
When calling a tool like `insert_excel_table`, the server returns an execution error:
```
ToolError: Excel COM automation failed: Excel COM automation interface unavailable: (-2147221005, 'Invalid class string', None, None)
```

### Root Cause
The requested COM application (e.g., Microsoft Excel) is either not installed on the system, or its COM registry keys are corrupted. The `win32com.client.Dispatch` call cannot locate the application class.

### Resolution
Ensure the target application (Excel, Word, PowerPoint) is fully installed and licensed on the host machine. If running in an isolated or virtualized environment, COM access might be restricted or absent. If the application is confirmed installed, repairing the Office installation usually resolves the COM registration issues.
