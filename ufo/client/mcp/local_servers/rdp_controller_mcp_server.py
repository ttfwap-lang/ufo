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

def _run_cmd(args: list, timeout: int=30, check: bool=True) -> str:
    """Run a subprocess command and return stdout."""
    logger.info(f"[RDP] Executing: {' '.join(args)}")
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        if check and result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip()
            logger.warning(f'[RDP] Command failed: {error_msg}')
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise ToolError(f'Command timed out after {timeout}s')
    except FileNotFoundError as e:
        raise ToolError(f'Command not found: {e}')

def _find_mstsc_window(host: str='', pid: int=0):
    """
    Find the mstsc.exe RDP window by host substring in title or PID.
    Returns (hwnd, title) or (0, '') if not found.
    """
    try:
        import win32gui
        import win32process
        results = []

        def _enum_cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return
            if pid:
                try:
                    _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                    if found_pid == pid:
                        results.append((hwnd, title))
                        return
                except Exception:
                    pass
            title_lower = title.lower()
            if host and host.lower() in title_lower:
                results.append((hwnd, title))
            elif 'remote desktop' in title_lower or 'mstsc' in title_lower:
                results.append((hwnd, title))
        win32gui.EnumWindows(_enum_cb, None)
        if results:
            return results[0]
    except ImportError:
        logger.warning('[RDP] win32gui not available — cannot find RDP window')
    except Exception as e:
        logger.warning(f'[RDP] Error finding mstsc window: {e}')
    return (0, '')

def _focus_window(hwnd: int) -> bool:
    """Bring a window to the foreground by its handle."""
    if not hwnd:
        return False
    try:
        import win32gui
        import win32con
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.SetForegroundWindow(hwnd)
        win32gui.BringWindowToTop(hwnd)
        time.sleep(0.3)
        return True
    except Exception as e:
        logger.warning(f'[RDP] Failed to focus window hwnd={hwnd}: {e}')
        return False

def _auto_focus_rdp(active_sessions: dict, host: str='') -> bool:
    """Auto-focus the RDP window, trying tracked sessions first."""
    for h, info in active_sessions.items():
        if host and host != h:
            continue
        hwnd, title = _find_mstsc_window(host=h, pid=info.get('pid', 0))
        if hwnd:
            return _focus_window(hwnd)
    hwnd, title = _find_mstsc_window(host=host)
    if hwnd:
        return _focus_window(hwnd)
    return False

