"""
File System MCP Server for Microsoft UFO
Provides comprehensive local file system interaction tools:
- read_file: read text/code content
- write_file: create or overwrite files
- list_directory: inspect folders
- grep_files: search for text patterns across files
- file_info: stat size, timestamps, permissions
"""
import os
import re
import logging
from pathlib import Path
from typing import Annotated, List, Optional
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field
from ufo.client.mcp.mcp_registry import MCPRegistry

logger = logging.getLogger(__name__)

@MCPRegistry.register_factory_decorator('FileSystemExecutor')
@MCPRegistry.register_factory_decorator('file_system_mcp_server')
def create_file_system_mcp_server(*args, **kwargs) -> FastMCP:
    """Create and return the File System MCP server instance."""
    mcp = FastMCP("UFO File System MCP Server")

    @mcp.tool()
    def read_file(
        file_path: Annotated[str, Field(description="Absolute or relative path to the file to read.")],
        start_line: Annotated[int, Field(description="1-based start line number (optional).")]=1,
        max_lines: Annotated[int, Field(description="Maximum number of lines to return.")]=500,
    ) -> str:
        """Read text content from a local file with line range support."""
        if not os.path.isfile(file_path):
            raise ToolError(f"File not found: {file_path}")
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            start_idx = max(0, start_line - 1)
            end_idx = min(len(lines), start_idx + max_lines)
            selected = lines[start_idx:end_idx]
            output = "".join(f"{start_idx + i + 1:4d}: {line}" for i, line in enumerate(selected))
            if len(lines) > end_idx:
                output += f"\n... [{len(lines) - end_idx} more lines truncated. Use start_line={end_idx + 1} to read more] ..."
            return output if output else "[File is empty]"
        except Exception as e:
            raise ToolError(f"Failed to read file {file_path}: {e}")

    @mcp.tool()
    def write_file(
        file_path: Annotated[str, Field(description="Path to the file to write.")],
        content: Annotated[str, Field(description="Content string to write.")],
        overwrite: Annotated[bool, Field(description="Whether to overwrite existing file.")]=True,
    ) -> str:
        """Write content to a file, creating parent directories automatically."""
        target = Path(file_path)
        if target.exists() and not overwrite:
            raise ToolError(f"File already exists and overwrite=False: {file_path}")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(content)
            return f"File successfully written to {target.resolve()} ({len(content)} chars, {content.count(chr(10))} lines)."
        except Exception as e:
            raise ToolError(f"Failed to write file {file_path}: {e}")

    @mcp.tool()
    def list_directory(
        directory_path: Annotated[str, Field(description="Directory path to inspect.")],
        recursive: Annotated[bool, Field(description="Whether to list recursively.")]=False,
        max_items: Annotated[int, Field(description="Maximum items to return.")]=100,
    ) -> str:
        """List files and subdirectories in a target directory."""
        target = Path(directory_path)
        if not target.is_dir():
            raise ToolError(f"Directory not found: {directory_path}")
        try:
            results = []
            if recursive:
                for root, dirs, files in os.walk(directory_path):
                    for d in dirs:
                        results.append(f"[DIR]  {os.path.relpath(os.path.join(root, d), directory_path)}")
                    for file in files:
                        p = os.path.join(root, file)
                        size = os.path.getsize(p) if os.path.isfile(p) else 0
                        results.append(f"[FILE] {os.path.relpath(p, directory_path)} ({size} bytes)")
                    if len(results) >= max_items:
                        break
            else:
                for entry in sorted(target.iterdir()):
                    if entry.is_dir():
                        results.append(f"[DIR]  {entry.name}/")
                    else:
                        size = entry.stat().st_size
                        results.append(f"[FILE] {entry.name} ({size} bytes)")
                    if len(results) >= max_items:
                        break
            return "\n".join(results) if results else "[Directory is empty]"
        except Exception as e:
            raise ToolError(f"Failed to list directory {directory_path}: {e}")

    @mcp.tool()
    def grep_files(
        search_path: Annotated[str, Field(description="Root file or directory path to search.")],
        pattern: Annotated[str, Field(description="Regex or literal string to search for.")],
        case_sensitive: Annotated[bool, Field(description="Case sensitivity flag.")]=False,
        max_matches: Annotated[int, Field(description="Maximum matches to return.")]=50,
    ) -> str:
        """Search for a pattern across files in a directory."""
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except Exception as err:
            raise ToolError(f"Invalid regex pattern: {err}")

        matches = []
        target = Path(search_path)
        if target.is_file():
            files_to_search = [target]
        elif target.is_dir():
            files_to_search = [p for p in target.rglob("*") if p.is_file() and p.stat().st_size < 2_000_000]
        else:
            raise ToolError(f"Search path not found: {search_path}")

        for fpath in files_to_search:
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for line_no, line in enumerate(f, 1):
                        if regex.search(line):
                            rel = os.path.relpath(fpath, search_path) if target.is_dir() else str(fpath)
                            matches.append(f"{rel}:{line_no}: {line.strip()[:150]}")
                            if len(matches) >= max_matches:
                                break
            except Exception:
                pass
            if len(matches) >= max_matches:
                break

        return "\n".join(matches) if matches else f"No matches found for pattern: {pattern}"

    return mcp

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.ERROR)
    mcp = create_file_system_mcp_server()
    mcp.run()
