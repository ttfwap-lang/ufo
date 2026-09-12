"""
LLM Resilience Module — Auto-Restart Daemon for local llama-server instances.

This module provides a background watchdog that monitors the health of local
LLM server instances (llama-server on :8080 and :8081) and automatically
restarts them if they become unresponsive during task execution.

If restart fails, it triggers cloud failover using a process-local memory override 
that leaves backend_state.json untouched.

Usage:
    from ufo.utils.llm_resilience import LLMWatchdog
    watchdog = LLMWatchdog()
    watchdog.start()    # Start monitoring in background thread
    watchdog.stop()     # Stop monitoring
"""
import logging
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import List, Optional
logger = logging.getLogger(__name__)

class LLMServerConfig:
    """Configuration for a single llama-server instance."""

    def __init__(self, name: str, port: int, model_path: str, mmproj_path: Optional[str]=None, threads: int=8, context_size: int=8192):
        self.name = name
        self.port = port
        self.model_path = model_path
        self.mmproj_path = mmproj_path
        self.threads = threads
        self.context_size = context_size
        self.process: Optional[subprocess.Popen] = None
        self.restart_count: int = 0
        self.max_restarts: int = 3
        self.last_healthy: float = 0.0
DEFAULT_SERVERS = [LLMServerConfig(name='Qwen3-VL-8B [HOST]', port=8080, model_path='C:\\ufo\\models\\qwen3-vl-8b-instruct-q4_k_m.gguf', mmproj_path='C:\\ufo\\models\\qwen3-vl-8b-instruct-mmproj-f16.gguf'), LLMServerConfig(name='Gemma-4-12B [APP]', port=8081, model_path='C:\\ufo\\models\\gemma-4-12b-it-q4_0.gguf', mmproj_path='C:\\ufo\\models\\gemma-4-12b-it-mmproj-q8_0.gguf')]
LLAMA_SERVER_PATH = 'C:\\ufo\\bin\\llama-server.exe'
UFO_DIR = Path('C:\\ufo\\ufo')

class LLMWatchdog:
    """
    Background watchdog that monitors local LLM server health and
    auto-restarts crashed instances or triggers cloud failover.

    This is the Phase 4 Zero-Fail auto-restart daemon.
    """

    def __init__(self, servers: Optional[List[LLMServerConfig]]=None, check_interval: float=30.0, health_timeout: float=5.0):
        """
        Initialize the watchdog.

        :param servers: List of server configurations to monitor
        :param check_interval: Seconds between health checks
        :param health_timeout: Seconds to wait for health endpoint response
        """
        self.servers = servers or DEFAULT_SERVERS
        self.check_interval = check_interval
        self.health_timeout = health_timeout
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the watchdog monitoring thread."""
        if self._thread and self._thread.is_alive():
            logger.warning('LLM Watchdog is already running')
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, name='llm-watchdog', daemon=True)
        self._thread.start()
        logger.info(f'LLM Watchdog started — monitoring {len(self.servers)} servers every {self.check_interval}s')

    def stop(self) -> None:
        """Stop the watchdog monitoring thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info('LLM Watchdog stopped')

    def _monitor_loop(self) -> None:
        """Main monitoring loop running in background thread."""
        logger.info('LLM Watchdog: Waiting 90s grace period for models to load...')
        self._stop_event.wait(90.0)
        while not self._stop_event.is_set():
            for server in self.servers:
                if self._stop_event.is_set():
                    break
                try:
                    if not self._check_health(server):
                        self._handle_unhealthy(server)
                    else:
                        server.last_healthy = time.time()
                except Exception as e:
                    logger.error(f'Watchdog error checking {server.name}: {e}')
            self._stop_event.wait(self.check_interval)

    def _check_health(self, server: LLMServerConfig) -> bool:
        """
        Check if a server is healthy by probing its /health endpoint.

        :param server: Server to check
        :return: True if healthy
        """
        url = f'http://127.0.0.1:{server.port}/health'
        try:
            req = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(req, timeout=self.health_timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _handle_unhealthy(self, server: LLMServerConfig) -> None:
        """
        Handle an unhealthy server — attempt restart or trigger cloud failover.

        :param server: Unhealthy server
        """
        logger.warning(f'LLM Watchdog: {server.name} on :{server.port} is UNHEALTHY (restarts: {server.restart_count}/{server.max_restarts})')
        if server.restart_count >= server.max_restarts:
            logger.error(f'LLM Watchdog: {server.name} exceeded max restarts. Triggering cloud failover.')
            self._trigger_cloud_failover()
            return
        success = self._restart_server(server)
        if success:
            server.restart_count += 1
            server.last_healthy = time.time()
            logger.info(f'LLM Watchdog: {server.name} restarted successfully (attempt {server.restart_count})')
        else:
            server.restart_count = server.max_restarts
            logger.error(f'LLM Watchdog: Failed to restart {server.name}')

    def _restart_server(self, server: LLMServerConfig) -> bool:
        """
        Restart a llama-server instance.

        :param server: Server to restart
        :return: True if restart succeeded
        """
        if not os.path.exists(LLAMA_SERVER_PATH):
            logger.error(f'llama-server.exe not found at {LLAMA_SERVER_PATH}')
            return False
        if not os.path.exists(server.model_path):
            logger.error(f'Model file not found: {server.model_path}')
            return False
        try:
            import psutil
            for proc in psutil.process_iter(['name', 'pid', 'cmdline']):
                if proc.info['name'] and 'llama-server' in proc.info['name'].lower():
                    cmdline = proc.info.get('cmdline', []) or []
                    if str(server.port) in ' '.join(cmdline):
                        logger.info(f"Killing existing llama-server PID {proc.info['pid']}")
                        proc.kill()
                        proc.wait(timeout=10)
        except Exception as e:
            logger.warning(f'Error killing existing process: {e}')
        cmd = [LLAMA_SERVER_PATH, '-m', server.model_path, '-t', str(server.threads), '-c', str(server.context_size), '--host', '127.0.0.1', '--port', str(server.port)]
        if server.mmproj_path and os.path.exists(server.mmproj_path):
            cmd.extend(['--mmproj', server.mmproj_path])
        try:
            server.process = subprocess.Popen(cmd, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logger.info(f'Launched llama-server for {server.name} (PID {server.process.pid})')
            for attempt in range(30):
                time.sleep(3)
                if self._check_health(server):
                    return True
                if server.process.poll() is not None:
                    logger.error(f'llama-server exited prematurely with code {server.process.returncode}')
                    return False
            logger.error(f'llama-server for {server.name} did not become healthy in 90s')
            return False
        except Exception as e:
            logger.error(f'Failed to launch llama-server: {e}')
            return False

    def _trigger_cloud_failover(self) -> None:
        """
        Process-local memory override to cloud config (Gemini) as ultimate fallback.
        backend_state.json is never touched — the persisted user intent is preserved.
        """
        try:
            from ufo.llm.config_helper import set_process_override
            if set_process_override('cloud'):
                logger.warning('LLM Watchdog: FAILOVER COMPLETE — switched active LLM route to Gemini cloud API in memory (zero disk writes).')
            else:
                logger.error('LLM Watchdog: Cloud failover failed — could not load or validate cloud configuration.')
        except Exception as e:
            logger.error(f'Cloud failover failed: {e}')
_watchdog_instance: Optional[LLMWatchdog] = None

def get_watchdog() -> LLMWatchdog:
    """Get or create the global LLM watchdog instance."""
    global _watchdog_instance
    if _watchdog_instance is None:
        _watchdog_instance = LLMWatchdog()
    return _watchdog_instance