@MCPRegistry.register_factory_decorator('RDPControllerExecutor')
@MCPRegistry.register_factory_decorator('mcp_rdp_controller')
def create_rdp_controller_mcp_server(*args, **kwargs) -> FastMCP:
    """Create and return the RDP Controller MCP server instance."""
    mcp = FastMCP('UFO RDP Controller MCP Server')
    _active_sessions = {}

    @mcp.tool()
    def connect_to_rdp(host: str, username: str, password: str='', port: int=3389, fullscreen: bool=False, width: int=1920, height: int=1080) -> str:
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
        target = f'{host}:{port}' if port != 3389 else host
        if password:
            cmdkey_args = ['cmdkey', f'/generic:TERMSRV/{host}', f'/user:{username}', f'/pass:{password}']
            _run_cmd(cmdkey_args, check=False)
            logger.info(f'[RDP] Credentials seeded for {host}')
        mstsc_args = ['mstsc', f'/v:{target}']
        if fullscreen:
            mstsc_args.append('/f')
        else:
            mstsc_args.extend([f'/w:{width}', f'/h:{height}'])
        try:
            proc = subprocess.Popen(mstsc_args)
            _active_sessions[host] = {'pid': proc.pid, 'username': username, 'port': port}
            time.sleep(3)
            logger.info(f'[RDP] mstsc.exe launched (PID: {proc.pid}) for {target}')
            return f'RDP connection initiated to {target} as {username}. mstsc.exe running with PID {proc.pid}. The Remote Desktop window should now be visible. Use the UFO UI automation to interact with the RDP window content.'
        except Exception as e:
            raise ToolError(f'Failed to launch mstsc.exe: {e}')

    @mcp.tool()
    def connect_via_rdp_file(rdp_file_path: str) -> str:
        """
        Launch an RDP connection using an existing .rdp file with pre-saved credentials.
        This is the simplest way to connect when credentials are already stored.
        :param rdp_file_path: Absolute path to the .rdp file.
        :return: Connection status message.
        """
        if not os.path.isfile(rdp_file_path):
            raise ToolError(f'RDP file not found: {rdp_file_path}')
        host = 'unknown'
        username = 'unknown'
        try:
            with open(rdp_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('full address:s:'):
                        host = line.split(':s:', 1)[1].strip()
                    elif line.startswith('username:s:'):
                        username = line.split(':s:', 1)[1].strip()
        except Exception:
            pass
        try:
            proc = subprocess.Popen(['mstsc', rdp_file_path])
            _active_sessions[host] = {'pid': proc.pid, 'username': username, 'port': 0}
            time.sleep(5)
            logger.info(f'[RDP] Launched .rdp file (PID: {proc.pid}) for {host}')
            return f'RDP connection initiated via .rdp file to {host} as {username}. mstsc.exe running with PID {proc.pid}. Credentials were pre-saved — connection should auto-authenticate. The Remote Desktop window should now be visible.'
        except Exception as e:
            raise ToolError(f'Failed to launch .rdp file: {e}')

    @mcp.tool()
    def connect_to_macincloud() -> str:
        """
        Quick-connect to MacInCloud using the pre-configured .rdp file on the Desktop.
        Credentials are pre-saved — no password input needed.
        Host: SY441.macincloud.com:6000, User: user294545
        :return: Connection status message.
        """
        rdp_path = os.path.join(os.path.expanduser('~'), 'Desktop', 'MacinCloud_VeryLowGraphics_FasterConnection_FullScreen.rdp')
        if not os.path.isfile(rdp_path):
            raise ToolError(f'MacInCloud .rdp file not found at {rdp_path}. Expected: Desktop\\MacinCloud_VeryLowGraphics_FasterConnection_FullScreen.rdp')
        return connect_via_rdp_file(rdp_path)

    @mcp.tool()
    def disconnect_rdp(host: str) -> str:
        """
        Disconnect an active RDP session and clean up stored credentials.
        :param host: The host to disconnect from.
        :return: Disconnection status.
        """
        _run_cmd(['cmdkey', f'/delete:TERMSRV/{host}'], check=False)
        session = _active_sessions.pop(host, None)
        if session:
            try:
                subprocess.run(['taskkill', '/PID', str(session['pid']), '/F'], capture_output=True, check=False)
            except Exception:
                pass
            return f'RDP session to {host} disconnected and credentials cleaned.'
        return f'Credentials for {host} removed. Close the RDP window manually if still open.'

    @mcp.tool()
    def list_rdp_sessions() -> str:
        """
        List all tracked active RDP sessions.
        :return: List of active sessions with host, username, and PID.
        """
        if not _active_sessions:
            return 'No active RDP sessions.'
        lines = ['Active RDP Sessions:']
        for host, info in _active_sessions.items():
            lines.append(f"  - {host} (user: {info['username']}, PID: {info['pid']}, port: {info['port']})")
        return '\n'.join(lines)

    @mcp.tool()
    def focus_rdp_window(host: str='') -> str:
        """
        Find and bring the RDP (mstsc.exe) window to the foreground.
        Must be called before sending keys or clicks if the RDP window is not focused.
        :param host: Optional host to match in window title. If empty, focuses any RDP window.
        :return: Status message.
        """
        focused = _auto_focus_rdp(_active_sessions, host=host)
        if focused:
            return f"RDP window focused successfully{(f' for {host}' if host else '')}."
        raise ToolError(f"Could not find or focus RDP window{(f' for {host}' if host else '')}. Ensure an RDP session is active and the window is not closed.")

    @mcp.tool()
    def screenshot_rdp(host: str='', save_path: str='') -> str:
        """
        Capture a screenshot of the active RDP window.
        The RDP window is automatically focused before capture.
        :param host: Optional host to identify which RDP window to capture.
        :param save_path: Optional file path to save the screenshot. If empty, returns base64.
        :return: Screenshot result (file path or base64 string).
        """
        _auto_focus_rdp(_active_sessions, host=host)
        time.sleep(0.3)
        try:
            import pyautogui
            from PIL import Image
            import base64
            from io import BytesIO
            screenshot = pyautogui.screenshot()
            if save_path:
                screenshot.save(save_path)
                logger.info(f'[RDP] Screenshot saved to {save_path}')
                return f'Screenshot saved to {save_path} ({screenshot.size[0]}x{screenshot.size[1]})'
            buffer = BytesIO()
            screenshot.save(buffer, format='PNG')
            b64_str = base64.b64encode(buffer.getvalue()).decode('ascii')
            return f'data:image/png;base64,{b64_str[:100]}... (full screenshot {screenshot.size[0]}x{screenshot.size[1]}, {len(b64_str)} chars)'
        except Exception as e:
            raise ToolError(f'Failed to capture screenshot: {e}')

    @mcp.tool()
    def send_keys_to_rdp(keys: str, host: str='', use_hotkey: bool=False) -> str:
        """
        Send keyboard input to the active RDP window using pyautogui.
        The RDP window is automatically focused before sending keys.
        :param keys: Text to type, or key name for special keys (e.g., 'enter', 'tab').
        :param host: Optional host to identify which RDP window to target.
        :param use_hotkey: If True, treat keys as a hotkey combo (e.g., 'ctrl+c').
        :return: Confirmation.
        """
        _auto_focus_rdp(_active_sessions, host=host)
        time.sleep(0.15)
        try:
            import pyautogui
            if use_hotkey:
                key_parts = [k.strip() for k in keys.split('+')]
                pyautogui.hotkey(*key_parts)
                return f"Sent hotkey '{keys}' to RDP window."
            try:
                pyautogui.write(keys, interval=0.02)
            except Exception:
                pyautogui.typewrite(keys, interval=0.02)
            return f"Typed '{keys}' into the active RDP window."
        except Exception as e:
            raise ToolError(f'Failed to send keys: {e}')

    @mcp.tool()
    def send_hotkey_to_rdp(keys: str, host: str='') -> str:
        """
        Send a keyboard shortcut/hotkey combination to the active RDP window.
        The RDP window is automatically focused before sending.
        :param keys: Key combination string separated by '+' (e.g., 'ctrl+c', 'alt+f4', 'ctrl+shift+s').
        :param host: Optional host to identify which RDP window to target.
        :return: Confirmation.
        """
        _auto_focus_rdp(_active_sessions, host=host)
        time.sleep(0.15)
        try:
            import pyautogui
            if not keys:
                raise ToolError("No keys specified. Provide keys as 'ctrl+c' format.")
            key_parts = [k.strip().lower() for k in keys.split('+')]
            pyautogui.hotkey(*key_parts)
            combo_str = '+'.join(key_parts)
            return f"Sent hotkey '{combo_str}' to RDP window."
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(f'Failed to send hotkey: {e}')

    @mcp.tool()
    def click_in_rdp(x: int, y: int, button: str='left', double: bool=False, host: str='') -> str:
        """
        Click at coordinates within the active RDP window using pyautogui.
        The RDP window is automatically focused before clicking.
        :param x: X coordinate on screen.
        :param y: Y coordinate on screen.
        :param button: Mouse button ('left', 'right', 'middle').
        :param double: If True, double-click.
        :param host: Optional host to identify which RDP window to target.
        :return: Confirmation.
        """
        _auto_focus_rdp(_active_sessions, host=host)
        time.sleep(0.15)
        try:
            import pyautogui
            clicks = 2 if double else 1
            pyautogui.click(x=x, y=y, button=button, clicks=clicks)
            return f"Clicked ({button}, {('double' if double else 'single')}) at ({x}, {y})."
        except Exception as e:
            raise ToolError(f'Failed to click: {e}')

    @mcp.tool()
    def check_rdp_session(host: str='') -> str:
        """
        Check the health/status of RDP sessions. Validates PID is still running and window exists.
        :param host: Optional specific host to check. If empty, checks all tracked sessions.
        :return: Session status report.
        """
        if not _active_sessions:
            return 'No tracked RDP sessions.'
        lines = ['RDP Session Health Check:']
        for h, info in _active_sessions.items():
            if host and host.lower() != h.lower():
                continue
            pid = info.get('pid', 0)
            pid_alive = False
            window_found = False
            if pid:
                try:
                    result = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'], capture_output=True, text=True, timeout=5, check=False)
                    pid_alive = str(pid) in result.stdout
                except Exception:
                    pass
            hwnd, title = _find_mstsc_window(host=h, pid=pid)
            window_found = hwnd != 0
            status = 'HEALTHY' if pid_alive and window_found else 'DEGRADED' if pid_alive else 'DEAD'
            lines.append(f"  - {h}: {status} (PID {pid}: {('alive' if pid_alive else 'dead')}, Window: {('found' if window_found else 'not found')})")
        return '\n'.join(lines)
    return mcp
if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.ERROR)
    mcp = create_rdp_controller_mcp_server()
    mcp.run()