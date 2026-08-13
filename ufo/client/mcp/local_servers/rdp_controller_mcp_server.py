#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
RDP Controller MCP Server
Provides MCP tools for connecting to and interacting with remote machines via RDP.
Uses mstsc.exe (Windows Remote Desktop client) with credential pre-seeding via cmdkey.
"""

import logging
import os
import subprocess
import time

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ufo.client.mcp.mcp_registry import MCPRegistry

logger = logging.getLogger(__name__)


def _run_cmd(args: list, timeout: int = 30, check: bool = True) -> str:
    """Run a subprocess command and return stdout."""
    logger.info(f"[RDP] Executing: {' '.join(args)}")
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if check and result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip()
            logger.warning(f"[RDP] Command failed: {error_msg}")
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise ToolError(f"Command timed out after {timeout}s")
    except FileNotFoundError as e:
        raise ToolError(f"Command not found: {e}")


@MCPRegistry.register_factory_decorator("RDPControllerExecutor")
def create_rdp_controller_mcp_server(*args, **kwargs) -> FastMCP:
    """Create and return the RDP Controller MCP server instance."""

    mcp = FastMCP("UFO RDP Controller MCP Server")

    # Track active RDP sessions
    _active_sessions = {}

    @mcp.tool()
    def connect_to_rdp(
        host: str,
        username: str,
        password: str = "",
        port: int = 3389,
        fullscreen: bool = False,
        width: int = 1920,
        height: int = 1080,
    ) -> str:
        """
        Connect to a remote machine via RDP using mstsc.exe.
        Pre-seeds credentials via cmdkey so no manual login is required.
        :param host: IP address or hostname of the remote machine.
        :param username: Username for authentication.
        :param password: Password for authentication.
        :param port: RDP port (default: 3389).
        :param fullscreen: If True, open RDP in fullscreen mode.
        :param width: Window width in pixels (default: 1920).
        :param height: Window height in pixels (default: 1080).
        :return: Connection status message.
        """
        target = f"{host}:{port}" if port != 3389 else host

        # Step 1: Pre-seed credentials via cmdkey
        if password:
            cmdkey_args = [
                "cmdkey",
                f"/generic:TERMSRV/{host}",
                f"/user:{username}",
                f"/pass:{password}",
            ]
            _run_cmd(cmdkey_args, check=False)
            logger.info(f"[RDP] Credentials seeded for {host}")

        # Step 2: Launch mstsc.exe
        mstsc_args = ["mstsc", f"/v:{target}"]
        if fullscreen:
            mstsc_args.append("/f")
        else:
            mstsc_args.extend([f"/w:{width}", f"/h:{height}"])

        try:
            proc = subprocess.Popen(mstsc_args)
            _active_sessions[host] = {
                "pid": proc.pid,
                "username": username,
                "port": port,
            }
            # Wait for RDP window to appear
            time.sleep(3)
            logger.info(f"[RDP] mstsc.exe launched (PID: {proc.pid}) for {target}")
            return (
                f"RDP connection initiated to {target} as {username}. "
                f"mstsc.exe running with PID {proc.pid}. "
                f"The Remote Desktop window should now be visible. "
                f"Use the UFO UI automation to interact with the RDP window content."
            )
        except Exception as e:
            raise ToolError(f"Failed to launch mstsc.exe: {e}")

    @mcp.tool()
    def connect_via_rdp_file(rdp_file_path: str) -> str:
        """
        Launch an RDP connection using an existing .rdp file with pre-saved credentials.
        This is the simplest way to connect when credentials are already stored.
        :param rdp_file_path: Absolute path to the .rdp file.
        :return: Connection status message.
        """
        if not os.path.isfile(rdp_file_path):
            raise ToolError(f"RDP file not found: {rdp_file_path}")

        # Parse the .rdp file for host info
        host = "unknown"
        username = "unknown"
        try:
            with open(rdp_file_path, "r") as f:
                for line in f:
                    if line.startswith("full address:s:"):
                        host = line.split(":s:", 1)[1].strip()
                    elif line.startswith("username:s:"):
                        username = line.split(":s:", 1)[1].strip()
        except Exception:
            pass

        try:
            proc = subprocess.Popen(["mstsc", rdp_file_path])
            _active_sessions[host] = {
                "pid": proc.pid,
                "username": username,
                "port": 0,
            }
            time.sleep(5)  # RDP files with pre-saved creds need time to authenticate
            logger.info(f"[RDP] Launched .rdp file (PID: {proc.pid}) for {host}")
            return (
                f"RDP connection initiated via .rdp file to {host} as {username}. "
                f"mstsc.exe running with PID {proc.pid}. "
                f"Credentials were pre-saved — connection should auto-authenticate. "
                f"The Remote Desktop window should now be visible."
            )
        except Exception as e:
            raise ToolError(f"Failed to launch .rdp file: {e}")

    @mcp.tool()
    def connect_to_macincloud() -> str:
        """
        Quick-connect to MacInCloud using the pre-configured .rdp file on the Desktop.
        Credentials are pre-saved — no password input needed.
        Host: SY441.macincloud.com:6000, User: user294545
        :return: Connection status message.
        """
        rdp_path = os.path.join(
            os.path.expanduser("~"),
            "Desktop",
            "MacinCloud_VeryLowGraphics_FasterConnection_FullScreen.rdp",
        )
        if not os.path.isfile(rdp_path):
            raise ToolError(
                f"MacInCloud .rdp file not found at {rdp_path}. "
                f"Expected: Desktop\\MacinCloud_VeryLowGraphics_FasterConnection_FullScreen.rdp"
            )
        return connect_via_rdp_file(rdp_path)

    @mcp.tool()
    def disconnect_rdp(host: str) -> str:
        """
        Disconnect an active RDP session and clean up stored credentials.
        :param host: The host to disconnect from.
        :return: Disconnection status.
        """
        # Remove stored credentials
        _run_cmd(["cmdkey", f"/delete:TERMSRV/{host}"], check=False)

        # Kill the mstsc process if tracked
        session = _active_sessions.pop(host, None)
        if session:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(session["pid"]), "/F"],
                    capture_output=True,
                    check=False,
                )
            except Exception:
                pass
            return f"RDP session to {host} disconnected and credentials cleaned."

        # Fallback: try to kill any mstsc window with this host in title
        return f"Credentials for {host} removed. Close the RDP window manually if still open."

    @mcp.tool()
    def list_rdp_sessions() -> str:
        """
        List all tracked active RDP sessions.
        :return: List of active sessions with host, username, and PID.
        """
        if not _active_sessions:
            return "No active RDP sessions."

        lines = ["Active RDP Sessions:"]
        for host, info in _active_sessions.items():
            lines.append(f"  - {host} (user: {info['username']}, PID: {info['pid']}, port: {info['port']})")
        return "\n".join(lines)

    @mcp.tool()
    def send_keys_to_rdp(keys: str) -> str:
        """
        Send keyboard input to the active RDP window using pyautogui.
        The RDP window must be in the foreground.
        :param keys: Keys to type. Use pyautogui key names for special keys.
        :return: Confirmation.
        """
        try:
            import pyautogui
            pyautogui.typewrite(keys, interval=0.02)
            return f"Typed '{keys}' into the active RDP window."
        except Exception as e:
            raise ToolError(f"Failed to send keys: {e}")

    @mcp.tool()
    def click_in_rdp(x: int, y: int, button: str = "left", double: bool = False) -> str:
        """
        Click at coordinates within the active RDP window using pyautogui.
        The RDP window must be in the foreground.
        :param x: X coordinate on screen.
        :param y: Y coordinate on screen.
        :param button: Mouse button ('left', 'right', 'middle').
        :param double: If True, double-click.
        :return: Confirmation.
        """
        try:
            import pyautogui
            clicks = 2 if double else 1
            pyautogui.click(x=x, y=y, button=button, clicks=clicks)
            return f"Clicked ({button}, {'double' if double else 'single'}) at ({x}, {y})."
        except Exception as e:
            raise ToolError(f"Failed to click: {e}")

    return mcp
